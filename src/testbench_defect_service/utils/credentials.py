"""Credential sources for client configs.

A credential comes from the environment variable ``<VAR>``, from the secret file named by
``<VAR>_FILE``, or from ``<VAR>_DPAPI``, which holds a base64-encoded blob encrypted with
the Windows Data Protection API.
"""

import base64
import binascii
import os
from pathlib import Path
from typing import Any, BinaryIO

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from testbench_defect_service.log import logger
from testbench_defect_service.utils import dpapi

__all__ = [
    "DPAPI_SUFFIX",
    "FILE_SUFFIX",
    "RAW_CREDENTIAL_ENV_VARS",
    "CredentialSourceError",
    "credential_fields",
    "encrypt_credential_with_dpapi",
    "ensure_private_file",
    "is_credential_field",
    "logger",
    "open_private_file",
    "read_credential_from_env",
    "resolve_credentials",
    "with_file_sourced_placeholders",
]

FILE_SUFFIX = "_FILE"
DPAPI_SUFFIX = "_DPAPI"

SET_CREDENTIAL_COMMAND = "testbench-defect-service set-client-credential"

# Credentials whose file content is used verbatim (e.g. PEM keys keep their trailing newline).
RAW_CREDENTIAL_ENV_VARS: frozenset[str] = frozenset({"JIRA_OAUTH1_KEY_CERT"})


class CredentialSourceError(ValueError):
    """Raised when a credential source is conflicting, unreadable or empty."""


def _get_field_extra(field_info: FieldInfo) -> dict:
    extra = field_info.json_schema_extra
    return extra if isinstance(extra, dict) else {}


def is_credential_field(field_info: FieldInfo) -> bool:
    """Return True for sensitive, non-excluded fields that declare an environment variable."""
    extra = _get_field_extra(field_info)
    return bool(extra.get("sensitive")) and field_info.exclude is not True and "env_var" in extra


def credential_fields(config_class: type[BaseModel]) -> dict[str, str]:
    """Return ``{field_name: env_var}`` for every credential field, in model field order."""
    return {
        name: _get_field_extra(info)["env_var"]
        for name, info in config_class.model_fields.items()
        if is_credential_field(info)
    }


def ensure_private_file(path: Path) -> None:
    """Make ``path`` readable and writable by its owner only (POSIX), creating it if missing.

    Does nothing on non-POSIX systems. Never raises: if the permissions cannot be set,
    a warning is logged instead.
    """
    if os.name != "posix":
        return
    try:
        if not path.exists():
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
        path.chmod(0o600)
    except OSError:
        logger.warning(
            f"Could not restrict '{path}' to the owner (chmod 600 failed); "
            "set the file permissions manually."
        )


def open_private_file(path: Path) -> BinaryIO:
    """Open ``path`` for binary writing, creating it with owner-only permissions (0600).

    An already existing file is truncated and, on POSIX, restricted to the owner too.
    Raises ``OSError`` like ``open``.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    try:
        handle = os.fdopen(fd, "wb")
    except BaseException:
        os.close(fd)
        raise
    ensure_private_file(path)
    return handle


def encrypt_credential_with_dpapi(value: str, *, machine_scope: bool = False) -> str:
    """Return ``value`` as the base64 DPAPI blob expected in ``<VAR>_DPAPI``.

    The blob can be decrypted by the current Windows user only, or with ``machine_scope``
    by every account on this machine. Raises ``dpapi.DpapiError`` off Windows.
    """
    blob = dpapi.protect(value.encode("utf-8"), machine_scope=machine_scope)
    return base64.b64encode(blob).decode("ascii")


def _decrypt_dpapi_credential(env_var: str, encoded: str) -> str:
    """Decrypt the base64 DPAPI blob found in ``<env_var>_DPAPI``."""
    dpapi_var = f"{env_var}{DPAPI_SUFFIX}"
    retry_hint = f"Set the credential again with '{SET_CREDENTIAL_COMMAND} {env_var}'."
    if not dpapi.is_available():
        raise CredentialSourceError(
            f"{dpapi_var} is set, but DPAPI-encrypted credentials are only supported on "
            f"Windows; use {env_var} or {env_var}{FILE_SUFFIX} instead."
        )
    try:
        blob = base64.b64decode(encoded.strip(), validate=True)
    except (binascii.Error, ValueError) as e:
        raise CredentialSourceError(f"{dpapi_var} is not valid base64. {retry_hint}") from e
    try:
        content = dpapi.unprotect(blob).decode("utf-8")
    except dpapi.DpapiError as e:
        raise CredentialSourceError(
            f"{dpapi_var} cannot be decrypted by this Windows account; it was encrypted by "
            f"another user or on another machine, or the value is damaged. {retry_hint}"
        ) from e
    except UnicodeDecodeError as e:
        raise CredentialSourceError(
            f"{dpapi_var} does not decrypt to valid UTF-8 text. {retry_hint}"
        ) from e
    if not content:
        raise CredentialSourceError(f"{dpapi_var} decrypts to an empty value. {retry_hint}")
    return content


def read_credential_from_env(env_var: str) -> tuple[str | None, str | None]:
    """Read a credential from ``<env_var>``, ``<env_var>_FILE`` or ``<env_var>_DPAPI``.

    Returns ``(value, source_var)``, or ``(None, None)`` if none is set (an empty
    string counts as unset). Raises ``CredentialSourceError`` if more than one is set,
    the file is unreadable or empty, or the DPAPI blob cannot be decrypted.
    """
    file_var = f"{env_var}{FILE_SUFFIX}"
    dpapi_var = f"{env_var}{DPAPI_SUFFIX}"
    plain = os.getenv(env_var) or None
    file_path = os.getenv(file_var) or None
    encrypted = os.getenv(dpapi_var) or None

    set_vars = [
        name
        for name, value in ((env_var, plain), (file_var, file_path), (dpapi_var, encrypted))
        if value is not None
    ]
    if len(set_vars) > 1:
        if len(set_vars) == 2:  # noqa: PLR2004
            raise CredentialSourceError(
                f"Both {set_vars[0]} and {set_vars[1]} are set; unset one of them."
            )
        raise CredentialSourceError(
            f"{', '.join(set_vars[:-1])} and {set_vars[-1]} are all set; keep only one of them."
        )
    if plain is not None:
        return plain, env_var
    if encrypted is not None:
        return _decrypt_dpapi_credential(env_var, encrypted), dpapi_var
    if file_path is not None:
        return _read_credential_file(env_var, file_path), file_var
    return None, None


def _read_credential_file(env_var: str, file_path: str) -> str:
    """Return the content of the secret file that ``<env_var>_FILE`` points to."""
    file_var = f"{env_var}{FILE_SUFFIX}"
    try:
        # utf-8-sig drops a BOM, as written e.g. by PowerShell.
        content = Path(file_path).read_bytes().decode("utf-8-sig")
    except OSError as e:
        raise CredentialSourceError(
            f"{file_var} points to '{file_path}', which cannot be read: {e.strerror or e}."
        ) from e
    except UnicodeDecodeError as e:
        raise CredentialSourceError(
            f"{file_var} points to '{file_path}', which cannot be read: not valid UTF-8."
        ) from e

    if env_var not in RAW_CREDENTIAL_ENV_VARS:
        if content.endswith("\r\n"):
            content = content[:-2]
        elif content.endswith("\n"):
            content = content[:-1]
    if not content:
        raise CredentialSourceError(f"{file_var} points to '{file_path}', which is empty.")
    return content


def with_file_sourced_placeholders(
    config_class: type[BaseModel], config: dict[str, Any]
) -> dict[str, Any]:
    """Return a copy of ``config`` with a placeholder for every indirectly sourced credential.

    A credential field gets ``"<from <VAR>_FILE>"`` (or ``"<from <VAR>_DPAPI>"``) when
    ``config`` has no non-empty value for it, ``<VAR>`` is unset or empty and ``<VAR>_FILE``
    (or ``<VAR>_DPAPI``) is set. The file is never read and the blob never decrypted: this
    lets the wizard validate a config whose secret only ``start`` will load.
    """
    result = dict(config)
    for field, env_var in credential_fields(config_class).items():
        if result.get(field) or os.getenv(env_var):
            continue
        for source_var in (f"{env_var}{FILE_SUFFIX}", f"{env_var}{DPAPI_SUFFIX}"):
            if os.getenv(source_var):
                result[field] = f"<from {source_var}>"
                break
    return result


def resolve_credentials(
    config_class: type[BaseModel], config: dict[str, Any], *, config_label: str
) -> dict[str, Any]:
    """Return a copy of ``config`` with credentials taken from the environment sources.

    A value from ``<VAR>``, ``<VAR>_FILE`` or ``<VAR>_DPAPI`` replaces the configured one.
    A credential found in the config logs a warning (never including the value). Raises
    ``CredentialSourceError`` if a source is conflicting, unreadable, empty or cannot be
    decrypted.
    """
    resolved = dict(config)
    for field, env_var in credential_fields(config_class).items():
        configured = config.get(field)
        in_config = isinstance(configured, str) and bool(configured)
        value, source_var = read_credential_from_env(env_var)
        if value is not None:
            resolved[field] = value
        if in_config:
            message = (
                f"Jira credential '{field}' is stored in {config_label}; "
                f"move it to .env ({env_var}) or use {env_var}{FILE_SUFFIX}."
            )
            if value is not None:
                message += f" The configured value is ignored: {source_var} overrides it."
            logger.warning(message)
    return resolved

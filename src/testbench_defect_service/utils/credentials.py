"""Credential sources for client configs: environment variables and ``<VAR>_FILE`` secret files."""

import os
from pathlib import Path
from typing import Any, BinaryIO

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from testbench_defect_service.log import logger

__all__ = [
    "FILE_SUFFIX",
    "RAW_CREDENTIAL_ENV_VARS",
    "CredentialSourceError",
    "credential_fields",
    "ensure_private_file",
    "is_credential_field",
    "logger",
    "open_private_file",
    "read_credential_from_env",
    "resolve_credentials",
]

FILE_SUFFIX = "_FILE"

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


def read_credential_from_env(env_var: str) -> tuple[str | None, str | None]:
    """Read a credential from ``<env_var>`` or the file named by ``<env_var>_FILE``.

    Returns ``(value, source_var)``, or ``(None, None)`` if neither is set (an empty
    string counts as unset). Raises ``CredentialSourceError`` if both are set, or the
    file is unreadable or empty.
    """
    file_var = f"{env_var}{FILE_SUFFIX}"
    plain = os.getenv(env_var) or None
    file_path = os.getenv(file_var) or None

    if plain is not None and file_path is not None:
        raise CredentialSourceError(f"Both {env_var} and {file_var} are set; unset one of them.")
    if plain is not None:
        return plain, env_var
    if file_path is None:
        return None, None

    try:
        content = Path(file_path).read_bytes().decode("utf-8")
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
    return content, file_var


def resolve_credentials(
    config_class: type[BaseModel], config: dict[str, Any], *, config_label: str
) -> dict[str, Any]:
    """Return a copy of ``config`` with credentials taken from environment or ``_FILE`` sources.

    An environment/``_FILE`` value replaces the configured one. A credential found in the
    config logs a warning (never including the value). Raises ``CredentialSourceError``
    if a source is conflicting, unreadable or empty.
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

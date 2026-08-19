from pathlib import Path
from typing import Any

import click
import tomli_w
from pydantic import BaseModel, ValidationError

from testbench_defect_service.clients.excel.config import ExcelDefectClientConfig
from testbench_defect_service.clients.jira.config import AUTH_OAUTH2_3LO, JiraDefectClientConfig
from testbench_defect_service.clients.jira.jira_oauth import (
    has_cached_refresh_token,
    seed_oauth2_refresh_token,
)
from testbench_defect_service.models.config import DefectServiceConfig
from testbench_defect_service.utils.auth import create_credentials
from testbench_defect_service.utils.config import CONFIG_PREFIX
from testbench_defect_service.utils.config_wizard import (
    merge_with_defaults,
    run_jira_oauth_wizard,
    setup_authentication,
    store_client_secret_in_env,
)
from testbench_defect_service.utils.dependencies import check_client_dependencies
from testbench_defect_service.utils.wizard import SCHEMA_KEYS, get_field_extra, prompt_model_fields

EXCEL_CLIENT_CLASS = "testbench_defect_service.clients.ExcelDefectClient"
JIRA_CLIENT_CLASS = "testbench_defect_service.clients.JiraDefectClient"

#: Which legacy wrapper format each file extension stands for.
LEGACY_SOURCE_TYPES: dict[str, str] = {".conf": "jira", ".properties": "excel"}

# The legacy wrappers were configured per system by an administrator, so a file that says
# nothing about writing must not convert into a client that writes.
READONLY_ALIASES = ("readonly", "readOnly")


class ConfConversionError(Exception):
    """Exception raised for errors in the configuration conversion process."""


AUTH_TYPE_FIELD = "auth_type"
SERVER_URL_FIELD = "server_url"

# Legacy .conf keys that map onto a `JiraDefectClientConfig` field. Everything not listed
# here is left to the model's own default, so this only has to cover what the .conf knows.
CONF_FIELD_KEYS: dict[str, tuple[str, ...]] = {
    "name": ("wrapper.name",),
    SERVER_URL_FIELD: ("jira.baseUri",),
    "defect_jql": ("jira.baseQuery",),
    "readonly": ("wrapper.readonly",),
    "timeout": ("wrapper.timeout_seconds",),
}

# Legacy .conf keys that can pre-fill a prompt default. They are only used when
# present, so an unknown legacy layout simply yields no default.
CONF_DEFAULT_KEYS: dict[str, tuple[str, ...]] = {
    SERVER_URL_FIELD: CONF_FIELD_KEYS[SERVER_URL_FIELD],
    "username": ("jira.username", "jira.user", "jira.login"),
}


def parse_conf_file(file_path: Path) -> dict[str, Any]:
    """
    Parses a configuration file and returns its contents as a dictionary.

    Args:
        file_path (Path): The path to the configuration file.
    """
    config: dict[str, Any] = {}

    try:
        if not file_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {file_path}")
        with file_path.open("r", encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if line and not line.startswith("#"):
                    key, value = line.split(":", 1)
                    config[key.strip()] = value.strip().removeprefix('"').removesuffix('"')
    except Exception as e:
        raise ConfConversionError(f"Failed to parse configuration file: {e}") from e

    return config


def parse_properties_file(file_path: Path) -> dict[str, Any]:
    """
    Parses a .properties configuration file and returns its contents as a dictionary.

    Args:
        file_path (Path): The path to the .properties configuration file.
    """
    config: dict[str, Any] = {}

    try:
        if not file_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {file_path}")
        with file_path.open("r", encoding="utf-8") as file:
            for line in file:
                raw_line = line.strip()
                if raw_line and not raw_line.startswith(("#", "!")):
                    key, value = line.split("=", 1)
                    config[key.strip()] = value.strip()
    except Exception as e:
        raise ConfConversionError(f"Failed to parse configuration file: {e}") from e

    return config


def auth_field_names() -> set[str]:
    """Return the server URL, ``auth_type`` and every field whose ``depends_on`` names it.

    Which of the dependent fields are actually asked for is decided by the wizard at
    runtime from the chosen ``auth_type``, so this only has to bound the prompts to the
    connection and authentication part of the model — SSL and timeout settings stay out.

    ``server_url`` belongs here even though the legacy .conf supplies it:
    ``prompt_model_fields`` validates its answers against the whole
    ``JiraDefectClientConfig``, in which it is the one required field. Leaving it out makes
    that validation fail with ``server_url: Field required``, and because the field can then
    never be filled in, the wizard's retry loop restarts forever.
    """
    names = {SERVER_URL_FIELD, AUTH_TYPE_FIELD}
    for field_name, field_info in JiraDefectClientConfig.model_fields.items():
        dependency = get_field_extra(field_info).get(SCHEMA_KEYS["DEPENDS_ON"])
        if isinstance(dependency, dict) and AUTH_TYPE_FIELD in dependency:
            names.add(field_name)
    return names


def fields_from_conf(
    conf_data: dict[str, Any], key_map: dict[str, tuple[str, ...]]
) -> dict[str, Any]:
    """Collect the legacy entries named by *key_map*, keyed by model field name.

    The first key present for a field wins, and absent or empty entries are skipped so
    the model's own default applies instead of an empty string.
    """
    fields: dict[str, Any] = {}
    for field_name, conf_keys in key_map.items():
        for conf_key in conf_keys:
            value = conf_data.get(conf_key)
            if value not in (None, ""):
                fields[field_name] = value
                break
    return fields


def conf_defaults(conf_data: dict[str, Any]) -> dict[str, Any]:
    """Translate legacy .conf entries into prompt defaults keyed by model field name."""
    return fields_from_conf(conf_data, CONF_DEFAULT_KEYS)


def prompt_jira_auth_config(conf_data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Ask how to authenticate against Jira and collect the credentials that implies.

    Delegates the prompting to the config wizard's ``prompt_model_fields`` restricted
    to the authentication fields of ``JiraDefectClientConfig``, so the auth types
    offered, the dependent credentials, masked input, environment-variable handling
    and validation all behave exactly as in ``testbench-defect-service configure``.
    The Jira server URL is part of the prompts because the credentials are validated
    against it; it is pre-filled from the legacy .conf.

    Args:
        conf_data (dict | None): Parsed legacy .conf data used for prompt defaults.

    Returns:
        The collected connection and auth fields, or ``None`` when the user aborts or
        the jira extra is not installed.
    """
    conf_data = conf_data or {}

    try:
        check_client_dependencies("jira", raise_on_missing=True)
    except ImportError as e:
        click.echo(f"\n{e}\n")
        return None

    auth_config = prompt_model_fields(
        JiraDefectClientConfig,
        existing_config=conf_defaults(conf_data),
        section_label="Jira Authentication",
        allowed_fields=auth_field_names(),
    )
    if auth_config is None:
        return None

    finalize_jira_oauth2(auth_config)
    return auth_config


def finalize_jira_oauth2(auth_config: dict[str, Any]) -> None:
    """Apply the config wizard's post-prompt OAuth2 handling to *auth_config*.

    For the 3LO flow the refresh token is seeded into the token cache (obtaining one
    through the OAuth wizard when neither the prompt nor the cache provided it), and
    the OAuth2 client secret is moved into ``.env`` instead of the generated TOML.
    Mutates *auth_config* in place.
    """
    if str(auth_config.get(AUTH_TYPE_FIELD) or "").startswith(AUTH_OAUTH2_3LO):
        # The model declares oauth2_refresh_token as exclude=True: it belongs in the
        # token cache, not in a config file.
        refresh_token = auth_config.pop("oauth2_refresh_token", None)
        if not (isinstance(refresh_token, str) and refresh_token) and (
            not has_cached_refresh_token()
        ):
            refresh_token = run_jira_oauth_wizard(auth_config)
        if isinstance(refresh_token, str) and refresh_token:
            seed_oauth2_refresh_token(refresh_token)

    store_client_secret_in_env(auth_config)


def _describe_validation_errors(error: ValidationError) -> str:
    """Render a ValidationError as a single ``field: message`` line per problem."""
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc']) or '<config>'}: {item['msg']}"
        for item in error.errors()
    )


def build_client_config(
    config_class: type[BaseModel], legacy_config: dict[str, Any], source: str
) -> dict[str, Any]:
    """Validate *legacy_config* against *config_class* and return it as a TOML-ready dict.

    The client config models read the legacy key names themselves - through the
    ``AliasChoices`` on each field and, for Excel, the ``mode="before"`` normalization that
    reassembles control fields, transitions and UDFs. Validating here is therefore the whole
    conversion: values arrive typed instead of as property strings, unset options fall back to
    the model's documented defaults via ``merge_with_defaults`` rather than to a second set of
    defaults kept in this module, and anything the client would reject at startup is reported
    now, while the .conf file being converted is still on screen.
    """
    if not any(alias in legacy_config for alias in READONLY_ALIASES):
        legacy_config = {**legacy_config, "readonly": True}
    try:
        return merge_with_defaults(legacy_config, config_class)
    except ValidationError as e:
        raise ConfConversionError(
            f"Cannot convert {source}: {_describe_validation_errors(e)}"
        ) from e


def prompt_service_credentials() -> tuple[str, str] | None:
    """Ask for the service login and derive a fresh password hash and salt from it.

    The legacy wrappers know nothing about these credentials - they protect the defect
    service's own HTTP API, not the defect tracker behind it - so there is nothing to carry
    over from the file being converted. Asking here is what makes the generated config
    usable as written: the hash and salt are renewed from the password entered now.

    Returns:
        The ``(password_hash, salt)`` pair to write, or ``None`` when the user aborts.
    """
    click.echo("\n🔐 Service Credentials\n")
    click.echo("These log in to the defect service itself, not to the defect tracker.\n")

    username, password = setup_authentication()
    if username is None or password is None:
        return None

    return create_credentials(username, password)


def build_service_toml(
    client_class: str, client_config: dict[str, Any], credentials: tuple[str, str]
) -> str:
    """Wrap a validated client config in a ``DefectServiceConfig`` and dump it as TOML.

    Host, port, logging and server settings come from the service model's defaults, so the
    generated file matches what ``testbench-defect-service configure`` would write. The
    service credentials are asked for unless a ``(password_hash, salt)`` pair is supplied.

    Raises:
        ConfConversionError: When the interactive credentials setup is cancelled.
    """

    password_hash, salt = credentials
    service_config = DefectServiceConfig(
        client_class=client_class,
        client_config=client_config,
        password_hash=password_hash,
        salt=salt,
    )
    return tomli_w.dumps({CONFIG_PREFIX: service_config.model_dump(mode="json", exclude_none=True)})


def generate_jira_base_toml(
    conf_data: dict[str, Any],
    auth_config: dict[str, Any] | None = None,
    credentials: tuple[str, str] | None = None,
) -> str:
    """
    Generates a TOML string for the Jira base configuration.

    Args:
        conf_data (dict): The configuration data.
        auth_config (dict | None): Authentication fields to write; a ``server_url``
            in it takes precedence over the one from the .conf. When omitted, the
            authentication type and the credentials it needs are asked for interactively.
        credentials (tuple | None): The service ``(password_hash, salt)`` to write. When
            omitted, the service login is asked for and the pair is generated from it.

    Raises:
        ConfConversionError: When the interactive authentication or credentials setup is
            cancelled, or when the result is not a valid ``JiraDefectClientConfig``.
    """
    if credentials is None:
        credentials = prompt_service_credentials()
        if credentials is None:
            raise ConfConversionError("Service credentials setup was cancelled")

    if auth_config is None:
        auth_config = prompt_jira_auth_config(conf_data)
        if auth_config is None:
            raise ConfConversionError("Jira authentication setup was cancelled")

    client_config = build_client_config(
        JiraDefectClientConfig,
        {**fields_from_conf(conf_data, CONF_FIELD_KEYS), **auth_config},
        "the Jira .conf file",
    )
    return build_service_toml(JIRA_CLIENT_CLASS, client_config, credentials)


def generate_excel_base_toml(
    properties: dict[str, Any], credentials: tuple[str, str] | None = None
) -> str:
    """
    Generates a TOML string for the Excel base configuration.

    Args:
        properties (dict): The parsed legacy `.properties` data, in its own key spelling.
        credentials (tuple | None): The service ``(password_hash, salt)`` to write. When
            omitted, the service login is asked for and the pair is generated from it.

    Raises:
        ConfConversionError: When the interactive credentials setup is cancelled, or when the
            result is not a valid ``ExcelDefectClientConfig``.
    """
    # Validate before asking for a login: an unconvertible file must say so without
    # making the user enter a password first.
    client_config = build_client_config(
        ExcelDefectClientConfig, properties, "the Excel .properties file"
    )

    if credentials is None:
        credentials = prompt_service_credentials()
        if credentials is None:
            raise ConfConversionError("Service credentials setup was cancelled")

    return build_service_toml(EXCEL_CLIENT_CLASS, client_config, credentials)


def detect_source_type(legacy_path: Path) -> str | None:
    """Return the legacy wrapper format implied by *legacy_path*'s extension, if any."""
    return LEGACY_SOURCE_TYPES.get(legacy_path.suffix.lower())


def convert_legacy_config(legacy_path: Path, source_type: str | None = None) -> str:
    """Convert a legacy wrapper configuration file into a service TOML document.

    Pairs each legacy format with the parser that reads its key spelling and the generator
    that validates it against the matching client model, so callers only supply the file.

    Args:
        legacy_path (Path): The legacy ``.conf`` or ``.properties`` file to convert.
        source_type (str | None): ``"jira"`` or ``"excel"``. Detected from the file
            extension when omitted.

    Raises:
        ConfConversionError: When the format cannot be detected, when the file cannot be
            parsed, when an interactive setup step is cancelled, or when the result is not
            a valid client configuration.
    """
    source_type = source_type or detect_source_type(legacy_path)

    if source_type == "jira":
        return generate_jira_base_toml(parse_conf_file(legacy_path))
    if source_type == "excel":
        return generate_excel_base_toml(parse_properties_file(legacy_path))

    known = ", ".join(sorted(set(LEGACY_SOURCE_TYPES.values())))
    raise ConfConversionError(
        f"Cannot tell the legacy format of '{legacy_path.name}' from its extension. "
        f"Name the source type explicitly ({known})."
    )

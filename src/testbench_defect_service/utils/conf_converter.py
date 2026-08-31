import re
from pathlib import Path
from typing import Any, NamedTuple

import click
import tomli_w
from pydantic import AliasChoices, BaseModel, ValidationError

from testbench_defect_service.clients.excel.config import (
    LEGACY_COMPOSITE_KEY_PATTERNS,
    ExcelDefectClientConfig,
)
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


#: Every legacy .conf key spelling the conversion reads, from either map above. Anything
#: else in a .conf file lands nowhere, which `report_unsupported_keys` reports.
CONF_KEYS_READ: frozenset[str] = frozenset(
    key for keys in (*CONF_FIELD_KEYS.values(), *CONF_DEFAULT_KEYS.values()) for key in keys
)


class _LegacyLineFormat(NamedTuple):
    """How one legacy wrapper format writes a flat `key<separator>value` line."""

    separator: str
    #: How an entry is spelled in this format, quoted back at the user in a parse error.
    line_example: str
    comment_prefixes: tuple[str, ...]
    strip_quotes: bool
    #: The separator, name and `--type` of the *other* format, so a file migrated as the
    #: wrong one can be told apart from a genuinely broken line.
    other_separator: str
    other_description: str
    other_source_type: str


_CONF_LINE_FORMAT = _LegacyLineFormat(
    separator=":",
    line_example="key: value",
    comment_prefixes=("#",),
    strip_quotes=True,
    other_separator="=",
    other_description="an Excel .properties file",
    other_source_type="excel",
)

_PROPERTIES_LINE_FORMAT = _LegacyLineFormat(
    separator="=",
    line_example="key=value",
    comment_prefixes=("#", "!"),
    strip_quotes=False,
    other_separator=":",
    other_description="a Jira .conf file",
    other_source_type="jira",
)


def _wrong_format_hint(line: str, line_format: _LegacyLineFormat) -> str:
    """Suggest the other `--type` when *line* is separated the other format's way.

    A wrapper file migrated as the wrong format fails on its very first entry, and the
    fix is a different `--type` rather than an edit to the file.
    """
    if line_format.other_separator not in line:
        return ""
    return (
        f" This line uses '{line_format.other_separator}' - is this "
        f"{line_format.other_description}? Migrate it with "
        f"--type {line_format.other_source_type}."
    )


def _parse_legacy_file(file_path: Path, line_format: _LegacyLineFormat) -> dict[str, Any]:
    """Read a flat legacy configuration file into a dictionary of raw string values.

    Every rejection names the file and the line number, because a legacy file is edited by
    hand and the user has to be able to find the entry being complained about.

    Raises:
        ConfConversionError: When the file is missing or unreadable, when a line carries no
            separator, or when a key is set twice to different values.
    """
    if not file_path.exists():
        raise ConfConversionError(f"Configuration file not found: {file_path}")

    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise ConfConversionError(f"Failed to read {file_path.name}: {e}") from e

    config: dict[str, Any] = {}
    for number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith(line_format.comment_prefixes):
            continue

        if line_format.separator not in line:
            raise ConfConversionError(
                f"{file_path.name} line {number}: expected "
                f"'{line_format.line_example}', got '{line}'."
                f"{_wrong_format_hint(line, line_format)}"
            )

        raw_key, raw_value = line.split(line_format.separator, 1)
        key = raw_key.strip()
        value = raw_value.strip()
        if line_format.strip_quotes:
            value = value.removeprefix('"').removesuffix('"')

        previous = config.get(key)
        if previous is not None and previous != value:
            raise ConfConversionError(
                f"{file_path.name} line {number}: '{key}' is set twice, to '{previous}' and "
                f"'{value}'. Remove one of them before migrating."
            )
        config[key] = value

    return config


def parse_conf_file(file_path: Path) -> dict[str, Any]:
    """
    Parses a legacy Jira `.conf` file and returns its contents as a dictionary.

    Args:
        file_path (Path): The path to the configuration file.
    """
    return _parse_legacy_file(file_path, _CONF_LINE_FORMAT)


def parse_properties_file(file_path: Path) -> dict[str, Any]:
    """
    Parses a legacy `.properties` file and returns its contents as a dictionary.

    Args:
        file_path (Path): The path to the .properties configuration file.
    """
    return _parse_legacy_file(file_path, _PROPERTIES_LINE_FORMAT)


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


def recognized_legacy_keys(config_class: type[BaseModel]) -> set[str]:
    """Return every key spelling *config_class* reads: field names and validation aliases.

    The legacy key names live on the model itself, as the `AliasChoices` of each field, so
    asking the model is what keeps this from becoming a second list to maintain.
    """
    names: set[str] = set()
    for field_name, field_info in config_class.model_fields.items():
        names.add(field_name)
        alias = field_info.validation_alias
        if isinstance(alias, AliasChoices):
            names.update(str(choice) for choice in alias.choices)
        elif isinstance(alias, str):
            names.add(alias)
        if field_info.alias:
            names.add(field_info.alias)
    return names


def report_unsupported_keys(
    legacy_config: dict[str, Any],
    keys_read: set[str] | frozenset[str],
    composite_patterns: tuple[re.Pattern[str], ...] = (),
) -> list[str]:
    """Echo the legacy entries that nothing in the conversion reads, and return their keys.

    Both client models are `extra="ignore"`, so a legacy setting with no equivalent here is
    dropped without a word and the migration still reports success. Naming the keys is what
    lets the user tell a complete migration from a partial one - and the file being
    converted stays on disk, so a setting that mattered can be applied by hand.

    Which spellings count as read differs per format, so the caller says: a `.properties`
    file is handed to the model whole, and `recognized_legacy_keys` describes it, while a
    `.conf` file is read by this module's own key maps and the model never sees its keys -
    passing the model's fields for a `.conf` would silently accept a legacy `password`
    entry that nothing carries over.

    Args:
        legacy_config (dict): The legacy entries, in their own key spelling.
        keys_read (set): Every key spelling the conversion reads for this format.
        composite_patterns (tuple): Patterns for keys a `mode="before"` validator folds
            into a nested model, which no alias mentions.
    """
    recognized = set(keys_read)
    unsupported = sorted(
        key
        for key in legacy_config
        if key not in recognized
        and not any(pattern.fullmatch(key) for pattern in composite_patterns)
    )

    if unsupported:
        _echo_unsupported_report(unsupported)

    return unsupported


def _echo_unsupported_report(unsupported: list[str]) -> None:
    """Print *unsupported* as a framed block, one key per line.

    The migration ends in a wall of prompts and a success message, so a warning that is
    only two lines long is read as part of the noise. This is the one thing on screen the
    user has to act on, so it is framed like the wizard's own section headings, coloured,
    and listed one key per line - a comma-separated run of a dozen keys is skipped, not
    read.
    """
    rule = "═" * 60
    click.echo(f"\n{rule}")
    click.secho(
        f"⚠️  {len(unsupported)} legacy setting(s) were NOT carried over", fg="yellow", bold=True
    )
    click.echo(rule)
    for key in unsupported:
        click.secho(f"  • {key}", fg="yellow")
    click.echo("\nNothing in the new configuration reads them. The legacy file is unchanged,")
    click.echo("so anything that still matters can be applied to the new file by hand.")
    click.echo(f"{rule}\n")


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
    report_unsupported_keys(conf_data, CONF_KEYS_READ)
    return build_service_toml(JIRA_CLIENT_CLASS, client_config, credentials)


def _absolute(path: str) -> str:
    """Return *path* as an absolute path, resolved against the current directory.

    A legacy wrapper may name its defect data relative to wherever it was started from.
    Carried over verbatim, that relative path would later be resolved against the service's
    working directory instead - a different directory whenever the service runs as a Windows
    service. Resolving it here pins it to the directory ``migrate`` was run in, which is the
    one the path was written for.
    """
    return str(Path(path).resolve())


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
    client_config["excel_file_path"] = _absolute(client_config["excel_file_path"])

    if credentials is None:
        credentials = prompt_service_credentials()
        if credentials is None:
            raise ConfConversionError("Service credentials setup was cancelled")

    # Reported after the last prompt, as in `generate_jira_base_toml`: printed before the
    # login it would scroll off behind the password entry, and it would describe a
    # configuration a cancelled login never writes.
    report_unsupported_keys(
        properties, recognized_legacy_keys(ExcelDefectClientConfig), LEGACY_COMPOSITE_KEY_PATTERNS
    )
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

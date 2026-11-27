import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

import click
import questionary
from dotenv import dotenv_values, set_key, unset_key
from pydantic import BaseModel

from testbench_defect_service.clients.jira.config import AUTH_OAUTH2_3LO
from testbench_defect_service.clients.jira.jira_oauth import (
    JiraAuthExpiredError,
    data_center_token_url,
    exchange_authorization_code_sync,
    seed_oauth2_refresh_token,
)
from testbench_defect_service.clients.utils import (
    get_client_config_class,
    get_defect_client_from_client_class_str,
)
from testbench_defect_service.models.config import DEFAULT_HOST, DEFAULT_PORT, DefectServiceConfig
from testbench_defect_service.utils import dpapi
from testbench_defect_service.utils.auth import create_credentials, save_credentials
from testbench_defect_service.utils.config import (
    CONFIG_PREFIX,
    create_config_backup_file,
    get_client_config,
    load_service_config,
    save_client_config,
    save_toml_config,
    update_config_files,
)
from testbench_defect_service.utils.credentials import (
    DPAPI_SUFFIX,
    FILE_SUFFIX,
    CredentialSourceError,
    credential_fields,
    encrypt_credential_with_dpapi,
    ensure_private_file,
    read_credential_from_env,
    with_file_sourced_placeholders,
)
from testbench_defect_service.utils.dependencies import check_client_dependencies
from testbench_defect_service.utils.wizard import get_env_sourced_field_names, prompt_model_fields

MAX_PORT = 65535
CLIENT_CLASSES = {
    "jsonl": "testbench_defect_service.clients.JsonlDefectClient",
    "excel": "testbench_defect_service.clients.ExcelDefectClient",
    "jira": "testbench_defect_service.clients.JiraDefectClient",
}
SERVICE_WIZARD_SKIP_FIELDS = {
    "client_class",
    "client_config",
    "client_config_path",
    "password_hash",
    "salt",
    "logging",
}

DEFAULT_DOTENV_PATH = Path(".env")

STORAGE_PLAIN = "plain"
STORAGE_DPAPI_USER = "dpapi-user"
STORAGE_DPAPI_MACHINE = "dpapi-machine"
CREDENTIAL_STORAGES = (STORAGE_PLAIN, STORAGE_DPAPI_USER, STORAGE_DPAPI_MACHINE)
STORAGE_NOTES = {
    STORAGE_PLAIN: "",
    STORAGE_DPAPI_USER: " (encrypted for this Windows user)",
    STORAGE_DPAPI_MACHINE: " (encrypted for this machine)",
}


def validate_port(value: Any) -> tuple[bool, str | None]:
    try:
        port_value = int(value)
    except (TypeError, ValueError):
        return False, "Enter a valid port number"

    if 1 <= port_value <= MAX_PORT:
        return True, None
    return False, f"Port must be between 1 and {MAX_PORT}"


def backup_config_file(config_path: Path) -> bool:
    """Backup existing configuration file."""
    if not config_path.exists():
        return True

    click.echo(f"⚠️  Found existing configuration: {config_path.name}")
    overwrite = questionary.confirm(
        "Do you want to reconfigure? (existing files will be backed up)", default=False
    ).ask()

    if not overwrite:
        click.echo("Configuration cancelled. Existing files preserved.")
        return False

    backup_path = create_config_backup_file(config_path)
    click.echo(f"✓ Backed up {config_path.name} to {backup_path.name}")
    click.echo()
    return True


def setup_authentication(
    existing_username: str | None = None,
    prompt_for_password: bool = True,
) -> tuple[str | None, str | None]:
    """Configure service credentials (username/password)."""
    username = questionary.text("Enter username:", default=existing_username or "admin").ask()

    if username is None:
        return None, None

    if not prompt_for_password:
        return username, None

    while True:
        password = questionary.password("Enter password:").ask()
        if password is None:
            return None, None

        password_confirm = questionary.password("Confirm password:").ask()
        if password_confirm is None:
            return None, None

        if password == password_confirm:
            return username, password

        click.echo("❌ Passwords do not match. Please try again.\n")


def get_client_class(client_type: str) -> str | None:
    if client_type == "custom":
        client_class: str | None = questionary.text(
            "Enter the full class path to your custom client class:",
            default="custom_client.py",
        ).ask()
        if client_class is None:
            return None
        try:
            get_defect_client_from_client_class_str(client_class)
            return client_class
        except Exception as e:
            click.echo(f"❌ Error: Could not load custom client class: {e}")
            return None
    return CLIENT_CLASSES.get(client_type)


def merge_with_defaults(
    config_dict: dict[str, Any],
    config_class: type[BaseModel],
    exclude_fields: set[str] | None = None,
) -> dict[str, Any]:
    """Merge user-provided config with model defaults to create complete config.

    This ensures all fields (including defaults) are written to config files,
    eliminating 'magic' values that only exist in code.
    Fields whose values are sourced from environment variables are excluded so
    that sensitive values are not persisted to the config file. Credential fields are
    always excluded: the environment, ``.env`` or ``<VAR>_FILE`` supplies them.

    Args:
        config_dict: User-provided configuration values
        config_class: Pydantic model class with field defaults
        exclude_fields: Optional set of field names to exclude from output

    Returns:
        Complete configuration dict with all fields (user values + defaults), TOML-serializable
    """
    config_obj = config_class.model_validate(
        with_file_sourced_placeholders(config_class, config_dict)
    )
    env_sourced = get_env_sourced_field_names(config_class)
    merged_exclude = (exclude_fields or set()) | env_sourced | set(credential_fields(config_class))
    exclude: set[str] | None = merged_exclude if merged_exclude else None
    return config_obj.model_dump(mode="json", by_alias=True, exclude_none=True, exclude=exclude)


def choose_credential_storage() -> str | None:
    """Ask how credentials are stored in ``.env``; plain text without asking off Windows.

    Returns one of the ``STORAGE_*`` values, or ``None`` if the prompt was cancelled.
    """
    if not dpapi.is_available():
        return STORAGE_PLAIN
    storage: str | None = questionary.select(
        "How should the credentials be stored in .env?",
        choices=[
            questionary.Choice(
                "🔒 Encrypted for this Windows user (recommended)", STORAGE_DPAPI_USER
            ),
            questionary.Choice(
                "🔒 Encrypted for this machine (for a service running under another account; "
                "every user on this machine can decrypt)",
                STORAGE_DPAPI_MACHINE,
            ),
            questionary.Choice("📄 Plain text", STORAGE_PLAIN),
        ],
    ).ask()
    return storage


def write_credential_to_env(env_var: str, value: str, dotenv_path: Path, storage: str) -> str:
    """Write one credential to ``dotenv_path`` and the process environment.

    With a DPAPI ``storage`` the value is encrypted and written as ``<env_var>_DPAPI``,
    otherwise as ``<env_var>`` in plain text. The other variants of the variable
    (``<env_var>``, ``_FILE``, ``_DPAPI``) are removed from the file and the process
    environment, since ``start`` refuses more than one source. Returns the variable written.
    Raises ``dpapi.DpapiError`` if the value cannot be encrypted.
    """
    if storage == STORAGE_PLAIN:
        target, stored_value = env_var, value
    else:
        target = f"{env_var}{DPAPI_SUFFIX}"
        stored_value = encrypt_credential_with_dpapi(
            value, machine_scope=storage == STORAGE_DPAPI_MACHINE
        )

    ensure_private_file(dotenv_path)
    set_key(str(dotenv_path), target, stored_value)
    os.environ[target] = stored_value
    in_dotenv = dotenv_values(dotenv_path, interpolate=False)
    for suffix in ("", FILE_SUFFIX, DPAPI_SUFFIX):
        other = f"{env_var}{suffix}"
        if other == target:
            continue
        if other in in_dotenv:
            unset_key(str(dotenv_path), other)
        os.environ.pop(other, None)
    ensure_private_file(dotenv_path)  # python-dotenv rewrites the file
    return target


def store_credentials_in_env(
    config: dict[str, Any],
    config_class: type[BaseModel],
    dotenv_path: Path = DEFAULT_DOTENV_PATH,
    storage: str | None = None,
) -> list[str]:
    """Always store credentials in an owner-only .env file, never in the config file.

    Every credential field of ``config_class`` with a non-empty string value in ``config`` is
    written to ``dotenv_path``, exported to the current process environment, and removed from
    ``config``. ``storage`` is one of the ``STORAGE_*`` values; if it is ``None`` and there is
    something to store, the user is asked (on Windows only, elsewhere plain text is used).
    Plain text goes under the environment variable itself, a DPAPI-encrypted value under
    ``<VAR>_DPAPI``. Because ``merge_with_defaults`` excludes fields whose variable is set,
    the secrets are thereby kept out of the generated config file while the config still
    validates.

    Mutates ``config`` in place. Returns the names of the credentials' environment variables
    (without the ``_DPAPI`` suffix; empty if there was nothing to store, in which case nothing
    is created or printed). Raises ``click.Abort`` if the storage prompt is cancelled.
    """
    to_store = {
        field: (env_var, config[field])
        for field, env_var in credential_fields(config_class).items()
        if isinstance(config.get(field), str) and config[field]
    }
    if not to_store:
        return []
    if storage is None:
        storage = choose_credential_storage()
        if storage is None:
            raise click.Abort

    stored: list[str] = []
    for field, (env_var, value) in to_store.items():
        target = write_credential_to_env(env_var, value, dotenv_path, storage)
        config.pop(field)
        stored.append(env_var)
        click.echo(f"✓ Stored {target} in {dotenv_path}{STORAGE_NOTES[storage]}")

    if storage == STORAGE_PLAIN:
        for env_var, value in to_store.values():
            if "${" in value:
                click.echo(
                    f"⚠️  {env_var} contains '${{', which .env files interpolate; if the value "
                    f"is not loaded correctly, use {env_var}{FILE_SUFFIX} instead."
                )
    click.echo("  Keep this file out of version control (e.g. add '.env' to .gitignore).")
    return stored


def _prompt_new_credential_value(env_var: str) -> str | None:
    """Ask twice for the new value of ``env_var``; ``None`` if cancelled or left empty."""
    while True:
        value = questionary.password(f"Enter the new value for {env_var}:").ask()
        if not value:
            return None
        confirmation = questionary.password("Confirm the new value:").ask()
        if confirmation is None:
            return None
        if value == confirmation:
            return str(value)
        click.echo("❌ The values do not match. Please try again.\n")


def _client_credential_env_vars(config_path: Path) -> list[str]:
    """Return the credential environment variables of the client configured in ``config_path``.

    Raises ``click.ClickException`` if the file is missing or the client has no credentials.
    """
    if not config_path.exists():
        raise click.ClickException(f"Configuration file not found: {config_path}")
    client_class = load_service_config(config_path).client_class
    try:
        config_class = get_client_config_class(client_class)
    except (ImportError, TypeError, ValueError) as e:
        raise click.ClickException(f"Unable to load the client configuration: {e}") from e
    env_vars = list(credential_fields(config_class).values()) if config_class else []
    if not env_vars:
        raise click.ClickException(f"The configured client ({client_class}) has no credentials.")
    return env_vars


def set_client_credential(
    config_path: Path,
    env_var: str | None = None,
    storage: str | None = None,
    dotenv_path: Path = DEFAULT_DOTENV_PATH,
) -> None:
    """Set or replace one credential of the configured client in ``.env``.

    ``env_var`` is the credential's environment variable (e.g. ``JIRA_PASSWORD``); it is
    asked for if omitted. Raises ``click.ClickException`` for an unknown credential, a
    client without credentials, or a value that cannot be encrypted.
    """
    env_vars = _client_credential_env_vars(config_path)
    if storage is not None and storage != STORAGE_PLAIN and not dpapi.is_available():
        raise click.ClickException("DPAPI encryption is only available on Windows.")

    if env_var is None:
        env_var = questionary.select("Which credential do you want to set?", choices=env_vars).ask()
    elif env_var.upper() not in env_vars:
        raise click.ClickException(
            f"Unknown credential '{env_var.upper()}'. Choose one of: {', '.join(env_vars)}."
        )
    value = _prompt_new_credential_value(env_var.upper()) if env_var else None
    if value and storage is None:
        storage = choose_credential_storage()
    if not env_var or not value or storage is None:
        click.echo("\nCancelled. Nothing was changed.")
        return
    env_var = env_var.upper()

    in_dotenv = dotenv_values(dotenv_path, interpolate=False) if dotenv_path.exists() else {}
    set_outside_dotenv = [
        name
        for name in (env_var, f"{env_var}{FILE_SUFFIX}", f"{env_var}{DPAPI_SUFFIX}")
        if os.getenv(name) and name not in in_dotenv
    ]
    try:
        target = write_credential_to_env(env_var, value, dotenv_path, storage)
    except dpapi.DpapiError as e:
        raise click.ClickException(f"Could not encrypt {env_var}: {e.strerror or e}") from e

    click.echo(f"\n✓ Stored {target} in {dotenv_path}{STORAGE_NOTES[storage]}")
    for name in set_outside_dotenv:
        if name != target:
            click.echo(
                f"⚠️  {name} is also set in the environment outside {dotenv_path}; unset it, "
                "otherwise the service refuses to start because both are set."
            )
    if storage == STORAGE_PLAIN and "${" in value:
        click.echo(
            f"⚠️  {env_var} contains '${{', which .env files interpolate; if the value "
            f"is not loaded correctly, use {env_var}{FILE_SUFFIX} instead."
        )
    click.echo("Restart the service to use the new value.")


def _report_moved_credentials(
    existing_credentials: list[str], config_class: type[BaseModel], stored: list[str]
) -> None:
    """Tell the user which credentials from the existing config now live in the .env file."""
    env_vars = credential_fields(config_class)
    for name in existing_credentials:
        if env_vars[name] in stored:
            click.echo(
                f"✓ Moved '{name}' out of the configuration file into {DEFAULT_DOTENV_PATH} "
                f"({env_vars[name]})"
            )


def load_existing_client_config(config_class: type[BaseModel], existing: dict) -> dict:
    """Validate an existing client config and dump it, without credential placeholders.

    Credentials supplied only through ``<VARIABLE>_FILE`` are validated with a placeholder
    (the file is never read). Afterwards every credential key is restored to its raw value
    from ``existing`` or removed, so a placeholder never reaches prompts or the config file.
    """
    validated = config_class.model_validate(
        with_file_sourced_placeholders(config_class, existing)
    ).model_dump()
    for name in credential_fields(config_class):
        if name in existing:
            validated[name] = existing[name]
        else:
            validated.pop(name, None)
    return validated


def configure_client(
    client_type: str, client_class: str, service_config: DefectServiceConfig | None = None
) -> dict | None:
    """Universal client configurator for built-in clients like JSONL, Excel, and Jira."""
    try:
        check_client_dependencies(client_type, raise_on_missing=True)
    except ImportError as e:
        click.echo(f"\n{e}\n")
        return None

    try:
        config_class = get_client_config_class(client_class)
    except (ImportError, TypeError, ValueError) as exc:
        click.echo(f"❌ Unable to load {client_type} client configuration: {exc}")
        return None

    if config_class is None:
        click.echo(
            f"❌ Client '{client_type}' does not expose a CONFIG_CLASS for guided configuration"
        )
        return None

    existing_config = {}
    if service_config is not None:
        try:
            existing_config = get_client_config(service_config) or {}
            existing_config = load_existing_client_config(config_class, existing_config)
        except Exception:
            pass

    existing_credentials = [
        name for name in credential_fields(config_class) if existing_config.get(name)
    ]

    client_config = prompt_model_fields(
        config_class,
        existing_config=existing_config,
        section_label=f"{client_type.title()} Client Configuration",
    )

    if client_config is None:
        return None

    if client_type == "jira" and str(client_config.get("auth_type") or "").startswith(
        AUTH_OAUTH2_3LO
    ):
        refresh_token = client_config.get("oauth2_refresh_token")
        if isinstance(refresh_token, str) and refresh_token:
            seed_oauth2_refresh_token(refresh_token)

    stored = store_credentials_in_env(client_config, config_class, dotenv_path=DEFAULT_DOTENV_PATH)
    _report_moved_credentials(existing_credentials, config_class, stored)

    return merge_with_defaults(client_config, config_class)


def ask_for_separate_config(client_type: str, existing_path: Path | None = None) -> str | None:
    """Ask user if they want to use a separate configuration file.

    Args:
        client_type: The type of client (jsonl, jira, custom)
        existing_path: Path to existing separate config file if any

    Returns:
        Path to separate config file, or None for inline config
    """
    if existing_path:
        click.echo(f"\nCurrent config location: {existing_path}")
        change_location = questionary.confirm(
            "Do you want to change the configuration location?", default=False
        ).ask()

        if not change_location:
            return str(existing_path)

    use_separate = questionary.confirm(
        "Do you want to use a separate configuration file?", default=False
    ).ask()

    if not use_separate:
        return None

    if client_type == "excel":
        default_path = "excel_config.properties"
    else:
        default_path = f"{client_type}_config.toml"

    config_file_path = questionary.text(
        "Enter path for separate config file:", default=default_path
    ).ask()

    if not config_file_path:
        return None

    config_path = Path(config_file_path)
    parent_dir = config_path.parent
    if not parent_dir.exists():
        try:
            parent_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            click.echo(f"⚠️  Warning: Cannot create directory {parent_dir}: {e}")
            click.echo("Using inline configuration instead.")
            return None

    return str(config_file_path)


def configure_service_only(config_path: Path):
    """Configure service settings (host, port, debug, etc.)."""
    click.echo("\n🌐 Service Configuration\n")

    service_config = load_service_config(config_path)

    click.echo(f"Current: http://{service_config.host}:{service_config.port}\n")

    updates = prompt_model_fields(
        DefectServiceConfig,
        existing_config=service_config.model_dump(),
        skip_fields=SERVICE_WIZARD_SKIP_FIELDS,
        field_overrides={"port": {"validate": validate_port}},
    )

    if updates is None:
        click.echo("\nConfiguration cancelled.")
        return

    click.echo()

    update_config_files(config_path, updates=updates)

    click.echo("\n✅ Service configuration updated successfully!")


def configure_credentials_only(
    config_path: Path, username: str | None = None, password: str | None = None
):
    """Configure service credentials (username/password)."""
    click.echo("\n🔐 Service Credentials Configuration\n")

    if not username or not password:
        username, collected_password = setup_authentication(
            existing_username=username, prompt_for_password=(password is None)
        )
        password = collected_password if collected_password else password
        if username is None or password is None:
            click.echo("\nConfiguration cancelled.")
            return

    password_hash, salt = create_credentials(username, password)
    save_credentials(password_hash, salt, config_path)
    click.echo("\n✅ Service credentials updated successfully!")


def get_client_type(client_class: str) -> str | None:
    """Infer client type from a client class path or name.

    Matches in order of specificity per client type:
    1. Exact full path (e.g. ``"testbench_defect_service.clients.JiraDefectClient"``)
    2. Exact class name segment (e.g. ``"JiraDefectClient"``)
    3. Exact client type keyword, case-insensitive (e.g. ``"jira"`` or ``"Jira"``)
    """
    if "." in client_class and not client_class.endswith(".py"):
        class_name = client_class.rsplit(".", 1)[-1]
    else:
        class_name = client_class

    for client_type, known_class in CLIENT_CLASSES.items():
        if client_class == known_class:
            return client_type
        if class_name == known_class.rsplit(".", 1)[-1]:
            return client_type
        if class_name.lower() == client_type:
            return client_type

    return None


def configure_client_only(config_path: Path):
    """Configure client settings only."""
    click.echo("\n📚 Client Configuration\n")

    service_config = load_service_config(config_path)

    client_class_path = service_config.client_class
    client_type = get_client_type(client_class_path) or "custom"
    click.echo(f"Current client type: {client_type.capitalize()}\n")

    change_client_type = questionary.confirm(
        "Do you want to change the client type?", default=False
    ).ask()
    if change_client_type is None:
        click.echo("\nConfiguration cancelled.")
        return

    if change_client_type:
        click.echo()
        client_type = questionary.select(
            "Select client type:",
            choices=[
                questionary.Choice("📄 JSONL Files", "jsonl"),
                questionary.Choice("🔗 Jira", "jira"),
                questionary.Choice("⚙️  Custom Client", "custom"),
            ],
        ).ask()
        if client_type is None:
            click.echo("\nConfiguration cancelled.")
            return

    if client_type == "custom" and not change_client_type:
        client_class = client_class_path
    else:
        raw_client_class = get_client_class(client_type)
        if raw_client_class is None:
            click.echo("\nConfiguration cancelled.")
            return
        client_class = raw_client_class

    client_config = configure_client(client_type, client_class, service_config)
    if client_config is None:
        click.echo("\nConfiguration cancelled.")
        return

    click.echo()

    client_config_path = ask_for_separate_config(client_type, service_config.client_config_path)
    if client_config_path:
        save_client_config(client_config, Path(client_config_path))

    updates: dict[str, Any] = {
        "client_class": client_class,
        "client_config_path": client_config_path,
    }
    update_config_files(config_path, updates=updates, client_config=client_config)

    click.echo("\n✅ Client configuration updated successfully!")


def is_sensitive_config_key(key: str) -> bool:
    """Check if a config key contains sensitive data (passwords, tokens, etc)."""
    sensitive_keys = {
        "password",
        "password_hash",
        "salt",
        "token",
        "api_token",
        "bearer_token",
        "oauth1_access_token",
        "oauth1_access_token_secret",
        "oauth1_consumer_key",
        "oauth1_key_cert",
        "oauth2_client_secret",
        "client_secret",
    }
    key_lower = key.lower()
    return any(sensitive in key_lower for sensitive in sensitive_keys)


def print_nested_config(config: dict[str, Any], indent: int = 0, parent_key: str = "") -> None:
    """Recursively print nested configuration dictionaries in TOML-like format.

    Args:
        config: Dictionary to print
        indent: Current indentation level
        parent_key: Parent key path for nested sections
    """
    for key, value in config.items():
        if isinstance(value, dict):
            section_path = f"{parent_key}.{key}" if parent_key else key
            click.echo(f"\n[{CONFIG_PREFIX}.{section_path}]")
            print_nested_config(value, indent, section_path)
        elif is_sensitive_config_key(key):
            click.echo(f"{key} = {'*' * 10}")
        else:
            click.echo(f"{key} = {value}")


def view_service_config(config_path: Path) -> DefectServiceConfig | None:
    """Display service configuration and return service config."""
    if not config_path.exists():
        click.echo(f"❌ No {config_path.name} found")
        return None

    service_config = load_service_config(config_path)

    click.echo(f"⚙️  Service Configuration ({config_path.name})")
    click.echo("─" * 50)
    click.echo(f"[{CONFIG_PREFIX}]")

    for key, value in service_config.model_dump(mode="json", exclude_none=True).items():
        if key == "client_config":
            continue
        if is_sensitive_config_key(key):
            click.echo(f"{key} = {'*' * 10}")
        elif isinstance(value, dict):
            print_nested_config(value, indent=0, parent_key=key)
        else:
            click.echo(f"{key} = {value}")

    return service_config


def view_client_config(service_config: DefectServiceConfig):
    """Display client configuration (separate file or inline)."""

    client_config_path = service_config.client_config_path
    if client_config_path and Path(client_config_path).exists():
        click.echo(f"⚙️  Client Configuration ({client_config_path})")
        click.echo("─" * 50)
    elif client_config_path:
        click.echo(f"❌ Client config file not found: {client_config_path}")
    else:
        click.echo("⚙️  Client Configuration")
        click.echo("─" * 50)
        click.echo(f"[{CONFIG_PREFIX}.client_config]")

    client_config = get_client_config(service_config)
    if not client_config:
        click.echo("❌ No client config found")
        return

    for key, value in client_config.items():
        click.echo(f"{key} = {'*' * 10}" if is_sensitive_config_key(key) else f"{key} = {value}")


def view_env_config(dotenv_path: Path = Path(".env")) -> None:
    """Display .env file contents.

    Args:
        dotenv_path: Path to the .env file (defaults to '.env' in current directory)
    """
    if not dotenv_path.exists():
        click.echo(f"❌ No {dotenv_path.name} file found")
        return

    click.echo(f"⚙️  Environment Variables ({dotenv_path.name})")
    click.echo("─" * 50)

    try:
        with dotenv_path.open(encoding="utf-8") as f:
            for line in f:
                line_stripped = line.rstrip()
                if line_stripped and not line_stripped.startswith("#") and "=" in line_stripped:
                    key = line_stripped.split("=", 1)[0]
                    if is_sensitive_config_key(key):
                        click.echo(f"{key}={'*' * 10}")
                    else:
                        click.echo(line_stripped)
    except (OSError, UnicodeDecodeError) as e:
        click.echo(f"❌ Error reading {dotenv_path.name}: {e}")


def view_current_config(config_path: Path):
    """Display current configuration (service, client, env)."""
    service_config = view_service_config(config_path)
    click.echo()
    if service_config is not None:
        view_client_config(service_config)
    click.echo()
    view_env_config()
    click.echo()


def show_main_menu(config_path: Path) -> str | None:
    """Show main menu and return selected mode."""
    click.echo("What would you like to do?\n")

    choices = [questionary.Choice("🚀 Full setup (first-time configuration)", "full")]

    if config_path.exists():
        choices.append(questionary.Choice("🌐 Update service settings", "service"))
        choices.append(questionary.Choice("🔐 Update service credentials", "credentials"))
        choices.append(questionary.Choice("📚 Update client configuration", "client"))
        choices.append(questionary.Choice("👁️  View current configuration", "view"))

    choices.append(questionary.Choice("❌ Quit", "quit"))

    mode: str | None = questionary.select("Choose an option:", choices=choices).ask()

    return mode


def run_full_wizard(config_path: Path):  # noqa: C901, PLR0912, PLR0915
    """Run the complete configuration wizard (first-time setup)."""
    click.echo("This wizard will help you configure the TestBench Defect Service.")
    click.echo("Press Ctrl+C at any time to cancel.\n")

    service_config: dict[str, Any] = {}

    if not backup_config_file(config_path):
        return

    click.echo("🌐 Step 1: Service Configuration\n")

    service_updates = prompt_model_fields(
        DefectServiceConfig,
        skip_fields=SERVICE_WIZARD_SKIP_FIELDS,
        field_overrides={"port": {"validate": validate_port}},
        allowed_fields={"host", "port"},
    )

    if service_updates is None:
        click.echo("\nConfiguration cancelled.")
        return

    service_config.update(service_updates)

    click.echo("\n🔐 Step 2: Service Credentials Setup\n")
    click.echo("The service requires credentials for API access.\n")

    username, password = setup_authentication()

    if username is None or password is None:
        click.echo("\nConfiguration cancelled.")
        return

    password_hash, salt = create_credentials(username, password)
    service_config["password_hash"] = password_hash
    service_config["salt"] = salt

    click.echo("\n📚 Step 3: Select Defect Source\n")

    client_type: str = questionary.select(
        "Where are your defects stored?",
        choices=[
            questionary.Choice("📄 JSONL Files (lightweight, file-based storage)", "jsonl"),
            questionary.Choice("🔗 Jira (connect to Atlassian Jira)", "jira"),
            questionary.Choice("⚙️  Custom Client (your own implementation)", "custom"),
        ],
    ).ask()

    click.echo(f"\n📝 Step 4: Configure {client_type.capitalize()} Client\n")

    client_class = get_client_class(client_type)
    if client_class is None:
        click.echo("\nConfiguration cancelled.")
        return

    client_config = configure_client(client_type, client_class)
    if client_config is None:
        click.echo("\nConfiguration cancelled.")
        return

    service_config["client_class"] = client_class

    click.echo()

    client_config_path = ask_for_separate_config(client_type)

    click.echo("\n📋 Configuration Summary\n")
    click.echo("─" * 60)
    click.echo(f"Client Type:          {client_type.upper()}")
    click.echo(f"Client Class:         {client_class}")
    if client_config_path:
        click.echo(f"Config Location:      {client_config_path} (separate file)")
    else:
        click.echo(f"Config Location:      Inline in {config_path.name}")
    if host := service_config.get("host"):
        click.echo(f"Service Host:         {host}")
    if port := service_config.get("port"):
        click.echo(f"Service Port:         {port}")
    if username:
        click.echo(f"Username:             {username}")
        click.echo(f"Password:             {'*' * len(password)}")
    click.echo("─" * 60)

    click.echo("\nFiles to be created:")
    click.echo(f"  • {config_path.name:20s} (application configuration)")
    if client_config_path:
        click.echo(f"  • {client_config_path:20s} (client configuration)")
    click.echo()

    confirm = questionary.confirm("Create configuration files?", default=True).ask()

    if not confirm:
        click.echo("\nConfiguration cancelled.")
        return

    click.echo("\n⚙️  Generating configuration files...\n")

    if client_config_path:
        # Save to separate file
        service_config["client_config_path"] = client_config_path
        save_client_config(client_config, Path(client_config_path))
        click.echo(f"✓ Created {client_config_path}")
    else:
        # Add client config inline to [testbench-requirement-service.client_config]
        service_config["client_config"] = client_config

    service_config = merge_with_defaults(service_config, DefectServiceConfig)
    config_dict: dict[str, Any] = {CONFIG_PREFIX: service_config}
    save_toml_config(config_dict, config_path)
    click.echo(f"✓ Created {config_path.name}")

    click.echo("\n" + "═" * 60)
    click.echo("✅ Configuration completed successfully!")
    click.echo("═" * 60)
    click.echo("\nNext steps:")
    click.echo("  1. Review the generated configuration files")
    click.echo("  2. Start the service with: testbench-defect-service start")
    click.echo(
        "  3. Access the API documentation at: "
        f"http://{host or DEFAULT_HOST}:{port or DEFAULT_PORT}/docs"
    )
    click.echo()


_OAUTH_CHOICE_REFRESH_TOKEN = "Enter a refresh token (Jira Cloud)"
_OAUTH_CHOICE_AUTH_CODE = "Exchange an authorization code (Jira Data Center)"


def run_jira_oauth_wizard(client_config: dict | None = None) -> str | None:
    """Obtain a Jira OAuth2 refresh token interactively.

    Offers two paths: paste an existing refresh token (Jira Cloud), or exchange
    a 3LO authorization code + PKCE verifier against the Jira Data Center token
    endpoint. Returns the refresh token, or ``None`` when the user aborts or
    the exchange fails.
    """
    click.echo("Jira OAuth2 refresh token is not configured. ")
    choice = questionary.select(
        "How would you like to provide OAuth2 authorization?",
        choices=[_OAUTH_CHOICE_REFRESH_TOKEN, _OAUTH_CHOICE_AUTH_CODE],
    ).ask()

    if choice == _OAUTH_CHOICE_REFRESH_TOKEN:
        refresh_token = questionary.password("Please enter your OAuth2 refresh token: ").ask()
        return refresh_token if isinstance(refresh_token, str) and refresh_token else None

    if choice == _OAUTH_CHOICE_AUTH_CODE:
        while True:
            refresh_token = _run_jira_dc_code_exchange(client_config or {})
            if refresh_token:
                return refresh_token
            retry = questionary.confirm(
                "Retry the authorization code exchange?", default=False
            ).ask()
            if not retry:
                return None

    return None


def _run_jira_dc_code_exchange(client_config: dict) -> str | None:
    """Prompt for code/verifier/redirect URI and exchange them at the DC endpoint."""
    server_url = client_config.get("server_url") or ""
    client_id = client_config.get("oauth2_client_id") or os.getenv("JIRA_OAUTH2_CLIENT_ID")
    client_secret = client_config.get("oauth2_client_secret")
    source_error = ""
    if not client_secret:
        try:
            client_secret, _ = read_credential_from_env("JIRA_OAUTH2_CLIENT_SECRET")
        except CredentialSourceError as e:
            source_error = f" ({e})"
    if not server_url or not client_id or not client_secret:
        click.echo(
            "Cannot exchange the authorization code: server_url and OAuth2 client "
            f"credentials must be configured first.{source_error}"
        )
        return None

    code = questionary.text("Enter the authorization code: ").ask()
    code_verifier = questionary.text("Enter the PKCE code_verifier: ").ask()
    redirect_uri = questionary.text(
        "Enter the redirect URI used in the authorization request: "
    ).ask()
    if not all(isinstance(v, str) and v for v in (code, code_verifier, redirect_uri)):
        return None

    token_url = data_center_token_url(server_url)
    try:
        return exchange_authorization_code_sync(
            token_url=token_url,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            code=code,
            code_verifier=code_verifier,
        )
    except JiraAuthExpiredError:
        click.echo(
            "Token exchange failed (HTTP 400/401). Authorization codes are single-use "
            "and short-lived — generate a new code and try again."
        )
        return None
    except HTTPError as exc:
        click.echo(
            f"Token exchange failed: HTTP {exc.code} from {token_url}. "
            "Check that an incoming OAuth 2.0 application link is configured in Jira "
            "Data Center and that server_url is correct."
        )
        return None
    except URLError as exc:
        click.echo(
            f"Token exchange failed: could not reach {token_url} ({exc.reason}). "
            "Check that server_url is correct and the Jira Data Center instance is "
            "reachable."
        )
        return None

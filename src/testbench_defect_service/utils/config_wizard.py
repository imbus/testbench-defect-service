from pathlib import Path
from typing import Any

import click
import questionary
from pydantic import BaseModel

from testbench_defect_service.clients.utils import (
    get_client_config_class,
    get_defect_client_from_client_class_str,
)
from testbench_defect_service.models.config import DEFAULT_HOST, DEFAULT_PORT, DefectServiceConfig
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
    that sensitive values are not persisted to the config file.

    Args:
        config_dict: User-provided configuration values
        config_class: Pydantic model class with field defaults
        exclude_fields: Optional set of field names to exclude from output

    Returns:
        Complete configuration dict with all fields (user values + defaults), TOML-serializable
    """
    config_obj = config_class.model_validate(config_dict)
    env_sourced = get_env_sourced_field_names(config_class)
    merged_exclude = (exclude_fields or set()) | env_sourced
    exclude: set[str] | None = merged_exclude if merged_exclude else None
    return config_obj.model_dump(mode="json", by_alias=True, exclude_none=True, exclude=exclude)


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
            existing_config = config_class.model_validate(existing_config).model_dump()
        except Exception:
            pass

    client_config = prompt_model_fields(
        config_class,
        existing_config=existing_config,
        section_label=f"{client_type.title()} Client Configuration",
    )

    if client_config is None:
        return None

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
        client_class = get_client_class(client_type)
        if client_class is None:
            click.echo("\nConfiguration cancelled.")
            return

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
        with dotenv_path.open() as f:
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

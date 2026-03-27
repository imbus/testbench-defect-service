import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import javaproperties
import tomli_w
from pydantic import ValidationError

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

try:
    import javaproperties  # type: ignore[import-not-found]
except ImportError:
    javaproperties = None  # type: ignore[assignment]

from testbench_defect_service.models.config import DefectServiceConfig

CONFIG_PREFIX = "testbench-defect-service"


def create_default_config_file(output_path: str, force: bool = False):
    """
    Write the default config to a TOML configuration file.

    Args:
        output_path: Path where the configuration file will be saved.
        force: Overwrite existing file if True.
    """
    default_config_json = DefectServiceConfig().model_dump_json(exclude_none=True)
    default_config = json.loads(default_config_json)
    create_config_file(config=default_config, output_path=output_path, force=force)


def create_config_file(
    config: DefectServiceConfig | dict,
    output_path: str | Path,
    config_prefix: str = CONFIG_PREFIX,
    force: bool = False,
):
    """
    Write the given config object to a TOML configuration file.

    Args:
        config: Settings instance or dict representing configuration.
        output_path: Path where the configuration file will be saved.
        config_prefix: String prefix to nest config under (default: 'testbench-defect-service')
        force: Overwrite existing file if True.
    """
    output_path = Path(output_path)
    if output_path.exists() and not force:
        click.echo(
            f"Configuration file already exists at '{output_path.resolve()}'. "
            "Use --force to overwrite existing file."
        )
        sys.exit(1)

    config_data = config.model_dump() if isinstance(config, DefectServiceConfig) else config
    to_serialize = {config_prefix: config_data}
    toml_str = tomli_w.dumps(to_serialize)
    output_path.write_text(toml_str, encoding="utf-8")

    click.echo(f"Configuration file created at '{output_path.resolve()}'.")


def print_config_errors(
    e: ValidationError,
    config_path: Path | None = None,
    config_prefix: str | None = CONFIG_PREFIX,
):
    """
    Print user-friendly config validation errors from a pydantic ValidationError.

    This function processes all validation errors in a pydantic ValidationError instance,
    formatting each error message to show only the field name and its context
    (TOML section or file).

    Args:
        e: Pydantic ValidationError with error details
        config_path: Optional path to the configuration file, used for error messages
        config_prefix: Optional TOML section name (e.g., "testbench-defect-service")
    """
    for error in e.errors():
        loc = [str(loc) for loc in error["loc"]]
        field_name = loc[-1] if loc else None

        error_type = error.get("type", "")
        if error_type == "missing":
            msg = (
                f"Missing required field '{field_name}'" if field_name else "Missing required field"
            )
            detail = None
        else:
            msg = f"Invalid field '{field_name}'" if field_name else "Invalid configuration"
            detail = error.get("msg")

        if config_path is not None:
            msg += f" in file '{config_path.resolve()}'"
        if config_prefix is not None:
            section_parts = [config_prefix, *loc[:-1]] if config_prefix else loc[:-1]
            section = ".".join(section_parts) if section_parts else config_prefix
            msg += f" in TOML section [{section}]"

        click.echo(f"Configuration Error: {msg}")
        if detail:
            click.echo(f"  Detail: {detail}")
        click.echo()


def load_config_from_toml_file(
    config_path: Path, config_prefix: str = CONFIG_PREFIX
) -> DefectServiceConfig:
    """
    This function reads a TOML configuration file, extracts the section specified
    by `config_prefix`, and validates it against the `DefectServiceConfig` model.

    Args:
        config_path (Path): Path to the TOML configuration file.
        config_prefix (str): The top-level section in the TOML file containing the app config.

    Returns:
        DefectServiceConfig: An instance of the validated application configuration.
    """
    if not config_path.exists():
        click.echo(f"Configuration file not found at: '{config_path.resolve()}'.")
        sys.exit(1)

    try:
        with config_path.open("rb") as config_file:
            config_dict = tomllib.load(config_file)
    except tomllib.TOMLDecodeError as e:
        click.echo(
            f"Configuration Error: The configuration file contains invalid TOML syntax.\nDetails: {e}"  # noqa: E501
        )
        sys.exit(1)

    if config_prefix not in config_dict:
        click.echo(
            f"Configuration Error: TOML section [{config_prefix}] not found in the configuration file."  # noqa: E501
        )
        sys.exit(1)

    try:
        return DefectServiceConfig(**config_dict[config_prefix])
    except ValidationError as e:
        print_config_errors(e, config_path=config_path, config_prefix=config_prefix)
        sys.exit(1)


def resolve_config_file_path(config_path: Path | str | None) -> Path:
    """Determine which config file to load."""

    if config_path:
        return Path(config_path)

    toml_path = Path("config.toml")
    if toml_path.exists():
        return toml_path

    return toml_path


def load_service_config(config_path: Path | str | None = None) -> DefectServiceConfig:
    if not config_path:
        config_file_path = resolve_config_file_path(config_path)
    else:
        config_file_path = Path(config_path)
    return load_config_from_toml_file(config_file_path)


def load_toml_config(config_path: Path) -> dict[str, Any]:
    """Load TOML configuration if the config file exists."""
    if not config_path.exists():
        return {}

    try:
        with config_path.open("rb") as config_file:
            return tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as e:
        click.echo(f"⚠️  Error loading {config_path}: {e}")
        return {}


def load_properties_config(config_path: Path) -> dict[str, Any]:
    """Load .properties configuration if the config file exists."""
    if not config_path.exists() or javaproperties is None:
        return {}

    try:
        with config_path.open("r") as config_file:
            return javaproperties.load(config_file)  # type: ignore[no-any-return]
    except (OSError, UnicodeDecodeError) as e:
        click.echo(f"⚠️  Error loading {config_path}: {e}")
        return {}


def load_client_config_from_file(config_path: Path) -> dict:
    """Load client configuration from a separate file (TOML or properties format).

    Args:
        config_path: Path to the client config file (.toml or .properties)

    Returns:
        Dictionary containing client configuration

    Raises:
        ValueError: If file format is unsupported or file not found
    """
    if not config_path.exists():
        raise ValueError(f"Client config file not found: '{config_path}'")

    suffix = config_path.suffix.lower()
    if suffix == ".toml":
        config = load_toml_config(config_path)
        if CONFIG_PREFIX in config and "client_config" in config[CONFIG_PREFIX]:
            client_cfg: dict[Any, Any] = config[CONFIG_PREFIX]["client_config"]
            return client_cfg
        return config
    if suffix == ".properties":
        return load_properties_config(config_path)

    raise ValueError(
        f"Unsupported client config file format: '{suffix}'. Supported formats: .toml, .properties"
    )


def get_client_config(service_config: DefectServiceConfig) -> dict:
    """
    Get client configuration from either service config or a separate client config file.

    Priority:
    1. If client_config_path points to a separate file that exists, load from there
    2. Otherwise, use client_config dict from service_config
    """
    if service_config.client_config_path:
        client_config_file = Path(service_config.client_config_path)
        if client_config_file.exists():
            return load_client_config_from_file(client_config_file)
        return {}
    return service_config.client_config or {}


def create_config_backup_file(config_path: Path) -> Path:
    """Create a timestamped backup of the existing config file."""
    backup_path = Path(f"{config_path}.backup")
    if backup_path.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = Path(f"{config_path}.backup.{timestamp}")
    config_path.rename(backup_path)
    return backup_path


def save_toml_config(config_dict: dict, config_path: Path):
    """Save configuration to TOML configuration file.

    Note: config_dict should already be TOML-serializable (use Pydantic's model_dump(mode='json')).
    """
    try:
        with config_path.open("wb") as config_file:
            tomli_w.dump(config_dict, config_file)
    except (OSError, TypeError, ValueError) as e:
        click.echo(f"❌ Error saving TOML config to {config_path}: {e}")


def save_properties_config(config_dict: dict, config_path: Path):
    """Save configuration to .properties configuration file.

    Note: config_dict should already be serializable (use Pydantic's model_dump(mode='json')).
    All values will be converted to strings as required by properties format.
    """
    # Convert all values to strings for properties file format
    str_config = {}
    for key, value in config_dict.items():
        if value is None:
            continue
        if isinstance(value, bool):
            str_config[key] = "true" if value else "false"
        else:
            str_config[key] = str(value)

    if javaproperties:
        try:
            with config_path.open("w") as config_file:
                javaproperties.dump(str_config, config_file, timestamp=False)  # type: ignore[no-any-return]
        except (OSError, UnicodeEncodeError) as e:
            click.echo(f"❌ Error saving properties config to {config_path}: {e}")
    else:
        click.echo("⚠️  javaproperties not installed, creating as text file")
        try:
            with config_path.open("w") as f:
                for key, value in str_config.items():
                    f.write(f"{key}={value}\n")
        except OSError as e:
            click.echo(f"❌ Error saving properties config to {config_path}: {e}")


def save_service_config(config: DefectServiceConfig, config_path: Path):
    """Save service configuration to TOML config file."""
    config_dict = {CONFIG_PREFIX: config.model_dump(mode="json", exclude_none=True)}
    save_toml_config(config_dict, config_path)


def save_client_config(client_config: dict, client_config_path: Path):
    """Save client config to separate file."""
    if client_config_path.suffix == ".toml":
        save_toml_config(client_config, client_config_path)
    elif client_config_path.suffix == ".properties":
        save_properties_config(client_config, client_config_path)


def update_config_files(
    config_path: Path,
    updates: dict,
    client_config: dict | None = None,
):
    """Update specific fields in config file while preserving others.

    Args:
        config_path: Path to the main config file
        updates: Dictionary of fields to update in service config section
        client_config: Optional client configuration to save to separate file or inline.
                      If None, client config is not modified.
    """
    service_config = load_service_config(config_path)

    config_data = service_config.model_dump()
    config_data.update(updates)
    updated_config = DefectServiceConfig.model_validate(config_data)

    if client_config is not None:
        if updated_config.client_config_path:
            save_client_config(client_config, Path(updated_config.client_config_path))
            updated_config.client_config = {}
        else:
            updated_config.client_config = client_config
    elif updated_config.client_config_path:
        updated_config.client_config = {}

    save_service_config(updated_config, config_path)

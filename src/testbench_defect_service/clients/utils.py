import sys
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib
try:  # noqa: SIM105
    import javaproperties
except ImportError:
    pass

from testbench_defect_service.clients.abstract_client import AbstractDefectClient
from testbench_defect_service.utils.helper import (
    get_project_root,
    import_class_from_file_path,
    import_class_from_module_str,
)

T = TypeVar("T")


def load_toml_config_from_path(config_path: Path) -> dict[str, Any]:
    """
    Load client config from a .toml file.

    Args:
        config_path: Path to the .toml config file.

    Returns:
        dict[str, Any]: Parsed TOML content.

    Raises:
        ImportError: If the file can't be read or parsing fails.
    """
    try:
        with config_path.open("rb") as config_file:
            return tomllib.load(config_file)
    except Exception as e:
        raise ImportError(f"Importing client config from '{config_path}' failed.") from e


def load_properties_config_from_path(config_path: Path) -> dict[str, str]:
    """
    Load client config from a .properties file.

    Args:
        config_path: Path to the .properties config file.

    Returns:
        dict[str, str]: Mapping of property names to string values.

    Raises:
        ImportError: If the file can't be read or parsing fails.
    """
    try:
        with config_path.open("r") as config_file:
            return javaproperties.load(config_file)
    except Exception as e:
        raise ImportError(f"Importing client config from '{config_path}' failed.") from e


def load_client_config_from_path(
    config_path: Path, config_class: type[T], config_prefix: str | None = None
) -> T:
    """
    Load client config from a file path into an instance of config_class.

    Args:
        config_path: Path to the config file (.toml or .properties).
        config_class: Pydantic or dataclass type to instantiate with loaded config.
        config_prefix: Optional key in config dict whose value dict is the config to load.

    Returns:
        An instance of config_class populated with the config data.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        ValueError: If file format unsupported, prefix missing, or validation fails.
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Client config file not found at: '{config_path.resolve()}'")

    suffix = config_path.suffix.lower()
    if suffix == ".toml":
        config_dict = load_toml_config_from_path(config_path)
    elif suffix == ".properties":
        config_dict = load_properties_config_from_path(config_path)
    else:
        raise ValueError(
            f"Unsupported config file format: '{suffix}'. Supported formats: .toml and .properties"
        )

    if config_prefix is None:
        config_section = config_dict
    else:
        if config_prefix not in config_dict:
            raise ValueError(f"TOML section [{config_prefix}] not found in client config file.")
        config_section = config_dict[config_prefix]

    try:
        return config_class(**config_section)
    except Exception as e:
        raise ValueError(f"Invalid client config: {e}") from e


def get_client_class_from_file_path(file_path: Path) -> type[AbstractDefectClient]:
    try:
        return import_class_from_file_path(file_path, subclass_from=AbstractDefectClient)  # type: ignore
    except Exception as e:
        message = f"Failed to import custom DefectClient class from '{file_path}'."
        raise ImportError(message) from e


def get_client_class_from_module_str(
    client_name: str, default_package: str = "testbench_defect_service.clients"
) -> type[AbstractDefectClient]:
    try:
        if "." in client_name:
            return import_class_from_module_str(  # type: ignore
                client_name, subclass_from=AbstractDefectClient
            )

        return import_class_from_module_str(  # type: ignore
            default_package,
            class_name=client_name,
            subclass_from=AbstractDefectClient,
        )
    except Exception as e:
        message = f"Failed to import custom DefectClient class from '{client_name}'."
        raise ImportError(message) from e


def get_defect_client_from_client_class_str(client_class: str) -> type[AbstractDefectClient]:
    client_path = Path(client_class)
    if client_path.is_file():
        return get_client_class_from_file_path(client_path)
    local_file = Path(__file__).resolve().parent / client_path
    if local_file.is_file():
        return get_client_class_from_file_path(local_file)
    if not local_file.suffix and local_file.with_suffix(".py").is_file():
        return get_client_class_from_file_path(local_file.with_suffix(".py"))
    relative_from_root = get_project_root() / client_path
    if relative_from_root.is_file():
        return get_client_class_from_file_path(relative_from_root)
    return get_client_class_from_module_str(client_class)


def get_client_config_class(
    client_class: str | type[AbstractDefectClient],
) -> type[BaseModel] | None:
    """Resolve the CONFIG_CLASS for a client class path or type."""

    client_cls: type[AbstractDefectClient]
    if isinstance(client_class, str):
        client_cls = get_defect_client_from_client_class_str(client_class)
    else:
        client_cls = client_class

    config_class = getattr(client_cls, "CONFIG_CLASS", None)
    if config_class is None:
        return None

    if not isinstance(config_class, type) or not issubclass(config_class, BaseModel):
        raise TypeError(
            f"CONFIG_CLASS on {client_cls.__name__} must inherit from pydantic.BaseModel"
        )

    return config_class


def get_defect_client(app) -> AbstractDefectClient:
    if not getattr(app.ctx, "defect_client", None):
        defect_client_class_str = app.config.CLIENT_CLASS
        defect_client_class = get_defect_client_from_client_class_str(defect_client_class_str)
        defect_client_config = app.config.CLIENT_CONFIG
        defect_client = defect_client_class(defect_client_config)  # type: ignore
        if not isinstance(defect_client, AbstractDefectClient):
            raise ImportError(f"{defect_client_class} is no instance of AbstractDefectClient!")
        app.ctx.defect_client = defect_client
    return app.ctx.defect_client  # type: ignore

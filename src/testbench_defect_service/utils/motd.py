"""Build the client summary rows shown in the Sanic startup MOTD box."""

from collections.abc import Callable
from pathlib import Path, PurePath
from typing import Any

from pydantic import BaseModel

from testbench_defect_service.clients.excel.config import ExcelDefectClientConfig
from testbench_defect_service.clients.jira.config import JiraDefectClientConfig
from testbench_defect_service.clients.jsonl.config import JsonlDefectClientConfig
from testbench_defect_service.config import AppConfig


def _jsonl_source(reader_config: JsonlDefectClientConfig) -> str:
    return Path(reader_config.defects_path).as_posix()


def _excel_source(reader_config: ExcelDefectClientConfig) -> str:
    source = Path(reader_config.excel_file_path).as_posix()
    if reader_config.worksheet_name:
        return f"{source} ({reader_config.worksheet_name})"
    return source


def _jira_source(reader_config: JiraDefectClientConfig) -> str:
    return f"{reader_config.server_url} ({reader_config.auth_type})"


_CLIENTS: tuple[tuple[type[BaseModel], str, Callable[[Any], str]], ...] = (
    (JsonlDefectClientConfig, "JSONL", _jsonl_source),
    (ExcelDefectClientConfig, "Excel", _excel_source),
    (JiraDefectClientConfig, "Jira", _jira_source),
)


def _client_name_from_class_str(client_class: str) -> str:
    name = PurePath(client_class).name
    if name.endswith(".py"):
        return name[: -len(".py")]
    return name.rsplit(".", 1)[-1]


def build_client_motd(config: AppConfig) -> dict[str, str]:
    """Build a summary row for the given client config."""
    client_config = config.CLIENT_CONFIG

    for config_class, client_name, build_source in _CLIENTS:
        if isinstance(client_config, config_class):
            motd = {
                "client": client_name,
                "source": build_source(client_config),
            }
            break
    else:
        motd = {
            "client": _client_name_from_class_str(config.CLIENT_CLASS),
        }

    if config.CLIENT_CONFIG_PATH:
        motd["config"] = Path(config.CLIENT_CONFIG_PATH).name
    else:
        motd["config"] = f"{Path(config.CONFIG_PATH).name} [client_config]"

    return motd

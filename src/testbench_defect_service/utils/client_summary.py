"""Summarise the configured defect reader for the startup log."""

import platform
import sys
from collections.abc import Callable
from pathlib import Path, PurePath
from typing import Any

from pydantic import BaseModel

from testbench_defect_service.clients.jira.config import JiraDefectClientConfig
from testbench_defect_service.clients.jsonl.config import JsonlDefectClientConfig
from testbench_defect_service.config import AppConfig
from testbench_defect_service.log import logger

INDENT = "  "


def _jsonl_source(client_config: JsonlDefectClientConfig) -> str:
    return Path(client_config.defects_path).as_posix()


def _jira_source(client_config: JiraDefectClientConfig) -> str:
    return f"{client_config.server_url} ({client_config.auth_type})"


_CLIENTS: tuple[tuple[type[BaseModel], str, Callable[[Any], str]], ...] = (
    (JsonlDefectClientConfig, "JSONL", _jsonl_source),
    (JiraDefectClientConfig, "Jira", _jira_source),
)


def _client_name(client_class: str) -> str:
    """Derive a display name from a dotted import path or a module file path."""
    name = PurePath(client_class).name
    name = name.removesuffix(".py")
    return name.rsplit(".", 1)[-1]


def _reader_fields(config: AppConfig) -> dict[str, str]:
    """Name the configured reader and, if it is a known one, where it reads from."""
    client_config = config.CLIENT_CONFIG

    for config_class, reader_name, build_source in _CLIENTS:
        if isinstance(client_config, config_class):
            return {"Reader": reader_name, "Source": build_source(client_config)}

    return {"Reader": _client_name(config.CLIENT_CLASS)}


def _config_fields(config: AppConfig) -> dict[str, str]:
    """Name the file the reader is configured in."""
    if config.CLIENT_CONFIG_PATH:
        return {"Config": Path(config.CLIENT_CONFIG_PATH).name}
    return {"Config": f"{Path(config.CONFIG_PATH).name} [client_config]"}


def _runtime_fields() -> dict[str, str]:
    """Describe the interpreter and machine the service runs on."""
    system = " ".join(part for part in (platform.system(), platform.release()) if part)
    return {
        "Python": f"{platform.python_version()} ({platform.python_implementation()})",
        "Platform": f"{system or sys.platform} {platform.machine()}".strip(),
    }


def build_client_summary(config: AppConfig) -> dict[str, str]:
    """Build the reader/source/config/runtime summary for the given app config."""
    return {
        **_reader_fields(config),
        **_config_fields(config),
        **_runtime_fields(),
    }


def log_client_summary(config: AppConfig) -> None:
    """Log which reader is configured, where it reads from and where it is configured."""
    try:
        summary = build_client_summary(config)
    except Exception:
        logger.debug("Could not build the reader summary", exc_info=True)
        return

    width = max(len(label) for label in summary) + 1
    for label, value in summary.items():
        logger.info("%s%s %s", INDENT, f"{label}:".ljust(width), value)

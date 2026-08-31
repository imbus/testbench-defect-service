"""Tests for the startup reader summary."""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from testbench_defect_service.clients.jira.config import JiraDefectClientConfig
from testbench_defect_service.clients.jsonl.config import JsonlDefectClientConfig
from testbench_defect_service.utils.client_summary import (
    build_client_summary,
    log_client_summary,
)


def _app_config(client_config, client_class="", client_config_path=None):
    return SimpleNamespace(
        CLIENT_CONFIG=client_config,
        CLIENT_CLASS=client_class,
        CLIENT_CONFIG_PATH=client_config_path,
        CONFIG_PATH=Path("config.toml"),
    )


@pytest.fixture
def jira_config():
    return JiraDefectClientConfig(
        server_url="https://jira.imbus.de/",
        auth_type="oauth2 3LO (user account)",
        control_fields={"status": ["open"]},
        oauth2_client_id="id",
        oauth2_client_secret="secret",
        oauth2_refresh_token="refresh",
    )


class TestBuildClientSummary:
    def test_jira_reader_reports_server_and_auth_type(self, jira_config):
        summary = build_client_summary(_app_config(jira_config))

        assert summary["Reader"] == "Jira"
        assert summary["Source"] == "https://jira.imbus.de/ (oauth2 3LO (user account))"

    def test_inline_client_config_names_the_service_config_section(self, jira_config):
        summary = build_client_summary(_app_config(jira_config))

        assert summary["Config"] == "config.toml [client_config]"

    def test_separate_client_config_file_is_reported_by_name(self, jira_config):
        config = _app_config(jira_config, client_config_path=Path("conf/jira.toml"))

        assert build_client_summary(config)["Config"] == "jira.toml"

    def test_jsonl_reader_reports_the_defects_path(self, tmp_path):
        client_config = JsonlDefectClientConfig(
            defects_path=tmp_path,
            control_fields={"status": ["open"]},
        )

        summary = build_client_summary(_app_config(client_config))

        assert summary["Reader"] == "JSONL"
        assert summary["Source"] == tmp_path.as_posix()

    def test_unknown_client_falls_back_to_the_class_name(self):
        config = _app_config(
            {"name": "custom"},
            client_class="testbench_defect_service.clients.CustomDefectClient",
        )

        summary = build_client_summary(config)

        assert summary["Reader"] == "CustomDefectClient"
        assert "Source" not in summary


class TestLogClientSummary:
    def test_logs_one_indented_line_per_field(self, jira_config, caplog):
        with caplog.at_level("INFO"):
            log_client_summary(_app_config(jira_config))

        messages = [record.getMessage() for record in caplog.records]

        assert messages[:3] == [
            "  Reader:   Jira",
            "  Source:   https://jira.imbus.de/ (oauth2 3LO (user account))",
            "  Config:   config.toml [client_config]",
        ]
        assert [message.split(":")[0].strip() for message in messages[3:]] == [
            "Python",
            "Platform",
        ]

    def test_all_values_start_in_the_same_column(self, jira_config, caplog):
        with caplog.at_level("INFO"):
            log_client_summary(_app_config(jira_config))

        columns = {
            len(re.match(r"\s*\w+:\s+", record.getMessage()).group()) for record in caplog.records
        }

        assert len(columns) == 1

    def test_a_broken_config_does_not_raise(self, caplog):
        with caplog.at_level("INFO"):
            log_client_summary(object())  # type: ignore[arg-type]

        assert caplog.records == []

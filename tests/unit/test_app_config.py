from pathlib import Path

import pytest

import testbench_defect_service.config as service_config
from testbench_defect_service.clients.jira.config import JiraDefectClientConfig


@pytest.fixture
def jira_app_config() -> service_config.AppConfig:
    config = service_config.AppConfig.__new__(service_config.AppConfig)
    config.CLIENT_CLASS = "testbench_defect_service.clients.JiraDefectClient"
    return config


def _inline_jira_app_config(jira_app_config, client_config: dict):
    jira_app_config.CLIENT_CONFIG_PATH = None
    jira_app_config.CONFIG_PATH = Path("config.toml")
    jira_app_config._client_config_inline = client_config
    return jira_app_config


@pytest.mark.unit
def test_start_refuses_unreadable_credential_file_naming_only_the_variable(
    jira_app_config, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
):
    monkeypatch.delenv("JIRA_PASSWORD", raising=False)
    monkeypatch.setenv("JIRA_PASSWORD_FILE", str(tmp_path / "missing"))
    monkeypatch.setattr(
        service_config, "get_client_config_class", lambda _cls: JiraDefectClientConfig
    )
    app_config = _inline_jira_app_config(
        jira_app_config,
        {"server_url": "https://jira.example.com", "auth_type": "basic", "username": "u"},
    )

    with pytest.raises(SystemExit) as excinfo:
        app_config._validate_client_config()

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "Configuration Error: JIRA_PASSWORD_FILE points to" in out


@pytest.mark.unit
def test_start_uses_credential_file_over_config_value(
    jira_app_config, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.delenv("JIRA_PASSWORD", raising=False)
    (tmp_path / "pw").write_text("file-secret\n")
    monkeypatch.setenv("JIRA_PASSWORD_FILE", str(tmp_path / "pw"))
    monkeypatch.setattr(
        service_config, "get_client_config_class", lambda _cls: JiraDefectClientConfig
    )
    app_config = _inline_jira_app_config(
        jira_app_config,
        {
            "server_url": "https://jira.example.com",
            "auth_type": "basic",
            "username": "u",
            "password": "config-secret",
        },
    )

    client_config = app_config._validate_client_config()

    assert client_config.password == "file-secret"

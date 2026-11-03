import io
import os
import stat
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from dotenv import get_key

from testbench_defect_service.clients.jira.config import JiraDefectClientConfig
from testbench_defect_service.clients.jira.jira_oauth import JiraAuthExpiredError
from testbench_defect_service.utils import config_wizard
from testbench_defect_service.utils.config_wizard import run_jira_oauth_wizard

JIRA_CLIENT_CLASS = "testbench_defect_service.clients.JiraDefectClient"
CREDENTIAL_ENV_VARS = [
    "JIRA_PASSWORD",
    "JIRA_BEARER_TOKEN",
    "JIRA_OAUTH2_CLIENT_SECRET",
    "JIRA_OAUTH1_ACCESS_TOKEN",
    "JIRA_OAUTH1_ACCESS_TOKEN_SECRET",
    "JIRA_OAUTH1_KEY_CERT",
]


@pytest.fixture(autouse=True)
def _clean_jira_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in CREDENTIAL_ENV_VARS:
        for name in (var, f"{var}_FILE"):
            # setenv first so monkeypatch records the original state and restores it on teardown
            monkeypatch.setenv(name, "")
            monkeypatch.delenv(name)


_WIZARD = "testbench_defect_service.utils.config_wizard"

_DC_CLIENT_CONFIG = {
    "server_url": "https://jira.example.com",
    "oauth2_client_id": "cid",
    "oauth2_client_secret": "csec",
}


def _mock_questionary(select_answer: str, text_answers: list[str], confirm_answer: bool = False):
    """Return a questionary mock wired with the given .ask() answers."""
    questionary = MagicMock()
    questionary.select.return_value.ask.return_value = select_answer
    questionary.text.return_value.ask.side_effect = text_answers
    questionary.confirm.return_value.ask.return_value = confirm_answer
    return questionary


@pytest.mark.unit
def test_wizard_refresh_token_path_returns_pasted_token() -> None:
    questionary = _mock_questionary("Enter a refresh token (Jira Cloud)", ["pasted-refresh-token"])
    with patch(f"{_WIZARD}.questionary", questionary):
        result = run_jira_oauth_wizard(_DC_CLIENT_CONFIG)

    assert result == "pasted-refresh-token"


@pytest.mark.unit
def test_wizard_dc_path_exchanges_authorization_code() -> None:
    questionary = _mock_questionary(
        "Exchange an authorization code (Jira Data Center)",
        ["auth-code-1", "verifier-1", "https://localhost/callback"],
    )
    with (
        patch(f"{_WIZARD}.questionary", questionary),
        patch(f"{_WIZARD}.exchange_authorization_code_sync", return_value="ref-1") as mock_ex,
    ):
        result = run_jira_oauth_wizard(_DC_CLIENT_CONFIG)

    assert result == "ref-1"
    mock_ex.assert_called_once_with(
        token_url="https://jira.example.com/rest/oauth2/1.0/token",
        client_id="cid",
        client_secret="csec",
        redirect_uri="https://localhost/callback",
        code="auth-code-1",
        code_verifier="verifier-1",
    )


@pytest.mark.unit
def test_wizard_dc_path_reads_client_secret_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The wizard stores the secret in .env, so client_config may not carry it.
    monkeypatch.setenv("JIRA_OAUTH2_CLIENT_SECRET", "env-secret")
    client_config = {"server_url": "https://jira.example.com", "oauth2_client_id": "cid"}
    questionary = _mock_questionary(
        "Exchange an authorization code (Jira Data Center)",
        ["auth-code-1", "verifier-1", "https://localhost/callback"],
    )
    with (
        patch(f"{_WIZARD}.questionary", questionary),
        patch(f"{_WIZARD}.exchange_authorization_code_sync", return_value="ref-1") as mock_ex,
    ):
        result = run_jira_oauth_wizard(client_config)

    assert result == "ref-1"
    assert mock_ex.call_args.kwargs["client_secret"] == "env-secret"


@pytest.mark.unit
def test_wizard_dc_path_failed_exchange_without_retry_returns_none() -> None:
    questionary = _mock_questionary(
        "Exchange an authorization code (Jira Data Center)",
        ["auth-code-1", "verifier-1", "https://localhost/callback"],
        confirm_answer=False,
    )
    with (
        patch(f"{_WIZARD}.questionary", questionary),
        patch(
            f"{_WIZARD}.exchange_authorization_code_sync",
            side_effect=JiraAuthExpiredError,
        ),
    ):
        result = run_jira_oauth_wizard(_DC_CLIENT_CONFIG)

    assert result is None


@pytest.mark.unit
def test_wizard_dc_path_http_error_without_retry_returns_none() -> None:
    questionary = _mock_questionary(
        "Exchange an authorization code (Jira Data Center)",
        ["auth-code-1", "verifier-1", "https://localhost/callback"],
        confirm_answer=False,
    )
    http_error = urllib.error.HTTPError(
        "https://jira.example.com/rest/oauth2/1.0/token",
        404,
        "Not Found",
        {},  # type: ignore[arg-type]
        io.BytesIO(b""),
    )
    with (
        patch(f"{_WIZARD}.questionary", questionary),
        patch(
            f"{_WIZARD}.exchange_authorization_code_sync",
            side_effect=http_error,
        ),
    ):
        result = run_jira_oauth_wizard(_DC_CLIENT_CONFIG)

    assert result is None


@pytest.mark.unit
def test_wizard_dc_path_url_error_without_retry_returns_none() -> None:
    questionary = _mock_questionary(
        "Exchange an authorization code (Jira Data Center)",
        ["auth-code-1", "verifier-1", "https://localhost/callback"],
        confirm_answer=False,
    )
    with (
        patch(f"{_WIZARD}.questionary", questionary),
        patch(
            f"{_WIZARD}.exchange_authorization_code_sync",
            side_effect=urllib.error.URLError("connection refused"),
        ),
    ):
        result = run_jira_oauth_wizard(_DC_CLIENT_CONFIG)

    assert result is None


@pytest.mark.unit
def test_wizard_dc_path_missing_config_returns_none() -> None:
    questionary = _mock_questionary(
        "Exchange an authorization code (Jira Data Center)",
        ["auth-code-1", "verifier-1", "https://localhost/callback"],
    )
    with patch(f"{_WIZARD}.questionary", questionary):
        # No server_url / credentials at all.
        result = run_jira_oauth_wizard({})

    assert result is None


@pytest.mark.unit
def test_store_credentials_in_env_writes_every_credential_and_strips_config(tmp_path: Path):
    dotenv_path = tmp_path / ".env"
    config = {
        "auth_type": "oauth1",
        "oauth1_consumer_key": "key",
        "oauth1_access_token": "at",
        "oauth1_access_token_secret": "ats",
        "oauth1_key_cert": "-----BEGIN-----\nx\n-----END-----\n",
    }
    stored = config_wizard.store_credentials_in_env(config, JiraDefectClientConfig, dotenv_path)
    assert stored == [
        "JIRA_OAUTH1_ACCESS_TOKEN",
        "JIRA_OAUTH1_ACCESS_TOKEN_SECRET",
        "JIRA_OAUTH1_KEY_CERT",
    ]
    assert config == {"auth_type": "oauth1", "oauth1_consumer_key": "key"}
    assert get_key(str(dotenv_path), "JIRA_OAUTH1_ACCESS_TOKEN_SECRET") == "ats"
    assert (
        get_key(str(dotenv_path), "JIRA_OAUTH1_KEY_CERT") == "-----BEGIN-----\nx\n-----END-----\n"
    )


@pytest.mark.unit
def test_store_credentials_in_env_exports_to_process_environment(tmp_path: Path):
    config = {"auth_type": "basic", "password": "s3cret"}
    config_wizard.store_credentials_in_env(config, JiraDefectClientConfig, tmp_path / ".env")
    assert os.environ["JIRA_PASSWORD"] == "s3cret"


@pytest.mark.unit
def test_store_credentials_in_env_ignores_runtime_tokens_and_missing_values(tmp_path: Path, capsys):
    config = {"auth_type": "oauth2 3LO", "oauth2_refresh_token": "rt", "oauth2_client_secret": ""}
    assert (
        config_wizard.store_credentials_in_env(config, JiraDefectClientConfig, tmp_path / ".env")
        == []
    )
    assert config["oauth2_refresh_token"] == "rt"
    assert not (tmp_path / ".env").exists()
    assert capsys.readouterr().out == ""


@pytest.mark.unit
def test_store_credentials_in_env_prints_names_not_values(tmp_path: Path, capsys):
    config_wizard.store_credentials_in_env(
        {"password": "s3cret"}, JiraDefectClientConfig, tmp_path / ".env"
    )
    out = capsys.readouterr().out
    assert f"✓ Stored JIRA_PASSWORD in {tmp_path / '.env'}" in out
    assert "Keep this file out of version control" in out
    assert "s3cret" not in out


@pytest.mark.unit
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file permissions")
def test_store_credentials_in_env_creates_owner_only_dotenv(tmp_path: Path):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("OTHER=1\n")
    dotenv_path.chmod(0o644)
    config_wizard.store_credentials_in_env(
        {"password": "s3cret"}, JiraDefectClientConfig, dotenv_path
    )
    assert stat.S_IMODE(dotenv_path.stat().st_mode) == 0o600
    assert get_key(str(dotenv_path), "OTHER") == "1"


@pytest.mark.unit
def test_configure_client_stores_credentials_in_env_not_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    dotenv_path = tmp_path / ".env"
    monkeypatch.setattr(config_wizard, "DEFAULT_DOTENV_PATH", dotenv_path)
    answers = {
        "server_url": "https://jira.example.com",
        "auth_type": "basic",
        "username": "u",
        "password": "s3cret",
    }
    with (
        patch.object(config_wizard, "check_client_dependencies"),
        patch.object(config_wizard, "get_client_config_class", return_value=JiraDefectClientConfig),
        patch.object(config_wizard, "prompt_model_fields", return_value=dict(answers)),
    ):
        result = config_wizard.configure_client("jira", JIRA_CLIENT_CLASS)

    assert result is not None
    assert "password" not in result
    assert result["username"] == "u"
    assert get_key(str(dotenv_path), "JIRA_PASSWORD") == "s3cret"


@pytest.mark.unit
def test_configure_client_moves_existing_credentials_and_reports_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
):
    dotenv_path = tmp_path / ".env"
    monkeypatch.setattr(config_wizard, "DEFAULT_DOTENV_PATH", dotenv_path)
    existing = {
        "server_url": "https://jira.example.com",
        "auth_type": "token",
        "token": "old-pat",
    }
    with (
        patch.object(config_wizard, "check_client_dependencies"),
        patch.object(config_wizard, "get_client_config_class", return_value=JiraDefectClientConfig),
        patch.object(config_wizard, "get_client_config", return_value=dict(existing)),
        patch.object(config_wizard, "prompt_model_fields", return_value=dict(existing)),
    ):
        result = config_wizard.configure_client("jira", JIRA_CLIENT_CLASS, service_config=object())  # type: ignore[arg-type]

    out = capsys.readouterr().out
    assert result is not None
    assert "token" not in result
    assert get_key(str(dotenv_path), "JIRA_BEARER_TOKEN") == "old-pat"
    assert (
        f"✓ Moved 'token' out of the configuration file into {dotenv_path} (JIRA_BEARER_TOKEN)"
        in out
    )
    assert "old-pat" not in out

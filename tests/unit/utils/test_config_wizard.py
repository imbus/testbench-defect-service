import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from dotenv import get_key

from testbench_defect_service.clients.jira.jira_oauth import JiraAuthExpiredError
from testbench_defect_service.utils.config_wizard import (
    JIRA_CLIENT_SECRET_ENV_VAR,
    run_jira_oauth_wizard,
    store_client_secret_in_env,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(JIRA_CLIENT_SECRET_ENV_VAR, raising=False)


@pytest.mark.unit
def test_always_stores_secret_in_env_and_strips_from_config(tmp_path: Path) -> None:
    dotenv_path = tmp_path / ".env"
    client_config = {"auth_type": "oauth2_3lo", "oauth2_client_secret": "super-secret"}

    store_client_secret_in_env(client_config, dotenv_path)

    assert "oauth2_client_secret" not in client_config
    assert get_key(str(dotenv_path), JIRA_CLIENT_SECRET_ENV_VAR) == "super-secret"


@pytest.mark.unit
def test_exports_secret_to_process_environment(tmp_path: Path) -> None:
    dotenv_path = tmp_path / ".env"
    client_config = {"auth_type": "oauth2_2lo", "oauth2_client_secret": "super-secret"}

    store_client_secret_in_env(client_config, dotenv_path)

    assert os.environ[JIRA_CLIENT_SECRET_ENV_VAR] == "super-secret"


@pytest.mark.unit
def test_no_action_when_no_secret_present(tmp_path: Path) -> None:
    dotenv_path = tmp_path / ".env"
    client_config = {"auth_type": "basic", "oauth2_client_secret": None}

    store_client_secret_in_env(client_config, dotenv_path)

    assert not dotenv_path.exists()


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
    questionary = _mock_questionary(
        "Enter a refresh token (Jira Cloud)", ["pasted-refresh-token"]
    )
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
def test_wizard_dc_path_missing_config_returns_none() -> None:
    questionary = _mock_questionary(
        "Exchange an authorization code (Jira Data Center)",
        ["auth-code-1", "verifier-1", "https://localhost/callback"],
    )
    with patch(f"{_WIZARD}.questionary", questionary):
        # No server_url / credentials at all.
        result = run_jira_oauth_wizard({})

    assert result is None

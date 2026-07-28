from pathlib import Path
from unittest.mock import patch

import pytest
from dotenv import get_key

from testbench_defect_service.utils.config_wizard import (
    JIRA_CLIENT_SECRET_ENV_VAR,
    maybe_store_client_secret_in_env,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(JIRA_CLIENT_SECRET_ENV_VAR, raising=False)


@pytest.mark.unit
def test_stores_secret_in_env_and_strips_from_config(tmp_path: Path) -> None:
    dotenv_path = tmp_path / ".env"
    client_config = {"auth_type": "oauth2_3lo", "oauth2_client_secret": "super-secret"}

    with patch("testbench_defect_service.utils.config_wizard.questionary.confirm") as confirm:
        confirm.return_value.ask.return_value = True
        maybe_store_client_secret_in_env(client_config, dotenv_path)

    assert "oauth2_client_secret" not in client_config
    assert get_key(str(dotenv_path), JIRA_CLIENT_SECRET_ENV_VAR) == "super-secret"


@pytest.mark.unit
def test_keeps_secret_in_config_when_declined(tmp_path: Path) -> None:
    dotenv_path = tmp_path / ".env"
    client_config = {"auth_type": "oauth2_3lo", "oauth2_client_secret": "super-secret"}

    with patch("testbench_defect_service.utils.config_wizard.questionary.confirm") as confirm:
        confirm.return_value.ask.return_value = False
        maybe_store_client_secret_in_env(client_config, dotenv_path)

    assert client_config["oauth2_client_secret"] == "super-secret"
    assert not dotenv_path.exists()


@pytest.mark.unit
def test_no_prompt_when_no_secret_present(tmp_path: Path) -> None:
    dotenv_path = tmp_path / ".env"
    client_config = {"auth_type": "basic", "oauth2_client_secret": None}

    with patch("testbench_defect_service.utils.config_wizard.questionary.confirm") as confirm:
        maybe_store_client_secret_in_env(client_config, dotenv_path)

    confirm.assert_not_called()
    assert not dotenv_path.exists()

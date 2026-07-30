import os
from pathlib import Path

import pytest
from dotenv import get_key

from testbench_defect_service.utils.config_wizard import (
    JIRA_CLIENT_SECRET_ENV_VAR,
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

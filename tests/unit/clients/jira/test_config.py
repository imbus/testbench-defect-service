import pytest

from testbench_defect_service.clients.jira import jira_oauth
from testbench_defect_service.clients.jira.config import (
    AUTH_OAUTH2_2LO,
    AUTH_OAUTH2_3LO,
    JiraDefectClientConfig,
    is_oauth2,
)


@pytest.fixture(autouse=True)
def isolated_token_cache(tmp_path, monkeypatch):
    """Point the OAuth2 disk cache at an empty temp path so a real
    tmp/oauth2_tokens.toml in the working directory cannot leak a cached
    refresh token into config validation."""
    monkeypatch.setattr(jira_oauth, "_TOKEN_CACHE_PATH", tmp_path / "oauth2_tokens.toml")


def _base(**overrides):
    defaults = {"server_url": "https://example.atlassian.net"}
    defaults.update(overrides)
    return defaults


class TestIsOauth2:
    def test_recognizes_both_flows(self):
        assert is_oauth2(AUTH_OAUTH2_2LO) is True
        assert is_oauth2(AUTH_OAUTH2_3LO) is True

    def test_rejects_other_auth_types(self):
        assert is_oauth2("basic") is False
        assert is_oauth2("token") is False
        assert is_oauth2("oauth1") is False
        assert is_oauth2("oauth2") is False


class TestOauth2TwoLegged:
    def test_valid_with_client_credentials_only(self):
        cfg = JiraDefectClientConfig(
            **_base(
                auth_type=AUTH_OAUTH2_2LO,
                oauth2_client_id="cid",
                oauth2_client_secret="secret",
            )
        )
        assert cfg.auth_type == AUTH_OAUTH2_2LO
        assert cfg.oauth2_client_id == "cid"

    def test_does_not_require_refresh_token(self):
        # Unlike 3LO, 2LO needs no refresh token to validate.
        cfg = JiraDefectClientConfig(
            **_base(
                auth_type=AUTH_OAUTH2_2LO,
                oauth2_client_id="cid",
                oauth2_client_secret="secret",
            )
        )
        assert cfg.oauth2_refresh_token is None

    def test_missing_client_credentials_raises(self, monkeypatch):
        monkeypatch.delenv("JIRA_OAUTH2_CLIENT_ID", raising=False)
        monkeypatch.delenv("JIRA_OAUTH2_CLIENT_SECRET", raising=False)
        with pytest.raises(ValueError, match="client credentials"):
            JiraDefectClientConfig(**_base(auth_type=AUTH_OAUTH2_2LO))

    def test_reads_client_credentials_from_env(self, monkeypatch):
        monkeypatch.setenv("JIRA_OAUTH2_CLIENT_ID", "env_id")
        monkeypatch.setenv("JIRA_OAUTH2_CLIENT_SECRET", "env_secret")
        cfg = JiraDefectClientConfig(**_base(auth_type=AUTH_OAUTH2_2LO))
        assert cfg.oauth2_client_id == "env_id"
        assert cfg.oauth2_client_secret == "env_secret"


class TestOauth2ThreeLegged:
    def test_requires_refresh_token(self, monkeypatch):
        monkeypatch.delenv("JIRA_OAUTH2_REFRESH_TOKEN", raising=False)
        with pytest.raises(ValueError, match="refresh token"):
            JiraDefectClientConfig(
                **_base(
                    auth_type=AUTH_OAUTH2_3LO,
                    oauth2_client_id="cid",
                    oauth2_client_secret="secret",
                )
            )

    def test_valid_with_refresh_token(self):
        cfg = JiraDefectClientConfig(
            **_base(
                auth_type=AUTH_OAUTH2_3LO,
                oauth2_client_id="cid",
                oauth2_client_secret="secret",
                oauth2_refresh_token="refresh",
            )
        )
        assert cfg.auth_type == AUTH_OAUTH2_3LO
        assert cfg.oauth2_refresh_token == "refresh"

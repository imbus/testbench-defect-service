import io
import json
import time
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest
import tomli_w

from testbench_defect_service.clients.jira import jira_oauth  # type: ignore


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """
    Automatically isolates global state and file I/O for every test in every class.
    Redirects the TOML cache path to a temporary directory so real files aren't overwritten.
    """
    temp_toml = tmp_path / "oauth2_tokens.toml"
    monkeypatch.setattr(jira_oauth, "_TOKEN_CACHE_PATH", temp_toml)

    # Save original state
    orig_store = jira_oauth.token_store.copy()
    orig_settings = jira_oauth._oauth2_settings.copy()

    # Set default safe state for testing
    jira_oauth.token_store.update(
        {
            "access_token": "YOUR_CURRENT_ACCESS_TOKEN",
            "refresh_token": "YOUR_CURRENT_REFRESH_TOKEN",
            "expires_at": time.time() + 3600,
        }
    )
    jira_oauth._oauth2_settings.update(
        {
            "client_id": "YOUR_CLIENT_ID",
            "client_secret": "YOUR_CLIENT_SECRET",
        }
    )

    yield temp_toml

    # Restore state after test completes
    jira_oauth.token_store.update(orig_store)
    jira_oauth._oauth2_settings.update(orig_settings)


class TestIsPlaceholder:
    """Tests for the _is_placeholder function."""

    def test_true_for_your_prefix(self):
        assert jira_oauth._is_placeholder("YOUR_TOKEN") is True
        assert jira_oauth._is_placeholder("YOUR_CLIENT_ID") is True

    def test_false_for_valid_token(self):
        assert jira_oauth._is_placeholder("VALID_TOKEN") is False

    def test_false_for_empty_string(self):
        assert jira_oauth._is_placeholder("") is False


class TestLoadTokenStoreFromDisk:
    """Tests for the _load_token_store_from_disk function."""

    def test_loads_refresh_token_only(self, isolated_env):
        # Even if an old cache file contains an access token, it must never be
        # loaded back into memory — only the refresh token is read.
        payload = {
            jira_oauth._TOKEN_CACHE_SECTION: {
                "access_token": "disk_access",
                "refresh_token": "disk_refresh",
                "expires_at": 9999999999,
            }
        }
        with isolated_env.open("wb") as f:
            tomli_w.dump(payload, f)

        jira_oauth.token_store["access_token"] = "YOUR_CURRENT_ACCESS_TOKEN"
        jira_oauth._load_token_store_from_disk()

        assert jira_oauth.token_store["refresh_token"] == "disk_refresh"
        assert jira_oauth.token_store["access_token"] == "YOUR_CURRENT_ACCESS_TOKEN"

    def test_handles_missing_file(self):
        jira_oauth.token_store["access_token"] = "initial"
        jira_oauth._load_token_store_from_disk()
        assert jira_oauth.token_store["access_token"] == "initial"


class TestPersistTokenStoreToDisk:
    """Tests for the _persist_token_store_to_disk function."""

    def test_persists_refresh_token_only(self, isolated_env):
        # The access token must never be written to disk, only the refresh token.
        jira_oauth.token_store.update(
            {
                "access_token": "real_access",
                "refresh_token": "real_refresh",
                "expires_at": 1234567890.0,
            }
        )

        jira_oauth._persist_token_store_to_disk()

        assert isolated_env.exists()

        if hasattr(jira_oauth, "tomllib"):
            with isolated_env.open("rb") as f:
                data = jira_oauth.tomllib.load(f)
                section = data[jira_oauth._TOKEN_CACHE_SECTION]
                assert section["refresh_token"] == "real_refresh"
                assert "access_token" not in section
                assert "expires_at" not in section

    def test_persists_refresh_token_when_access_token_placeholder(self, isolated_env):
        jira_oauth.token_store.update(
            {
                "access_token": "YOUR_TOKEN",
                "refresh_token": "real_refresh",
                "expires_at": 0.0,
            }
        )

        jira_oauth._persist_token_store_to_disk()

        with isolated_env.open("rb") as f:
            data = jira_oauth.tomllib.load(f)
            section = data[jira_oauth._TOKEN_CACHE_SECTION]
            assert "access_token" not in section
            assert section["refresh_token"] == "real_refresh"

    def test_skips_placeholder_refresh_token(self, isolated_env):
        jira_oauth.token_store.update(
            {
                "access_token": "real_access",
                "refresh_token": "YOUR_REFRESH",
            }
        )

        jira_oauth._persist_token_store_to_disk()

        assert not isolated_env.exists()

    def test_seed_oauth2_refresh_token_writes_refresh_only_cache(self, isolated_env):
        jira_oauth.seed_oauth2_refresh_token("seed_refresh")

        with isolated_env.open("rb") as f:
            data = jira_oauth.tomllib.load(f)
            section = data[jira_oauth._TOKEN_CACHE_SECTION]
            assert "access_token" not in section
            assert section["refresh_token"] == "seed_refresh"
            assert "expires_at" not in section


class TestConfigureOauth2Runtime:
    """Tests for the configure_oauth2_runtime function."""

    def test_updates_all_values(self):
        jira_oauth.configure_oauth2_runtime(
            access_token="new_acc",
            refresh_token="new_ref",
            client_id="new_id",
            client_secret="new_sec",
            expires_at=1000,
        )
        assert jira_oauth.token_store["access_token"] == "new_acc"
        assert jira_oauth.token_store["refresh_token"] == "new_ref"
        assert jira_oauth.token_store["expires_at"] == 1000.0
        assert jira_oauth._oauth2_settings["client_id"] == "new_id"
        assert jira_oauth._oauth2_settings["client_secret"] == "new_sec"

    def test_updates_client_credentials_when_cache_exists(self, isolated_env):
        payload = {
            jira_oauth._TOKEN_CACHE_SECTION: {
                "access_token": "disk_access",
                "refresh_token": "disk_refresh",
                "expires_at": 9999999999,
            }
        }
        with isolated_env.open("wb") as f:
            tomli_w.dump(payload, f)

        jira_oauth.configure_oauth2_runtime(
            client_id="cfg_id",
            client_secret="cfg_secret",
        )

        assert jira_oauth._oauth2_settings["client_id"] == "cfg_id"
        assert jira_oauth._oauth2_settings["client_secret"] == "cfg_secret"


class TestRefreshJiraTokenSync:
    """Tests for the _refresh_jira_token_sync function."""

    @patch("urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        jira_oauth._oauth2_settings.update(
            {
                "client_id": "valid_id",
                "client_secret": "valid_secret",
            }
        )
        jira_oauth.token_store["refresh_token"] = "valid_refresh"

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {
                "access_token": "refreshed_access",
                "refresh_token": "refreshed_refresh",
                "expires_in": 3600,
            }
        ).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        data = jira_oauth._refresh_jira_token_sync()

        assert data["access_token"] == "refreshed_access"
        assert data["expires_in"] == 3600

    def test_missing_creds(self):
        with pytest.raises(
            jira_oauth.JiraAuthExpiredError, match="Missing OAuth2 client credentials"
        ):
            jira_oauth._refresh_jira_token_sync()

    @patch("urllib.request.urlopen")
    def test_http_error(self, mock_urlopen):
        jira_oauth._oauth2_settings.update({"client_id": "id", "client_secret": "sec"})

        error = HTTPError("url", 401, "Unauthorized", {}, io.BytesIO(b""))
        mock_urlopen.side_effect = error

        with pytest.raises(jira_oauth.JiraAuthExpiredError):
            jira_oauth._refresh_jira_token_sync()


class TestGetValidJiraTokenSync:
    """Tests for the get_valid_jira_token_sync function."""

    def test_returns_valid_token(self):
        jira_oauth.token_store.update(
            {"access_token": "valid_access", "expires_at": time.time() + 1000}
        )

        token = jira_oauth.get_valid_jira_token_sync()
        assert token == "valid_access"

    def test_uses_fallback_when_placeholder(self):
        jira_oauth.token_store.update(
            {"access_token": "YOUR_ACCESS", "expires_at": time.time() + 1000}
        )

        token = jira_oauth.get_valid_jira_token_sync(fallback_token="fallback_acc")
        assert token == "fallback_acc"

    # Updated patch path to reflect the correct module location
    @patch("testbench_defect_service.clients.jira.jira_oauth._refresh_jira_token_sync")
    def test_triggers_refresh_when_expired(self, mock_refresh):
        jira_oauth.token_store.update(
            {
                "access_token": "old_access",
                "refresh_token": "real_refresh",
                "expires_at": time.time() - 1000,
            }
        )

        mock_refresh.return_value = {
            "access_token": "new_acc",
            "refresh_token": "new_ref",
            "expires_in": 3600,
        }

        token = jira_oauth.get_valid_jira_token_sync()

        assert mock_refresh.called
        assert token == "new_acc"


class TestMintClientCredentialsTokenSync:
    """Tests for the 2LO _mint_client_credentials_token_sync function."""

    @patch("urllib.request.urlopen")
    def test_success_sends_client_credentials_grant(self, mock_urlopen):
        jira_oauth._oauth2_settings.update(
            {"client_id": "valid_id", "client_secret": "valid_secret"}
        )

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"access_token": "service_access", "expires_in": 3600, "token_type": "Bearer"}
        ).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        data = jira_oauth._mint_client_credentials_token_sync()

        assert data["access_token"] == "service_access"
        assert "refresh_token" not in data

        sent_request = mock_urlopen.call_args.args[0]
        sent_payload = json.loads(sent_request.data.decode("utf-8"))
        assert sent_payload == {
            "grant_type": "client_credentials",
            "client_id": "valid_id",
            "client_secret": "valid_secret",
        }

    def test_missing_creds_raises(self):
        with pytest.raises(
            jira_oauth.JiraAuthExpiredError, match="Missing OAuth2 client credentials"
        ):
            jira_oauth._mint_client_credentials_token_sync()

    @patch("urllib.request.urlopen")
    def test_http_error_raises_auth_expired(self, mock_urlopen):
        jira_oauth._oauth2_settings.update({"client_id": "id", "client_secret": "sec"})
        mock_urlopen.side_effect = HTTPError("url", 401, "Unauthorized", {}, io.BytesIO(b""))

        with pytest.raises(jira_oauth.JiraAuthExpiredError):
            jira_oauth._mint_client_credentials_token_sync()


class TestGetValidJiraTokenSyncClientCredentials:
    """Tests for the 2LO branch of get_valid_jira_token_sync."""

    @patch("testbench_defect_service.clients.jira.jira_oauth._mint_client_credentials_token_sync")
    def test_mints_on_first_call(self, mock_mint):
        jira_oauth._oauth2_settings["grant_type"] = jira_oauth.GRANT_CLIENT_CREDENTIALS
        mock_mint.return_value = {"access_token": "minted", "expires_in": 3600}

        token = jira_oauth.get_valid_jira_token_sync(is_first_call=True)

        assert mock_mint.called
        assert token == "minted"
        assert jira_oauth.token_store["access_token"] == "minted"

    @patch("testbench_defect_service.clients.jira.jira_oauth._mint_client_credentials_token_sync")
    def test_reuses_cached_token_when_valid(self, mock_mint):
        jira_oauth._oauth2_settings["grant_type"] = jira_oauth.GRANT_CLIENT_CREDENTIALS
        jira_oauth.token_store.update({"access_token": "cached", "expires_at": time.time() + 1000})

        token = jira_oauth.get_valid_jira_token_sync()

        assert not mock_mint.called
        assert token == "cached"

    @patch("testbench_defect_service.clients.jira.jira_oauth._mint_client_credentials_token_sync")
    def test_remints_when_expired(self, mock_mint):
        jira_oauth._oauth2_settings["grant_type"] = jira_oauth.GRANT_CLIENT_CREDENTIALS
        jira_oauth.token_store.update({"access_token": "stale", "expires_at": time.time() - 1000})
        mock_mint.return_value = {"access_token": "fresh", "expires_in": 3600}

        token = jira_oauth.get_valid_jira_token_sync()

        assert mock_mint.called
        assert token == "fresh"

    @patch("testbench_defect_service.clients.jira.jira_oauth._mint_client_credentials_token_sync")
    def test_remints_when_cached_token_is_placeholder(self, mock_mint):
        # The default token_store seeds a placeholder access token with a
        # future expiry; the 2LO path must not hand that placeholder back.
        jira_oauth._oauth2_settings["grant_type"] = jira_oauth.GRANT_CLIENT_CREDENTIALS
        jira_oauth.token_store.update(
            {"access_token": "YOUR_CURRENT_ACCESS_TOKEN", "expires_at": time.time() + 3600}
        )
        mock_mint.return_value = {"access_token": "fresh", "expires_in": 3600}

        token = jira_oauth.get_valid_jira_token_sync()

        assert mock_mint.called
        assert token == "fresh"

    @patch("testbench_defect_service.clients.jira.jira_oauth._mint_client_credentials_token_sync")
    def test_does_not_persist_to_disk(self, mock_mint, isolated_env):
        jira_oauth._oauth2_settings["grant_type"] = jira_oauth.GRANT_CLIENT_CREDENTIALS
        mock_mint.return_value = {"access_token": "minted", "expires_in": 3600}

        jira_oauth.get_valid_jira_token_sync(is_first_call=True)

        assert not isolated_env.exists()
        assert jira_oauth.token_store["access_token"] == "minted"

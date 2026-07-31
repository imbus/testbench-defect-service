import io
import json
import threading
import time
from typing import ClassVar
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs

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
            "token_url": jira_oauth.CLOUD_TOKEN_URL,
            "body_format": jira_oauth.BODY_FORMAT_JSON,
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


def _run_concurrent_first_calls(fetch_name: str, response: dict[str, object]) -> tuple[list, list]:
    """Race two ``is_first_call=True`` callers and record token fetches and results.

    Returns ``(fetch_calls, tokens)``. Both threads are released from a barrier
    simultaneously, and the patched fetch sleeps briefly so the loser is
    guaranteed to be waiting on ``refresh_lock_sync`` while the winner is still
    in flight — the exact window the double-checked lock exists to close.
    """
    fetch_calls: list[int] = []
    tokens: list[str] = []
    gate = threading.Barrier(2)

    def fake_fetch() -> dict[str, object]:
        fetch_calls.append(1)
        time.sleep(0.05)
        return response

    def worker() -> None:
        gate.wait()
        tokens.append(jira_oauth.get_valid_jira_token_sync(is_first_call=True))

    with patch.object(jira_oauth, fetch_name, side_effect=fake_fetch):
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

    return fetch_calls, tokens


class TestConcurrentFirstCalls:
    """Two threads cold-starting at once must trigger exactly one token fetch.

    Regression tests for the double-checked-locking defect where the post-lock
    re-check honoured ``is_first_call`` and therefore always fell through, making
    both racing threads perform a live token request against Atlassian.
    """

    def test_3lo_refreshes_only_once(self, isolated_env):
        jira_oauth._oauth2_settings["grant_type"] = jira_oauth.GRANT_REFRESH_TOKEN
        jira_oauth.token_store.update(
            {
                "access_token": "YOUR_CURRENT_ACCESS_TOKEN",
                "refresh_token": "real_refresh",
                "expires_at": time.time() + 3600,
            }
        )

        fetch_calls, tokens = _run_concurrent_first_calls(
            "_refresh_jira_token_sync",
            {"access_token": "fresh", "refresh_token": "next_refresh", "expires_in": 3600},
        )

        assert len(fetch_calls) == 1
        assert tokens == ["fresh", "fresh"]

    def test_2lo_mints_only_once(self, isolated_env):
        jira_oauth._oauth2_settings["grant_type"] = jira_oauth.GRANT_CLIENT_CREDENTIALS
        jira_oauth.token_store.update(
            {"access_token": "YOUR_CURRENT_ACCESS_TOKEN", "expires_at": time.time() + 3600}
        )

        fetch_calls, tokens = _run_concurrent_first_calls(
            "_mint_client_credentials_token_sync",
            {"access_token": "minted", "expires_in": 3600},
        )

        assert len(fetch_calls) == 1
        assert tokens == ["minted", "minted"]

    def test_3lo_single_first_call_still_forces_refresh(self, isolated_env):
        """A lone first call must not be short-circuited by the peer-refresh check."""
        jira_oauth._oauth2_settings["grant_type"] = jira_oauth.GRANT_REFRESH_TOKEN
        jira_oauth.token_store.update(
            {
                "access_token": "stale_but_unexpired",
                "refresh_token": "real_refresh",
                "expires_at": time.time() + 3600,
            }
        )

        with patch.object(
            jira_oauth,
            "_refresh_jira_token_sync",
            return_value={
                "access_token": "fresh",
                "refresh_token": "next_refresh",
                "expires_in": 3600,
            },
        ) as mock_refresh:
            token = jira_oauth.get_valid_jira_token_sync(is_first_call=True)

        assert mock_refresh.called
        assert token == "fresh"


class TestExchangeAuthorizationCode:
    """Tests for the one-time authorization_code + PKCE exchange (Jira DC)."""

    _KWARGS: ClassVar[dict[str, str]] = {
        "token_url": "https://jira.example.com/rest/oauth2/1.0/token",
        "client_id": "cid",
        "client_secret": "csec",
        "redirect_uri": "https://localhost/callback",
        "code": "auth-code-1",
        "code_verifier": "verifier-1",
    }

    @patch("urllib.request.urlopen")
    def test_success_sends_form_payload_and_persists_refresh_token(
        self, mock_urlopen, isolated_env
    ):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"access_token": "acc-1", "refresh_token": "ref-1", "expires_in": 3600}
        ).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        refresh = jira_oauth.exchange_authorization_code_sync(**self._KWARGS)

        assert refresh == "ref-1"
        assert jira_oauth.token_store["access_token"] == "acc-1"
        assert jira_oauth.token_store["refresh_token"] == "ref-1"

        sent_request = mock_urlopen.call_args.args[0]
        assert sent_request.full_url == "https://jira.example.com/rest/oauth2/1.0/token"
        assert sent_request.get_header("Content-type") == "application/x-www-form-urlencoded"
        sent_body = parse_qs(sent_request.data.decode("utf-8"))
        assert sent_body == {
            "grant_type": ["authorization_code"],
            "client_id": ["cid"],
            "client_secret": ["csec"],
            "redirect_uri": ["https://localhost/callback"],
            "code": ["auth-code-1"],
            "code_verifier": ["verifier-1"],
        }

        # Refresh token (and only the refresh token) is persisted to disk.
        with isolated_env.open("rb") as f:
            data = jira_oauth.tomllib.load(f)
        section = data[jira_oauth._TOKEN_CACHE_SECTION]
        assert section["refresh_token"] == "ref-1"
        assert "access_token" not in section

    @patch("urllib.request.urlopen")
    def test_http_400_raises_auth_expired(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError("url", 400, "Bad Request", {}, io.BytesIO(b""))

        with pytest.raises(jira_oauth.JiraAuthExpiredError):
            jira_oauth.exchange_authorization_code_sync(**self._KWARGS)

    @patch("urllib.request.urlopen")
    def test_missing_refresh_token_in_response_raises(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"access_token": "acc-1", "expires_in": 3600}
        ).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        with pytest.raises(jira_oauth.JiraAuthExpiredError, match="refresh token"):
            jira_oauth.exchange_authorization_code_sync(**self._KWARGS)


class TestDataCenterTokenUrl:
    """Tests for the data_center_token_url helper."""

    def test_builds_dc_token_endpoint(self):
        assert (
            jira_oauth.data_center_token_url("https://jira.example.com")
            == "https://jira.example.com/rest/oauth2/1.0/token"
        )

    def test_strips_trailing_slash(self):
        assert (
            jira_oauth.data_center_token_url("https://jira.example.com/")
            == "https://jira.example.com/rest/oauth2/1.0/token"
        )


class TestPostOauthTokenRequestEncoding:
    """Tests for token_url / body_format handling in _post_oauth_token_request."""

    def _mock_response(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"access_token": "a"}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

    @patch("urllib.request.urlopen")
    def test_defaults_to_cloud_url_and_json(self, mock_urlopen):
        self._mock_response(mock_urlopen)

        jira_oauth._post_oauth_token_request({"grant_type": "refresh_token"})

        sent_request = mock_urlopen.call_args.args[0]
        assert sent_request.full_url == jira_oauth.CLOUD_TOKEN_URL
        assert sent_request.get_header("Content-type") == "application/json"
        assert json.loads(sent_request.data.decode("utf-8")) == {"grant_type": "refresh_token"}

    @patch("urllib.request.urlopen")
    def test_form_encoding_against_configured_dc_url(self, mock_urlopen):
        self._mock_response(mock_urlopen)
        jira_oauth._oauth2_settings.update(
            {
                "token_url": "https://jira.example.com/rest/oauth2/1.0/token",
                "body_format": jira_oauth.BODY_FORMAT_FORM,
            }
        )

        jira_oauth._post_oauth_token_request({"grant_type": "refresh_token", "client_id": "id"})

        sent_request = mock_urlopen.call_args.args[0]
        assert sent_request.full_url == "https://jira.example.com/rest/oauth2/1.0/token"
        assert sent_request.get_header("Content-type") == "application/x-www-form-urlencoded"
        sent_body = parse_qs(sent_request.data.decode("utf-8"))
        assert sent_body == {"grant_type": ["refresh_token"], "client_id": ["id"]}

    @patch("urllib.request.urlopen")
    def test_explicit_args_override_settings(self, mock_urlopen):
        self._mock_response(mock_urlopen)

        jira_oauth._post_oauth_token_request(
            {"grant_type": "authorization_code"},
            token_url="https://dc.example.com/rest/oauth2/1.0/token",
            body_format=jira_oauth.BODY_FORMAT_FORM,
        )

        sent_request = mock_urlopen.call_args.args[0]
        assert sent_request.full_url == "https://dc.example.com/rest/oauth2/1.0/token"
        assert sent_request.get_header("Content-type") == "application/x-www-form-urlencoded"


class TestConfigureOauth2RuntimeTokenUrl:
    """configure_oauth2_runtime must apply token_url and body_format."""

    def test_sets_token_url_and_body_format(self):
        jira_oauth.configure_oauth2_runtime(
            token_url="https://jira.example.com/rest/oauth2/1.0/token",
            body_format=jira_oauth.BODY_FORMAT_FORM,
        )
        assert (
            jira_oauth._oauth2_settings["token_url"]
            == "https://jira.example.com/rest/oauth2/1.0/token"
        )
        assert jira_oauth._oauth2_settings["body_format"] == jira_oauth.BODY_FORMAT_FORM

    def test_defaults_remain_cloud(self):
        jira_oauth.configure_oauth2_runtime(client_id="id")
        assert jira_oauth._oauth2_settings["token_url"] == jira_oauth.CLOUD_TOKEN_URL
        assert jira_oauth._oauth2_settings["body_format"] == jira_oauth.BODY_FORMAT_JSON


class TestRefreshUsesConfiguredDcEndpoint:
    """3LO refresh must hit the configured DC endpoint with a form body."""

    @patch("urllib.request.urlopen")
    def test_refresh_payload_form_encoded_to_dc(self, mock_urlopen):
        jira_oauth._oauth2_settings.update(
            {
                "client_id": "cid",
                "client_secret": "csec",
                "token_url": "https://jira.example.com/rest/oauth2/1.0/token",
                "body_format": jira_oauth.BODY_FORMAT_FORM,
            }
        )
        jira_oauth.token_store["refresh_token"] = "rt-1"

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"access_token": "new_acc", "refresh_token": "rt-2", "expires_in": 3600}
        ).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        data = jira_oauth._refresh_jira_token_sync()

        assert data["access_token"] == "new_acc"
        sent_request = mock_urlopen.call_args.args[0]
        assert sent_request.full_url == "https://jira.example.com/rest/oauth2/1.0/token"
        sent_body = parse_qs(sent_request.data.decode("utf-8"))
        assert sent_body == {
            "grant_type": ["refresh_token"],
            "client_id": ["cid"],
            "client_secret": ["csec"],
            "refresh_token": ["rt-1"],
        }

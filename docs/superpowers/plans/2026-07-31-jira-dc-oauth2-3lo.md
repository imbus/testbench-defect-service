# Jira Data Center OAuth2 3LO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support OAuth 2.0 3LO (authorization code + PKCE) against Jira Data Center: token requests go to `{server_url}/rest/oauth2/1.0/token` (form-encoded), API requests go directly to `{server_url}` (no Atlassian gateway).

**Architecture:** The existing module-level OAuth2 runtime in `jira_oauth.py` gains a configurable token endpoint (`token_url`) and body encoding (`body_format`). `JiraClient._connect` probes the cloud_id first: found → existing Cloud/gateway path unchanged; `None` → new direct Data Center path. The setup wizard gains a "paste authorization code + code_verifier + redirect_uri" option that performs the one-time `authorization_code` exchange.

**Tech Stack:** Python 3.10+, `urllib` (token HTTP), `jira` package (API), pydantic (config), click + questionary (wizard), pytest (tests).

**Spec:** `docs/superpowers/specs/2026-07-31-jira-dc-oauth2-3lo-design.md`

## Global Constraints

- Jira Cloud OAuth2 behavior (2LO and 3LO) must remain bit-for-bit unchanged: default token URL `https://auth.atlassian.com/oauth/token`, JSON bodies, gateway connection.
- DC token endpoint: `{server_url}/rest/oauth2/1.0/token`, bodies `application/x-www-form-urlencoded`.
- Only the refresh token is ever persisted to disk (`tmp/oauth2_tokens.toml`); access tokens, codes, verifiers, and redirect URIs are never written to disk or config files.
- No new config fields; `auth_type = "oauth2 3LO (user account)"` covers both deployments.
- 2LO (client_credentials) is not supported on Data Center — fail with a clear error.
- Line length 100 (ruff); run all commands from the repo root `E:\Testbench-ecosystem\test\testbench-defect-service`.
- Test command: `.venv/Scripts/pytest.exe tests/unit/... -v` (Windows venv). Lint: `.venv/Scripts/ruff.exe check src tests` and `.venv/Scripts/ruff.exe format --check src tests`.
- Every commit message ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Configurable token endpoint + form encoding in `jira_oauth.py`

**Files:**
- Modify: `src/testbench_defect_service/clients/jira/jira_oauth.py`
- Test: `tests/unit/clients/jira/test_jira_oauth.py`

**Interfaces:**
- Produces:
  - `data_center_token_url(server_url: str) -> str` — returns `{server_url.rstrip("/")}/rest/oauth2/1.0/token`.
  - Module constants `BODY_FORMAT_JSON = "json"`, `BODY_FORMAT_FORM = "form"`, `CLOUD_TOKEN_URL = "https://auth.atlassian.com/oauth/token"`.
  - `_oauth2_settings` gains keys `"token_url"` (default `CLOUD_TOKEN_URL`) and `"body_format"` (default `BODY_FORMAT_JSON`).
  - `configure_oauth2_runtime(..., token_url: str | None = None, body_format: str | None = None)` — sets those keys when provided.
  - `_post_oauth_token_request(payload, token_url: str | None = None, body_format: str | None = None)` — explicit args override the settings; falls back to `_oauth2_settings` values.

- [ ] **Step 1: Extend the autouse fixture so new settings keys are reset per test**

In `tests/unit/clients/jira/test_jira_oauth.py`, inside the `isolated_env` fixture, extend the existing `jira_oauth._oauth2_settings.update({...})` "safe state" block to:

```python
    jira_oauth._oauth2_settings.update(
        {
            "client_id": "YOUR_CLIENT_ID",
            "client_secret": "YOUR_CLIENT_SECRET",
            "token_url": jira_oauth.CLOUD_TOKEN_URL,
            "body_format": jira_oauth.BODY_FORMAT_JSON,
        }
    )
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/unit/clients/jira/test_jira_oauth.py`:

```python
from urllib.parse import parse_qs


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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/pytest.exe tests/unit/clients/jira/test_jira_oauth.py -v`
Expected: the whole file ERRORS in the autouse fixture (`AttributeError: module ... has no attribute 'CLOUD_TOKEN_URL'`) — the fixture from Step 1 already references the new constants. This confirms the implementation is missing; pre-existing tests will pass again after Step 4.

- [ ] **Step 4: Implement in `jira_oauth.py`**

Add `from urllib.parse import urlencode` to the existing `from urllib import error, request` import block (as a separate line: `from urllib.parse import urlencode`).

Below the `GRANT_*` constants, add:

```python
# Token endpoint targets:
# - Jira Cloud uses the central Atlassian identity endpoint with JSON bodies.
# - Jira Data Center serves its own endpoint under the site base URL and
#   expects application/x-www-form-urlencoded bodies (RFC 6749).
CLOUD_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
_DC_TOKEN_PATH = "/rest/oauth2/1.0/token"
BODY_FORMAT_JSON = "json"
BODY_FORMAT_FORM = "form"


def data_center_token_url(server_url: str) -> str:
    """Return the Jira Data Center OAuth2 token endpoint for *server_url*."""
    return server_url.rstrip("/") + _DC_TOKEN_PATH
```

Extend the `_oauth2_settings` dict:

```python
_oauth2_settings = {
    "client_id": _CLIENT_ID,
    "client_secret": _CLIENT_SECRET,
    "grant_type": GRANT_REFRESH_TOKEN,
    "token_url": CLOUD_TOKEN_URL,
    "body_format": BODY_FORMAT_JSON,
}
```

Add two keyword-only parameters to `configure_oauth2_runtime` (after `grant_type`): `token_url: str | None = None, body_format: str | None = None`, and inside the "Always accept explicit config credentials" block add:

```python
    if token_url:
        _oauth2_settings["token_url"] = token_url
    if body_format:
        _oauth2_settings["body_format"] = body_format
```

Replace `_post_oauth_token_request` with:

```python
def _post_oauth_token_request(
    payload: dict[str, str],
    token_url: str | None = None,
    body_format: str | None = None,
) -> dict[str, object]:
    """POST *payload* to the configured OAuth token endpoint and return the JSON body.

    Explicit *token_url* / *body_format* arguments override the runtime settings
    (used for the one-time authorization-code exchange, which runs before the
    OAuth2 runtime is configured). Cloud uses JSON bodies; Data Center expects
    application/x-www-form-urlencoded.

    Raises ``JiraAuthExpiredError`` on HTTP 400/401 (invalid/expired grant), and
    re-raises any other HTTP error unchanged.
    """
    url = token_url or str(_oauth2_settings.get("token_url", CLOUD_TOKEN_URL))
    fmt = body_format or str(_oauth2_settings.get("body_format", BODY_FORMAT_JSON))
    if fmt == BODY_FORMAT_FORM:
        data = urlencode(payload).encode("utf-8")
        content_type = "application/x-www-form-urlencoded"
    else:
        data = json.dumps(payload).encode("utf-8")
        content_type = "application/json"

    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": content_type},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=20) as resp:
            raw_data = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        if exc.code in {400, 401}:
            raise JiraAuthExpiredError from exc
        raise

    data_obj = json.loads(raw_data)
    if not isinstance(data_obj, dict):
        raise RuntimeError("Unexpected token response format from Jira OAuth endpoint")
    return data_obj
```

`_refresh_jira_token_sync` and `_mint_client_credentials_token_sync` need no changes — they call `_post_oauth_token_request(payload)` which now reads the settings.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/pytest.exe tests/unit/clients/jira/test_jira_oauth.py -v`
Expected: ALL PASS (new and pre-existing).

- [ ] **Step 6: Lint and commit**

Run: `.venv/Scripts/ruff.exe check src/testbench_defect_service/clients/jira/jira_oauth.py tests/unit/clients/jira/test_jira_oauth.py && .venv/Scripts/ruff.exe format --check src/testbench_defect_service/clients/jira/jira_oauth.py tests/unit/clients/jira/test_jira_oauth.py`
Expected: no errors (run `ruff format` without `--check` to fix formatting if needed).

```bash
git add src/testbench_defect_service/clients/jira/jira_oauth.py tests/unit/clients/jira/test_jira_oauth.py
git commit -m "feat: configurable OAuth2 token endpoint with form encoding for Jira DC

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `exchange_authorization_code_sync` in `jira_oauth.py`

**Files:**
- Modify: `src/testbench_defect_service/clients/jira/jira_oauth.py`
- Test: `tests/unit/clients/jira/test_jira_oauth.py`

**Interfaces:**
- Consumes: `_post_oauth_token_request(payload, token_url=..., body_format=...)`, `BODY_FORMAT_FORM`, `token_store`, `_persist_token_store_to_disk()` (Task 1).
- Produces:
  - `exchange_authorization_code_sync(*, token_url: str, client_id: str, client_secret: str, redirect_uri: str, code: str, code_verifier: str) -> str` — performs the one-time `authorization_code` + PKCE exchange, stores access/refresh token in the token store, persists the refresh token, returns the refresh token. Raises `JiraAuthExpiredError` on HTTP 400/401 or when the response lacks a refresh token.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/clients/jira/test_jira_oauth.py`:

```python
class TestExchangeAuthorizationCode:
    """Tests for the one-time authorization_code + PKCE exchange (Jira DC)."""

    _KWARGS = {
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest.exe tests/unit/clients/jira/test_jira_oauth.py::TestExchangeAuthorizationCode -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'exchange_authorization_code_sync'`.

- [ ] **Step 3: Implement**

Add to `jira_oauth.py` (place after `seed_oauth2_refresh_token`, before `class JiraAuthExpiredError` — note the function references `JiraAuthExpiredError`, which is fine at call time; if you prefer, place it after the class definition instead):

```python
def exchange_authorization_code_sync(  # noqa: PLR0913
    *,
    token_url: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    code_verifier: str,
) -> str:
    """Exchange a 3LO authorization code (with PKCE verifier) for tokens (Jira DC).

    Performs the one-time ``authorization_code`` grant against *token_url*
    (``{server_url}/rest/oauth2/1.0/token`` on Jira Data Center), stores the
    resulting access and refresh tokens in the in-memory token store, persists
    the refresh token to the on-disk cache, and returns the refresh token.

    Raises ``JiraAuthExpiredError`` on HTTP 400/401 (invalid, expired, or
    already-used code; verifier mismatch) or when the response contains no
    refresh token.
    """
    payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "code": code,
        "code_verifier": code_verifier,
    }
    data = _post_oauth_token_request(payload, token_url=token_url, body_format=BODY_FORMAT_FORM)

    refresh_token = str(data.get("refresh_token", ""))
    if not refresh_token:
        raise JiraAuthExpiredError(
            "Jira OAuth2 token response did not contain a refresh token"
        )

    token_store["access_token"] = str(data.get("access_token", ""))
    token_store["refresh_token"] = refresh_token
    token_store["expires_at"] = time.time() + int(str(data.get("expires_in", 0)))
    _persist_token_store_to_disk()
    return refresh_token
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest.exe tests/unit/clients/jira/test_jira_oauth.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Lint and commit**

Run: `.venv/Scripts/ruff.exe check src/testbench_defect_service/clients/jira/jira_oauth.py tests/unit/clients/jira/test_jira_oauth.py`
Expected: no errors.

```bash
git add src/testbench_defect_service/clients/jira/jira_oauth.py tests/unit/clients/jira/test_jira_oauth.py
git commit -m "feat: add authorization_code + PKCE token exchange for Jira DC

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Direct Data Center OAuth2 connection in `jira_client.py`

**Files:**
- Modify: `src/testbench_defect_service/clients/jira/jira_client.py`
- Test: `tests/unit/clients/jira/test_jira_client.py`

**Interfaces:**
- Consumes: `configure_oauth2_runtime(..., token_url=..., body_format=...)`, `data_center_token_url()`, `BODY_FORMAT_FORM` (Task 1); existing `get_valid_jira_token_sync`, `_patch_session_for_oauth2_token`, `_verify_connection`, `_create_jira_instance`.
- Produces:
  - `_connect` OAuth2 branch: probes `_fetch_cloud_id()`; cloud_id → `_connect_via_gateway(cloud_id)`; `None` → `_connect_direct_oauth2()`.
  - `_connect_via_gateway(cloud_id: str | None = None)` — optional param; fetches the cloud_id itself when not given (preserves the basic-auth scoped-token fallback call).
  - `_connect_direct_oauth2(self) -> JIRA` — new DC path.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/clients/jira/test_jira_client.py`:

```python
def _make_oauth2_3lo_config(**overrides) -> JiraDefectClientConfig:
    defaults: dict[str, Any] = {
        "server_url": "https://jira.example.com",
        "auth_type": "oauth2 3LO (user account)",
        "oauth2_client_id": "cid",
        "oauth2_client_secret": "csec",
        "oauth2_refresh_token": "rt-1",
        "attributes": ["title", "status"],
        "readonly": False,
        "show_change_history": False,
    }
    defaults.update(overrides)
    return JiraDefectClientConfig(**defaults)


@pytest.mark.unit
class TestConnectDirectOauth2:
    """OAuth2 3LO against Jira Data Center: no cloud_id -> direct connection."""

    def _connect(self, config: JiraDefectClientConfig) -> tuple[JiraClient, Mock, Mock]:
        """Build a JiraClient on the DC path with all externals mocked."""
        prefix = "testbench_defect_service.clients.jira.jira_client"
        with (
            patch(f"{prefix}.JIRA") as mock_jira_cls,
            patch.object(JiraClient, "_fetch_cloud_id", return_value=None),
            patch(f"{prefix}.configure_oauth2_runtime") as mock_configure,
            patch(f"{prefix}.get_valid_jira_token_sync", return_value="tok-1"),
        ):
            mock_jira_cls.return_value = _make_jira(is_cloud=False, version=(9, 0, 0))
            client = JiraClient(config)
        return client, mock_jira_cls, mock_configure

    def test_connects_directly_against_server_url(self):
        client, mock_jira_cls, _ = self._connect(_make_oauth2_3lo_config())

        _, kwargs = mock_jira_cls.call_args
        assert kwargs["server"] == "https://jira.example.com"
        assert kwargs["token_auth"] == "tok-1"
        assert client._uses_gateway is False
        assert client._gateway_url is None

    def test_configures_dc_token_endpoint_with_form_encoding(self):
        _, _, mock_configure = self._connect(_make_oauth2_3lo_config())

        _, kwargs = mock_configure.call_args
        assert kwargs["token_url"] == "https://jira.example.com/rest/oauth2/1.0/token"
        assert kwargs["body_format"] == "form"
        assert kwargs["grant_type"] == "refresh_token"
        assert kwargs["client_id"] == "cid"
        assert kwargs["client_secret"] == "csec"
        assert kwargs["refresh_token"] == "rt-1"

    def test_session_send_is_patched_for_bearer_injection(self):
        client, _, _ = self._connect(_make_oauth2_3lo_config())

        # _patch_session_for_oauth2_token replaces session.send with a closure.
        assert client.jira._session.send.__name__ == "_oauth2_send"

    def test_2lo_without_cloud_id_raises(self):
        prefix = "testbench_defect_service.clients.jira.jira_client"
        config = _make_config(
            auth_type="oauth2 2LO (service account)",
            username=None,
            password=None,
            oauth2_client_id="cid",
            oauth2_client_secret="csec",
        )
        with (
            patch(f"{prefix}.JIRA"),
            patch.object(JiraClient, "_fetch_cloud_id", return_value=None),
            pytest.raises(ConnectionError, match="2LO"),
        ):
            JiraClient(config)


@pytest.mark.unit
class TestConnectOauth2CloudUnchanged:
    """OAuth2 with a cloud_id must keep using the Atlassian gateway."""

    def test_gateway_used_when_cloud_id_present(self):
        prefix = "testbench_defect_service.clients.jira.jira_client"
        with (
            patch(f"{prefix}.JIRA") as mock_jira_cls,
            patch.object(JiraClient, "_fetch_cloud_id", return_value="cid-1"),
            patch(f"{prefix}.configure_oauth2_runtime"),
            patch(f"{prefix}.get_valid_jira_token_sync", return_value="tok-1"),
        ):
            mock_jira_cls.return_value = _make_jira(is_cloud=True)
            client = JiraClient(_make_oauth2_3lo_config())

        _, kwargs = mock_jira_cls.call_args
        assert kwargs["server"] == "https://api.atlassian.com/ex/jira/cid-1"
        assert client._uses_gateway is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest.exe tests/unit/clients/jira/test_jira_client.py -v -k "DirectOauth2 or CloudUnchanged"`
Expected: FAIL — the DC tests raise `ConnectionError` (current code treats a missing cloud_id as a hard error); the Cloud test may already pass.

- [ ] **Step 3: Implement in `jira_client.py`**

Add imports: extend the jira_oauth import block with `BODY_FORMAT_FORM` and `data_center_token_url`, and add `from urllib import error as urllib_error` to the stdlib imports:

```python
from testbench_defect_service.clients.jira.jira_oauth import (
    BODY_FORMAT_FORM,
    GRANT_CLIENT_CREDENTIALS,
    GRANT_REFRESH_TOKEN,
    JiraAuthExpiredError,
    configure_oauth2_runtime,
    data_center_token_url,
    get_valid_jira_token_sync,
)
```

In `_connect`, replace the line `return self._connect_via_gateway()` (inside `if is_oauth2(self.config.auth_type):`) with:

```python
            if is_oauth2(self.config.auth_type):
                cloud_id = self._fetch_cloud_id()
                if cloud_id:
                    return self._connect_via_gateway(cloud_id)
                logger.info(
                    "No Atlassian Cloud ID found for '%s' — treating the instance as "
                    "Jira Data Center and connecting directly (OAuth2).",
                    self.config.server_url,
                )
                return self._connect_direct_oauth2()
```

Also update `_connect`'s docstring connection-strategy notes to mention the OAuth2 DC path (cloud_id probe decides gateway vs direct).

Change `_connect_via_gateway` to accept the pre-fetched cloud_id (the basic-auth scoped-token fallback still calls it without arguments):

```python
    def _connect_via_gateway(self, cloud_id: str | None = None) -> JIRA:
        """Connect to Jira Cloud through the Atlassian API gateway.

        Uses *cloud_id* when given (already fetched by the caller), otherwise
        fetches it. Creates a JIRA instance against the gateway URL.

        Raises ``ConnectionError`` when the Cloud ID cannot be fetched or the
        gateway connection fails.
        """
        cloud_id = cloud_id or self._fetch_cloud_id()
        if not cloud_id:
            ...  # rest of the method body unchanged
```

Add the new method after `_connect_via_gateway`:

```python
    def _connect_direct_oauth2(self) -> JIRA:
        """Connect to Jira Data Center directly with OAuth2 (3LO).

        Jira DC has no Atlassian gateway: tokens come from
        ``{server_url}/rest/oauth2/1.0/token`` (form-encoded bodies) and API
        requests go straight to the configured server URL.  Only the 3LO
        (refresh_token) grant is supported on Data Center.
        """
        if self.config.auth_type == AUTH_OAUTH2_2LO:
            raise ConnectionError(
                f"OAuth2 2LO (client_credentials) is not supported on Jira Data Center "
                f"('{self.config.server_url}'). Use 'oauth2 3LO (user account)' or another "
                "auth_type."
            )

        token_url = data_center_token_url(self.config.server_url)
        configure_oauth2_runtime(
            grant_type=GRANT_REFRESH_TOKEN,
            refresh_token=self.config.oauth2_refresh_token,
            client_id=self.config.oauth2_client_id,
            client_secret=self.config.oauth2_client_secret,
            expires_at=self.config.oauth2_expires_at,
            token_url=token_url,
            body_format=BODY_FORMAT_FORM,
        )
        try:
            initial_oauth2_token = get_valid_jira_token_sync(is_first_call=True)
        except JiraAuthExpiredError as exc:
            raise ConnectionError(
                "Jira OAuth2 authorization expired while establishing the initial connection. "
                "Please re-run the setup wizard to authorize Jira OAuth2."
            ) from exc
        except urllib_error.HTTPError as exc:
            if exc.code == HTTPStatus.NOT_FOUND:
                raise ConnectionError(
                    f"Jira OAuth2 token endpoint not found at '{token_url}' (HTTP 404). "
                    "Ensure an incoming OAuth 2.0 application link is configured in Jira "
                    "Data Center — or, if this is a Jira Cloud site, that "
                    f"'{self.config.server_url}{_TENANT_INFO_PATH}' is reachable."
                ) from exc
            raise

        jira = self._create_jira_instance(
            self.config.server_url, token_override=initial_oauth2_token
        )
        self._patch_session_for_oauth2_token(jira._session)

        if not self._verify_connection(jira):
            raise JiraConnectionError(
                f"OAuth2 authentication failed against Jira Data Center at "
                f"'{self.config.server_url}'. Please re-run the setup wizard to "
                "authorize Jira OAuth2.",
                status_code=HTTPStatus.UNAUTHORIZED,
            )
        return jira
```

- [ ] **Step 4: Run the full jira test suite**

Run: `.venv/Scripts/pytest.exe tests/unit/clients/jira -v`
Expected: ALL PASS (new DC tests, gateway tests, and all pre-existing tests).

- [ ] **Step 5: Lint and commit**

Run: `.venv/Scripts/ruff.exe check src/testbench_defect_service/clients/jira/jira_client.py tests/unit/clients/jira/test_jira_client.py`
Expected: no errors.

```bash
git add src/testbench_defect_service/clients/jira/jira_client.py tests/unit/clients/jira/test_jira_client.py
git commit -m "feat: connect directly to Jira Data Center for OAuth2 3LO

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Wizard authorization-code path + `config.py` call site

**Files:**
- Modify: `src/testbench_defect_service/utils/config_wizard.py` (function `run_jira_oauth_wizard`, currently at the end of the file)
- Modify: `src/testbench_defect_service/config.py:173` (`_prompt_for_missing_jira_oauth2_refresh_token`)
- Test: `tests/unit/utils/test_config_wizard.py`

**Interfaces:**
- Consumes: `exchange_authorization_code_sync(...)`, `data_center_token_url(...)`, `JiraAuthExpiredError` (Tasks 1–2).
- Produces: `run_jira_oauth_wizard(client_config: dict | None = None) -> str | None` — returns a refresh token (pasted or exchanged) or `None`. The caller (`config.py`) keeps seeding the returned token via `seed_oauth2_refresh_token` (idempotent; the exchange already persisted it).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/utils/test_config_wizard.py`:

```python
from unittest.mock import MagicMock, patch

from testbench_defect_service.clients.jira.jira_oauth import JiraAuthExpiredError
from testbench_defect_service.utils.config_wizard import run_jira_oauth_wizard

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
```

Note: `tests/unit/utils/test_config_wizard.py` already imports `os`, `pytest`, and `Path`; add the new imports shown above to the existing import block. The existing autouse `_clear_env` fixture already deletes `JIRA_OAUTH2_CLIENT_SECRET` before each test, so the env-var test's `monkeypatch.setenv` is isolated.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest.exe tests/unit/utils/test_config_wizard.py -v`
Expected: new tests FAIL (`run_jira_oauth_wizard() takes 0 positional arguments but 1 was given`); pre-existing tests still PASS.

- [ ] **Step 3: Implement the wizard changes**

In `src/testbench_defect_service/utils/config_wizard.py`, extend the jira_oauth import (top of file, currently `from testbench_defect_service.clients.jira.jira_oauth import seed_oauth2_refresh_token`):

```python
from testbench_defect_service.clients.jira.jira_oauth import (
    JiraAuthExpiredError,
    data_center_token_url,
    exchange_authorization_code_sync,
    seed_oauth2_refresh_token,
)
```

Replace `run_jira_oauth_wizard` (end of file) with:

```python
_OAUTH_CHOICE_REFRESH_TOKEN = "Enter a refresh token (Jira Cloud)"
_OAUTH_CHOICE_AUTH_CODE = "Exchange an authorization code (Jira Data Center)"


def run_jira_oauth_wizard(client_config: dict | None = None) -> str | None:
    """Obtain a Jira OAuth2 refresh token interactively.

    Offers two paths: paste an existing refresh token (Jira Cloud), or exchange
    a 3LO authorization code + PKCE verifier against the Jira Data Center token
    endpoint. Returns the refresh token, or ``None`` when the user aborts or
    the exchange fails.
    """
    click.echo("Jira OAuth2 refresh token is not configured. ")
    choice = questionary.select(
        "How would you like to provide OAuth2 authorization?",
        choices=[_OAUTH_CHOICE_REFRESH_TOKEN, _OAUTH_CHOICE_AUTH_CODE],
    ).ask()

    if choice == _OAUTH_CHOICE_REFRESH_TOKEN:
        refresh_token = questionary.text("Please enter your OAuth2 refresh token: ").ask()
        return refresh_token if isinstance(refresh_token, str) and refresh_token else None

    if choice == _OAUTH_CHOICE_AUTH_CODE:
        while True:
            refresh_token = _run_jira_dc_code_exchange(client_config or {})
            if refresh_token:
                return refresh_token
            retry = questionary.confirm(
                "Retry the authorization code exchange?", default=False
            ).ask()
            if not retry:
                return None

    return None


def _run_jira_dc_code_exchange(client_config: dict) -> str | None:
    """Prompt for code/verifier/redirect URI and exchange them at the DC endpoint."""
    server_url = client_config.get("server_url") or ""
    client_id = client_config.get("oauth2_client_id") or os.getenv("JIRA_OAUTH2_CLIENT_ID")
    client_secret = client_config.get("oauth2_client_secret") or os.getenv(
        "JIRA_OAUTH2_CLIENT_SECRET"
    )
    if not server_url or not client_id or not client_secret:
        click.echo(
            "Cannot exchange the authorization code: server_url and OAuth2 client "
            "credentials must be configured first."
        )
        return None

    code = questionary.text("Enter the authorization code: ").ask()
    code_verifier = questionary.text("Enter the PKCE code_verifier: ").ask()
    redirect_uri = questionary.text(
        "Enter the redirect URI used in the authorization request: "
    ).ask()
    if not all(isinstance(v, str) and v for v in (code, code_verifier, redirect_uri)):
        return None

    try:
        return exchange_authorization_code_sync(
            token_url=data_center_token_url(server_url),
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            code=code,
            code_verifier=code_verifier,
        )
    except JiraAuthExpiredError:
        click.echo(
            "Token exchange failed (HTTP 400/401). Authorization codes are single-use "
            "and short-lived — generate a new code and try again."
        )
        return None
```

Note the prompt order in `_run_jira_dc_code_exchange` must stay code → verifier → redirect URI (the tests feed `.ask()` answers in that order). `config_wizard.py` already imports `os`, `click`, and `questionary` at the top — verify, and add any that are missing.

In `src/testbench_defect_service/config.py`, change line 173 from `refresh_token = run_jira_oauth_wizard()` to:

```python
        refresh_token = run_jira_oauth_wizard(client_config)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest.exe tests/unit/utils/test_config_wizard.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Run the full unit test suite**

Run: `.venv/Scripts/pytest.exe tests/unit -v`
Expected: ALL PASS.

- [ ] **Step 6: Lint and commit**

Run: `.venv/Scripts/ruff.exe check src/testbench_defect_service/utils/config_wizard.py src/testbench_defect_service/config.py tests/unit/utils/test_config_wizard.py`
Expected: no errors.

```bash
git add src/testbench_defect_service/utils/config_wizard.py src/testbench_defect_service/config.py tests/unit/utils/test_config_wizard.py
git commit -m "feat: wizard option to exchange a Jira DC authorization code

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Documentation and changelog

**Files:**
- Modify: `docs/clients/jira-client.md` (after the existing "OAuth 2.0 (3LO) auth — user account (Jira Cloud)" section, which starts at line 239)
- Modify: `CHANGELOG.md` (top of the file, following the existing entry format)

**Interfaces:**
- Consumes: wizard behavior from Task 4 (prompt labels), endpoints from Tasks 1–3.

- [ ] **Step 1: Add the Data Center 3LO section to `docs/clients/jira-client.md`**

Insert after the end of the existing Cloud 3LO section (read the section first to place it before the following heading). Content:

````markdown
### OAuth 2.0 (3LO) auth — user account (Jira Data Center)

Jira Data Center supports the same 3-Legged OAuth flow with an *incoming*
OAuth 2.0 application link (**Administration → Applications → Application
links**, type "External application", direction "Incoming"). Configure it with
a redirect URL you control and take note of the generated client ID and client
secret. The same `auth_type` is used as on Jira Cloud — the service detects
Data Center automatically and sends token and API requests directly to your
`server_url` instead of the Atlassian gateway.

```toml
[testbench-defect-service.client_config]
server_url   = "https://jira.example.com"
auth_type    = "oauth2 3LO (user account)"
oauth2_client_id = "YOUR_CLIENT_ID"
```

**Step 1 — Direct the user to the authorization URL**

Data Center requires PKCE. Generate a random `code_verifier` (43–128
characters) and its `code_challenge` (Base64-URL-encoded SHA-256 hash of the
verifier), then open:

```
https://jira.example.com/rest/oauth2/latest/authorize?
  client_id=YOUR_CLIENT_ID&
  redirect_uri=YOUR_REDIRECT_URI&
  response_type=code&
  scope=WRITE&
  code_challenge=YOUR_CODE_CHALLENGE&
  code_challenge_method=S256
```

After the user approves, the browser is redirected to
`YOUR_REDIRECT_URI?code=AUTHORIZATION_CODE`.

**Step 2 — Exchange the code in the setup wizard**

Authorization codes are single-use and short-lived. When the service starts
without a stored refresh token, the wizard offers *"Exchange an authorization
code (Jira Data Center)"* — paste the authorization code, the `code_verifier`,
and the redirect URI. The wizard exchanges them at
`{server_url}/rest/oauth2/1.0/token` and stores only the resulting refresh
token in `tmp/oauth2_tokens.toml`. Access tokens are refreshed automatically
from there; Data Center rotates the refresh token on every refresh, and the
service persists each new one.
````

- [ ] **Step 2: Update the environment-variable table note in `docs/clients/jira-client.md`**

The table around line 352 scopes `JIRA_OAUTH2_CLIENT_ID` / `JIRA_OAUTH2_CLIENT_SECRET` / `JIRA_OAUTH2_REFRESH_TOKEN` to "Jira Cloud". Change those descriptions to "(2LO and 3LO, Jira Cloud; 3LO, Jira Data Center)" and "(3LO only)" respectively so DC is covered.

- [ ] **Step 3: Add a CHANGELOG entry**

Read the top of `CHANGELOG.md` and follow its existing format (version heading + bullet). Add under a new "Unreleased" heading (or the current unreleased section if one exists):

```markdown
- Jira: OAuth 2.0 3LO support for Jira Data Center — automatic Data Center
  detection, token requests against `{server_url}/rest/oauth2/1.0/token`
  (form-encoded, PKCE authorization-code exchange in the setup wizard), and
  API requests sent directly to the configured server URL instead of the
  Atlassian gateway.
```

- [ ] **Step 4: Verify docs build/lint isn't broken and commit**

Run: `.venv/Scripts/pytest.exe tests/unit -q` (sanity: docs changes touch no code)
Expected: ALL PASS.

```bash
git add docs/clients/jira-client.md CHANGELOG.md
git commit -m "docs: document Jira Data Center OAuth2 3LO setup

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

# Design: OAuth2 3LO Support for Jira Data Center

**Date:** 2026-07-31
**Status:** Approved

## Goal

Support the OAuth 2.0 three-legged (3LO, authorization code + PKCE) flow against
Jira Data Center instances. Jira DC differs from Jira Cloud in three ways:

1. The token endpoint is `{server_url}/rest/oauth2/1.0/token` instead of
   `https://auth.atlassian.com/oauth/token`.
2. The initial token exchange uses the `authorization_code` grant with a PKCE
   `code_verifier`:

   ```
   grant_type    = authorization_code
   client_id     = <CLIENT_ID>
   client_secret = <CLIENT_SECRET>
   redirect_uri  = <REDIRECT_URI>
   code          = <auth_code>
   code_verifier = <code_verifier>
   ```

3. API requests go directly to `{server_url}` — there is no Atlassian API
   gateway and no cloud_id.

## Scope

- 3LO only. No 2LO/client_credentials for DC (DC does not offer it the same way).
- The user performs the browser authorization step externally and pastes the
  resulting authorization code and code_verifier into the setup wizard; the
  wizard performs the token exchange (decided during brainstorming).
- Expired-refresh-token behavior stays "re-run the setup wizard".
- The existing Jira Cloud OAuth2 behavior (2LO and 3LO) must remain unchanged.

## 1. Deployment detection (`jira_client.py`)

The OAuth2 connect path (`_connect`) probes `_fetch_cloud_id()` first:

- **cloud_id found** → existing Cloud path, unchanged (auth.atlassian.com,
  gateway URL, session URL-rewrite patch).
- **cloud_id is `None`** → Data Center path via a new `_connect_direct_oauth2()`:
  - configure the OAuth runtime with token URL
    `{server_url}/rest/oauth2/1.0/token` and form-encoded bodies,
  - obtain an initial access token (`get_valid_jira_token_sync(is_first_call=True)`),
  - create the JIRA instance directly against `config.server_url`,
  - reuse the existing `_patch_session_for_oauth2_token()` for bearer injection,
  - verify authentication via `/myself` (`_verify_connection`),
  - no gateway, no URL rewriting, `_uses_gateway` stays `False`.

Today a failed cloud_id fetch is a hard error for OAuth2; it becomes the DC
signal (logged at info level).

**Misdetection failure mode:** a Cloud site whose `/_edge/tenant_info` is
blocked (e.g. by a proxy) is treated as DC, hits the DC token endpoint, gets a
404/400, and fails with an error message naming both possibilities.

## 2. Token module (`jira_oauth.py`)

- `_oauth2_settings` gains two keys:
  - `token_url` — default `https://auth.atlassian.com/oauth/token`,
  - `body_format` — `"json"` (default, Cloud) or `"form"` (DC; the DC endpoint
    expects `application/x-www-form-urlencoded` per RFC 6749).
- `configure_oauth2_runtime()` accepts `token_url` and `body_format` parameters.
- `_post_oauth_token_request()` posts to the configured URL in the configured
  format. Cloud behavior is bit-for-bit unchanged.
- New `exchange_authorization_code_sync(token_url, client_id, client_secret,
  redirect_uri, code, code_verifier)`:
  - posts the `authorization_code` grant payload (above) to *token_url*,
  - stores access token, refresh token, and expiry in the token store,
  - persists the refresh token to `tmp/oauth2_tokens.toml`,
  - returns the refresh token,
  - raises `JiraAuthExpiredError` on HTTP 400/401.
- `_refresh_jira_token_sync()` is unchanged logically — it already stores the
  rotated refresh token from each response, which DC requires (DC refresh
  tokens are single-use).

## 3. Setup wizard (`config_wizard.py` + `config.py`)

When the 3LO refresh token is missing, `run_jira_oauth_wizard` offers a choice:

- **"I have a refresh token"** (Cloud, current behavior) → paste it; returned
  to the caller and seeded as today.
- **"I have an authorization code (Data Center)"** → prompt for the
  authorization code, `code_verifier`, and `redirect_uri`; call
  `exchange_authorization_code_sync()` against
  `{server_url}/rest/oauth2/1.0/token`; on success the refresh token is seeded
  exactly like today. On failure (400/401): clear message that authorization
  codes are single-use and short-lived; the user may retry or abort.

The call site in `config.py` passes the Jira `client_config` (server_url,
client id, client secret) into the wizard function.

Nothing new is persisted — code, verifier, and redirect_uri are one-time-use;
only the refresh token goes to the token cache, as today.

## 4. Config model

No new config fields. `auth_type = "oauth2 3LO (user account)"` covers both
deployments; existing validation (client id/secret required, refresh token or
cached token required) applies unchanged.

## 5. Error handling

- Exchange HTTP 400/401 → `JiraAuthExpiredError` with an actionable message
  (invalid, expired, or already-used code; verifier mismatch).
- DC token endpoint HTTP 404 → error suggesting the incoming OAuth 2.0
  application link may not be configured in Jira DC, or that the site is
  actually Cloud with `/_edge/tenant_info` blocked.
- Expired refresh token at runtime → unchanged: "re-run the setup wizard".

## 6. Testing

Mirror the existing test layout (all HTTP mocked):

- `tests/unit/clients/jira/test_jira_oauth.py` — exchange function payload and
  token-store effects, form encoding, DC token URL used for refresh,
  refresh-token rotation persisted.
- `tests/unit/clients/jira/test_jira_client.py` — cloud_id `None` → direct DC
  connect against server_url, bearer patch applied, no gateway rewrite patch;
  cloud_id present → gateway path unchanged.
- `tests/unit/utils/test_config_wizard.py` — DC prompt path, exchange called
  with pasted values, refresh token seeded.

## 7. Documentation

- Extend `docs/clients/jira-client.md` with an "OAuth 2.0 (3LO) — Jira Data
  Center" section: constructing the authorize URL
  `{server_url}/rest/oauth2/latest/authorize` with PKCE, obtaining the code and
  verifier, and the wizard exchange step.
- Add a CHANGELOG entry.

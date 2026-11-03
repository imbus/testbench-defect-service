# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
---

## [Unreleased]

### Added
- Jira credentials can be read from secret files: every credential environment variable
  (`JIRA_PASSWORD`, `JIRA_BEARER_TOKEN`, `JIRA_OAUTH2_CLIENT_SECRET`,
  `JIRA_OAUTH1_ACCESS_TOKEN`, `JIRA_OAUTH1_ACCESS_TOKEN_SECRET`, `JIRA_OAUTH1_KEY_CERT`)
  accepts a `<VARIABLE>_FILE` variant naming a file that holds the value.

### Changed
- The configuration wizard stores every Jira credential in `.env` instead of
  `config.toml`, and moves credentials found in an existing `config.toml` into `.env`.
- A credential set in the environment or a `_FILE` now overrides the value in
  `config.toml`; a credential found in `config.toml` logs a warning at start.
- The service refuses to start when a `_FILE` cannot be read or is empty, or when both
  `<VARIABLE>` and `<VARIABLE>_FILE` are set. The message names the variable only.

### Security
- `.env` and the OAuth2 token cache (`tmp/oauth2_tokens.toml`) are created readable and
  writable by the owner only on Linux and macOS.

## [0.3.0][0.3.0] 30.07.2026

### Added

- OAuth2 2LO (service account) authentication for the Jira backend, using the
  `client_credentials` grant. The access token is minted from the client
  id/secret alone — no refresh token, no user authorization — and kept in memory
  (re-minted on expiry, never written to disk).
- Jira: OAuth 2.0 3LO support for Jira Data Center — automatic Data Center
  detection, token requests against `{server_url}/rest/oauth2/1.0/token`
  (form-encoded, PKCE authorization-code exchange in the setup wizard), and
  API requests sent directly to the configured server URL instead of the
  Atlassian gateway.
- Jira: OAuth 2.0 2LO (client_credentials) support for Jira Data Center —
  tokens are minted directly from `{server_url}/rest/oauth2/1.0/token`
  (form-encoded) when no Atlassian Cloud ID is found. Note that vanilla Jira
  Data Center only offers authorization-code flows; the instance must provide
  the `client_credentials` grant (e.g. via a marketplace app).
- Jira: the short `auth_type` values `"oauth2 2LO"` and `"oauth2 3LO"` are
  accepted as aliases for the descriptive long forms.


### Changed

- Split the Jira `auth_type` OAuth2 option into
  `"oauth2 2LO (service account)"` and `"oauth2 3LO (user account)"` (previously
  a single `"oauth2"` value), and updated the client, wizard, and validation to
  recognize both flows.
- OAuth2 access tokens are now held in memory only and are never written to
  `tmp/oauth2_tokens.toml`. Only the 3LO refresh token is persisted to disk.
- Split the Jira `auth_type` OAuth2 option into
  `"oauth2 2LO (service account)"` and `"oauth2 3LO (user account)"` (previously
  a single `"oauth2"` value), and updated the client, wizard, and validation to
  recognize both flows.
- OAuth2 access tokens are now held in memory only and are never written to
  `tmp/oauth2_tokens.toml`. Only the 3LO refresh token is persisted to disk.

---

## [0.2.0][0.2.0] - 2026-07-27

### Added

- OAuth2 authentication support for the Jira backend, including client ID/secret
  configuration, refresh token handling, and token cache management.
- Setup wizard for retrieving and storing Jira OAuth2 tokens during
  configuration.
- Extended defect creation via `create_extended_defect_from_issue`.
- `site_url` parameter for defect creation to generate correct permalinks and
  attachment URLs.
- Reporter field mapping when creating and updating Jira issues.
- Migration procedure and documentation for transitioning from the previous
  Defect Service architecture (including reuse of existing DMProxy configuration
  values).
- Troubleshooting guidance for Jira synchronization issues related to
  permissions.

### Changed

- Refactored error handling in `JiraDefectClient`; introduced
  `JiraConnectionError` to preserve HTTP status codes and improve error
  messaging.
- OAuth2 client ID and secret are now required; runtime client credentials can
  override cached token values.
- Renamed `fetch_all_custom_fields` to `get_all_project_fields` for clarity.
- `fetch_project_issue_fields` now falls back to the `createmeta` endpoint for
  improved reliability.
- Default name in `JiraDefectClientConfig` changed to `DefectService`.
- Documentation clarifications, formatting, and consistency improvements.

### Removed

- Deprecated `_connect_old` method from `JiraClient`.
- Control fields from defect mapping, streamlining the mapping logic.
- Duplicate attributes.

## [0.1.0][0.1.0] - 2026-04-20

### Added

- Initial release of TestBench Defect Service.
- REST API for managing defects backed by Jira or JSONL (file-based) clients.
- Interactive configuration wizard (`testbench-defect-service init`).
- HTTP Basic Authentication for API access.
- OpenAPI / Swagger UI documentation served at `/docs`.
- Pre/post sync command hooks.
- Support for multiple projects from a single service instance.
- CLI entry point (`testbench-defect-service`) with `init`, `start`, and `set-credentials` commands.
- `jira` optional dependency group for Jira backend support.

[0.3.0]: https://github.com/imbus/testbench-defect-service/releases/tag/v0.3.0
[0.2.0]: https://github.com/imbus/testbench-defect-service/releases/tag/v0.2.0
[0.1.0]: https://github.com/imbus/testbench-defect-service/releases/tag/v0.1.0

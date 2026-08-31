# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
---

## [Unreleased]

---

## [0.4.0][0.4.0] - 2026-08-21

### Added

- **Excel client** — a new backend that reads and writes defects directly from
  spreadsheet and delimited files (`.xlsx`, `.xls`, `.csv`, `.tsv`, `.txt`)
  instead of from a defect tracker. Each project is a subdirectory under
  `excel_file_path`, one row is one defect, and every defect field is mapped to a
  1-based column number — so a spreadsheet that is already in use can be
  synchronized without changing its layout. The client is optional: install it
  with `pip install "testbench-defect-service[excel]"`. It is not bundled in the
  ready-to-use executable, and the service refuses to start if it is configured
  without the extra. Legacy `.xls` files are read-only; set `readonly = true` for
  those projects.
- Excel client: control fields (status, priority, classification, …) that carry
  their own allowed values and transition rules, so an invalid status change is
  rejected before it is written to the file.
- Excel client: user-defined attributes mapped to their own columns, including
  boolean columns with configurable true/false values.
- Excel client: defect IDs generated with a configurable prefix, starting value
  and zero padding. Duplicate or ambiguous IDs in a file are reported instead of
  a row being picked silently.
- Excel client: write buffering, and file locking so that two concurrent
  synchronizations cannot corrupt a file another writer holds.
- Excel client: per-project overrides, either as `[projects.<name>]` sections in
  `config.toml` or as a `<Project>.properties` file placed beside the project's
  data.
- Excel client: pre- and post-sync command hooks, matching those of the Jira and
  JSONL clients.
- Excel client: legacy DMProxy `.properties` files are read directly, so an
  existing connector configuration can be pointed at instead of rewritten.
- `migrate` command to convert a legacy `.conf` (Jira) or `.properties` (Excel)
  wrapper configuration into a TOML configuration file. The converted values are
  validated against the client models, the authentication settings and service
  credentials the legacy formats never carried are asked for interactively, and an
  existing configuration file is backed up before being replaced.

### Fixed

- A defect that could not be created in Jira no longer aborts the whole
  synchronization. The response carried `value: ""` on failure, which TestBench
  read as a successful creation with an empty ID and rejected with its non-empty
  ID assertion. The field is now `null` when no defect was created.
- The Jira legacy-configuration prompts no longer restart forever. The server URL was
  missing from the prompted field set while the collected answers were validated
  against the whole `JiraDefectClientConfig`, in which it is the only required field,
  so validation always failed with `server_url: Field required` and the wizard's retry
  loop could never terminate. The server URL is now prompted for and pre-filled from
  the legacy `jira.baseUri` entry.
- An empty row in an Excel or delimited defect file no longer fails the whole
  file. Empty rows are skipped with a single import warning per synchronization
  and are preserved in the file when defects are created, updated or deleted.
- Blank boolean UDF cells are reported as unset instead of being coerced to the
  configured `falseValue`.

---

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

[0.4.0]: https://github.com/imbus/testbench-defect-service/releases/tag/v0.4.0
[0.3.0]: https://github.com/imbus/testbench-defect-service/releases/tag/v0.3.0
[0.2.0]: https://github.com/imbus/testbench-defect-service/releases/tag/v0.2.0
[0.1.0]: https://github.com/imbus/testbench-defect-service/releases/tag/v0.1.0

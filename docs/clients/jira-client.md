---
sidebar_position: 3
title: Jira Client
---
# Jira Client

The Jira client integrates the TestBench Defect Service with [Jira Cloud](https://www.atlassian.com/software/jira) and [Jira Data Center / Server](https://www.atlassian.com/enterprise/data-center/jira). It maps TestBench defect operations to Jira issue operations using the official `jira` Python library.

---

## Overview

When the Jira client is active, defect CRUD operations performed by TestBench are translated into Jira API calls:

| TestBench action   | Jira action                                             |
| ------------------ | ------------------------------------------------------- |
| List defects       | Search issues via JQL                                   |
| Create defect      | Create issue + transition status + add attachments      |
| Update defect      | Update fields + transition workflow + sync attachments  |
| Delete defect      | Delete issue                                            |
| Get control fields | Query Jira metadata (statuses, issue types, priorities) |

---

## Requirements

The Jira client is an **optional** component. Install it with:

```bash
pip install "testbench-defect-service[jira]"
```

Or when installing from source:

```bash
pip install -e ".[jira]"
```

### Required Jira permissions

The service account used by the Defect Service must hold the following Jira project permissions:

#### Project & users

| Permission                | Purpose                         |
| ------------------------- | ------------------------------- |
| **Browse Projects** | List and query projects         |
| **Browse Users**    | Display assignees and reporters |

#### Issue management

| Permission                  | Purpose                                    |
| --------------------------- | ------------------------------------------ |
| **Create Issues**     | Sync new defects to Jira                   |
| **Edit Issues**       | Update defect attributes                   |
| **Delete Issues**     | Delete defects (`readonly = false` only) |
| **Transition Issues** | Update defect status                       |

#### Attachments

| Permission                   | Purpose                                        |
| ---------------------------- | ---------------------------------------------- |
| **Create Attachments** | Sync attachments to defects                    |
| **Delete Attachments** | Remove attachments (`readonly = false` only) |

**Configuration:** Permissions are configured per project under **Project Settings → Permissions**. Assign them to the role or user the service authenticates as.

:::note
 When `readonly = true` is set, the service does not exercise any write permissions. Browse Projects and Browse Users are still required for read operations.
:::

### Jira scoped API token scopes (Jira Cloud)

When you use a **scoped** Jira API token (instead of a classic API token), grant at least:

- **`read:jira-work`** — required for project and issue data (projects, issue search, issue fields, changelogs, versions, boards/sprints).
- **`read:jira-user`** — required for user/account information used by Jira APIs.
- **`write:jira-work`** —  required for field metadata calls.

---

## Configuration

Add the following to your `config.toml` to enable the Jira client:

```toml
# config.toml
[testbench-defect-service]
client_class       = "testbench_defect_service.clients.JiraDefectClient"
client_config_path = "config.toml"

[testbench-defect-service.client_config]
name           = "Jira"
server_url     = "https://your-company.atlassian.net"
auth_type      = "basic"
defect_jql     = "project = '{project}' AND issuetype in standardIssueTypes()"
attributes     = ["title", "status", "priority", "classification"]
readonly       = false
```

### Connection settings

| Option         | Type   | Description                                                                                          | Required      | Default    |
| -------------- | ------ | ---------------------------------------------------------------------------------------------------- | ------------- | ---------- |
| `name`       | String | Display name shown in TestBench. Must match the name in the DMProxy properties file or during setup. | No            | "DefectService" |
| `server_url` | String | Base URL of your Jira instance (no trailing slash).                                                  | **Yes** | —         |

### Network & SSL settings
| Option | Type | Description | Required | Default |
|--------|------|-------------|----------|---------|
| `proxy_url` | String | Proxy URL (leave empty if no proxy is needed). | No |
| `verify_ssl` | Boolean | Enable SSL certificate verification for the Jira HTTPS connection. Set to `false` only in development/test environments with self-signed certificates when providing a CA cert file is not possible. Can also be set via `JIRA_VERIFY_SSL`. | No |
| `ssl_ca_cert_path` | String | Path to a CA certificate or bundle file (`.pem`/.`crt`) used to verify the Jira server's SSL certificate. Can also be set via `JIRA_SSL_CA_CERT_PATH`. | No |
| `client_cert_path` | String | Path to client certificate file for mutual TLS authentication (`.pem` or `.crt`). Can also be set via `JIRA_CLIENT_CERT_PATH`. | No |
| `client_key_path` | String | Path to client private key file for mutual TLS authentication (`.key` or `.pem`). Only needed when the key is stored separately from the certificate. Can also be set via `JIRA_CLIENT_KEY_PATH`. | No |

### Authentication methods

| Option                   | Type    | Description                                                                                                 | Required | Default     |
| ------------------------ | ------- | ----------------------------------------------------------------------------------------------------------- | -------- | ----------- |
| `auth_type`            | String  | Authentication method. One of `"basic"`, `"token"`, `"oauth1"`, `"oauth2 2LO (service account)"`, or `"oauth2 3LO (user account)"`. | No       | `"basic"` |
| `username`             | String  | Jira username for basic auth. Can also be set via`JIRA_USERNAME`.                                         | No       | —          |
| `password`             | String  | Jira API token for basic auth. Can also be set via`JIRA_PASSWORD`.                                        | No       | —          |
| `token`                | String  | Personal Access Token for token auth (Jira Data Center). Can also be set via`JIRA_BEARER_TOKEN`.          | No       | —          |
| `oauth2_client_id`     | String  | OAuth 2.0 client ID for both oauth2 flows (Jira Cloud; 3LO also on Jira Data Center). Can also be set via `JIRA_OAUTH2_CLIENT_ID`.         | No       | —          |
| `oauth2_client_secret` | String  | OAuth 2.0 client secret for both oauth2 flows (Jira Cloud; 3LO also on Jira Data Center). Always stored via the `JIRA_OAUTH2_CLIENT_SECRET` environment variable (`.env`), never in `config.toml`. | No       | —          |
| `enable_shared_auth`   | Boolean | Use service account credentials for all projects instead of per-user auth.                                  | No       | —          |

There are two OAuth 2.0 flows:

- **2LO (service account)** — the `client_credentials` grant. The access token is
  minted from `oauth2_client_id` + `oauth2_client_secret` alone; there is no user,
  no refresh token, and no authorization step. The token is held in memory and
  re-minted automatically when it nears expiry (nothing is written to disk).
- **3LO (user account)** — the authorization-code grant with a refresh token. The
  setup wizard collects the refresh token once and stores it in
  `tmp/oauth2_tokens.toml`; the service exchanges it for access tokens at runtime.

For 3LO, do not add access or refresh token values to `config.toml` or `.env`.

### Query & fields

| Option         | Type   | Description                                                                                                                                | Required | Default                                                           |
| -------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------ | -------- | ----------------------------------------------------------------- |
| `defect_jql` | String | JQL query used to fetch defects.`{project}` is replaced with the project key at runtime. See [Example JQL queries](#example-jql-queries). | No       | `"project = '{project}' AND issuetype in standardIssueTypes()"` |
| `attributes` | List   | Jira fields to include in defect responses.                                                                                                | No       | `["title", "status"]`                                           |

### Behavior

| Option                          | Type    | Description                                           | Required | Default   |
| ------------------------------- | ------- | ----------------------------------------------------- | -------- | --------- |
| `readonly`                    | Boolean | When`true`, all write operations are rejected.      | No       | `false` |
| `show_change_history`         | Boolean | Include change history in extended defect attributes. | No       | —        |
| `supports_changes_timestamps` | Boolean | Whether the client tracks modification timestamps.    | No       | `true`  |

### Advanced

| Option       | Type  | Description                                                                             | Required | Default |
| ------------ | ----- | --------------------------------------------------------------------------------------- | -------- | ------- |
| `commands` | Table | Pre/post sync commands. See[Configuration](../configuration.md#prepost-sync-commands).   | No       | —      |
| `projects` | Table | Per-project configuration overrides. See[Per-project overrides](#per-project-overrides). | No       | `{}`  |

---

## Authentication

### Basic auth (Jira Cloud)

Recommended for Jira Cloud. Uses your Atlassian account email and an API token.

```toml
# config.toml
[testbench-defect-service.client_config]
auth_type  = "basic"
username   = "your-email@company.com"
password  = "your-api-token"
```

Generate an API token at `https://id.atlassian.com/manage-profile/security/api-tokens`.

### Token auth (Jira Data Center)

Uses a Personal Access Token (PAT) generated in your Jira Data Center profile.

```toml
# config.toml
[testbench-defect-service.client_config]
auth_type = "token"
token     = "your-personal-access-token"
```

:::note
Personal Access Tokens expire based on the duration set in your Jira Data Center profile. If the service stops authenticating unexpectedly, check whether the token has expired and generate a new one.
:::

### OAuth 2.0 (2LO) auth — service account (Jira Cloud)

Uses the Atlassian 2-Legged OAuth (2LO) `client_credentials` grant. This is the
simplest OAuth option: the service mints its own access token from the client
credentials — there is no user, no browser authorization step, and no refresh
token to manage. Use it when your Atlassian app is set up as a service account
and you want all access under that single identity.

```toml
# config.toml
[testbench-defect-service.client_config]
auth_type        = "oauth2 2LO (service account)"
oauth2_client_id = "YOUR_CLIENT_ID"
```

The `oauth2_client_secret` is **always stored as an environment variable**
(`JIRA_OAUTH2_CLIENT_SECRET`), never in `config.toml`. When you enter it in the
setup wizard it is written to a `.env` file automatically; you can also export it
yourself. The client ID may be given either in `config.toml` (as above) or via
`JIRA_OAUTH2_CLIENT_ID`. No setup-wizard token step is required.

At runtime the service requests a token from the Atlassian token endpoint:

```bash
curl --request POST \
  --url 'https://auth.atlassian.com/oauth/token' \
  --header 'Content-Type: application/json' \
  --data '{
    "grant_type": "client_credentials",
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET"
  }'
```

The returned access token is held in memory only and re-minted automatically as
it nears expiry. Because it is always re-derivable from the client credentials,
nothing is written to `tmp/oauth2_tokens.toml`.

:::note
The client secret is the only value to protect and is always kept in the
environment (`.env`), never in `config.toml`.
:::

### OAuth 2.0 (3LO) auth — user account (Jira Cloud)

Uses an OAuth 2.0 access token obtained via the Atlassian 3-Legged OAuth (3LO) flow. This is recommended when your Atlassian app is registered in the [Atlassian developer console](https://developer.atlassian.com/console/myapps/) and you need delegated user access.

```toml
# config.toml
[testbench-defect-service.client_config]
auth_type    = "oauth2 3LO (user account)"
```

#### How to obtain an OAuth 2.0 access token

**Step 1 — Direct the user to the Atlassian authorization URL**

Send the user to the following URL in a browser (GET request). You can construct it manually or copy it from **Authorization → OAuth 2.0 (3LO) → Configure** in the developer console:

```
https://auth.atlassian.com/authorize?
  audience=api.atlassian.com&
  client_id=YOUR_CLIENT_ID&
  scope=read%3Ajira-work%20read%3Ajira-user%20write%3Ajira-work%20offline_access&
  redirect_uri=https://YOUR_APP_CALLBACK_URL&
  state=defect-service&
  response_type=code&
  prompt=consent
```

| Parameter         | Required       | Description                                                                                                                                               |
| ----------------- | -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `audience`      | Yes            | Always`api.atlassian.com`.                                                                                                                              |
| `client_id`     | Yes            | **Client ID** from your app's **Settings** in the developer console.                                                                          |
| `scope`         | Yes            | Space-separated list of scopes (URL-encoded as`%20`). Only choose scopes already added to your app. See [Required scopes](#required-oauth-scopes) below. |
| `redirect_uri`  | Yes            | Callback URL configured in**Authorization** for your app.                                                                                           |
| `state`         | Yes (security) | An opaque string to prevent CSRF, e.g.`defect-service`.                                                                                                 |
| `response_type` | Yes            | Must be`code`.                                                                                                                                          |
| `prompt`        | Yes            | Must be`consent` to show the access-grant screen.                                                                                                       |

If the user grants access, Atlassian redirects to `redirect_uri` with an `?code=...` query parameter.

**Step 2 — Exchange the authorization code for an access token**

```bash
curl --request POST \
  --url 'https://auth.atlassian.com/oauth/token' \
  --header 'Content-Type: application/json' \
  --data '{
    "grant_type": "authorization_code",
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "code": "YOUR_AUTHORIZATION_CODE",
    "redirect_uri": "https://YOUR_APP_CALLBACK_URL"
  }'
```

A successful response returns:

```json
{
  "access_token": "<string>",
  "refresh_token":"<string>", 
  "expires_in": 3600,
  "scope": "<string>"
}
```

Run the setup wizard and enter the returned `refresh_token` when prompted. The wizard stores
that token in `tmp/oauth2_tokens.toml`, not in `config.toml`. Only the refresh token is written to
disk — the service uses it to request short-lived access tokens at runtime, and those access tokens
are held in memory only (never written to `tmp/oauth2_tokens.toml`).

Persist only the OAuth client credentials:

- `oauth2_client_id` — in `config.toml` or via `JIRA_OAUTH2_CLIENT_ID`
- `oauth2_client_secret` — always via the `JIRA_OAUTH2_CLIENT_SECRET` environment variable
  (`.env`); the setup wizard writes it there for you and keeps it out of `config.toml`

:::note
Do not store OAuth2 access tokens or refresh tokens in `config.toml` or `.env` files. If the refresh
token is revoked or expires, re-run the setup wizard to seed a new `tmp/oauth2_tokens.toml` cache.
:::

#### Required OAuth scopes

The minimum scopes needed by the Defect Service:

| Scope               | Purpose                                   |
| ------------------- | ----------------------------------------- |
| `read:jira-work`  | Read projects, issues, fields, changelogs |
| `read:jira-user`  | Read user/account information             |
| `write:jira-work` | Create and update issues, field metadata  |

For `readonly = true` deployments, `write:jira-work` can be omitted.

Refer to the Atlassian REST API documentation to confirm which scopes individual endpoints require:

- [Jira Cloud platform REST API](https://developer.atlassian.com/cloud/jira/platform/rest)
- [Jira Software Cloud REST API](https://developer.atlassian.com/cloud/jira/software/rest/intro/)

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

(`latest` is an alias for `1.0`, the same API version used by the token
endpoint below.)

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

:::warning
On Data Center, do not leave `JIRA_OAUTH2_REFRESH_TOKEN` set permanently: the
token rotates on every refresh, and a stale value from the environment would
override the newer token cached in `tmp/oauth2_tokens.toml` on the next
restart. Prefer the wizard flow; if you set the variable for the first start,
remove it afterwards.
:::

---

### Environment variables

:::tip
Prefer environment variables over hardcoding credentials in `config.toml` to avoid accidentally committing secrets to source control.
:::

To avoid storing credentials in the config file, use environment variables instead:

| Variable                      | Used for                                             |
| ----------------------------- | ---------------------------------------------------- |
| `JIRA_USERNAME`             | Username (basic auth)                                |
| `JIRA_PASSWORD`             | API token (basic auth)                               |
| `JIRA_BEARER_TOKEN`         | Personal Access Token (token auth, Jira Data Center) |
| `JIRA_OAUTH2_CLIENT_ID`     | OAuth 2.0 client ID (2LO and 3LO, Jira Cloud; 3LO, Jira Data Center) |
| `JIRA_OAUTH2_CLIENT_SECRET` | OAuth 2.0 client secret (2LO and 3LO, Jira Cloud; 3LO, Jira Data Center) |
| `JIRA_OAUTH2_REFRESH_TOKEN` | OAuth 2.0 refresh token (3LO only)       |

---

## Project mapping

The service lists Jira projects as `"<Project Name> (<PROJECT_KEY>)"`. TestBench selects a project by this combined name.

The `{project}` placeholder in `defect_jql` is replaced with the Jira **project key** (e.g. `MYPROJ`) at query time.

## Example JQL queries

Fetch only bugs, ordered by creation date:

```toml
defect_jql = "project = '{project}' AND issuetype = Bug ORDER BY created DESC"
```

Fetch all unresolved issues for a specific component:

```toml
defect_jql = "project = '{project}' AND component = 'Backend' AND resolution = Unresolved"
```

---

## Control fields

The Jira client automatically queries Jira metadata to populate allowed values for the following fields:

| Field         | Jira data source          |
| ------------- | ------------------------- |
| `status`    | Project workflow statuses |
| `issuetype` | Project issue types       |

All other fields (e.g. `priority`, custom select fields) are discovered automatically from the Jira field metadata API.

---

## Per-project overrides

Any top-level `client_config` option can be overridden per Jira project key:

```toml
[testbench-defect-service.client_config.projects.MYPROJ]
readonly = true

[testbench-defect-service.client_config.projects.MYPROJ.commands.presync]
scheduled = "C:\\scripts\\myproj-pre.bat"
```

The project key must match the Jira project key exactly (case-sensitive).

---

## Jira Cloud vs. Data Center

The client automatically detects whether it is connected to Jira Cloud or Jira Data Center and adapts its behavior accordingly:

| Feature              | Jira Cloud                             | Jira Data Center                    |
| -------------------- | -------------------------------------- | ----------------------------------- |
| Authentication       | Basic (email + API token) or OAuth 2.0 | Token (PAT), Basic, or OAuth 2.0 3LO |
| Pagination           | `nextPageToken` cursor               | `startAt` offset                  |
| Issue types endpoint | Standard                               | `issuetypes` endpoint (DC ≥ 8.4) |
| API base path        | `/rest/api/3/`                       | `/rest/api/2/`                    |

---

## Tips & Troubleshooting

- If you are able to successfully select a project, but the synchronization and/or field mapping process throws an error, please verify that your integrated Jira user account has been granted the Create Issues permission within that specific Jira project.

---

## Tips & Troubleshooting
- If you are able to successfully select a project, but the synchronization and/or field mapping process throws an error, please verify that your integrated Jira user account has been granted the Create Issues permission within that specific Jira project.

---

## Known limitations

| Limitation                     | Details                                                                                                                         |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| **Attachment sync**      | Jira Data Center supports one-way attachment sync from TestBench to Jira only.                                                  |
| **Sprint field**         | The Sprint field cannot be reliably updated via the API and is not supported.                                                   |
| **Jira Server (legacy)** | Only Jira Data Center and Jira Cloud are actively tested. Older Jira Server versions may work but are not officially supported. |

---
sidebar_position: 3
title: Jira Client
---

# Jira Client

The Jira client integrates the TestBench Defect Service with [Jira Cloud](https://www.atlassian.com/software/jira) and [Jira Data Center / Server](https://www.atlassian.com/enterprise/data-center/jira). It maps TestBench defect operations to Jira issue operations using the official `jira` Python library.

---

## Overview

When the Jira client is active, defect CRUD operations performed by TestBench are translated into Jira API calls:

| TestBench action | Jira action |
|---|---|
| List defects | Search issues via JQL |
| Create defect | Create issue + transition status + add attachments |
| Update defect | Update fields + transition workflow + sync attachments |
| Delete defect | Delete issue |
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
| Permission | Required |
|------------|----------|
| **Browse Projects** | List and query projects |
| **Browse Users** | Display assignees and reporters |

#### Issue management
| Permission | Required |
|------------|----------|
| **Create Issues** | Sync new defects to Jira |
| **Edit Issues** | Update defect attributes |
| **Delete Issues** | Delete defects (`readonly = false` only) |
| **Transition Issues** | Update defect status |

#### Attachments
| Permission | Required |
|------------|----------|
| **Create Attachments** | Sync attachments to defects |
| **Delete Attachments** | Remove attachments (`readonly = false` only) |

**Configuration:** Permissions are configured per project under **Project Settings → Permissions**. Assign them to the role or user the service authenticates as.

:::note
 When `readonly = true` is set, the service does not exercise any write permissions. Browse Projects and Browse Users are still required for read operations.
:::

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
control_fields = ["priority", "status", "classification"]
readonly       = false
```


### Connection settings

| Option | Type | Description | Required | Default |
|--------|------|-------------|----------|---------|
| `name` | String | Display name shown in TestBench. Must match the name in the DMProxy properties file or during setup. | No | `"Jira"` |
| `server_url` | String | Base URL of your Jira instance (no trailing slash). | **Yes** | — |

### Authentication methods

| Option | Type | Description | Required | Default |
|--------|------|-------------|----------|---------|
| `auth_type` | String | Authentication method. One of `"basic"`, `"token"`, or `"oauth"`. | No | `"basic"` |
| `username` | String | Jira username for basic auth. Can also be set via `JIRA_USERNAME`. | No | — |
| `password` | String | Jira API token for basic auth. Can also be set via `JIRA_PASSWORD`. | No | — |
| `token` | String | Personal Access Token for token auth (Jira Data Center). Can also be set via `JIRA_BEARER_TOKEN`. | No | — |
| `enable_shared_auth` | Boolean | Use service account credentials for all projects instead of per-user auth. | No | — |

### Query & fields

| Option | Type | Description | Required | Default |
|--------|------|-------------|----------|---------|
| `defect_jql` | String | JQL query used to fetch defects. `{project}` is replaced with the project key at runtime. See [Example JQL queries](#example-jql-queries). | No | `"project = '{project}' AND issuetype in standardIssueTypes()"` |
| `attributes` | List | Jira fields to include in defect responses. | No | `["title", "status"]` |
| `control_fields` | List | Fields for which the client returns allowed values. See [Control fields](#control-fields). | No | `["priority", "status", "classification"]` |

### Behavior

| Option | Type | Description | Required | Default |
|--------|------|-------------|----------|---------|
| `readonly` | Boolean | When `true`, all write operations are rejected. | No | `false` |
| `show_change_history` | Boolean | Include change history in extended defect attributes. | No | — |
| `supports_changes_timestamps` | Boolean | Whether the client tracks modification timestamps. | No | `true` |

### Advanced

| Option | Type | Description | Required | Default |
|--------|------|-------------|----------|---------|
| `commands` | Table | Pre/post sync commands. See [Configuration](../configuration.md#prepost-sync-commands). | No | — |
| `projects` | Table | Per-project configuration overrides. See [Per-project overrides](#per-project-overrides). | No | `{}` |

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

### Environment variables

:::tip
Prefer environment variables over hardcoding credentials in `config.toml` to avoid accidentally committing secrets to source control.
:::

To avoid storing credentials in the config file, use environment variables instead:

| Variable | Used for |
|----------|----------|
| `JIRA_USERNAME` | Username (basic auth) |
| `JIRA_PASSWORD` | API token (basic auth) |
| `JIRA_BEARER_TOKEN` | Personal Access Token (token auth, Jira Data Center) |

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

| Field | Jira data source |
|-------|------------------|
| `status` | Project workflow statuses |
| `priority` | Global Jira priorities |
| `classification` | Project issue types |

Additional fields listed in `control_fields` are resolved via the Jira field metadata API.

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

| Feature | Jira Cloud | Jira Data Center |
|---------|------------|------------------|
| Authentication | Basic (email + API token) | Token (PAT) or Basic |
| Pagination | `nextPageToken` cursor | `startAt` offset |
| Issue types endpoint | Standard | `issuetypes` endpoint (DC ≥ 8.4) |
| API base path | `/rest/api/3/` | `/rest/api/2/` |

---

## Known limitations

| Limitation | Details |
|------------|----------|
| **Attachment sync** | Jira Data Center supports one-way attachment sync from TestBench to Jira only. |
| **Sprint field** | The Sprint field cannot be reliably updated via the API and is not supported. |
| **Jira Server (legacy)** | Only Jira Data Center and Jira Cloud are actively tested. Older Jira Server versions may work but are not officially supported. |

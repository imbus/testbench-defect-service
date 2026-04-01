---
sidebar_position: 3
title: Jira Client
---

# Jira Client

The Jira client integrates the Testbench Defect Service with [Jira Cloud](https://www.atlassian.com/software/jira) and [Jira Data Center / Server](https://www.atlassian.com/enterprise/data-center/jira). It maps TestBench defect operations to Jira issue operations using the official `jira` Python library.

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

## Prerequisites

The Jira client is an **optional** component. Install it with:

```bash
pip install "testbench-defect-service[jira]"
```

Or when installing from source:

```bash
pip install -e ".[jira]"
```

### Required Jira Permissions

The service account used by the Defect Service must hold the following Jira project permissions:

#### Project & Users
| Permission | Required |
|---|---|
| **Browse Projects** | List and query projects |
| **Browse Users** | Display assignees and reporters |

#### Issue Management
| Permission | Required |
|---|---|
| **Create Issues** | Sync new defects to Jira |
| **Edit Issues** | Update defect attributes |
| **Delete Issues** | Delete defects (`readonly = false` only) |
| **Transition Issues** | Update defect status |

#### Attachments
| Permission | Required |
|---|---|
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

### Option Reference

**Connection**

| Key | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | No | `"Jira"` | Display name shown in TestBench. Must match the name in the DMProxy properties file or during setup. |
| `server_url` | string | **Yes** | — | Base URL of your Jira instance (no trailing slash). |

**Authentication**

| Key | Type | Required | Default | Description |
|---|---|---|---|---|
| `auth_type` | string | No | `"basic"` | Authentication method. One of `"basic"`, `"token"`, or `"oauth"`. |
| `username` | string | No | — | Jira username for basic auth. Can also be set via `JIRA_USERNAME`. |
| `password` | string | No | — | Jira API token for basic auth. Can also be set via `JIRA_PASSWORD`. |
| `token` | string | No | — | Personal Access Token for token auth (Jira Data Center). Can also be set via `JIRA_BEARER_TOKEN`. |
| `enable_shared_auth` | boolean | No | — | Use service account credentials for all projects instead of per-user auth. |

**Query & Fields**

| Key | Type | Required | Default | Description |
|---|---|---|---|---|
| `defect_jql` | string | No | `"project = '{project}' AND issuetype in standardIssueTypes()"` | JQL query used to fetch defects. `{project}` is replaced with the project key at runtime. See [Example JQL Queries](jira-client#example-jql-queries)|
| `attributes` | list | No | `["title", "status"]` | Jira fields to include in defect responses. |
| `control_fields` | list | No | `["priority", "status", "classification"]` | Fields for which the client returns allowed values. See [Control Fields](jira-client#control-fields)|

**Behavior**

| Key | Type | Required | Default | Description |
|---|---|---|---|---|
| `readonly` | boolean | No | `false` | When `true`, all write operations are rejected. |
| `show_change_history` | boolean | No | — | Include change history in extended defect attributes. |
| `supports_changes_timestamps` | boolean | No | `true` | Whether the client tracks modification timestamps. |

**Advanced**

| Key | Type | Required | Default | Description |
|---|---|---|---|---|
| `commands` | table | No | — | Pre/post sync commands. See [Configuration](../configuration.md#prepost-sync-commands). |
| `projects` | table | No | `{}` | Per-project configuration overrides. See [Per-Project Overrides](jira-client#per-project-overrides) |

---

## Authentication

### Basic Auth (Jira Cloud)

Recommended for Jira Cloud. Uses your Atlassian account email and an API token.

```toml
[testbench-defect-service.client_config]
auth_type  = "basic"
username   = "your-email@company.com"
password  = "your-api-token"
```

Generate an API token at `https://id.atlassian.com/manage-profile/security/api-tokens`.

### Token Auth (Jira Data Center)

Uses a Personal Access Token (PAT) generated in your Jira Data Center profile.

```toml
[testbench-defect-service.client_config]
auth_type = "token"
token     = "your-personal-access-token"
```

:::note
Personal Access Tokens expire based on the duration set in your Jira Data Center profile. If the service stops authenticating unexpectedly, check whether the token has expired and generate a new one.
:::

### Environment Variables

:::tip
Prefer environment variables over hardcoding credentials in `config.toml` to avoid accidentally committing secrets to source control.
:::

To avoid storing credentials in the config file, use environment variables instead:

| Variable | Used for |
|---|---|
| `JIRA_USERNAME` | Username (basic auth) |
| `JIRA_PASSWORD` | API token (basic auth) |
| `JIRA_BEARER_TOKEN` | Personal Access Token (token auth, Jira Data Center) |

---

## Project Mapping

The service lists Jira projects as `"<Project Name> (<PROJECT_KEY>)"`. TestBench selects a project by this combined name.

The `{project}` placeholder in `defect_jql` is replaced with the Jira **project key** (e.g. `MYPROJ`) at query time.

### Example JQL Queries

Fetch only bugs, ordered by creation date:
```toml
defect_jql = "project = '{project}' AND issuetype = Bug ORDER BY created DESC"
```

Fetch all unresolved issues for a specific component:
```toml
defect_jql = "project = '{project}' AND component = 'Backend' AND resolution = Unresolved"
```

---

## Control Fields

The Jira client automatically queries Jira metadata to populate allowed values for the following fields:

| Field | Jira data source |
|---|---|
| `status` | Project workflow statuses |
| `priority` | Global Jira priorities |
| `classification` | Project issue types |

Additional fields listed in `control_fields` are resolved via the Jira field metadata API.

---

## Per-Project Overrides

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
|---|---|---|
| Authentication | Basic (email + API token) | Token (PAT) or Basic |
| Pagination | `nextPageToken` cursor | `startAt` offset |
| Issue types endpoint | Standard | `issuetypes` endpoint (DC ≥ 8.4) |
| API base path | `/rest/api/3/` | `/rest/api/2/` |

---

## Known Limitations

| Limitation | Details |
|---|---|
| **Attachment sync** | Jira Data Center supports one-way attachment sync from TestBench to Jira only. |
| **Sprint field** | The Sprint field cannot be reliably updated via the API and is not supported. |
| **Jira Server (legacy)** | Only Jira Data Center and Jira Cloud are actively tested. Older Jira Server versions may work but are not officially supported. |

---
sidebar_position: 1
title: Clients
---
# Clients

The TestBench Defect Service uses a pluggable client architecture. A **client** is a Python class that connects the service's generic defect API to a specific backend — such as a file system or a project management tool.

---

## How Clients Work

When the service receives an API request from TestBench, it delegates the operation to the configured client. Every client implements the same interface (`AbstractDefectClient`), so swapping one client for another requires only a configuration change.

The client is selected with the `client_class` key in `config.toml`:

```toml
[testbench-defect-service]
client_class = "testbench_defect_service.clients.JsonlDefectClient"
```

---

## Available Clients

| Client | `client_class` value | Extra required | Description |
|---|---|---|---|
| [**JSONL**](jsonl-client.md) | `testbench_defect_service.clients.JsonlDefectClient` | — | File-based storage using newline-delimited JSON. No external service required. |
| [**Jira**](jira-client.md) | `testbench_defect_service.clients.JiraDefectClient` | `[jira]` | Full integration with Jira Cloud or Jira Data Center / Server. |
| [**Custom**](custom-client.md) | Any fully qualified class path | — | Bring your own backend by implementing `AbstractDefectClient`. |

---

## Common Client Features

All clients share these capabilities:

- **Read / write defects** — create, read, update, delete defects per project.
- **Control fields** — return the allowed values for fields like `status` or `priority` so TestBench can present them as dropdowns.
- **User-defined fields (UDFs)** — expose custom fields to TestBench.
- **Pre/post sync hooks** — run shell scripts before and after a sync operation.
- **Read-only mode** — set `readonly = true` to prevent all write operations.
- **Per-project overrides** — most configuration options can be overridden for individual projects.

---

## Choosing a Client

Use the [**JSONL client**](jsonl-client.md) when:
- You want a simple, self-contained setup without external dependencies.
- You are evaluating the service or running tests.
- Your defect data lives in plain files that other tools also read.

Use the [**Jira client**](jira-client.md) when:
- You manage defects in Jira Cloud or Jira Data Center.
- You want TestBench to stay in sync with your existing Jira project.
- You need Jira-specific features like workflow transitions, issue types, and custom fields.

---

## Client Details

- [JSONL Client](jsonl-client.md)
- [Jira Client](jira-client.md)
- [Custom Client](custom-client.md)

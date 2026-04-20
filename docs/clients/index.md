---
sidebar_position: 1
title: Clients
---
# Clients

A **client** is a pluggable component that connects the service's generic defect API to a specific backend — such as a file system or a project management tool. The service ships with two built-in clients and supports [custom clients](custom-client.md).

## Built-in clients

| Client | Data source | Extra dependencies | Best for |
|--------|---------------------|-------------------|----------|
| [**JSONL**](jsonl-client.md) | `.jsonl` files on disk | None (included in base install) | Simple file-based setup; no external service required |
| [**Jira**](jira-client.md) | Jira REST API | `pip install testbench-defect-service[jira]` | Teams managing defects in Jira Cloud or Jira Data Center |

## Choosing a client

### JSONL client

Use the [**JSONL client**](jsonl-client.md) when:
- You want a simple, self-contained setup without external dependencies.
- You are evaluating the service or running tests.
- Your defect data lives in plain files that other tools also read.

**Get started:** [JSONL Client](jsonl-client.md)

---

### Jira client

Use the [**Jira client**](jira-client.md) when:
- You manage defects in Jira Cloud or Jira Data Center.
- You want TestBench to stay in sync with your existing Jira project.
- You need Jira-specific features like workflow transitions, issue types, and custom fields.

**Get started:** [Jira Client](jira-client.md)

---

### Custom client

None of the built-in clients fit? You can create your own by subclassing `AbstractDefectClient`.

**Learn how:** [Custom Client](custom-client.md)

---

## Configuring a client

Set `client_class` in your `config.toml` and provide client-specific settings under `[testbench-defect-service.client_config]`:

```toml
# config.toml
[testbench-defect-service]
client_class = "JsonlDefectClient"   # or JiraDefectClient

[testbench-defect-service.client_config]
# client-specific settings go here
```

Alternatively, keep client settings in a separate file using `client_config_path`:

```toml
# config.toml
[testbench-defect-service]
client_class = "JiraDefectClient"
client_config_path = "jira_config.toml"
```

```toml
# jira_config.toml
# client-specific settings go here
```

See the [Configuration](../configuration.md#service-settings) reference for details.

---
sidebar_position: 2
title: JSONL Client
---
# JSONL Client

The JSONL client is the default, zero-dependency backend for the TestBench Defect Service. It stores defects as [newline-delimited JSON](https://jsonlines.org) (`.jsonl`) files on the local file system.

---

## Overview

Each project maps to a subdirectory under the configured `defects_path`. Defects are stored as individual JSON objects, one per line, in a `.jsonl` file inside that directory.

```
defects/jsonl/
├── ProjectA/
│   ├── defects.jsonl
│   └── UserDefinedAttributes.json
└── ProjectB/
    └── defects.jsonl
```

A single defect line looks like:

```json
{"id": "BUG-1", "title": "Login fails on Safari", "status": "open", "priority": "high"}
```

---

## When to use the JSONL client

- No external service or internet access required.
- Defect data can be read and modified by any text editor or script.
- Supports the full defect lifecycle: create, read, update, delete.

---

## Configuration

Add the following to your `config.toml` to enable the JSONL client:

```toml
# config.toml
[testbench-defect-service]
client_class       = "testbench_defect_service.clients.JsonlDefectClient"
client_config_path = "config.toml"

[testbench-defect-service.client_config]
name                       = "JSONL"
description                = "File-based defect management"
defects_path               = "defects/jsonl"
readonly                   = false
supports_changes_timestamps = true
attributes                 = ["title", "status", "priority"]
```

### Configuration settings

**Identity**

| Option | Type | Description | Required | Default |
|--------|------|-------------|----------|---------|
| `name` | String | Display name shown in TestBench. Must match the name in the DMProxy properties file or during setup. | No | `"JSONL"` |
| `description` | String | Short description displayed in `/settings`. | No | `"JSONL client..."` |

**Storage**

| Option | Type | Description | Required | Default |
|--------|------|-------------|----------|---------|
| `defects_path` | String | Root directory for all defect files. Must exist before starting the service. | **Yes** | — |

:::warning
The `defects_path` directory and all project subdirectories must be created manually before starting the service. The service will not start if the path does not exist.
:::

**Query & Fields**

| Option | Type | Description | Required | Default |
|--------|------|-------------|----------|---------|
| `attributes` | List | Defect fields to include in responses. Field names must match the keys used in the `.jsonl` records. | No | `["title", "status"]` |
| `control_fields` | Table | Allowed values for controlled fields. See [Control fields](#control-fields). | No | `{}` |

**Behavior**

| Option | Type | Description | Required | Default |
|--------|------|-------------|----------|---------|
| `readonly` | Boolean | When `true`, all write operations (create, update, delete) are rejected. | No | `false` |
| `supports_changes_timestamps` | Boolean | Whether the client tracks modification timestamps. | No | `true` |

**Advanced**

| Option | Type | Description | Required | Default |
|--------|------|-------------|----------|---------|
| `commands` | Table | Pre/post sync commands. See [Configuration](../configuration.md#prepost-sync-commands). | No | — |
| `projects` | Table | Per-project configuration overrides. See [Per-project overrides](#per-project-overrides). | No | `{}` |

---

## Control fields

Control fields are attributes whose values are restricted to a predefined list. TestBench uses them to present validated dropdowns.

```toml
# config.toml
[testbench-defect-service.client_config.control_fields]
status   = ["open", "in_progress", "blocked", "closed"]
priority = ["low", "medium", "high", "critical"]
severity = ["minor", "major", "critical"]
```

Any key-value pair is valid. The field names must match the names used in the `attributes` list.

---

## User-defined attributes (UDFs)

Each project can have a `UserDefinedAttributes.json` file that describes custom fields:

```json
[
  {
    "name": "Customer",
    "valueType": "STRING",
    "mustField": false
  },
  {
    "name": "Regression",
    "valueType": "BOOLEAN",
    "mustField": true
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `name` | String | Field name as it appears in TestBench. |
| `valueType` | `"STRING"` \| `"BOOLEAN"` | Data type of the field. |
| `mustField` | Boolean | Whether the field is mandatory. |

---

## Per-project overrides

Any top-level option can be overridden for a specific project:

```toml
# config.toml
[testbench-defect-service.client_config.projects.ProjectA]
readonly = true

[testbench-defect-service.client_config.projects.ProjectA.control_fields]
status = ["open", "closed"]

[testbench-defect-service.client_config.projects.ProjectA.commands.presync]
scheduled = "C:\\scripts\\project-a-pre.bat"
```

The project key must match the subdirectory name under `defects_path`.

---

## How defect IDs work

IDs are auto-generated by the client when a defect is created. The format is `BUG-<n>` where `<n>` is an incrementing integer based on the current count of defects in the file.

:::warning
Do not manually edit or reuse defect IDs in the `.jsonl` file. TestBench uses the ID to track defect identity across syncs — changing an ID causes TestBench to treat it as a new defect and lose the link to the original.
:::
---

## Limitations

- **Single file per project** — all defects for a project are stored in one `.jsonl` file. Large projects with many thousands of defects may experience slower read/write times.
- **No concurrent write safety** — the client does not use file locking. Avoid modifying the `.jsonl` file externally while the service is running.
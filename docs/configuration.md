---
sidebar_position: 3
title: Configuration
---

# Configuration

The TestBench Defect Service is configured through a single TOML file (`config.toml` in the working directory by default). This page documents every available option.

:::tip
Use the CLI wizards instead of editing the file by hand — they validate your input and prevent syntax errors:

```bash
testbench-defect-service init        # Create a new config from scratch
testbench-defect-service configure   # Update an existing config
testbench-defect-service set-credentials  # Update credentials only
```

See [CLI Commands](cli.md) for all options.
:::

---

## Configuration precedence

The following order shows which source takes precedence when the same setting is defined in multiple places (highest priority first):

1. **Command-line flags** (`start --host ... --port ...`)
2. **Environment variables**
3. **`config.toml`**
4. **Built-in defaults**

---

## Full example

This example uses the JSONL client. Adjust `client_class` and `[testbench-defect-service.client_config]` for other clients.

```toml
# config.toml
[testbench-defect-service]
client_class = "JsonlDefectClient"
host = "127.0.0.1"
port = 8030
password_hash = "your_generated_hash"
salt = "your_generated_salt"

# Server process settings
[testbench-defect-service.server]
single_process = true

# Console logging
[testbench-defect-service.logging.console]
log_level = "INFO"
log_format = "%(asctime)s %(levelname)8s: %(message)s"

# File logging
[testbench-defect-service.logging.file]
log_level = "INFO"
log_format = "%(asctime)s - %(levelname)8s - %(name)s - %(message)s"
file_path = "testbench-defect-service.log"

# JSONL client configuration (inline, recommended)
[testbench-defect-service.client_config]
# JSONL-specific settings ...
```

---

## Service settings

**`[testbench-defect-service]`**

### Client

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `client_class` | String | Identifies the client to load. See supported formats below. | — |
| `client_config_path` | String | Path to the `.toml` config file containing the client config. When omitted, the `[testbench-defect-service.client_config]` section of the main config file is used. | — |

**Example:**

```toml
# config.toml
[testbench-defect-service]
client_class       = "testbench_defect_service.clients.JsonlDefectClient"
client_config_path = "config.toml"
```

#### `client_class` formats

| Format | Example | Notes |
|--------|---------|-------|
| Built-in class name | `"JsonlDefectClient"` | Short name of any class in the built-in `testbench_defect_service.clients` package |
| File path with extension | `"custom_client.py"` | Absolute path, or relative to the directory the service is started from |
| File path without extension | `"custom_client"` | `.py` is appended automatically |
| Module string | `"my_package.MyClient"` | Imported via `importlib`; the file must be on `PYTHONPATH` or in the working directory |
| Full dotted module path | `"my_package.my_module.MyClient"` | Module and class can also be combined into one string |

#### `client_config_path` formats

The path should point to a `.toml` file containing the client configuration as raw key-value pairs (no TOML section headers). The path is resolved relative to the directory where the service is started.

### Network

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `host` | String | Network interface to listen on. Use `"0.0.0.0"` to accept external connections. | `"127.0.0.1"` |
| `port` | Integer | TCP port the service listens on. | `8030` |
| `debug` | Boolean | Enable Sanic debug mode (verbose logging, auto-reload). **Do not use in production.** | `false` |

**Example:**

```toml
# config.toml
[testbench-defect-service]
host  = "127.0.0.1"
port  = 8030
debug = false
```

### Authentication

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `password_hash` | String | Bcrypt hash of the service password. | — |
| `salt` | String | Base64-encoded salt used for hashing. | — |

All API endpoints (except Swagger UI) require **HTTP Basic Authentication**.

#### Setting credentials

Generate and store a password hash and salt in your config:

```bash
testbench-defect-service set-credentials
```

You will be prompted for a password. The command writes `password_hash` and `salt` into `config.toml`. Credentials are stored as a hashed value — never store a plain-text password in the config file.

### Reverse proxy

Only needed when the service runs behind a load balancer or reverse proxy (e.g., nginx, Traefik).

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `proxies_count` | Integer | Number of trusted reverse proxies (for `X-Forwarded-For` processing). | `0` |
| `real_ip_header` | String | Custom header name carrying the real client IP. | — |
| `forwarded_secret` | String | Secret token for `Forwarded` header validation. | — |

### SSL / TLS

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `ssl_cert` | String | Path to the PEM certificate file. | — |
| `ssl_key` | String | Path to the PEM private key file. | — |
| `ssl_ca_cert` | String | Path to the CA certificate. When set, client certificates are required (mTLS). | — |

| `ssl_cert` | `ssl_key` | `ssl_ca_cert` | Mode |
|:---:|:---:|:---:|---|
| — | — | — | Plain HTTP |
| ✓ | ✓ | — | HTTPS (one-way TLS) |
| ✓ | ✓ | ✓ | HTTPS with mTLS (client certificates required) |

> **Note:** mTLS forces single-worker mode because `SSLContext` objects cannot be forked.

**Example:**

```toml
# config.toml
[testbench-defect-service]
ssl_cert    = "certs/server.crt"
ssl_key     = "certs/server.key"
ssl_ca_cert = "certs/ca.crt"   # optional — enables mTLS
```

---

## Server process settings

**`[testbench-defect-service.server]`**

Controls how Sanic spawns and manages its worker process. In most cases you can leave this section out and rely on the defaults.

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `single_process` | Boolean | Run in single-process mode. Required when using mTLS. Set to `false` to enable multi-worker throughput. | `true` |
| `keep_alive_timeout` | Integer | Seconds an idle HTTP keep-alive connection is held open waiting for the next request before being closed. A shorter value reduces the number of open connections that can delay shutdown. | `5` |
| `run_kwargs` | Table | Raw keyword arguments forwarded verbatim to Sanic's `run()` call. Use for advanced Sanic tuning not exposed by other settings. | `{}` |

**Example:**

```toml
# config.toml
[testbench-defect-service.server]
single_process = false
keep_alive_timeout = 3
run_kwargs = { workers = 4 }
```

---

## Logging

### Console

**`[testbench-defect-service.logging.console]`**

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `log_level` | String | Minimum log level. One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. | `"INFO"` |
| `log_format` | String | Python `logging` format string. | `"%(asctime)s %(levelname)8s: %(message)s"` |

**Example:**

```toml
# config.toml
[testbench-defect-service.logging.console]
log_level  = "INFO"
log_format = "%(asctime)s %(levelname)8s: %(message)s"
```

### File

**`[testbench-defect-service.logging.file]`**

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `log_level` | String | Minimum log level for file output. | `"INFO"` |
| `log_format` | String | Python `logging` format string. | — |
| `file_path` | String | Path to the log file. Relative paths are resolved from the working directory. | `"testbench-defect-service.log"` |

**Example:**

```toml
# config.toml
[testbench-defect-service.logging.file]
log_level  = "INFO"
log_format = "%(asctime)s - %(levelname)8s - %(name)s - %(message)s"
file_path  = "testbench-defect-service.log"
```

---

## Pre/post sync commands

Both clients support running shell commands before and after TestBench syncs defects, configured under a `commands` subsection.

| Option | Description |
|--------|-------------|
| `scheduled` | Script or executable to run during automatic (scheduled) syncs. |
| `manual` | Script or executable to run during manual syncs. |
| `partial` | Script or executable to run during partial syncs. |

The process is launched via `subprocess` and the service waits for it to complete before continuing.

**Example:**

```toml
# config.toml
# Global commands (applied to every project)
[testbench-defect-service.client_config.commands.presync]
scheduled = "C:\\scripts\\before-sync.bat"

[testbench-defect-service.client_config.commands.postsync]
scheduled = "C:\\scripts\\after-sync.bat"

# Per-project override
[testbench-defect-service.client_config.projects.<project-key>.commands.presync]
scheduled = "C:\\scripts\\project-before.bat"
```

---

## Client configuration

Each backend client has its own `[testbench-defect-service.client_config]` section. See the individual client documentation for the full option reference:

- [JSONL Client](clients/jsonl-client.md#configuration) — file-based storage, no external dependencies
- [Jira Client](clients/jira-client.md#configuration) — Jira Cloud / Data Center

---

## Running multiple instances

Each `start` command loads exactly one config file and binds to one port. To serve multiple data sources simultaneously — for example, one service for JSONL defects and one for Jira — start one process per config file on a different port.

### Setup

**1. Create a config file per instance:**

`jsonl_config.toml`
```toml
# config.toml
[testbench-defect-service]
client_class = "testbench_defect_service.clients.JsonlDefectClient"
port = 8030

[testbench-defect-service.client_config]
# Jsonl-specific settings ...
```

`jira_config.toml`
```toml
# config.toml
[testbench-defect-service]
client_class = "testbench_defect_service.clients.JiraDefectClient"
port = 8031

[testbench-defect-service.client_config]
# Jira-specific settings ...
```

**2. Start each instance in its own terminal (or as separate Windows services):**

```bash
# Terminal 1 — JSONL service on port 8030
testbench-defect-service start --config jsonl_config.toml

# Terminal 2 — Jira service on port 8031
testbench-defect-service start --config jira_config.toml
```

The `--port` flag overrides the port in the config file, so you can also reuse the same config and just change the port at start time:

```bash
testbench-defect-service start --config shared_config.toml --port 8032
```

### TestBench integration with multiple instances

For each running instance, configure a separate DMProxy wrapper entry in TestBench pointing to the corresponding URL:

```properties
# JSONL service
server.url=http://127.0.0.1:8030

# Jira service
server.url=http://127.0.0.1:8031
```

See the [TestBench Integration](testbench-integration.md) page for the full DMProxy setup.

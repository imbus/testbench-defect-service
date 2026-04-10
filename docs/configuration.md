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

See [CLI Reference](cli.md) for all options.
:::

---

## File Structure

A `config.toml` has two top-level sections:

```toml
[testbench-defect-service]
# Service-level settings: network, auth, logging, SSL/TLS

[testbench-defect-service.client_config]
# Client-specific settings (see JSONL or Jira client docs)
```

---

## Service Settings

### Client

```toml
[testbench-defect-service]
client_class       = "testbench_defect_service.clients.JsonlDefectClient"
client_config_path = "config.toml"
```

| Key | Type | Default | Description |
|---|---|---|---|
| `client_class` | string | — | Fully qualified Python class name of the backend client. See [Clients](clients/). |
| `client_config_path` | string | — | Path to the TOML file containing the `client_config` section. Defaults to the same file. |

### Network

```toml
[testbench-defect-service]
host  = "127.0.0.1"
port  = 8030
debug = false
```

| Key | Type | Default | Description |
|---|---|---|---|
| `host` | string | `"127.0.0.1"` | Network interface to listen on. Use `"0.0.0.0"` to accept external connections. |
| `port` | integer | `8030` | TCP port the service listens on. |
| `debug` | boolean | `false` | Enable Sanic debug mode (verbose logging, auto-reload). **Do not use in production.** |

### Authentication

Credentials are managed by the [`set-credentials`](cli.md#set-credentials) command and stored as a hashed value — never store a plain-text password here.

```toml
[testbench-defect-service]
password_hash = ""   # set via `testbench-defect-service set-credentials`
salt          = ""   # set via `testbench-defect-service set-credentials`
```

| Key | Type | Description |
|---|---|---|
| `password_hash` | string | Bcrypt hash of the service password. |
| `salt` | string | Base64-encoded salt used for hashing. |

### Reverse Proxy

Only needed when the service runs behind a load balancer or reverse proxy (e.g., nginx, Traefik).

| Key | Type | Default | Description |
|---|---|---|---|
| `proxies_count` | integer | `0` | Number of trusted reverse proxies (for `X-Forwarded-For` processing). |
| `real_ip_header` | string | — | Custom header name carrying the real client IP. |
| `forwarded_secret` | string | — | Secret token for `Forwarded` header validation. |

### SSL / TLS

```toml
[testbench-defect-service]
ssl_cert    = "certs/server.crt"
ssl_key     = "certs/server.key"
ssl_ca_cert = "certs/ca.crt"   # optional — enables mTLS
```

| Key | Type | Description |
|---|---|---|
| `ssl_cert` | string | Path to the PEM certificate file. |
| `ssl_key` | string | Path to the PEM private key file. |
| `ssl_ca_cert` | string | Path to the CA certificate. When set, client certificates are required (mTLS). |

| `ssl_cert` | `ssl_key` | `ssl_ca_cert` | Mode |
|:---:|:---:|:---:|---|
| — | — | — | Plain HTTP |
| ✓ | ✓ | — | HTTPS (one-way TLS) |
| ✓ | ✓ | ✓ | HTTPS with mTLS (client certificates required) |

> **Note:** mTLS forces single-worker mode because `SSLContext` objects cannot be forked.

---

## Server Process Settings

**`[testbench-defect-service.server]`**

Controls how Sanic spawns and manages its worker process. In most cases you can leave this section out and rely on the defaults.

| Key | Type | Default | Description |
|---|---|---|---|
| `single_process` | boolean | `true` | Run in single-process mode. Required when using mTLS. Set to `false` to enable multi-worker throughput. |
| `keep_alive_timeout` | integer | `5` | Seconds an idle HTTP keep-alive connection is held open waiting for the next request before being closed. A shorter value reduces the number of open connections that can delay shutdown. |
| `run_kwargs` | table | `{}` | Raw keyword arguments forwarded verbatim to Sanic's `run()` call. Use for advanced Sanic tuning not exposed by other settings. |

```toml
[testbench-defect-service.server]
single_process = false
keep_alive_timeout = 3
run_kwargs = { workers = 4 }
```

---

## Logging

### Console

```toml
[testbench-defect-service.logging.console]
log_level  = "INFO"
log_format = "%(asctime)s %(levelname)8s: %(message)s"
```

| Key | Type | Default | Description |
|---|---|---|---|
| `log_level` | string | `"INFO"` | Minimum log level. One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `log_format` | string | `"%(asctime)s %(levelname)8s: %(message)s"` | Python `logging` format string. |

### File

```toml
[testbench-defect-service.logging.file]
log_level  = "INFO"
log_format = "%(asctime)s - %(levelname)8s - %(name)s - %(message)s"
file_path  = "testbench-defect-service.log"
```

| Key | Type | Default | Description |
|---|---|---|---|
| `log_level` | string | `"INFO"` | Minimum log level for file output. |
| `log_format` | string | — | Python `logging` format string. |
| `file_path` | string | `"testbench-defect-service.log"` | Path to the log file. Relative paths are resolved from the working directory. |

---

## Pre/Post Sync Commands

Both clients support running shell commands before and after TestBench syncs defects, configured under a `commands` subsection.

```toml
# Global commands (applied to every project)
[testbench-defect-service.client_config.commands.presync]
scheduled = "C:\\scripts\\before-sync.bat"

[testbench-defect-service.client_config.commands.postsync]
scheduled = "C:\\scripts\\after-sync.bat"

# Per-project override
[testbench-defect-service.client_config.projects.<project-key>.commands.presync]
scheduled = "C:\\scripts\\project-before.bat"
```

| Key | Description |
|---|---|
| `scheduled` | Script or executable to run during automatic (scheduled) syncs. |
| `manual` | Script or executable to run during manual syncs. |
| `partial` | Script or executable to run during partial syncs. |

The process is launched via `subprocess` and the service waits for it to complete before continuing.

---

## Client Configuration

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
[testbench-defect-service]
client_class = "testbench_defect_service.clients.JsonlDefectClient"
port = 8030

[testbench-defect-service.client_config]
# Jsonl-specific settings ...
```

`jira_config.toml`
```toml
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

For each running instance, configure a separate RMProxy wrapper entry in TestBench pointing to the corresponding URL:

```properties
# JSONL service
server.url=http://127.0.0.1:8030

# Jira service
server.url=http://127.0.0.1:8031
```

See the [TestBench Integration](testbench-integration.md) page for the full RMProxy setup.

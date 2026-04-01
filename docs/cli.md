---
sidebar_position: 6
title: CLI reference
---

# CLI Reference

The Testbench Defect Service is controlled entirely from the command line. The main entry point is:

```bash
testbench-defect-service [COMMAND] [OPTIONS]
```

---

## Commands Overview

| Command | Description |
|---|---|
| [`init`](#init) | Interactive wizard to create a new configuration file from scratch. |
| [`configure`](#configure) | Create or update an existing configuration interactively. |
| [`set-credentials`](#set-credentials) | Set the service username and password. |
| [`start`](#start) | Start the defect service. |

---

## `init`

Creates a new `config.toml` interactively. The wizard walks you through all required settings and writes the result to disk.

```bash
testbench-defect-service init [OPTIONS]
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--path PATH` | string | `config.toml` | Path where the configuration file should be written. |
| `--help` | — | — | Show help and exit. |

### Example

```bash
# Create config.toml in the current directory
testbench-defect-service init

# Create config at a custom path
testbench-defect-service init --path /etc/defect-service/config.toml
```

### What the wizard asks

1. **Client selection** — choose JSONL or Jira.
2. **Service settings** — host, port.
3. **Client settings** — backend-specific options (e.g. `defects_path` for JSONL, `server_url` for Jira).
4. **Credentials setup** — prompts to set a username and password immediately after file creation.

---

## `configure`

Updates an existing configuration file. Can be run fully interactively (menu-driven) or targeted at a specific section with flags.

```bash
testbench-defect-service configure [OPTIONS]
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--path PATH` | string | `config.toml` | Path to the configuration file to update. |
| `--full` | flag | — | Reconfigure all sections interactively. |
| `--service-only` | flag | — | Update only the `[testbench-defect-service]` section. |
| `--credentials-only` | flag | — | Update only the username/password. |
| `--client-only` | flag | — | Update only the client configuration section. |
| `--view` | flag | — | Print the current configuration to the console without modifying it. |
| `--help` | — | — | Show help and exit. |

### Examples

```bash
# Interactive menu — choose what to update
testbench-defect-service configure

# Reconfigure everything
testbench-defect-service configure --full

# Only update service-level settings (host, port, debug …)
testbench-defect-service configure --service-only

# View the current configuration
testbench-defect-service configure --view

# Operate on a config file at a custom path
testbench-defect-service configure --path /etc/defect-service/config.toml --full
```

> **Note:** `--full`, `--service-only`, `--credentials-only`, and `--client-only` are mutually exclusive.

---

## `set-credentials`

Sets the service username and password. The password is hashed with bcrypt and stored in the config file — it is never stored in plain text.

```bash
testbench-defect-service set-credentials [OPTIONS]
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--config PATH` | string | `config.toml` | Path to the configuration file. |
| `--username TEXT` | string | — | Username. If omitted, you will be prompted interactively. |
| `--password TEXT` | string | — | Password. If omitted, you will be prompted interactively (input is hidden). |
| `--help` | — | — | Show help and exit. |

### Examples

```bash
# Interactive prompts for both username and password
testbench-defect-service set-credentials

# Non-interactive (from a script)
testbench-defect-service set-credentials --username admin --password "s3cret!"

# Update a config file at a custom path
testbench-defect-service set-credentials --config /etc/defect-service/config.toml
```

> **Security note:** Avoid passing passwords as command-line arguments in shared or audited environments, as they may appear in shell history. Prefer the interactive prompt or use an environment variable pipeline.

---

## `start`

Starts the defect service. Reads the configuration file and launches the Sanic HTTP server.

```bash
testbench-defect-service start [OPTIONS]
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--config PATH` | string | `config.toml` | Path to the configuration file. |
| `--client-class TEXT` | string | — | Override `client_class` from the config file. Useful for testing. |
| `--client-config PATH` | string | — | Override `client_config_path` from the config file. |
| `--host HOST` | string | — | Override the `host` from the config file. |
| `--port PORT` | integer | — | Override the `port` from the config file. |
| `--dev` | flag | — | Enable Sanic development mode (auto-reload on file changes, extra debug output). |
| `--ssl-cert PATH` | string | — | Path to a PEM certificate file. Enables HTTPS. |
| `--ssl-key PATH` | string | — | Path to the PEM private key for the certificate. |
| `--ssl-ca-cert PATH` | string | — | Path to a CA certificate for mutual TLS (mTLS). |
| `--help` | — | — | Show help and exit. |

### Priority Rules

CLI flags always override values from the configuration file. The resolution order is (highest priority last):

1. Built-in defaults
2. `config.toml` values
3. CLI flags

### Examples

```bash
# Start with default config.toml in the current directory
testbench-defect-service start

# Start with a specific config file
testbench-defect-service start --config /etc/defect-service/config.toml

# Override host and port
testbench-defect-service start --host 0.0.0.0 --port 9000

# Start with HTTPS
testbench-defect-service start --ssl-cert cert.pem --ssl-key key.pem

# Start with mutual TLS (mTLS)
testbench-defect-service start --ssl-cert cert.pem --ssl-key key.pem --ssl-ca-cert ca.pem

# Development mode (with auto-reload)
testbench-defect-service start --dev

# Use a different backend without changing config.toml
testbench-defect-service start \
  --client-class testbench_defect_service.clients.JiraDefectClient \
  --client-config jira.toml
```

### Single-Process vs. Multi-Process

By default the service runs in **multi-process mode** (one worker per CPU core), managed by Sanic's `AppLoader`.

The service automatically switches to **single-process mode** when:
- mTLS is enabled (`--ssl-ca-cert`), because `ssl.SSLContext` objects cannot be forked.

---

## Global Options

These options are available on every command:

| Option | Description |
|---|---|
| `--help` | Show help for the command and exit. |

---

## Getting Help

```bash
# General help
testbench-defect-service --help

# Help for a specific command
testbench-defect-service start --help
testbench-defect-service configure --help
```

# TestBench Defect Service
[![PyPI version](https://img.shields.io/pypi/v/testbench-defect-service)](https://pypi.org/project/testbench-defect-service/)
[![Python versions](https://img.shields.io/pypi/pyversions/testbench-defect-service)](https://pypi.org/project/testbench-defect-service/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

## Introduction

[imbus TestBench](https://www.testbench.com/) can create and synchronise bug reports with external defect tracking systems, but requires a specific HTTP interface to do so. The **TestBench Defect Service** provides exactly that interface.

It is a lightweight, self-hosted REST API you run alongside TestBench. TestBench talks to this service, and the service translates those calls into operations against your actual defect tracker.

Supported backends out of the box:
- **[Jira](https://www.atlassian.com/software/jira)** — Cloud and Data Center
- **JSONL** — simple file-based storage for testing or offline use
- **Custom** — implement your own client by extending the abstract base class

Key features:
- Per-project field mappings and configuration overrides
- Pre/post sync hooks (shell commands)
- HTTP Basic Auth with bcrypt password hashing
- SSL/TLS and mutual TLS (mTLS) support
- Interactive setup wizard (`init` / `configure`)
- OpenAPI / Swagger UI at `/docs`

Requires **Python 3.10–3.14**.

---

## Installation

### From PyPI *(recommended)*

```bash
pip install testbench-defect-service
```

With Jira support:

```bash
pip install "testbench-defect-service[jira]"
```

### Offline (from a wheel package)

Unzip the provided package to a local folder, then install without internet access:

```bash
pip install --no-index --find-links "C:\install" testbench-defect-service
pip install --no-index --find-links "C:\install" testbench-defect-service[jira]
```

### From Source *(development)*

```bash
git clone https://github.com/imbus/testbench-defect-service.git
cd testbench-defect-service
pip install -e ".[dev,jira]"
```

Available extras:

| Extra | When to use |
|---|---|
| *(default)* | JSONL file-based backend |
| `jira` | Jira Cloud / Data Center backend |
| `dev` | Linting, testing, and build tools |

---

## Usage

### Interactive setup (recommended)

**1. Create a configuration:**

```bash
testbench-defect-service init
```

This wizard walks you through service settings, credentials, and client selection and writes a complete `config.toml`.

**2. Start the service:**

```bash
testbench-defect-service start
```

The service listens on `http://127.0.0.1:8030` by default.  
Swagger UI is available at [http://127.0.0.1:8030/docs](http://127.0.0.1:8030/docs).

**3. Verify:**

```bash
curl -u "admin:mypassword" http://127.0.0.1:8030/projects
```

### Manual setup

Create a `config.toml` by hand (see [Configuration](#configuration)), then set credentials:

```bash
testbench-defect-service set-credentials
```

---

## Documentation

### CLI Reference

The main entry point is:

```bash
testbench-defect-service [COMMAND] [OPTIONS]
```

| Command | Description |
|---|---|
| `init` | Interactive wizard — creates `config.toml` from scratch |
| `configure` | Create or update an existing configuration interactively |
| `set-credentials` | Set the service username and password (bcrypt-hashed) |
| `start` | Start the defect service |

#### `init`

```bash
testbench-defect-service init [--path PATH]
```

| Option | Default | Description |
|---|---|---|
| `--path PATH` | `config.toml` | Where to write the new configuration file |

#### `configure`

```bash
testbench-defect-service configure [OPTIONS]
```

| Option | Description |
|---|---|
| `--path PATH` | Path to the configuration file to update |
| `--full` | Reconfigure all sections interactively |
| `--service-only` | Update only service-level settings |
| `--credentials-only` | Update only username/password |
| `--client-only` | Update only the client configuration |
| `--view` | Print the current configuration without modifying it |

#### `set-credentials`

```bash
testbench-defect-service set-credentials [--config PATH] [--username TEXT] [--password TEXT]
```

Passwords are bcrypt-hashed and never stored in plain text. Prefer the interactive prompt over passing `--password` on the command line.

#### `start`

```bash
testbench-defect-service start [OPTIONS]
```

| Option | Description |
|---|---|
| `--config PATH` | Path to the configuration file (default: `config.toml`) |
| `--host HOST` | Override the host from config |
| `--port PORT` | Override the port from config |
| `--dev` | Enable development mode (auto-reload) |
| `--ssl-cert PATH` | PEM certificate — enables HTTPS |
| `--ssl-key PATH` | PEM private key |
| `--ssl-ca-cert PATH` | CA certificate — enables mTLS |

---

### Configuration

The service is configured through a single `config.toml` file.

```toml
[testbench-defect-service]
client_class  = "testbench_defect_service.clients.JsonlDefectClient"
host          = "127.0.0.1"
port          = 8030
debug         = false
password_hash = ""   # set via set-credentials
salt          = ""   # set via set-credentials
```

#### Network

| Key | Type | Default | Description |
|---|---|---|---|
| `host` | string | `"127.0.0.1"` | Interface to listen on. Use `"0.0.0.0"` for external access. |
| `port` | integer | `8030` | TCP port. |
| `debug` | boolean | `false` | Verbose logging and auto-reload. Do not use in production. |

#### SSL / TLS

```toml
[testbench-defect-service]
ssl_cert    = "certs/server.crt"
ssl_key     = "certs/server.key"
ssl_ca_cert = "certs/ca.crt"   # optional — enables mTLS
```

| `ssl_cert` | `ssl_key` | `ssl_ca_cert` | Mode |
|:---:|:---:|:---:|---|
| — | — | — | Plain HTTP |
| ✓ | ✓ | — | HTTPS (one-way TLS) |
| ✓ | ✓ | ✓ | HTTPS with mTLS |

#### Logging

```toml
[testbench-defect-service.logging.console]
log_level  = "INFO"
log_format = "%(asctime)s %(levelname)8s: %(message)s"

[testbench-defect-service.logging.file]
log_level  = "INFO"
file_path  = "testbench-defect-service.log"
```

#### Pre/Post Sync Commands

Run shell commands before or after TestBench syncs defects:

```toml
[testbench-defect-service.client_config.commands.presync]
scheduled = "C:\\scripts\\before-sync.bat"

[testbench-defect-service.client_config.commands.postsync]
scheduled = "C:\\scripts\\after-sync.bat"
```

Per-project override:

```toml
[testbench-defect-service.client_config.projects.<project-key>.commands.presync]
scheduled = "C:\\scripts\\project-before.bat"
```

| Key | Description |
|---|---|
| `scheduled` | Runs during automatic syncs |
| `manual` | Runs during manual syncs |
| `partial` | Runs during partial syncs |

---

### JSONL Client

The default, zero-dependency backend. Stores defects as [newline-delimited JSON](https://jsonlines.org) files on the local file system.

```
defects/jsonl/
├── ProjectA/
│   ├── defects.jsonl
│   └── UserDefinedAttributes.json
└── ProjectB/
    └── defects.jsonl
```

**Configuration:**

```toml
[testbench-defect-service]
client_class = "testbench_defect_service.clients.JsonlDefectClient"

[testbench-defect-service.client_config]
name         = "JSONL"
defects_path = "defects/jsonl"
readonly     = false
attributes   = ["title", "status", "priority"]
```

| Key | Required | Default | Description |
|---|---|---|---|
| `defects_path` | **Yes** | — | Root directory for defect files. Must exist before starting. |
| `name` | No | `"JSONL"` | Display name shown in TestBench. |
| `readonly` | No | `false` | Reject all write operations when `true`. |
| `attributes` | No | `["title", "status"]` | Fields included in defect responses. |

---

### Jira Client

Integrates with [Jira Cloud](https://www.atlassian.com/software/jira) and Jira Data Center. Requires the `jira` extra.

```bash
pip install "testbench-defect-service[jira]"
```

**Configuration:**

```toml
[testbench-defect-service]
client_class = "testbench_defect_service.clients.JiraDefectClient"

[testbench-defect-service.client_config]
name           = "Jira"
server_url     = "https://your-company.atlassian.net"
auth_type      = "basic"
defect_jql     = "project = '{project}' AND issuetype in standardIssueTypes()"
attributes     = ["title", "status", "priority"]
control_fields = ["priority", "status", "classification"]
readonly       = false
```

#### Connection & Query options

| Key | Required | Default | Description |
|---|---|---|---|
| `server_url` | **Yes** | — | Base URL of your Jira instance (no trailing slash) |
| `auth_type` | No | `"basic"` | `"basic"`, `"token"`, or `"oauth"` |
| `defect_jql` | No | `"project = '{project}' AND issuetype in standardIssueTypes()"` | JQL query; `{project}` is replaced with the project key at runtime |
| `attributes` | No | `["title", "status"]` | Jira fields to include in defect responses |
| `control_fields` | No | `["priority", "status", "classification"]` | Fields for which allowed values are returned |
| `readonly` | No | `false` | Reject all write operations when `true` |

#### Authentication

**Jira Cloud — Basic Auth (email + API token):**

```toml
auth_type = "basic"
username  = "your-email@company.com"
password  = "your-api-token"   # generate at id.atlassian.com
```

**Jira Data Center — Personal Access Token:**

```toml
auth_type = "token"
token     = "your-personal-access-token"
```

Prefer environment variables over hardcoding credentials in `config.toml`:

| Variable | Used for |
|---|---|
| `JIRA_USERNAME` | Username (basic auth) |
| `JIRA_PASSWORD` | API token (basic auth) |
| `JIRA_BEARER_TOKEN` | Personal Access Token (token auth) |

#### Required Jira Permissions

The service account must hold the following project permissions (**Project Settings → Permissions**):

| Permission | Required for |
|---|---|
| Browse Projects | All operations |
| Browse Users | Displaying assignees / reporters |
| Create Issues | Syncing new defects |
| Edit Issues | Updating defect attributes |
| Delete Issues | Deleting defects (`readonly = false`) |
| Transition Issues | Updating defect status |
| Create Attachments | Syncing attachments |
| Delete Attachments | Removing attachments (`readonly = false`) |

---

### Running Multiple Instances

Each `start` command loads one config file and binds to one port. To serve multiple backends simultaneously, start one process per config file on a different port:

```bash
# Terminal 1 — JSONL service on port 8030
testbench-defect-service start --config jsonl_config.toml

# Terminal 2 — Jira service on port 8031
testbench-defect-service start --config jira_config.toml
```

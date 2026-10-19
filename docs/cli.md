---
sidebar_position: 7
title: CLI Commands
---

# CLI Commands

The executable is `testbench-defect-service`. All commands support `--help` for detailed usage.

```bash
testbench-defect-service [COMMAND] [OPTIONS]
```

---

## Commands overview

| Command | Description |
|---|---|
| [`init`](#init) | Interactive wizard to create a new configuration file from scratch. |
| [`configure`](#configure) | Create or update an existing configuration interactively. |
| [`set-credentials`](#set-credentials) | Set the service username and password. |
| [`migrate`](#migrate) | Convert a legacy `.conf` / `.properties` configuration into a TOML configuration. |
| [`migrate workbook`](#migrate-workbook) | Convert legacy `.xls` defect workbooks into `.xlsx`. |
| [`start`](#start) | Start the defect service. |

---

## `init`

Create a new configuration file with an interactive wizard.

The wizard guides you through:
1. Service settings (host, port)
2. Credential setup (username, password)
3. Client selection (JSONL or Jira)
4. Client-specific configuration

```bash
testbench-defect-service init [--path PATH]
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--path PATH` | Path to the configuration file to create | `config.toml` |

### Examples

```bash
# Create config.toml in the current directory
testbench-defect-service init

# Create config at a custom path
testbench-defect-service init --path /etc/defect-service/config.toml
```

---

## `configure`

Update an existing configuration file interactively.

```bash
testbench-defect-service configure [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--path PATH` | Path to the configuration file to update (default: `config.toml`) |
| `--full` | Run the full configuration wizard (skip the menu) |
| `--service-only` | Configure service settings only (host, port, debug) |
| `--credentials-only` | Configure credentials only (username, password) |
| `--client-only` | Configure client settings only |
| `--view` | View the current configuration |

### Examples

```bash
# Interactive menu (default)
testbench-defect-service configure

# Update only service settings
testbench-defect-service configure --service-only

# View current configuration
testbench-defect-service configure --view
```

---

## `set-credentials`

Set or update the HTTP Basic Auth credentials used to protect API endpoints.
This command generates a secure password hash and salt and stores them in your configuration file.

```bash
testbench-defect-service set-credentials [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--config PATH` | Path to the configuration file (default: `config.toml`) |
| `--username TEXT` | Username (prompts interactively if not provided) |
| `--password TEXT` | Password (prompts interactively if not provided) |

### Examples

```bash
# Interactive (prompts for credentials)
testbench-defect-service set-credentials

# Non-interactive
testbench-defect-service set-credentials --username admin --password "s3cret!"
```

:::warning[Security]
Avoid passing passwords as command-line arguments in shared or audited environments, as they may appear in shell history. Prefer the interactive prompt or use an environment variable pipeline.
:::

---

## `migrate`

Convert a legacy `.conf` / `.properties` configuration into a TOML configuration file.

The previous TestBench defect wrappers were configured with a Jira `.conf` file or an Excel
`.properties` file. `migrate` reads one of those, asks for the settings the legacy format
never carried - how to authenticate against Jira, and the credentials that protect the
service's own API - and writes a ready-to-use configuration file.

The converted values are validated against the same client models the service uses at
startup, so anything the service would reject is reported during the migration instead of
on the first start. A legacy file the converter cannot read is rejected with the file and
line number — and, when the line is separated the other format's way, with the `--type` to
use instead. Legacy entries that have no equivalent in the new configuration are listed
before the file is written, so a partial migration cannot pass for a complete one.

```bash
testbench-defect-service migrate --from PATH [OPTIONS]
```

:::tip
The [Migration guide](migration.md) walks through the whole procedure — which legacy keys are
carried over, what you are asked for, and how to reconnect TestBench afterwards.
:::

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--from PATH` | Legacy `.conf` or `.properties` file to convert (required) | - |
| `--path PATH` | Path to the configuration file to write | `config.toml` |
| `--type [excel\|jira]` | Legacy source type | detected from the file extension |

The source type follows from the extension: `.conf` is a Jira wrapper configuration,
`.properties` an Excel one. Pass `--type` when the file has been renamed and the extension
no longer says which format it is.

### Examples

```bash
# Convert a legacy Jira wrapper configuration
testbench-defect-service migrate --from jira.conf

# Convert a legacy Excel wrapper configuration to a custom path
testbench-defect-service migrate --from genericexcel.properties --path /etc/defect-service/config.toml

# Convert a wrapper file whose extension no longer identifies the format
testbench-defect-service migrate --from wrapper.txt --type jira
```

:::info[Existing configurations]
If the target file already exists you are asked to confirm, and it is renamed to
`config.toml.backup` (timestamped when a backup is already present) before the new file is
written. The conversion runs to completion first, so cancelling any prompt leaves your
existing configuration exactly as it was.
:::

:::note
Only the Jira and Excel clients have a legacy wrapper format to migrate from. Configure the
JSONL client with [`init`](#init) or [`configure`](#configure).
:::

---

## `migrate workbook`

Convert legacy `.xls` defect workbooks into the `.xlsx` format the Excel client can write to.

The Excel client reads both formats, but it refuses to *write* to a legacy `.xls` file — so
creating or updating a defect in one fails with `Writing to legacy .xls files is not
supported`. This command converts those workbooks once, up front.

```bash
testbench-defect-service migrate workbook PATH
```

`PATH` is either a single `.xls` file or a folder, which is searched **recursively**. Each
workbook is written as an `.xlsx` file beside the original; the `.xls` file is left
untouched, so the conversion is reversible by deleting the new file.

### Options

| Argument | Description | Default |
|--------|-------------|---------|
| `PATH` | A `.xls` file, or a folder to search recursively (required) | - |

### Examples

```bash
# Convert a single workbook
testbench-defect-service migrate workbook "current baseline.xls"

# Convert every .xls below a folder
testbench-defect-service migrate workbook C:\defects\baselines
```

Each workbook is reported on its own line, followed by a tally:

```text
Found 3 .xls workbook(s). Starting Microsoft Excel...

  converted: current baseline.xls -> current baseline.xlsx
  skipped:   archive\old baseline.xls (target already exists)
  failed:    archive\corrupt.xls: Excel could not open the file

1 converted, 1 skipped, 1 failed
```

A workbook that already has an `.xlsx` beside it is **skipped**, never overwritten — so
re-running the command over a folder is safe. A workbook Excel cannot open is reported and
the rest of the batch still converts; the command then exits with a non-zero status.

:::warning[Requires Windows and Microsoft Excel]
The conversion drives an installed Microsoft Excel through COM automation, which keeps
formatting, column widths and formulas intact — a conversion through a Python library would
reduce the workbook to bare cell values. It therefore only runs on Windows with Excel
installed, and needs the optional `convert` extra:

```bash
pip install testbench-defect-service[convert]
```

Excel runs hidden in a separate instance, so it will not disturb workbooks you already have
open. Macros are not carried over, because `.xlsx` cannot hold them.
:::

---

## `start`

Start the defect service.

```bash
testbench-defect-service start [OPTIONS]
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--config PATH` | Path to the configuration file | `config.toml` |
| `--client-class TEXT` | Client class name or module path (overrides config) | from config |
| `--client-config PATH` | Path to client configuration file (overrides config) | from config |
| `--host HOST` | Host to bind to | `127.0.0.1` |
| `--port PORT` | Port to listen on | `8030` |
| `--dev` | Run in development mode (debug + auto reload) | off |
| `--ssl-cert PATH` | Path to SSL certificate file for HTTPS | — |
| `--ssl-key PATH` | Path to SSL private key file for HTTPS | — |
| `--ssl-ca-cert PATH` | Path to CA certificate file for client verification (mTLS) | — |

Command-line arguments take **precedence** over configuration file settings.

:::info[Built-in client class names]
When using `--client-class`, you can specify:
- `JsonlDefectClient` — for JSONL file storage
- `JiraDefectClient` — for Jira Cloud / Data Center

Or provide a custom client (e.g. `custom_client.py` or `custom_client.CustomClass`).
:::

### Examples

```bash
# Start with defaults
testbench-defect-service start

# Development mode
testbench-defect-service start --dev

# Override host and port
testbench-defect-service start --host 0.0.0.0 --port 9000

# Use a different client
testbench-defect-service start --client-class JiraDefectClient --client-config jira.toml

# Use a custom client class
testbench-defect-service start --client-class custom_client.CustomDefectClient

# Start with HTTPS
testbench-defect-service start --ssl-cert certs/server.crt --ssl-key certs/server.key

# Start with mutual TLS (mTLS)
testbench-defect-service start --ssl-cert certs/server.crt --ssl-key certs/server.key --ssl-ca-cert certs/ca.crt
```

---

## Getting help

```bash
# General help
testbench-defect-service --help

# Help for a specific command
testbench-defect-service start --help
testbench-defect-service configure --help
```

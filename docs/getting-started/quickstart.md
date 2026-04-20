---
sidebar_position: 2
title: Quickstart
---

# Quickstart

> **New users?** Use [Option 1: Interactive Wizard](#option-1-interactive-wizard-recommended) for the fastest setup.
>
> **Advanced users?** See [Option 2: Manual Configuration](#option-2-manual-configuration) for full control.

## Option 1: Interactive Wizard (Recommended)

### 1. Create a configuration

```bash
testbench-defect-service init
```

This single command walks you through:
- [Service settings](../configuration.md#service-settings) (host, port, debug mode)
- [Credentials setup](../configuration.md#authentication) (username, password)
- Client selection ([JSONL](../clients/jsonl-client.md) or [Jira](../clients/jira-client.md))
- Client-specific configuration (see the chosen client's Configuration section)

It creates a complete `config.toml` when finished.

### 2. Start the service

```bash
testbench-defect-service start
```

### 3. Open Swagger UI

Visit [http://127.0.0.1:8030/docs](http://127.0.0.1:8030/docs) to explore the API interactively.

### 4. Quick API check

```bash
curl -u "ADMIN_USERNAME:PASSWORD" http://127.0.0.1:8030/projects
```

**That's it!** Your service is ready to use.

---

## Option 2: Manual Configuration

### 1. Install optional dependencies (if needed)

Choose the extras for your backend. See [Installation](installation.md#from-pypi-online-recommended) for available options.

### 2. Create the configuration file

Create a new file called `config.toml` in the root directory of your installation. Start from a minimal example. Here is one for the JSONL client:

```toml
# config.toml
[testbench-defect-service]
client_class = "testbench_defect_service.clients.JsonlDefectClient"
host = "127.0.0.1"
port = 8030

[testbench-defect-service.client_config]
defects_path = "defects/jsonl/"
```

For other clients see [JSONL](../clients/jsonl-client.md) or [Jira](../clients/jira-client.md).

### 3. Set credentials

The API uses HTTP Basic Auth. Generate a hashed password:

```bash
testbench-defect-service set-credentials
```

This prompts for username and password and stores a secure hash in `config.toml`.

### 4. Start the service

```bash
testbench-defect-service start
```

### 5. Open Swagger UI

Visit [http://127.0.0.1:8030/docs](http://127.0.0.1:8030/docs).

### 6. Quick API check

```bash
curl -u "ADMIN_USERNAME:PASSWORD" http://127.0.0.1:8030/projects
```

:::tip
Use `testbench-defect-service configure` to update specific parts of your configuration later without starting from scratch.
:::

---

## API documentation endpoints

Once the service is running, these endpoints are available without authentication:

| Endpoint | Description |
|----------|-------------|
| `/docs` | Interactive Swagger UI |
| `/docs/openapi.json` | OpenAPI specification (JSON) |
| `/openapi.yaml` | OpenAPI specification (YAML) |

## Next steps

- Customize the service → [Configuration](../configuration.md)
- Learn about clients → [Clients overview](../clients/index.md)
- Connect TestBench → [TestBench Integration](../testbench-integration.md)
- Explore all CLI options → [CLI reference](../cli.md)

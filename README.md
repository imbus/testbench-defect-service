# TestBench Defect Service
[![PyPI version](https://img.shields.io/pypi/v/testbench-defect-service)](https://pypi.org/project/testbench-defect-service/)
[![Python versions](https://img.shields.io/pypi/pyversions/testbench-defect-service)](https://pypi.org/project/testbench-defect-service/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

## Introduction
A lightweight REST API service for [imbus TestBench](https://www.testbench.com) that provides a unified interface for creating and synchronising defects with external defect tracking systems.

## Features

- **Multiple clients**: JSONL files for testing/offline use, or Jira Cloud and Data Center via REST API
- **Unified REST API**: a single API surface regardless of the underlying defect tracker
- **Interactive setup wizard**: `testbench-defect-service init` generates a complete config in seconds
- **Swagger UI**: built-in interactive API docs at `/docs`
- **Per-project overrides**: field mappings and configuration per project key
- **Pre/post sync hooks**: run shell commands before or after sync operations
- **HTTPS & mTLS**: optional TLS and mutual TLS for production deployments
- **Extensible**: implement `AbstractDefectClient` to connect any defect tracker

## Installation

**With pip** (Python 3.10–3.14 required):

```bash
pip install testbench-defect-service
```

Optional extras for additional clients:

| Client | Data source | Install command |
|--------|-------------|-----------------|
| JSONL (default) | `.jsonl` files | included in base install |
| Jira | Jira Cloud / Data Center REST API | `pip install testbench-defect-service[jira]` |

**Standalone executable** (no Python required): download the pre-built binary from the [GitHub releases page](https://github.com/imbus/testbench-defect-service/releases).

## Quickstart

```bash
# 1. Create a configuration interactively
testbench-defect-service init

# 2. Start the service
testbench-defect-service start
```

The service runs at `http://127.0.0.1:8030` by default. Open `/docs` for the interactive Swagger UI.

## Documentation

Full documentation is available on the [TestBench Ecosystem documentation site](https://imbus.github.io/testbench-ecosystem-documentation/testbench-defect-service/intro):

- [Introduction](https://imbus.github.io/testbench-ecosystem-documentation/testbench-defect-service/intro)
- [Installation](https://imbus.github.io/testbench-ecosystem-documentation/testbench-defect-service/getting-started/installation)
- [Quickstart](https://imbus.github.io/testbench-ecosystem-documentation/testbench-defect-service/getting-started/quickstart)
- [Configuration](https://imbus.github.io/testbench-ecosystem-documentation/testbench-defect-service/configuration)
- [CLI Commands](https://imbus.github.io/testbench-ecosystem-documentation/testbench-defect-service/cli)
- [Clients overview](https://imbus.github.io/testbench-ecosystem-documentation/testbench-defect-service/clients/)
- [TestBench Integration](https://imbus.github.io/testbench-ecosystem-documentation/testbench-defect-service/testbench-integration)

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](https://github.com/imbus/testbench-defect-service/blob/main/CONTRIBUTING.md) for setup instructions and guidelines.

## Changelog

See [CHANGELOG.md](https://github.com/imbus/testbench-defect-service/blob/main/CHANGELOG.md) for release history.

## License

Apache 2.0 — see [LICENSE](https://github.com/imbus/testbench-defect-service/blob/main/LICENSE) for details.

# Testbench Defect Service

[![PyPI Version](https://img.shields.io/pypi/v/testbench-defect-service)](https://pypi.org/project/testbench-defect-service/)
[![Python Versions](https://img.shields.io/pypi/pyversions/testbench-defect-service)](https://pypi.org/project/testbench-defect-service/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

A flexible REST API service for managing defects across multiple backends including Jira and JSONL (file-based). Built with Sanic for high-performance asynchronous operations.

## Table of Contents
- [Features](#features)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Setup and Configuration](#setup-and-configuration)
- [Usage](#usage)
- [Testbench Integration](#testbench-integration)
- [Configuration Reference](#configuration-reference)
- [API Documentation](#api-documentation)
- [Known Limitations](#known-limitations)
- [Development](#development)
  - [Prerequisites](#prerequisites)
  - [Set Up the Development Environment](#set-up-the-development-environment)
  - [Code Quality Tools](#code-quality-tools)
  - [Run Tests](#run-tests)
  - [Build Package](#build-package)
- [License](#license)

## Features

- Multiple Backends: Support for Jira, JSONL (file-based)
- HTTP Basic Authentication: Secure API access
- OpenAPI Documentation: Interactive API documentation via Swagger UI
- Flexible Configuration: TOML-based configuration with project-specific settings
- Pre/Post Sync Commands: Execute custom commands before/after sync operations
- Multiple Projects: Manage defects across different projects from a single service

For more details on the architecture and supported backends, see [docs/intro.md](docs/intro.md).

## Quick Start

```bash
pip install testbench-defect-service

# Interactive setup wizard — creates config.toml
testbench-defect-service init

# Start the service (default: http://127.0.0.1:8030)
testbench-defect-service start
```

Once running, open `http://127.0.0.1:8030/docs` for the interactive Swagger UI.

## Installation

For full installation instructions (prerequisites, Git, Wheel, optional extras), see [docs/getting-started/installation.md](docs/getting-started/installation.md).

## Setup and Configuration

For configuration instructions (initial setup, config file format, client configuration), see:

- [docs/getting-started/quickstart.md](docs/getting-started/quickstart.md)
- [docs/configuration.md](docs/configuration.md)
- [docs/clients/jsonl-client.md](docs/clients/jsonl-client.md)
- [docs/clients/jira-client.md](docs/clients/jira-client.md)

## Usage

For usage instructions and CLI reference, see:

- [docs/getting-started/quickstart.md](docs/getting-started/quickstart.md)
- [docs/cli.md](docs/cli.md)

## Testbench Integration

For instructions on integrating the service with TestBench (wrapper configuration, running multiple instances), see [docs/testbench-integration.md](docs/testbench-integration.md).

## Configuration Reference

For the full configuration reference (all parameters, logging, proxy settings, client options), see:

- [docs/configuration.md](docs/configuration.md)
- [docs/clients/jsonl-client.md](docs/clients/jsonl-client.md)
- [docs/clients/jira-client.md](docs/clients/jira-client.md)

## API Documentation

The interactive Swagger UI is available at `http://<host>:<port>/docs` when the service is running. It provides a full reference of all available endpoints and allows you to test them directly from the browser.

## Known Limitations

For known limitations (attachment handling, Sprint field, JSONL restrictions), see:

- [docs/clients/jira-client.md](docs/clients/jira-client.md)
- [docs/clients/jsonl-client.md](docs/clients/jsonl-client.md)

## Development

### Prerequisites

- Python 3.10–3.14
- [flit](https://flit.pypa.io/) for building packages

### Set Up the Development Environment

The quickest way is to use the provided bootstrap script, which creates a virtual environment and installs all dependencies automatically:

```bash
python bootstrap.py
```

Or set it up manually:

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -e ".[dev]"
```

For Jira support add the `jira` extra:

```bash
pip install -e ".[dev,jira]"
```

### Code Quality Tools

| Tool | Purpose | Run with |
|---|---|---|
| **Ruff** | Linting and auto-formatting | `ruff check .` / `ruff format .` |
| **MyPy** | Static type checking | `mypy src` |
| **Pre-commit** | Git hooks (runs Ruff + MyPy on commit) | `pre-commit install` |
| **Robocop** | Robot Framework linting | `robocop` |
| **Robotidy** | Robot Framework formatting | `robotidy` |

Install pre-commit hooks after cloning:

```bash
pre-commit install
```

### Run Tests

**Unit tests** (pytest):

```bash
pytest tests/unit/
```

**Integration / Robot Framework tests:**

```bash
robot tests/robot/
```

Run all checks at once via [Invoke](https://www.pyinvoke.org/) (if tasks are defined):

```bash
invoke test
```

### Build Package

```bash
flit build
```

This produces a `.whl` and `.tar.gz` in `dist/`.

## License

This project is licensed under the Apache License 2.0. See the [LICENSE](LICENSE) file for details.

---

**Need Help?**

For contributing guidelines, see [CONTRIBUTING.md](CONTRIBUTING.md).

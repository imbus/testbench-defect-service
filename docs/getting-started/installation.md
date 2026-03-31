---
sidebar_position: 1
title: Installation
---
# Installation

## Requirements

- **Python 3.10 or higher** — [Download Python](https://www.python.org/downloads/)
- **pip** — included with Python 3.4+; verify with `pip --version`
---

## Option 1: Install from PyPI (Recommended)

Install the latest release directly from [PyPI](https://pypi.org/project/testbench-defect-service/):

```bash
pip install testbench-defect-service
```

To include Jira support:

```bash
pip install "testbench-defect-service[jira]"
```

---

## Option 2: Install from a Wheel

Download the `.whl` file from the release page and install it with pip:

```bash
pip install testbench_defect_service-<version>-py3-none-any.whl
```

To include Jira support:

```bash
pip install "testbench_defect_service-<version>-py3-none-any.whl[jira]"
```

---

## Option 3: Install from Source (Development)

Clone the repository and install in editable mode:

```bash
git clone https://github.com/imbus/testbench-defect-service.git
cd defect-service-python
pip install -e ".[dev,jira]"
```

Available extras:

| Extra | Packages installed | When to use |
|---|---|---|
| *(default)* | — | Uses JSONL files as data source; included in base install |
| `jira` | `jira`, `beautifulsoup4` | Required for Jira backend |
| `dev` | `ruff`, `pre-commit`, `invoke`, `mypy`, `flit`, `wheel`, `robotframework`, `pytest`, … | Development, linting, and testing |

---

## Verifying the Installation

After installation, verify the CLI is available:

```bash
testbench-defect-service --help
```

Expected output:

```
Usage: testbench-defect-service [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  configure        Create or update the service configuration interactively.
  init             Initialize a new service configuration interactively.
  set-credentials  Set the service username and password.
  start            Start the defect service.
```

---

## Next Step

→ [Quick Start](quickstart.md)

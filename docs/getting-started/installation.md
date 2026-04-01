---
sidebar_position: 1
title: Installation
---
# Installation

## Requirements

- **Python 3.10 or higher** — [Download Python](https://www.python.org/downloads/)
- **pip** — included with Python 3.4+; verify with `pip --version`
---

## Option 1: Install from PyPI *(Recommended)*

Install the latest release directly from [PyPI](https://pypi.org/project/testbench-defect-service/):

```bash
pip install testbench-defect-service
```

To include Jira support:

```bash
pip install "testbench-defect-service[jira]"
```

---

## Option 2: Install from a wheel package *(Offline)*

Use this option when installing on a machine without internet access, for example when you received an offline installation package (`.zip`).

**1. Extract the zip:**

Unzip the provided package to a local folder, e.g. `C:\install\`:

```
C:\install\
  testbench_defect_service-x.y.z-py3-none-any.whl
  <dependency wheels ...>
```

**2. Install from the local folder:**

```bash
pip install --no-index --find-links "C:\install" testbench-defect-service
```

To include optional extras, add them as usual — pip will resolve them from the local folder:

```bash
pip install --no-index --find-links "C:\install" testbench-defect-service[jira]
```

:::note
The offline package is platform- and Python-version-specific. Make sure you use the package that matches your system (e.g. `win_amd64`, `py310`).
:::

---

## Option 3: Install from Source *(Development)*

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

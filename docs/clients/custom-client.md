---
sidebar_position: 4
title: Custom Client
---

# Custom Client

The TestBench Defect Service supports custom backends through a pluggable client interface. Any Python class that extends `AbstractDefectClient` and implements the required methods can be used as a drop-in replacement for the built-in JSONL or Jira clients.

Typical use cases:

- Integrating a defect tracker that is not supported out of the box (e.g. Azure DevOps, GitHub Issues, Bugzilla).
- Wrapping an internal or proprietary issue management system.
- Building a read-only adapter over a reporting or analytics backend.

---

## How it works

At startup the service reads `client_class` from `config.toml`, imports the class by its fully qualified Python dotted path, and instantiates it with the validated `client_config` section. As long as your class is importable and implements the interface, no other changes to the service are required.

---

## Setup

### 1. Define a config model

Create a Pydantic `BaseModel` for your client's configuration. The service uses this class to validate the config before passing it to your client:

```python
# my_client/config.py
from pydantic import BaseModel, Field

class MyClientConfig(BaseModel):
    server_url: str = ""
    api_key: str = ""
    readonly: bool = False
    project_prefix: str = "PRJ"
```

### 2. Implement the client class

Subclass `AbstractDefectClient`, set `CONFIG_CLASS`, and implement all abstract methods. Your `__init__` receives an already-validated instance of your config model — you do not need to load or parse any config file yourself:

```python
# my_client/client.py
from pydantic import BaseModel
from sanic.exceptions import NotFound

from testbench_defect_service.clients.abstract_client import AbstractDefectClient
from testbench_defect_service.models.defects import (
    Defect,
    DefectID,
    DefectWithAttributes,
    ExtendedAttributes,
    Protocol,
    ProtocolCode,
    ProtocolledDefectSet,
    ProtocolledString,
    Results,
    Settings,
    SyncContext,
    UserDefinedAttribute,
)

from .config import MyClientConfig


class MyDefectClient(AbstractDefectClient):
    CONFIG_CLASS = MyClientConfig

    def __init__(self, config: MyClientConfig):
        self.config = config
        # Initialise your backend connection here

    # --- Identity & settings ------------------------------------------------

    def get_settings(self) -> Settings:
        return Settings(
            name="My Backend",
            description="Custom defect client for My Backend",
            readonly=self.config.readonly,
        )

    def check_login(self, project: str | None) -> bool:
        # Return True when credentials are valid and the backend is reachable
        return True

    def supports_changes_timestamps(self) -> bool:
        return False

    # --- Projects ------------------------------------------------------------

    def get_projects(self) -> list[str]:
        # Return the list of project identifiers available to the authenticated user
        return []

    # --- Control fields & UDFs ----------------------------------------------

    def get_control_fields(self, project: str | None) -> dict[str, list[str]]:
        return {"status": ["open", "closed"], "priority": ["low", "high"]}

    def get_user_defined_attributes(self, project: str | None) -> list[UserDefinedAttribute]:
        return []

    # --- Defect CRUD ---------------------------------------------------------

    def get_defects(self, project: str, sync_context: SyncContext) -> ProtocolledDefectSet:
        raise NotImplementedError

    def get_defects_batch(
        self, project: str, defect_ids: list[DefectID], sync_context: SyncContext
    ) -> ProtocolledDefectSet:
        raise NotImplementedError

    def get_defect_extended(
        self, project: str, defect_id: str, sync_context: SyncContext
    ) -> DefectWithAttributes:
        raise NotImplementedError

    def create_defect(
        self, project: str, defect: Defect, sync_context: SyncContext
    ) -> ProtocolledString:
        raise NotImplementedError

    def update_defect(
        self, project: str, defect_id: str, defect: Defect, sync_context: SyncContext
    ) -> Protocol:
        raise NotImplementedError

    def delete_defect(
        self, project: str, defect_id: str, defect: Defect, sync_context: SyncContext
    ) -> Protocol:
        raise NotImplementedError

    # --- Sync lifecycle ------------------------------------------------------

    def before_sync(self, project: str, sync_type: str, sync_context: SyncContext) -> Protocol:
        return Protocol(protocolCode=ProtocolCode.OK, messages=[])

    def after_sync(self, project: str, sync_type: str, sync_context: SyncContext) -> Protocol:
        return Protocol(protocolCode=ProtocolCode.OK, messages=[])

    def correct_sync_results(self, project: str, body: Results) -> Results:
        return body
```

#### Required methods

| Method | Purpose |
|---|---|
| `__init__(config)` | Initialise the client with the validated config object. |
| `get_settings()` | Return the backend name, description, and read-only flag. |
| `check_login(project)` | Validate credentials; return `True` if the backend is reachable. |
| `supports_changes_timestamps()` | Return `True` if the backend tracks modification timestamps. |
| `get_projects()` | List all available project identifiers. |
| `get_control_fields(project)` | Return allowed values per field (e.g. statuses, priorities). |
| `get_user_defined_attributes(project)` | Return custom field definitions. |
| `get_defects(project, sync_context)` | Return all defects for a project. |
| `get_defects_batch(project, ids, sync_context)` | Return a specific subset of defects by ID. |
| `get_defect_extended(project, id, sync_context)` | Return a single defect with its extended attributes. |
| `create_defect(project, defect, sync_context)` | Create a defect; return its assigned ID. |
| `update_defect(project, id, defect, sync_context)` | Update an existing defect. |
| `delete_defect(project, id, defect, sync_context)` | Delete an existing defect. |
| `before_sync(project, sync_type, sync_context)` | Pre-sync hook (acquire locks, validate state). |
| `after_sync(project, sync_type, sync_context)` | Post-sync hook (release locks, persist state). |
| `correct_sync_results(project, results)` | Filter or adjust the proposed sync change set. |

#### Exception conventions

Raise the following Sanic exceptions consistently so the service translates them into the correct HTTP responses:

| Situation | Exception |
|---|---|
| Project or defect not found | `sanic.exceptions.NotFound` |
| Backend or network error | `sanic.exceptions.ServerError` |
| Invalid input data | `pydantic.ValidationError` |

### 3. Make the class importable

Place your package somewhere on the Python path. The simplest options are:

**Use a single file** in the directory you run the service from. File-path loading requires no additional setup.

**Add the directory to `PYTHONPATH`:**

```bash
export PYTHONPATH="/path/to/custom_client:$PYTHONPATH"
```

**Install as a package alongside the service:**

```bash
pip install ./custom_client
```

:::warning
The package must be importable from the same Python environment as the Defect Service. Installing it globally or in a different virtual environment will result in an `ImportError` at startup.
:::

### 4. Configure the service

Point `client_class` at your class and add the matching `client_config` section.

**Using a file path (recommended for single-file clients):**

```toml
[testbench-defect-service]
client_class = "my_defect_client.py"

[testbench-defect-service.client_config]
server_url     = "https://backend.example.com"
api_key        = "secret"
readonly       = false
project_prefix = "PRJ"
```

**Using a module string (recommended for packaged clients):**

```toml
[testbench-defect-service]
client_class = "my_client.client.MyDefectClient"

[testbench-defect-service.client_config]
server_url     = "https://backend.example.com"
api_key        = "secret"
readonly       = false
project_prefix = "PRJ"
```

The `client_class` option accepts several formats:

| Format | Example |
|--------|--------|
| File path (with extension) | `"my_defect_client.py"` |
| File path (without extension) | `"my_defect_client"` |
| Absolute file path | `"/opt/clients/my_defect_client.py"` |
| Module string | `"my_package.MyDefectClient"` |
| Full dotted module path | `"my_package.my_module.MyDefectClient"` |

File paths are resolved relative to the directory you start the service from. For file-path loading the class is discovered automatically — either by deriving the PascalCase class name from the filename (`my_defect_client.py` → `MyDefectClient`), or by scanning the file for the single `AbstractDefectClient` subclass defined in it.

The `client_config` keys must match the fields defined in your `MyClientConfig` Pydantic model. The service validates the section on startup and raises an error if required fields are missing or have the wrong type.

---

## Tips

- **Reuse config building blocks** — `SyncCommandConfig`, `PhaseCommands`, and `ProjectConfig` from `testbench_defect_service.clients.jsonl.config` are plain Pydantic models you can compose into your own config to get pre/post sync command and per-project override support for free.
- **Look at the JSONL client** — `testbench_defect_service.clients.jsonl.client` is the simplest complete reference implementation.
- **Read-only mode** — check `self.config.readonly` in every write method and raise `sanic.exceptions.Forbidden` when set.
- **Logging** — import and use `from testbench_defect_service.log import logger` instead of the standard `logging` module so your output appears in the same structured log stream.

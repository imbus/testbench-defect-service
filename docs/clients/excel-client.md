---
sidebar_position: 3
title: Excel Client
---
# Excel Client

The Excel client reads and writes defects directly from spreadsheet and delimited text files — `.xlsx`, `.xls`, `.csv`, `.tsv` and `.txt`. Instead of mapping defects to a fixed schema, it maps each defect field to a **column number** in an existing file, so it can be pointed at spreadsheets that are already in use.

---

## Overview

Each project maps to a subdirectory under the configured `excel_file_path`. The client picks the **first file in that directory whose extension matches `file_type`** (alphabetically sorted).

```
excel/                     <- excel_file_path
├── project_1/
│   └── car_config.xls     <- file_type = ".xls"
└── project_2/
    └── defects.xlsx       <- file_type = ".xlsx"
```

:::note
`excel_file_path` points at the **root directory**, not at a single file. Project names in TestBench correspond to the subdirectory names.
:::

Within the file, one row is one defect. The row and column layout is described entirely through configuration:

| Config option                  | Meaning                                 |
| ------------------------------ | --------------------------------------- |
| `defects_data_header_line`   | Row containing the column headers       |
| `defects_data_starting_line` | First row containing defect data        |
| `*_column_no`                | 1-based column number of a defect field |

A minimal sheet with the default column numbers looks like this:

|             | A (1)   | B (2)                 | C (3)      | D (4)      | E (5)       | F (6)                       | G (7)  |
| ----------- | ------- | --------------------- | ---------- | ---------- | ----------- | --------------------------- | ------ |
| **1** | ID      | Title                 | References | Discoverer | Last edited | Description                 | Status |
| **2** | BUG0001 | Login fails on Safari | TC-1,TC-2  | jdoe       | 2026-01-14  | Clicking login does nothing | open   |

---

## When to use the Excel client

- Defects already live in a spreadsheet maintained by hand or exported from another tool.
- The file layout cannot be changed, but its columns can be mapped.
- You are migrating from the legacy DMProxy Excel connector and want to reuse its `.properties` file. See [Legacy `.properties` configuration](#legacy-properties-configuration).

---

## Requirements

The Excel client is an **optional** component. Install it with:

```bash
pip install "testbench-defect-service[excel]"
```

Or when installing from source:

```bash
pip install -e ".[excel]"
```

This installs `pandas`, `openpyxl` (for `.xlsx`) and `xlrd` (for `.xls`). The service refuses to start if the Excel client is configured but the extra is missing.

:::note
The Excel client is not bundled in the [ready-to-use executable](../getting-started/installation.md#option-1-ready-to-use-executable). Use the Python installation for Excel-based setups.
:::

### Supported file formats

| Format    | Read | Write | Engine                        |
| --------- | ---- | ----- | ----------------------------- |
| `.xlsx` | ✅   | ✅    | openpyxl                      |
| `.xls`  | ✅   | ❌    | xlrd                          |
| `.csv`  | ✅   | ✅    | pandas                        |
| `.txt`  | ✅   | ✅    | pandas (uses`separator`)    |
| `.tsv`  | ✅   | ✅    | pandas (tab-separated, fixed) |

:::warning
Legacy `.xls` files are **read-only**. Attempting to create, update or delete a defect fails with an error asking you to convert the file to `.xlsx`. Set `readonly = true` for `.xls` projects to make this explicit in TestBench, or convert the workbooks with [`migrate workbook`](../cli.md#migrate-workbook).
:::

---

## Configuration

Add the following to your `config.toml` to enable the Excel client:

```toml
# config.toml
[testbench-defect-service]
client_class       = "testbench_defect_service.clients.ExcelDefectClient"
client_config_path = "config.toml"

[testbench-defect-service.client_config]
system_name                = "Excel"
excel_file_path            = "examples/excel"
file_type                  = ".xlsx"
worksheet_name             = "Defects"
readonly                   = false
simple_date_format         = "yyyy-MM-dd HH:mm:ss"
defects_data_header_line   = 1
defects_data_starting_line = 2
attributes                 = ["title", "status"]

# Column layout (1-based column numbers)
id_column_no          = 1
title_column_no       = 2
references_column_no  = 3
discoverer_column_no  = 4
lastedit_column_no    = 5
description_column_no = 6

# Status / priority / classification live in control fields
[[testbench-defect-service.client_config.control_fields]]
name          = "status"
column_number = 7
values        = ["open", "in_progress", "closed"]
```

### Configuration settings

**Identity**

| Option          | Type   | Description                                                                                          | Required | Default             |
| --------------- | ------ | ---------------------------------------------------------------------------------------------------- | -------- | ------------------- |
| `system_name` | String | Display name shown in TestBench. Must match the name in the DMProxy properties file or during setup. | No       | `"DefectService"` |

**Storage**

| Option              | Type   | Description                                                                                                                                                                   | Required               | Default             |
| ------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- | ------------------- |
| `excel_file_path` | String | Root directory containing one subdirectory per project.                                                                                                                       | **Yes**          | —                  |
| `file_type`       | String | Extension of the defect file inside each project directory, including the dot (`".xlsx"`, `".xls"`, `".csv"`, `".tsv"`, `".txt"`).                                  | **Yes**          | —                  |
| `worksheet_name`  | String | Worksheet to read. Ignored for delimited files. When omitted — or when the sheet is missing or hidden — the first**visible** sheet is used and a warning is reported. | No                     | first visible sheet |
| `separator`       | String | Single character separating values in`.csv` / `.txt` files. `.tsv` always uses a tab.                                                                                   | For`.csv` / `.txt` | —                  |

:::warning
`file_type` has no usable default. If it is not set, every project lookup fails with `No file_type configured for project '<name>'`.
:::

:::note
`separator` applies to `.csv` and `.txt` only and must be a single character; a longer value fails the operation. When it is omitted, a comma is used — for the header row, the data rows and writes alike. A `.tsv` file always uses a tab and ignores `separator`.
:::

**Layout**

| Option                         | Type    | Description                                                                                  | Required | Default |
| ------------------------------ | ------- | -------------------------------------------------------------------------------------------- | -------- | ------- |
| `defects_data_header_line`   | Integer | 1-based row number of the header row.                                                        | No       | `1`   |
| `defects_data_starting_line` | Integer | 1-based row number of the first data row. Rows between the header and this line are skipped. | No       | `2`   |

**Column mapping** (all 1-based; `0` disables the field)

| Option                    | Type    | Defect field    | Required      | Default |
| ------------------------- | ------- | --------------- | ------------- | ------- |
| `id_column_no`          | Integer | `id`          | **Yes** | `1`   |
| `title_column_no`       | Integer | `title`       | No            | `2`   |
| `references_column_no`  | Integer | `references`  | No            | `3`   |
| `discoverer_column_no`  | Integer | `reporter`    | No            | `4`   |
| `lastedit_column_no`    | Integer | `lastEdited`  | No            | `5`   |
| `description_column_no` | Integer | `description` | No            | `6`   |

The `id` column is mandatory: if the configured column number lies outside the file, the import fails. Missing optional columns produce a warning and the field stays empty.

An empty row — one where every configured column is blank — is skipped during import and reported as a single warning per synchronization. Empty rows are kept in the file: they are not removed when defects are created, updated or deleted.

A row the service cannot identify — one that has content but no defect ID, or one whose ID is also used by another row — is reported as an import error and skipped, while every other defect in the file still synchronizes. Such a row is never silently dropped: the report is what keeps a skipped row from quietly losing a defect. Like empty rows, these rows stay in the file untouched by later creates, updates and deletes, so they remain available to repair.

**Query & fields**

| Option             | Type           | Description                                                                                                                                                                                    | Required | Default                           |
| ------------------ | -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | --------------------------------- |
| `attributes`     | List           | Fields shown in the extended defect view. Use logical field names (`title`, `status`, `description`, …) or user-defined attribute names.                                                | No       | `["title", "status", "isOpen"]` |
| `control_fields` | List of tables | Columns whose values are restricted to a fixed list, optionally with a transition workflow. Required for`status`, `priority` and `classification`. See [Control fields](#control-fields). | No       | `[]`                            |
| `udfs`           | List of tables | User-defined attributes. See[User-defined attributes](#user-defined-attributes-udfs).                                                                                                           | No       | `[]`                            |

**Values & formatting**

| Option                       | Type    | Description                                                                                                      | Required | Default        |
| ---------------------------- | ------- | ---------------------------------------------------------------------------------------------------------------- | -------- | -------------- |
| `simple_date_format`       | String  | Date format of the last-edited column, in Java`SimpleDateFormat` notation. See [Date handling](#date-handling). | No       | — (automatic) |
| `references_separator`     | String  | Separates multiple references inside the references cell.                                                        | No       | `","`        |
| `id_prefix`                | String  | Prefix of generated defect IDs.                                                                                  | No       | `"BUG"`      |
| `defect_id_digit_numbers`  | Integer | Number of digits the numeric part of a generated ID is padded to.                                                | No       | `4`          |
| `defect_id_starting_value` | String  | Number the first generated ID uses while the file has no ID matching`id_prefix`.                               | No       | `"1"`        |

**Behavior**

| Option       | Type    | Description                                                               | Required | Default   |
| ------------ | ------- | ------------------------------------------------------------------------- | -------- | --------- |
| `readonly` | Boolean | When`true`, all write operations (create, update, delete) are rejected. | No       | `false` |

**Performance**

| Option                              | Type  | Description                                                      | Required | Default  |
| ----------------------------------- | ----- | ---------------------------------------------------------------- | -------- | -------- |
| `buffer_max_age_minutes`          | Float | How long a parsed file stays in memory.`0` disables buffering. | No       | `1440` |
| `buffer_max_size_mib`             | Float | Total memory budget for buffered files.`0` disables buffering. | No       | `1024` |
| `buffer_cleanup_interval_minutes` | Float | How often the background cleanup thread runs.`0` disables it.  | No       | `1`    |

See [Buffering](#buffering) for details.

**Advanced**

| Option       | Type  | Description                                                                             | Required | Default |
| ------------ | ----- | --------------------------------------------------------------------------------------- | -------- | ------- |
| `commands` | Table | Scripts run before and after a sync. See[Sync hooks](#sync-hooks).                       | No       | —      |
| `projects` | Table | Per-project configuration overrides. See[Per-project overrides](#per-project-overrides). | No       | `{}`  |

---

## Control fields

`status`, `priority` and `classification` are **not** configured as plain column numbers. They are declared as control fields, which combines the column number with the list of allowed values:

```toml
# config.toml
[[testbench-defect-service.client_config.control_fields]]
name          = "status"
column_number = 7
values        = ["open", "in_progress", "blocked", "closed"]

[[testbench-defect-service.client_config.control_fields]]
name          = "priority"
column_number = 8
values        = ["low", "medium", "high"]

[[testbench-defect-service.client_config.control_fields]]
name          = "classification"
column_number = 9
values        = ["bug", "change_request"]
```

| Field             | Type           | Description                                                                                                                                                                       |
| ----------------- | -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`          | String         | Field name as used by TestBench.`"class"` is accepted as an alias for `"classification"`.                                                                                     |
| `column_number` | Integer        | 1-based column of the field in the file.                                                                                                                                          |
| `values`        | List           | Allowed values. Presented as a dropdown in TestBench.                                                                                                                             |
| `transitions`   | List of tables | Allowed changes to this field's value. Omit to allow any change. Each entry needs`from_state` and `to_state`, and both must appear in `values` when `values` is declared. |

TestBench tells the service at sync time which attribute it uses for status, priority and classification. Each of those attribute names must match a control field `name`:

- **No matching control field** — the import is rejected with `sync attribute '<name>' for '<field>' is not configured in the Excel control fields`.
- **Value outside `values`** — create and update are rejected with the list of allowed values.

### Transitions

By default any change to a control field's value is allowed. Declaring
transitions restricts updates to an explicit workflow:

```toml
[[testbench-defect-service.client_config.control_fields]]
name          = "status"
column_number = 7
values        = ["open", "in_progress", "blocked", "closed"]
transitions   = [
    { from_state = "open",        to_state = "in_progress" },
    { from_state = "in_progress", to_state = "closed" },
]
```

An update that changes the value to a state without a matching transition is
rejected with a warning naming the control field. Updates that leave the value
unchanged are always allowed.

Every `from_state` and `to_state` must be one of the field's `values`. A state
outside that list is a configuration error and the service refuses to start —
unless `values` is empty, in which case there is nothing to validate against
and the check is skipped.

:::note
Transitions are only checked on **update**, not when a defect is created.
:::

:::warning[Deprecated]
A top-level `transitions` list is still honoured, but applies to `status` only
and cannot be validated against the field's `values`. Move it into the `status`
control field. If both are present, the nested list wins. The configuration
wizard no longer offers it — it asks for transitions per control field only, and
leaves an already configured top-level list untouched.
:::

---

## User-defined attributes (UDFs)

Custom columns are exposed to TestBench as user-defined attributes:

```toml
# config.toml
[[testbench-defect-service.client_config.udfs]]
name     = "Customer"
column   = 10
type     = "STRING"
required = false

[[testbench-defect-service.client_config.udfs]]
name       = "Regression"
column     = 11
type       = "BOOLEAN"
required   = true
trueValue  = "yes"
falseValue = "no"
```

| Field                          | Type                          | Description                                                                                               |
| ------------------------------ | ----------------------------- | --------------------------------------------------------------------------------------------------------- |
| `name`                       | String                        | Field name as it appears in TestBench. Also usable in`attributes`.                                      |
| `column`                     | Integer                       | 1-based column number of the field.                                                                       |
| `type`                       | `"STRING"` \| `"BOOLEAN"` | Data type of the field.                                                                                   |
| `required`                   | Boolean                       | Whether the field is mandatory.                                                                           |
| `value`                      | String                        | Fallback value used when the column is not present in the file.                                           |
| `trueValue` / `falseValue` | String                        | Cell values representing`true` / `false` for `BOOLEAN` fields. Default to `"true"` / `"false"`. |

`BOOLEAN` values are translated in both directions: cells matching `trueValue` are read as `true`, and writes convert `true` / `false` back to `trueValue` / `falseValue`. A cell that matches neither is reported as unset.

---

## Date handling

`simple_date_format` uses Java `SimpleDateFormat` patterns, which are translated to Python `strftime` patterns:

| Pattern           | Meaning                                         | Example           |
| ----------------- | ----------------------------------------------- | ----------------- |
| `yyyy` / `yy` | Year                                            | `2026` / `26` |
| `MM`            | Month                                           | `08`            |
| `dd`            | Day                                             | `03`            |
| `HH` / `hh`   | Hour (24 h / 12 h)                              | `14` / `02`   |
| `mm`            | Minute (only when the pattern contains an hour) | `05`            |
| `ss`            | Second                                          | `09`            |

```toml
simple_date_format = "yyyy-MM-dd HH:mm:ss"
```

Parsing behavior:

- The configured format is tried first, and is also used when writing the last-edited value.
- If a cell does not match, the client falls back to automatic date detection and reports a single warning per sync.
- If a value cannot be parsed at all — or the cell is empty — the current UTC timestamp is used and a warning is added for that defect.
- Values without a timezone are treated as UTC.

Setting `lastedit_column_no = 0` disables change timestamps for the whole client, and TestBench then treats every defect as potentially changed.

---

## Defect IDs

IDs are generated on create as `<id_prefix><number>`, where the number is the highest existing numeric suffix plus one, zero-padded to `defect_id_digit_numbers`:

```toml
id_prefix                 = "BUG"
defect_id_digit_numbers   = 4
defect_id_starting_value  = "1"
```

With the settings above, the first defect becomes `BUG0001`, the next `BUG0002`. IDs that do not start with `id_prefix` are ignored when determining the next number.

`defect_id_starting_value` decides where numbering begins while no ID in the file matches `id_prefix` — set it to `"500"` and the first defect becomes `BUG0500`. It is consulted for that first ID only: as soon as the file carries matching IDs, the next one continues from the highest of them, so raising the value later never renumbers a project that is already in use. A value that is not a number is ignored with a warning and numbering starts at 1.

:::warning
Defect IDs must be unique and non-empty. A row with an empty ID, and every row sharing an ID with another row, is reported as an import error and skipped — the rest of the file still synchronizes. An update or delete aimed at an ID that several rows use is refused rather than applied to one of them, because the others would stay behind as stale copies of the same defect. Do not renumber existing IDs — TestBench uses the ID to track defect identity across syncs.
:::

---

## Buffering

Parsing a large spreadsheet on every request is expensive, so parsed files are kept in memory:

- A buffered file is reused as long as its modification time on disk is unchanged, so edits made outside the service are picked up automatically.
- Entries older than `buffer_max_age_minutes` are dropped by a background thread that runs every `buffer_cleanup_interval_minutes`.
- When the total buffer exceeds `buffer_max_size_mib`, the least recently used entries are evicted until 80 % of the limit is reached.
- Setting `buffer_max_age_minutes` or `buffer_max_size_mib` to `0` disables buffering entirely and reads the file on every request.

---

## Per-project overrides

Any top-level option can be overridden for a specific project:

```toml
# config.toml
[testbench-defect-service.client_config.projects.project_1]
file_type          = ".xls"
readonly           = true
worksheet_name     = "Defects 2026"
simple_date_format = "dd.MM.yyyy"

[[testbench-defect-service.client_config.projects.project_1.control_fields]]
name          = "status"
column_number = 5
values        = ["open", "closed"]
```

The project key must match the subdirectory name under `excel_file_path`. Options that are not overridden fall back to the global values.

### `<Project>.properties` beside the data

A project directory may also carry a file named exactly like the project. If it
exists it is read as an override — there is no option to switch it on:

```
excel_file_path/
├── project_1/
│   ├── project_1.properties   ← optional override, picked up automatically
│   └── defects.xlsx
└── project_2/                 ← no file, global config used as-is
    └── defects.xlsx
```

```properties
# project_1/project_1.properties
fileType=.xls
worksheetName=Defects 2026
controlFields=status
status.columnNo=5
status.value=open,closed
```

Both the modern key names and the [legacy ones](#legacy-properties-configuration)
work, including the composite forms (`controlFields`, `udf.attrN.*`,
`<field>.transitionN`).

Settings are layered nearest-last: global config, then the
`[…client_config.projects.<name>]` table, then `<Project>.properties`. The file
sits next to the data it describes, so it wins where both name the same key;
keys it does not mention keep the value from the layer below.

The file is re-read on each request, so edits take effect without a restart. If
it cannot be read or a value is invalid, the whole file is skipped, a warning is
logged, and the project keeps its configured values.

:::note

Only `<Project>.properties` is picked up — `<Project>.toml` is not. The name must
match the directory exactly, including case. Since `.properties` is a Java format,
`\` is an escape character in values: write paths as `C:/path/x` or `C:\\path\\x`.

:::

---

## Sync hooks

A script can be run before and after each sync — for example to check out the
workbook from version control and check it back in afterwards:

```toml
# config.toml
[testbench-defect-service.client_config.commands.presync]
scheduled = "C:\\scripts\\checkout-workbook.bat"
manual    = "C:\\scripts\\checkout-workbook.bat"

[testbench-defect-service.client_config.commands.postsync]
scheduled = "C:\\scripts\\checkin-workbook.bat"

# Per-project override
[testbench-defect-service.client_config.projects.project_1.commands.presync]
scheduled = "C:\\scripts\\project-1-checkout.bat"
```

`scheduled`, `manual` and `partial` select the script by sync type. Each value
must be a path to a `.bat`, `.sh` or `.exe` file; anything else is logged and
skipped. The service waits for the script to finish before continuing, and
passes the project key and the sync type to it as arguments.

A project's `commands` table replaces the global one for that project rather
than merging with it. See [Pre/post sync commands](../configuration.md#prepost-sync-commands)
for the shared reference.

---

## Legacy `.properties` configuration

The client accepts the key names used by the legacy DMProxy Excel connector, so an existing `.properties` file can be reused as-is:

:::tip
To convert the file into a regular `config.toml` instead of pointing at it, run
`testbench-defect-service migrate --from <file>.properties` — see the
[Migration guide](../migration.md).
:::

```toml
# config.toml
[testbench-defect-service]
client_class       = "testbench_defect_service.clients.ExcelDefectClient"
client_config_path = "excel_config.properties"
```

```properties
# excel_config.properties
systemName=Excel
excelFilePath=C:\\defects\\excel
fileType=.xlsx
worksheetName=Defects
simpleDateFormat=yyyy-MM-dd
defects.header.line=1
defects.data.startingLine=2
defect.id.columnNo=1
defect.title.columnNo=2
defect.references.columnNo=3
defect.discoverer.columnNo=4
defect.lastedit.columnNo=5
defect.description.columnNo=6
defect.references.separator=,
defect.id.prefix=BUG
defect.id.digitNumber=4

controlFields=status,priority
status.columnNo=7
status.value=open,in_progress,closed
priority.columnNo=8
priority.value=low,medium,high

status.transition.number=2
status.transition1=open-in_progress
status.transition2=in_progress-closed

udf.attr.number=1
udf.attr1.name=Customer
udf.attr1.column=10
udf.attr1.type=STRING
udf.attr1.required=false
```

### Key mapping

| Legacy key                       | TOML option                         |
| -------------------------------- | ----------------------------------- |
| `systemName`                   | `system_name`                     |
| `excelFilePath`                | `excel_file_path`                 |
| `worksheetName`                | `worksheet_name`                  |
| `fileType`                     | `file_type`                       |
| `simpleDateFormat`             | `simple_date_format`              |
| `separator`                    | `separator`                       |
| `defects.header.line`          | `defects_data_header_line`        |
| `defects.data.startingLine`    | `defects_data_starting_line`      |
| `defect.id.columnNo`           | `id_column_no`                    |
| `defect.title.columnNo`        | `title_column_no`                 |
| `defect.references.columnNo`   | `references_column_no`            |
| `defect.discoverer.columnNo`   | `discoverer_column_no`            |
| `defect.lastedit.columnNo`     | `lastedit_column_no`              |
| `defect.lastedited.columnNo`   | `lastedit_column_no`              |
| `defect.description.columnNo`  | `description_column_no`           |
| `defect.references.separator`  | `references_separator`            |
| `defect.id.prefix`             | `id_prefix`                       |
| `defect.id.digitNumber`        | `defect_id_digit_numbers`         |
| `defect.id.startingValue`      | `defect_id_starting_value`        |
| `bufferMaxAgeMinutes`          | `buffer_max_age_minutes`          |
| `bufferMaxSizeMiB`             | `buffer_max_size_mib`             |
| `bufferCleanupIntervalMinutes` | `buffer_cleanup_interval_minutes` |

Structured settings are reassembled from their numbered legacy keys:

| Legacy pattern                                                                                           | Becomes                                                                                                                                             |
| -------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `controlFields`, `<field>.columnNo`, `<field>.value`                                               | one`control_fields` entry per listed field (`class` → `classification`)                                                                      |
| `<field>.transition<n>` or `<state>.transition<n>` with a `from-to` value                             | one`transitions` entry on the control field named by the prefix (`class` → `classification`), or on the field that lists the prefix among its `values`; a prefix that is neither is logged and ignored |
| `udf.attr<n>.name`, `.column`, `.type`, `.required`, `.value`, `.trueValue`, `.falseValue` | one`udfs` entry each                                                                                                                              |

:::note
Both spellings work in either file format — a `.toml` file may use the legacy key names and a `.properties` file may use the new ones. Where both are present, the new key wins.
:::

---

## Writing behavior

When a defect is created, updated or deleted, the client rewrites only the **mapped columns**, at the configured header and data rows. Columns that are not part of the mapping are left untouched, as are other worksheets.

:::warning
Rewriting an `.xlsx` file with openpyxl does not preserve everything Excel can store. Charts, images, pivot tables and conditional formatting can be lost, and formulas in mapped columns are replaced by the written values. Keep a backup of production files, or set `readonly = true` for workbooks that contain more than a defect table.
:::

### Concurrent writers

Each create, update and delete reads the file, changes one row and writes the whole file back. For the duration of that sequence the client holds an exclusive lock on the file, so two writers cannot both start from the same content and silently drop one of the two changes.

The lock is enforced by the operating system, which makes it effective across worker processes (`server.single_process = false` starts one worker per core), across two service instances, and across machines that mount the same share. It lives in a `<defect file>.lock` sidecar next to the defect file, created on the first write and then left in place; the lock itself is released as soon as the write finishes or the process ends. A write that cannot take the lock within 30 seconds fails with a protocol error asking the user to run the synchronization again.

:::note
If the directory holding the defect file is not writable, the sidecar cannot be created. The client then logs a warning and writes without a lock rather than failing an otherwise working setup.
:::

---

## Limitations

| Limitation                                          | Details                                                                                                                                                                                                                        |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **`.xls` is read-only**                     | Creating, updating or deleting a defect in a legacy`.xls` file fails. Convert the file to `.xlsx` with [`migrate workbook`](../cli.md#migrate-workbook).                                                                   |
| **`.tsv` ignores `separator`**            | A`.tsv` file is always read and written tab-separated; a configured `separator` has no effect on it. Use `.txt` with `separator = "\t"` to take the delimiter from the configuration instead.                          |
| **Single-character separators only**          | `separator` must be exactly one character. A longer value fails the operation with`Unsupported separator '<value>' for '<file>'`, on reads as well as writes.                                                              |
| **Editing during a sync**                     | The client locks the file against other writers, but not against a person: avoid editing the spreadsheet while a sync is running. Note that Excel itself holds an exclusive lock on an open workbook, which makes writes fail. |
| **One file per project**                      | Only the first file matching`file_type` in a project directory is used. Additional files are ignored.                                                                                                                        |
| **`defect_id_starting_value` applies once** | It sets the number of the*first* generated ID only. Once the file carries IDs matching`id_prefix`, the next ID always continues from the highest existing one.                                                             |

# Tolerate empty rows in delimited and Excel defect files

Date: 2026-08-05
Status: approved

## Problem

A single empty row in a defect file disables the whole project.

`ExcelDefectClient` serves `.csv`, `.tsv`, `.txt`, `.xlsx` and `.xls` through one
reader (`clients/excel/file_utils.py`). `_validate_required_column_values`
treats `id` as required and raises `ValueError` when any row has a blank `id`.
`get_defects` catches that as a *general* error with `READ_ACCESS_ERROR`, so the
project returns zero defects; `create_defect`, `update_defect` and
`delete_defect` abort the same way.

Reproduced against `examples/excel/project_1/car_config_2.csv`, which already
contains such a row at line 13:

```
12  Bug 0137,eee,,New,Patch,Crash,05.08.2026,,,ee,2-no
13  ,,,,,,,,,,
14  Bug 0138,asd,,New,Patch,Crash,05.08.2026,Hello,,AHHHHHHHH,2-no
```

```
ValueError: Required columns contain empty values in '...car_config_2.csv':
  - 'id': empty at row 14
```

Two further observations:

- Truly blank lines (`\n\n`) are already dropped by pandas
  (`skip_blank_lines=True`). The breaking case is a **separator-only** row —
  which Excel, LibreOffice and this project's own CSV writer all produce, since
  `_clear_stale_delimited_rows` drops only *trailing* all-empty rows.
- `_validate_unique_constraints` reports two or more blank `id`s as
  `duplicate id ''`. This latent bug is currently masked because the
  required-value check raises first.
- `client.py` `_build_defects_from_dataframe` already skips a row with no `id`
  (per-row `IMPORT_ERROR`). That graceful path is unreachable because the
  file-level validation aborts first.

## Definition

A row is **empty** when every column the configuration maps — `id`, `title`,
`description`, `reporter`, `lastEdited`, `references`, the control-field
columns and every UDF column — is blank after `coerce_cell_to_string`.

Content in a column the configuration does not map does not make a row
non-empty. Because empty rows are preserved on write (see below), no such
content is lost.

## Decisions

| Question | Decision |
| --- | --- |
| Which rows are tolerated | Only fully empty rows. A row with a blank `id` but content in another mapped column remains a hard error — silently dropping it would lose a defect. |
| How skipped rows are reported | One general warning per import, naming the count and the file. |
| Are empty rows removed on the next write | No. File layout is preserved. |
| Configurable | No. Tolerating empty rows is unconditionally better than failing the file. |

Rationale for preserving layout: the read frame is positionally aligned with
the file, and `write_defect_data_to_csv` overlays rows contiguously from
`defects_data_starting_line`. Dropping an empty row from the frame would shift
every later defect up one line on the next write, re-pairing any unmapped
column with the wrong defect.

## Changes

### 1. `is_blank_row` predicate — `clients/excel/utils.py`

Add next to `row_value` / `optional_row_value`:

```python
def is_blank_row(row: pd.Series) -> bool:
    """True when every mapped cell in the row is blank."""
```

Values are already strings at this point (`coerce_cell_to_string` runs in
`_load_dataframe`), so a `str(value).strip()` test over the row suffices.

### 2. Reader stops aborting — `clients/excel/file_utils.py`

- `_validate_required_column_values`: exclude blank rows before collecting
  `blank_indices` for `id`. A non-blank row with a blank `id` still raises,
  with the existing message and row numbers.
- `_validate_unique_constraints`: exclude blank `id`s from the duplicate scan.

### 3. Client skips and warns once — `clients/excel/client.py`

In `_build_defects_from_dataframe`:

- blank row → skip, increment a counter, no per-row protocol entry;
- non-blank row with no `id` → keep the existing per-row `IMPORT_ERROR`;
- after the loop, if the counter is non-zero, add exactly one
  `protocol.add_general_warning("Skipped N empty row(s) in '<file>'.",
  ProtocolCode.IMPORT_WARNING)`.

The warning belongs here rather than in the reader: `_get_dataframe` caches
frames in the dataframe buffer, so a warning emitted inside
`read_data_frame_from_file_path` would appear on the first sync and vanish on
every cached one.

`_build_defects_from_dataframe(df, config, sync_context, protocol)` has no
access to the file name today. `get_defects` already holds `defect_path`, so add
an optional `file_name` parameter and pass `defect_path.name`; when it is
absent (the `get_defect_extended` call site) the message omits the file name.

### 4. Boolean UDF blank preservation — `file_utils.py`

Required for the empty row to survive a write unchanged.

`map_boolean_values` maps `v == trueValue -> "true"`, **else `"false"`**, so a
blank boolean cell becomes `"false"` on read. Consequences: the empty row is no
longer blank by the time the client sees it, and on the next write
`_apply_boolean_udf_write_mapping` turns that `"false"` into the configured
`falseValue` and stamps it into the previously-empty row. That row then has a
blank `id` *and* content, so the whole-file abort returns on the following
sync.

Both mappers must preserve blanks:

```python
# read:  "" stays ""
"" if str(v).strip() == "" else ("true" if v == t else "false")
# write: "" stays ""
"" if str(v).strip() == "" else (tv if str(v).lower() == "true" else fv)
```

Accepted side effect beyond empty rows: for a real defect with an empty boolean
cell, the UDF value is reported as `""` instead of `falseValue`. This matches
TestBench semantics — an empty boolean cell is unset, not false.

### 5. Scope

The reader is shared, so `.xlsx` and `.xls` gain the same tolerance. Trailing
empty rows are common in worksheets, so this is wanted there too.

## Tests

`tests/unit/clients/excel/`:

1. A separator-only row no longer raises in `read_data_frame_from_file_path`.
2. Two or more empty rows do not trip the uniqueness check.
3. A row with a blank `id` and content in another mapped column still raises,
   with the correct file row number.
4. `get_defects` returns exactly the non-empty defects and exactly one general
   warning carrying the right count.
5. A blank boolean cell round-trips as blank through
   `map_boolean_values` and `_apply_boolean_udf_write_mapping`.
6. `create_defect` on a file with an interior empty row leaves that line blank
   and every other line byte-identical.

## Out of scope

- Compacting empty rows out of the file.
- A configuration flag for the tolerance.
- Changing `_clear_stale_delimited_rows`, which keeps its current behaviour of
  blanking rows past the new data and dropping only trailing all-empty rows.

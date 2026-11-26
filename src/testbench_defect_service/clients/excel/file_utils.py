import time
import zipfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

import openpyxl
import pandas as pd

from testbench_defect_service.clients.excel.config import ExcelDefectClientConfig
from testbench_defect_service.clients.excel.utils import (
    _format_last_edited,
    boolean_udf_labels,
    coerce_cell_to_string,
    get_column_mapping_for_config,
    get_visible_sheets,
    is_blank_cell,
    resolve_delimited_separator,
    resolve_sheet_name,
    resolve_visible_sheet_name,
    to_excel_number_format,
    to_local_wall_time,
    to_python_datetime_format,
)
from testbench_defect_service.log import logger
from testbench_defect_service.models.defects import Protocol, ProtocolCode, SyncContext, ValueType

_REQUIRED_DATA_COLUMNS: tuple[str, ...] = ("id",)

_EXCEL_SUFFIXES: tuple[str, ...] = (".xlsx", ".xls")
_DELIMITED_SUFFIXES: tuple[str, ...] = (".csv", ".tsv", ".txt")
_DELIMITED_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "windows-1252")

#: Suffix of the file a write is staged in before it replaces the defect file. It is not a
#: `file_type` the client can be configured with, so a leftover is never picked up as data.
_STAGING_SUFFIX = ".tmp"


def read_data_frame_from_file_path(
    file_path: Path,
    config: ExcelDefectClientConfig,
    sync_context: SyncContext,
    protocol: Protocol | None = None,
) -> pd.DataFrame:
    logger.debug(
        "Reading file: %s (%.2f MiB)",
        file_path,
        file_path.stat().st_size / (1024**2),
    )
    start = time.monotonic()

    df = _load_dataframe(file_path, config, protocol)
    column_mapping = get_column_mapping_for_config(config, sync_context, protocol)
    if column_mapping is None:
        return cast(pd.DataFrame, df.iloc[0:0].copy())
    udf_names = {udf_cfg.name for udf_cfg in config.udfs}
    valid_mapping = _validate_column_mapping(
        column_mapping,
        len(df.columns),
        udf_names,
        protocol,
    )

    df = _apply_column_mapping(df, valid_mapping)

    map_boolean_values(config, df)

    # Rows the service cannot use are not rejected here: they stay in the frame so the file
    # layout survives the next write, and the defect builder reports and skips them.
    _require_mapped_columns(df, file_path)

    bytes_used = df.memory_usage(index=True, deep=True).sum()
    logger.debug(
        "Read dataframe in %.3fs (%.2f MiB)",
        time.monotonic() - start,
        bytes_used / (1024**2),
    )
    return df


def map_boolean_values(config: ExcelDefectClientConfig, df: pd.DataFrame) -> None:
    for udf in config.udfs:
        if udf.type == ValueType.BOOLEAN:
            true_value, false_value = boolean_udf_labels(udf)
            try:
                df[udf.name] = df[udf.name].map(
                    lambda v, t=true_value, f=false_value: _map_boolean_read_value(v, t, f)
                )
            except KeyError:
                logger.warning(f"{udf.name} not in the dataframe")


def _map_boolean_read_value(value: Any, true_value: str, false_value: str) -> str:
    """Map a boolean UDF cell to the internal 'true'/'false' form.

    A blank cell stays blank: it is unset, not false. Coercing it would also
    re-fill an otherwise-empty row on the next write.

    A cell holding neither label is left as it is. Calling it false would send TestBench a
    value nobody entered; the defect builder reports the cell and leaves the attribute out.
    """
    if is_blank_cell(value):
        return ""
    if value == true_value:
        return "true"
    if value == false_value:
        return "false"
    return str(value)


def _validate_column_mapping(
    column_mapping: dict[int, list[str]],
    total_columns: int,
    udf_names: set[str],
    protocol: Protocol | None = None,
) -> dict[int, list[str]]:
    valid_mapping: dict[int, list[str]] = {}
    for idx, names in column_mapping.items():
        primary_name = names[0]
        if idx < total_columns:
            if len(names) > 1:
                logger.warning(
                    "Column index %d is mapped to multiple fields (%s).",
                    idx + 1,
                    ", ".join(f"'{name}'" for name in names),
                )
            valid_mapping[idx] = names
            continue

        if primary_name in _REQUIRED_DATA_COLUMNS:
            raise ValueError(
                f"Required column '{primary_name}' (index {idx + 1}) not found in the file."
            )

        kind = "UDF" if primary_name in udf_names else "Optional"
        warning_message = (
            f"{kind} column '{primary_name}' (index {idx + 1}) is not present in the file "
            f"({total_columns} columns)."
        )
        logger.warning(warning_message)
        if protocol is not None:
            protocol.add_general_warning(
                warning_message,
                protocol_code=ProtocolCode.IMPORT_WARNING,
            )

    return valid_mapping


def _require_mapped_columns(df: pd.DataFrame, file_path: Path) -> None:
    """Fail the read when a required column is not mapped at all.

    Without it no row in the file can be identified, so there is no partial result worth
    returning - unlike a single unusable row, which is reported and skipped.
    """
    missing = [col for col in _REQUIRED_DATA_COLUMNS if col not in df.columns]
    if not missing:
        return
    names = ", ".join(f"'{col}'" for col in missing)
    logger.error(
        "Required column(s) %s are not configured or could not be found in '%s'.",
        names,
        file_path,
    )
    raise ValueError(
        f"Required column(s) {names} are not configured or could not be found in '{file_path}'."
    )


def _apply_column_mapping(
    df: pd.DataFrame,
    valid_mapping: dict[int, list[str]],
) -> pd.DataFrame:
    ordered_indices = sorted(valid_mapping.keys())
    mapped_df = df.iloc[:, ordered_indices].copy()
    mapped_df.columns = pd.Index([valid_mapping[idx][0] for idx in ordered_indices])

    for names in valid_mapping.values():
        for alias in names[1:]:
            mapped_df[alias] = mapped_df[names[0]]

    return cast(pd.DataFrame, mapped_df)


def _coerce_timestamp_cell(value: Any, date_format: str | None) -> str:
    """Render a cell of the last-edited column without cutting the time off a real date.

    `simple_date_format` says how the date is *shown* - `dd.MM.yyyy` is typical - while the
    cell itself holds the time of day as well. Formatting it with that pattern threw the time
    away, so a change made later on the day of the last sync looked older than the sync.
    Text cells have nothing more to give and are rendered as before.
    """
    if value is not None and value is not pd.NaT and isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return coerce_cell_to_string(value, date_format)


def _load_dataframe(
    file_path: Path,
    config: ExcelDefectClientConfig,
    protocol: Protocol | None = None,
) -> pd.DataFrame:
    header_row_idx = max(config.defects_data_header_line - 1, 0)
    data_row_idx = max(config.defects_data_starting_line - 1, header_row_idx + 1)
    read_params: dict[str, Any] = {
        "header": header_row_idx,
        "dtype": object,
        "skiprows": list(range(header_row_idx + 1, data_row_idx)),
    }

    if file_path.suffix.lower() in (".xls", ".xlsx"):
        try:
            visible_sheets = get_visible_sheets(file_path)
        except Exception as exc:
            raise ValueError(f"Could not open Excel file '{file_path.name}': {exc}") from exc

        if not visible_sheets:
            raise ValueError(f"No visible worksheets found in '{file_path.name}'.")

        sheet_name = resolve_sheet_name(
            (config.worksheet_name or ""),
            visible_sheets,
            file_path.name,
            protocol,
        )
        engine: Literal["openpyxl", "xlrd"]
        engine = "openpyxl" if file_path.suffix.lower() == ".xlsx" else "xlrd"
        df = pd.read_excel(file_path, sheet_name=sheet_name, engine=engine, **read_params)
    elif file_path.suffix.lower() in _DELIMITED_SUFFIXES:
        separator = resolve_delimited_separator(file_path, config)
        df, _ = _read_delimited_dataframe(file_path, separator, **read_params)
    else:
        raise ValueError(f"Unsupported file format: {file_path.suffix}")

    date_format = to_python_datetime_format(config.simple_date_format)
    last_edited_idx = config.lastedit_column_no - 1
    normalized_columns = [
        df.iloc[:, position].map(
            lambda value, keep_time=(position == last_edited_idx): (
                _coerce_timestamp_cell(value, date_format)
                if keep_time
                else coerce_cell_to_string(value, date_format)
            )
        )
        for position in range(len(df.columns))
    ]
    normalized_df = pd.concat(normalized_columns, axis=1) if normalized_columns else df.copy()
    normalized_df.columns = df.columns
    return cast(pd.DataFrame, normalized_df)


def _read_delimited_dataframe(
    file_path: Path,
    separator: str,
    **read_params: Any,
) -> tuple[pd.DataFrame, str]:
    """Read a delimited file, returning the frame and the encoding that decoded it."""
    last_error: UnicodeDecodeError | None = None
    for encoding in _DELIMITED_ENCODINGS:
        try:
            df = pd.read_csv(file_path, sep=separator, encoding=encoding, **read_params)
            return df, encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    assert last_error is not None  # the loop above always runs at least once
    raise last_error


# --- Writing ---------------------------------------------------------------------------------
#
# A write touches the one row it is about and nothing else. Rewriting every mapped column of
# every row - which is what this module used to do - turned each date and number in the file
# into text on the first defect created, because the frame the cells were rewritten from
# holds strings only.


def write_defect_row(
    sync_context: SyncContext,
    defect_path: Path,
    config: ExcelDefectClientConfig,
    row_position: int,
    values: Mapping[str, Any],
) -> None:
    """Write one defect's cells into the data row at *row_position* (0 = first data row).

    Only the fields named in *values* are written; a field that is absent keeps whatever the
    file holds. A position one past the last row appends a new defect.

    Raises:
        ValueError: When the file format cannot be written.
        OSError: When the file cannot be read or replaced.
    """
    suffix = defect_path.suffix.lower()
    if suffix not in (*_EXCEL_SUFFIXES, *_DELIMITED_SUFFIXES):
        raise ValueError(f"Unsupported file format for writing: '{defect_path.suffix}'.")
    _reject_legacy_xls(defect_path)

    column_positions = get_column_mapping_for_config(config, sync_context)
    if not column_positions:
        return

    as_text = suffix in _DELIMITED_SUFFIXES
    cells: dict[int, tuple[str, Any]] = {}
    for col_idx, col_names in column_positions.items():
        col_name = col_names[0]
        if col_name not in values:
            continue
        cells[col_idx] = (col_name, _cell_value(config, col_name, values[col_name], as_text))

    if as_text:
        _write_row_to_delimited(defect_path, config, row_position, cells)
    else:
        _write_row_to_excel(defect_path, config, row_position, cells)


def delete_defect_row(
    defect_path: Path,
    config: ExcelDefectClientConfig,
    row_position: int,
) -> None:
    """Remove the data row at *row_position* (0 = first data row), closing the gap.

    The whole row goes, not only the columns the client maps: cells in columns it does not
    know about belong to the defect just as much, and leaving them behind would hand them to
    whichever defect moves up into that row.

    Raises:
        ValueError: When the file format cannot be written.
        OSError: When the file cannot be read or replaced.
    """
    suffix = defect_path.suffix.lower()
    if suffix in _DELIMITED_SUFFIXES:
        _delete_row_from_delimited(defect_path, config, row_position)
    elif suffix in _EXCEL_SUFFIXES:
        _reject_legacy_xls(defect_path)
        _delete_row_from_excel(defect_path, config, row_position)
    else:
        raise ValueError(f"Unsupported file format for writing: '{defect_path.suffix}'.")


def _reject_legacy_xls(defect_path: Path) -> None:
    if defect_path.suffix.lower() == ".xls":
        raise ValueError(
            f"Writing to legacy .xls files is not supported: '{defect_path.name}'. "
            "Convert the file to .xlsx to create or update defects."
        )


def _cell_value(
    config: ExcelDefectClientConfig,
    col_name: str,
    value: Any,
    as_text: bool,
) -> Any:
    """Turn one logical value into what its cell should hold."""
    if isinstance(value, datetime):
        if as_text:
            return _format_last_edited(value, config)
        return to_local_wall_time(value)
    if is_blank_cell(value):
        return ""
    for udf in config.udfs:
        if udf.name == col_name and udf.type == ValueType.BOOLEAN:
            return _map_boolean_write_value(value, *boolean_udf_labels(udf))
    return str(value)


def _map_boolean_write_value(value: Any, true_value: str, false_value: str) -> str:
    """Convert the internal 'true'/'false' back to the configured cell contents."""
    normalized = str(value).strip().lower()
    if normalized == "true":
        return true_value
    if normalized == "false":
        return false_value
    return str(value)


def _staging_path(defect_path: Path) -> Path:
    return defect_path.with_name(defect_path.name + _STAGING_SUFFIX)


def _replace_defect_file(staged_path: Path, defect_path: Path) -> None:
    """Put the finished file in place of the defect file in one step.

    Writing straight into the defect file left it truncated when the write failed half way.
    The replace also fails cleanly while the file is open in Excel, with the file untouched.
    """
    try:
        staged_path.replace(defect_path)
    except OSError:
        staged_path.unlink(missing_ok=True)
        raise


def _open_workbook_for_writing(defect_path: Path) -> Any:
    try:
        return openpyxl.load_workbook(defect_path)
    except (KeyError, zipfile.BadZipFile) as exc:
        raise ValueError(
            f"File '{defect_path.name}' does not appear to be a valid xlsx file "
            f"(it may be corrupted or in a different format): {exc}"
        ) from exc


def _save_workbook(workbook: Any, defect_path: Path) -> None:
    staged_path = _staging_path(defect_path)
    try:
        workbook.save(staged_path)
    except OSError:
        staged_path.unlink(missing_ok=True)
        raise
    _replace_defect_file(staged_path, defect_path)


def _write_row_to_excel(
    defect_path: Path,
    config: ExcelDefectClientConfig,
    row_position: int,
    cells: dict[int, tuple[str, Any]],
) -> None:
    sheet_name = resolve_visible_sheet_name(defect_path, config)
    file_row = config.defects_data_starting_line + row_position
    logger.debug("Writing defect row %d to '%s' on sheet '%s'", file_row, defect_path, sheet_name)

    workbook = _open_workbook_for_writing(defect_path)
    try:
        worksheet = workbook[sheet_name]
        for col_idx, (col_name, value) in cells.items():
            # A column the file does not have yet gets a header; an existing one is kept.
            header_cell = worksheet.cell(row=config.defects_data_header_line, column=col_idx + 1)
            if is_blank_cell(header_cell.value):
                header_cell.value = col_name

            cell = worksheet.cell(row=file_row, column=col_idx + 1)
            if isinstance(value, datetime):
                cell.value = value
                cell.number_format = to_excel_number_format(config.simple_date_format)
            else:
                cell.value = None if value == "" else value
        _save_workbook(workbook, defect_path)
    finally:
        workbook.close()


def _delete_row_from_excel(
    defect_path: Path,
    config: ExcelDefectClientConfig,
    row_position: int,
) -> None:
    sheet_name = resolve_visible_sheet_name(defect_path, config)
    file_row = config.defects_data_starting_line + row_position
    logger.debug(
        "Deleting defect row %d from '%s' on sheet '%s'", file_row, defect_path, sheet_name
    )

    workbook = _open_workbook_for_writing(defect_path)
    try:
        workbook[sheet_name].delete_rows(file_row, 1)
        _save_workbook(workbook, defect_path)
    finally:
        workbook.close()


def _read_delimited_grid(defect_path: Path, separator: str) -> tuple[pd.DataFrame, str]:
    """Read a delimited file as a raw grid of strings, with the encoding to write it back in.

    dtype=str and keep_default_na=False keep untouched cells byte-for-byte: no "007" -> 7,
    no "N/A" -> NaN -> "".
    """
    grid_df, encoding = _read_delimited_dataframe(
        defect_path,
        separator,
        header=None,
        dtype=str,
        keep_default_na=False,
    )
    # utf-8-sig also decodes plain utf-8; only write a BOM if the file had one.
    if encoding == "utf-8-sig":
        with defect_path.open("rb") as handle:
            if handle.read(3) != b"\xef\xbb\xbf":
                encoding = "utf-8"
    return grid_df, encoding


def _save_delimited_grid(
    grid_df: pd.DataFrame, defect_path: Path, separator: str, encoding: str
) -> None:
    staged_path = _staging_path(defect_path)
    try:
        grid_df.to_csv(
            staged_path,
            mode="w",
            index=False,
            header=False,
            na_rep="",
            sep=separator,
            encoding=encoding,
        )
    except OSError:
        staged_path.unlink(missing_ok=True)
        raise
    _replace_defect_file(staged_path, defect_path)


def _write_row_to_delimited(
    defect_path: Path,
    config: ExcelDefectClientConfig,
    row_position: int,
    cells: dict[int, tuple[str, Any]],
) -> None:
    separator = resolve_delimited_separator(defect_path, config)
    logger.debug("Writing defect row to delimited file '%s'", defect_path)
    grid_df, encoding = _read_delimited_grid(defect_path, separator)

    header_row_idx = config.defects_data_header_line - 1
    grid_row_idx = config.defects_data_starting_line - 1 + row_position
    required_rows = max(header_row_idx, grid_row_idx) + 1
    if len(grid_df) < required_rows:
        padding = pd.DataFrame(
            "", index=range(len(grid_df), required_rows), columns=grid_df.columns
        )
        grid_df = pd.concat([grid_df, padding], ignore_index=True)

    for col_idx, (col_name, value) in cells.items():
        while col_idx >= len(grid_df.columns):
            grid_df[len(grid_df.columns)] = ""
        if is_blank_cell(grid_df.iat[header_row_idx, col_idx]):
            grid_df.iat[header_row_idx, col_idx] = col_name
        grid_df.iat[grid_row_idx, col_idx] = value

    _save_delimited_grid(grid_df, defect_path, separator, encoding)


def _delete_row_from_delimited(
    defect_path: Path,
    config: ExcelDefectClientConfig,
    row_position: int,
) -> None:
    separator = resolve_delimited_separator(defect_path, config)
    logger.debug("Deleting defect row from delimited file '%s'", defect_path)
    grid_df, encoding = _read_delimited_grid(defect_path, separator)

    grid_row_idx = config.defects_data_starting_line - 1 + row_position
    if grid_row_idx >= len(grid_df):
        return
    grid_df = grid_df.drop(index=grid_df.index[grid_row_idx]).reset_index(drop=True)

    _save_delimited_grid(grid_df, defect_path, separator, encoding)

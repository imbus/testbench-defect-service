import math
import time
from pathlib import Path
from typing import Any, Literal, cast

import openpyxl
import pandas as pd
import xlrd

from testbench_defect_service.clients.excel.config import ExcelDefectClientConfig
from testbench_defect_service.log import logger
from testbench_defect_service.models.defects import Protocol, ProtocolCode, SyncContext

_REQUIRED_DATA_COLUMNS: tuple[str, ...] = ("id",)


def get_column_mapping_for_config(
    config: ExcelDefectClientConfig, sync_context: SyncContext, protocol: Protocol | None = None
) -> dict[int, list[str]] | None:
    column_mapping: dict[int, list[str]] = {}

    status_column_no = None
    priority_column_no = None
    class_column_no = None

    for control_field in config.control_fields:
        if sync_context.statusAttribute == control_field.name:
            status_column_no = control_field.column_number
        if sync_context.priorityAttribute == control_field.name:
            priority_column_no = control_field.column_number
        if sync_context.classAttribute == control_field.name:
            class_column_no = control_field.column_number

    if _add_missing_control_field_errors(
        sync_context,
        protocol,
        status_column_no=status_column_no,
        priority_column_no=priority_column_no,
        class_column_no=class_column_no,
    ):
        return None

    base_columns = {
        "id": config.id_column_no,
        "title": config.title_column_no,
        "references": config.references_column_no,
        "reporter": config.discoverer_column_no,
        "lastEdited": config.lastedit_column_no,
        "description": config.description_column_no,
        "status": status_column_no,
        "classification": class_column_no,
        "priority": priority_column_no,
    }
    for field_name, column_number in base_columns.items():
        _register_column(column_mapping, column_number, field_name)

    for udf_config in config.udfs:
        _register_column(column_mapping, udf_config.column, udf_config.name)

    return column_mapping


def _add_missing_control_field_errors(
    sync_context: SyncContext,
    protocol: Protocol | None,
    *,
    status_column_no: int | None,
    priority_column_no: int | None,
    class_column_no: int | None,
) -> bool:
    messages: list[str] = []
    required_control_fields = (
        ("status", sync_context.statusAttribute, status_column_no),
        ("priority", sync_context.priorityAttribute, priority_column_no),
        ("classification", sync_context.classAttribute, class_column_no),
    )

    for defect_field, attribute_name, column_number in required_control_fields:
        if not attribute_name or column_number:
            continue
        messages.append(
            f"Cannot import Excel defects: sync attribute '{attribute_name}' for "
            f"'{defect_field}' is not configured in the Excel control fields."
        )

    if not messages:
        return False

    if protocol is None:
        raise ValueError("\n".join(messages))

    for message in messages:
        logger.warning(message)
        protocol.add_general_error(
            message,
            protocol_code=ProtocolCode.IMPORT_ERROR,
        )
    return True


def _register_column(
    column_mapping: dict[int, list[str]],
    column_number: int | None,
    field_name: str,
) -> None:
    if column_number is None or column_number <= 0:
        return
    column_idx = column_number - 1
    column_mapping.setdefault(column_idx, [])
    if field_name not in column_mapping[column_idx]:
        column_mapping[column_idx].append(field_name)


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
    _validate_required_column_values(df, file_path, config)
    _validate_unique_constraints(df, file_path, config)

    bytes_used = df.memory_usage(index=True, deep=True).sum()
    logger.debug(
        "Read dataframe in %.3fs (%.2f MiB)",
        time.monotonic() - start,
        bytes_used / (1024**2),
    )
    return df


def _validate_unique_constraints(
    df: pd.DataFrame,
    file_path: Path,
    config: ExcelDefectClientConfig,
) -> None:
    first_data_file_row = config.defects_data_starting_line
    max_displayed_rows = 10

    errors: list[str] = []
    if "id" in df.columns:
        duplicated_mask = df.duplicated(subset=["id"], keep=False)
        duplicate_ids = df.loc[duplicated_mask, ["id"]].drop_duplicates()
        for _, duplicate_row in duplicate_ids.iterrows():
            duplicate_id = duplicate_row["id"]
            indices = df.index[df["id"] == duplicate_id].tolist()
            displayed = [str(first_data_file_row + idx) for idx in indices[:max_displayed_rows]]
            overflow = len(indices) - max_displayed_rows
            suffix = f" (and {overflow} more)" if overflow > 0 else ""
            errors.append(
                f"  - duplicate id {duplicate_id!r} at rows {', '.join(displayed)}{suffix}"
            )

    if errors:
        raise ValueError(f"Uniqueness constraints violated in '{file_path}':\n" + "\n".join(errors))


def _validate_required_column_values(
    df: pd.DataFrame,
    file_path: Path,
    config: ExcelDefectClientConfig,
) -> None:
    first_data_file_row = config.defects_data_starting_line
    errors: list[str] = []

    for col in _REQUIRED_DATA_COLUMNS:
        if col not in df.columns:
            errors.append(f"  - '{col}': column is not configured or could not be found.")
            continue
        blank_indices = df.index[df[col].str.strip() == ""].tolist()
        if not blank_indices:
            continue
        displayed = [str(first_data_file_row + idx) for idx in blank_indices[:10]]
        overflow = len(blank_indices) - 10
        suffix = f" (and {overflow} more)" if overflow > 0 else ""
        row_label = "row" if len(blank_indices) == 1 else "rows"
        errors.append(f"  - '{col}': empty at {row_label} {', '.join(displayed)}{suffix}")

    if errors:
        raise ValueError(
            f"Required columns contain empty values in '{file_path}':\n" + "\n".join(errors)
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
            visible_sheets = _get_visible_sheets(file_path)
        except Exception as exc:
            raise ValueError(f"Could not open Excel file '{file_path.name}': {exc}") from exc

        if not visible_sheets:
            raise ValueError(f"No visible worksheets found in '{file_path.name}'.")

        sheet_name = _resolve_sheet_name(
            (config.worksheet_name or ""),
            visible_sheets,
            file_path.name,
            protocol,
        )
        engine: Literal["openpyxl", "xlrd"]
        engine = "openpyxl" if file_path.suffix.lower() == ".xlsx" else "xlrd"
        df = pd.read_excel(file_path, sheet_name=sheet_name, engine=engine, **read_params)
    elif file_path.suffix.lower() in (".csv", ".tsv", ".txt"):
        separator = "\t" if file_path.suffix.lower() == ".tsv" else config.seperator
        try:
            df = pd.read_csv(file_path, sep=separator, **read_params)
        except UnicodeDecodeError:
            df = pd.read_csv(file_path, sep=separator, encoding="windows-1252", **read_params)
    else:
        raise ValueError(f"Unsupported file format: {file_path.suffix}")

    normalized_df = df.fillna("").apply(lambda column: column.map(_coerce_cell_to_string))
    return cast(pd.DataFrame, normalized_df)


def _coerce_cell_to_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _get_visible_sheets(file_path: Path) -> list[str]:
    suffix = file_path.suffix.lower()
    if suffix == ".xlsx":
        xlsx_workbook = openpyxl.load_workbook(
            file_path,
            read_only=True,
            data_only=True,
            keep_links=False,
        )
        try:
            return [
                sheet.title for sheet in xlsx_workbook.worksheets if sheet.sheet_state == "visible"
            ]
        finally:
            xlsx_workbook.close()

    if suffix == ".xls":
        xls_workbook = xlrd.open_workbook(str(file_path), on_demand=True)
        try:
            return [sheet.name for sheet in xls_workbook.sheets() if sheet.visibility == 0]
        finally:
            xls_workbook.release_resources()

    raise ValueError(f"Unsupported Excel file format: '{suffix}'.")


def _resolve_sheet_name(
    configured_sheet_name: str | None,
    visible_sheets: list[str],
    file_name: str,
    protocol: Protocol | None = None,
) -> str:
    if not configured_sheet_name:
        return visible_sheets[0]
    if configured_sheet_name in visible_sheets:
        return configured_sheet_name

    warning_message = (
        f"Worksheet '{configured_sheet_name}' was not found or is hidden in '{file_name}'. "
        f"Falling back to '{visible_sheets[0]}'."
    )
    logger.warning(warning_message)
    if protocol is not None:
        protocol.add_general_warning(
            warning_message,
            protocol_code=ProtocolCode.IMPORT_WARNING,
        )
    return visible_sheets[0]

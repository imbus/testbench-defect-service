import time
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np
import pandas as pd

from testbench_defect_service.clients.excel.config import ExcelDefectClientConfig
from testbench_defect_service.clients.excel.utils import (
    coerce_cell_to_string,
    get_column_mapping_for_config,
    get_visible_sheets,
    resolve_sheet_name,
    resolve_visible_sheet_name,
)
from testbench_defect_service.log import logger
from testbench_defect_service.models.defects import Protocol, ProtocolCode, SyncContext, ValueType

_REQUIRED_DATA_COLUMNS: tuple[str, ...] = ("id",)


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

    map_boolean_values(config, df)

    df = _apply_column_mapping(df, valid_mapping)

    try:
        _validate_required_column_values(df, file_path, config)
        _validate_unique_constraints(df, file_path, config)
    except ValueError:
        logger.error(
            f"Data validation failed for file: '{file_path}'. "
            "Check required columns and unique constraints."
        )

    bytes_used = df.memory_usage(index=True, deep=True).sum()
    logger.debug(
        "Read dataframe in %.3fs (%.2f MiB)",
        time.monotonic() - start,
        bytes_used / (1024**2),
    )
    return df


def map_boolean_values(config, df):
    for udf in config.udfs:
        if udf.type == ValueType.BOOLEAN:
            try:
                df[udf.name] = df[udf.name].map(
                    lambda v, t=udf.trueValue: "true" if v == t else "false"
                )
            except KeyError:
                logger.warning(f"{udf.name} not in the dataframe")


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
    elif file_path.suffix.lower() in (".csv", ".tsv", ".txt"):
        separator = "\t" if file_path.suffix.lower() == ".tsv" else config.separator
        try:
            df = pd.read_csv(file_path, sep=separator, **read_params)
        except UnicodeDecodeError:
            df = pd.read_csv(file_path, sep=separator, encoding="windows-1252", **read_params)
    else:
        raise ValueError(f"Unsupported file format: {file_path.suffix}")

    normalized_df = df.fillna("").apply(lambda column: column.map(coerce_cell_to_string))
    return cast(pd.DataFrame, normalized_df)


def write_defect_data_to_excel(
    sync_context: SyncContext,
    defect_path: Path,
    config: ExcelDefectClientConfig,
    header: dict[int, str],
    df_with_new_defect: pd.DataFrame,
):
    column_positions = get_column_mapping_for_config(config, sync_context)
    if not column_positions:
        return
    if defect_path.suffix.lower() == ".xls":
        raise ValueError(
            f"Writing to legacy .xls files is not supported: '{defect_path.name}'. "
            "Convert the file to .xlsx to create or update defects."
        )
    sheet_name = resolve_visible_sheet_name(defect_path, config)

    logger.debug("Writing defect data to '%s' on sheet '%s'", defect_path, sheet_name)
    is_existing_xlsx = defect_path.exists() and defect_path.suffix.lower() == ".xlsx"
    writer_kwargs: dict[str, Any] = {"engine": "openpyxl"}
    if is_existing_xlsx:
        writer_kwargs["mode"] = "a"
        writer_kwargs["if_sheet_exists"] = "overlay"
    with pd.ExcelWriter(defect_path, **writer_kwargs) as writer:
        for col_idx, col_names in column_positions.items():
            col_name = col_names[0]
            if col_name not in df_with_new_defect.columns:
                continue
            original_header = header.get(col_idx + 1, col_name)

            for udf in config.udfs:
                if udf.name == col_name and udf.type == ValueType.BOOLEAN:
                    true_val: str | None = udf.trueValue
                    false_val: str | None = udf.falseValue

                    def _map_bool(
                        v: str, tv: str | None = true_val, fv: str | None = false_val
                    ) -> str | None:
                        return tv if v == "true" else fv

                    df_with_new_defect[col_name] = df_with_new_defect[col_name].map(_map_bool)

            # --- STEP 1: Write ONLY the Header ---
            header_only_df = (
                df_with_new_defect[[col_name]].iloc[0:0].rename(columns={col_name: original_header})
            )
            header_only_df.to_excel(
                writer,
                sheet_name=sheet_name,
                startcol=col_idx,
                startrow=config.defects_data_header_line - 1,
                index=False,
                header=True,
            )

            # --- STEP 2: Write ONLY the Values ---
            df_with_new_defect[[col_name]].to_excel(
                writer,
                sheet_name=sheet_name,
                startcol=col_idx,
                startrow=config.defects_data_starting_line - 1,
                index=False,
                header=False,
            )


def write_defect_data_to_csv(
    sync_context: SyncContext,
    defect_path: Path,
    config: ExcelDefectClientConfig,
    header: dict[int, str],
    df_with_new_defect: pd.DataFrame,
):
    column_positions = get_column_mapping_for_config(config, sync_context)
    if not column_positions:
        return

    logger.debug("Overlaying defect data to CSV '%s'", defect_path)

    is_existing_csv = defect_path.exists() and defect_path.suffix.lower() == ".csv"
    grid_df = pd.read_csv(defect_path, header=None) if is_existing_csv else pd.DataFrame()

    header_row_idx = config.defects_data_header_line - 1
    start_row_idx = config.defects_data_starting_line - 1
    num_new_rows = len(df_with_new_defect)
    required_rows = max(header_row_idx + 1, start_row_idx + num_new_rows)

    # Expand grid rows if necessary
    if len(grid_df) < required_rows:
        padding = pd.DataFrame(
            np.nan, index=range(len(grid_df), required_rows), columns=grid_df.columns
        )
        # Using concat to add the required empty rows to the bottom
        grid_df = pd.concat([grid_df, padding], ignore_index=True)

    for col_idx, col_names in column_positions.items():
        col_name = col_names[0]
        if col_name not in df_with_new_defect.columns:
            continue

        original_header = header.get(col_idx + 1, col_name)

        # Apply UDF boolean mappings
        for udf in config.udfs:
            if udf.name == col_name and udf.type == ValueType.BOOLEAN:
                true_val: str | None = udf.trueValue
                false_val: str | None = udf.falseValue

                def _map_bool(
                    v: str, tv: str | None = true_val, fv: str | None = false_val
                ) -> str | None:
                    return tv if str(v).lower() == "true" else fv

                df_with_new_defect[col_name] = df_with_new_defect[col_name].map(_map_bool)

        while col_idx >= len(grid_df.columns):
            grid_df[len(grid_df.columns)] = np.nan

        # Overlay the Header at the specific coordinate
        grid_df.iat[header_row_idx, col_idx] = original_header
        grid_df.iloc[start_row_idx : start_row_idx + num_new_rows, col_idx] = df_with_new_defect[
            col_name
        ].values

    grid_df.to_csv(
        defect_path, mode="w", index=False, header=False, na_rep="", sep=config.separator
    )

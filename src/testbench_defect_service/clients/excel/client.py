import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sanic.exceptions import NotFound

from testbench_defect_service.clients.abstract_client import AbstractDefectClient
from testbench_defect_service.clients.excel.config import ExcelDefectClientConfig
from testbench_defect_service.clients.excel.utils import (
    get_column_mapping_for_config,
    read_data_frame_from_file_path,
    read_header_columns_from_file_path,
    resolve_visible_sheet_name,
)
from testbench_defect_service.log import logger
from testbench_defect_service.models.defects import (
    Defect,
    DefectID,
    DefectWithAttributes,
    DefectWithID,
    ExtendedAttributes,
    Login,
    Protocol,
    ProtocolCode,
    ProtocolledDefectSet,
    ProtocolledString,
    Results,
    Settings,
    SyncContext,
    UserDefinedAttribute,
    UserDefinedFieldProperties,
    ValueType,
)


@dataclass
class DataFrameBufferEntry:
    data_frame: pd.DataFrame
    last_accessed_at: float
    file_mtime: float
    size_bytes: int


class ExcelDefectClient(AbstractDefectClient):
    CONFIG_CLASS = ExcelDefectClientConfig

    def __init__(self, config: ExcelDefectClientConfig):
        self.config = config
        self._buffer_catalog: dict[str, DataFrameBufferEntry] = {}
        self._buffer_size_bytes = 0
        self._buffer_lock = threading.RLock()
        self._start_buffer_cleanup_thread()

    def check_login(self, project: str | None) -> bool:
        if project is None:
            return self.config.excel_file_path.exists()

        try:
            self._get_file_path(project)
        except FileNotFoundError:
            return False
        return True

    def get_settings(self) -> Settings:
        return Settings(
            name=self.config.system_name,
            description="Excel Defect Manager",
            readonly=self.config.readonly,
        )

    def get_projects(self) -> list[str]:
        if not self.config.excel_file_path.exists():
            return []
        return sorted(p.name for p in self.config.excel_file_path.iterdir() if p.is_dir())

    def get_control_fields(self, project: str | None) -> dict[str, list[str]]:
        control_fields = {}
        for field in self._get_config_value("control_fields", project) or []:
            control_fields[field.name] = field.values
        return control_fields

    def get_defects(self, project: str, sync_context: SyncContext) -> ProtocolledDefectSet:
        protocol = Protocol()
        try:
            defect_path = self._get_file_path(project=project)
            effective_config = self._get_effective_config(project)
            df = self._get_dataframe(defect_path, effective_config, sync_context, protocol)
        except FileNotFoundError as exc:
            protocol.add_general_error(str(exc), protocol_code=ProtocolCode.PROJECT_NOT_FOUND)
            return ProtocolledDefectSet(value=[], protocol=protocol)
        except (OSError, ValueError) as exc:
            protocol.add_general_error(str(exc), protocol_code=ProtocolCode.READ_ACCESS_ERROR)
            return ProtocolledDefectSet(value=[], protocol=protocol)

        if protocol.generalErrors:
            return ProtocolledDefectSet(value=[], protocol=protocol)

        defects = self._build_defects_from_dataframe(df, effective_config, protocol)
        if not defects:
            protocol.add_general_warning(
                f"No defects were found in '{defect_path.name}' for project '{project}'.",
                protocol_code=ProtocolCode.NO_DEFECT_FOUND,
            )
        protocol.add_success(
            key=project,
            message=(
                f"Loaded {len(defects)} defect(s) from Excel file '{defect_path.name}' "
                f"for project '{project}'."
            ),
            protocol_code=ProtocolCode.IMPORT_SUCCESS,
        )
        logger.info("Loaded %d Excel defects for project '%s'", len(defects), project)
        return ProtocolledDefectSet(value=defects, protocol=protocol)

    def _get_dataframe(
        self,
        file_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
        protocol: Protocol | None = None,
    ) -> pd.DataFrame:
        max_age_seconds, max_size_bytes = self._get_buffer_limits(config)

        if max_age_seconds <= 0 or max_size_bytes <= 0:
            return read_data_frame_from_file_path(file_path, config, sync_context, protocol)

        cache_key = "|".join(
            [
                file_path.as_posix(),
                sync_context.statusAttribute or "",
                sync_context.priorityAttribute or "",
                sync_context.classAttribute or "",
            ]
        )
        current_mtime = file_path.stat().st_mtime

        with self._buffer_lock:
            self._purge_expired_entries(max_age_seconds)
            entry = self._buffer_catalog.get(cache_key)
            if entry and entry.file_mtime == current_mtime:
                entry.last_accessed_at = time.time()
                return entry.data_frame
            if entry and entry.file_mtime != current_mtime:
                logger.debug(
                    "Refreshing buffered dataframe '%s': source file modified.",
                    file_path,
                )

        df = read_data_frame_from_file_path(file_path, config, sync_context, protocol)
        if protocol is not None and protocol.generalErrors:
            return df
        size_bytes = int(df.memory_usage(index=True, deep=True).sum())
        now = time.time()

        with self._buffer_lock:
            existing_entry = self._buffer_catalog.get(cache_key)
            if existing_entry:
                self._buffer_size_bytes -= existing_entry.size_bytes

            self._buffer_catalog[cache_key] = DataFrameBufferEntry(
                data_frame=df,
                last_accessed_at=now,
                file_mtime=current_mtime,
                size_bytes=size_bytes,
            )
            self._buffer_size_bytes += size_bytes

            logger.info(
                "Buffered dataframe '%s' (%.2f MiB). Total buffer: %.2f MiB",
                file_path,
                size_bytes / (1024**2),
                self._buffer_size_bytes / (1024**2),
            )

            self._enforce_buffer_size_limit(max_size_bytes)
        return df

    def _purge_expired_entries(self, max_age_seconds: float) -> None:
        if max_age_seconds <= 0:
            return
        now = time.time()
        expired_keys = [
            key
            for key, entry in self._buffer_catalog.items()
            if now - entry.last_accessed_at >= max_age_seconds
        ]

        if not expired_keys:
            return

        for key in expired_keys:
            entry = self._buffer_catalog.pop(key)
            self._buffer_size_bytes -= entry.size_bytes

        logger.info(
            "Purged %d buffered dataframe(s). Total buffer: %.2f MiB",
            len(expired_keys),
            self._buffer_size_bytes / (1024**2),
        )

    def _get_buffer_limits(self, config: ExcelDefectClientConfig) -> tuple[float, int]:
        max_age_minutes = float(getattr(config, "buffer_max_age_minutes", 0) or 0)
        max_size_mib = float(getattr(config, "buffer_max_size_mib", 0) or 0)
        return max_age_minutes * 60, int(max_size_mib * 1024**2)

    def _get_file_path(self, project: str) -> Path:
        project_path = self.config.excel_file_path.joinpath(project)
        if not project_path.exists() or not project_path.is_dir():
            raise FileNotFoundError(
                f"Project '{project}' does not exist below '{self.config.excel_file_path}'."
            )

        expected_file_suffix = str(self._get_config_value("file_type", project) or "").lower()
        if not expected_file_suffix:
            raise FileNotFoundError(f"No file_type configured for project '{project}'.")

        for file in sorted(project_path.iterdir()):
            if file.is_file() and file.suffix.lower() == expected_file_suffix:
                return file
        raise FileNotFoundError(
            f"No '{expected_file_suffix}' file found for project '{project}' in '{project_path}'."
        )

    def get_defects_batch(
        self, project: str, defect_ids: list[DefectID], sync_context: SyncContext
    ) -> ProtocolledDefectSet:
        defects_result = self.get_defects(project, sync_context)
        requested_ids = {
            str(getattr(defect_id, "root", defect_id))
            for defect_id in defect_ids
            if getattr(defect_id, "root", defect_id)
        }
        defects = [defect for defect in defects_result.value if defect.id.root in requested_ids]
        found_ids = {defect.id.root for defect in defects}

        for missing_id in sorted(requested_ids - found_ids):
            defects_result.protocol.add_warning(
                key=missing_id,
                message=f"Defect '{missing_id}' was not found in project '{project}'.",
                protocol_code=ProtocolCode.DEFECT_NOT_FOUND,
            )

        return ProtocolledDefectSet(value=defects, protocol=defects_result.protocol)

    def create_defect(
        self, project: str, defect: Defect, sync_context: SyncContext
    ) -> ProtocolledString:

        protocol = Protocol()

        if self._get_config_value("readonly", project):
            protocol.add_error(
                project,
                "Excel client is configured as read-only.",
                protocol_code=ProtocolCode.INSERT_ACCESS_ERROR,
            )
            return ProtocolledString(value="", protocol=protocol)

        try:
            defect_path = self._get_file_path(project=project)
            effective_config = self._get_effective_config(project)
            header = read_header_columns_from_file_path(defect_path, effective_config)
            df = self._get_dataframe(defect_path, effective_config, sync_context, protocol)
        except FileNotFoundError as exc:
            protocol.add_general_error(str(exc), protocol_code=ProtocolCode.PROJECT_NOT_FOUND)
            return ProtocolledString(value="", protocol=protocol)
        except (OSError, ValueError) as exc:
            protocol.add_general_error(str(exc), protocol_code=ProtocolCode.READ_ACCESS_ERROR)
            return ProtocolledString(value="", protocol=protocol)

        if protocol.generalErrors:
            return ProtocolledString(value="", protocol=protocol)

        df_with_new_defect = self.add_defect_to_dataframe(defect, effective_config, df, protocol)
        new_defect_id = str(df_with_new_defect.iloc[-1]["id"])

        try:
            self.write_defect_data_to_excel(
                sync_context, defect_path, effective_config, header, df_with_new_defect
            )
        except (OSError, ValueError) as exc:
            protocol.add_general_error(str(exc), protocol_code=ProtocolCode.INSERT_ERROR)
            return ProtocolledString(value="", protocol=protocol)

        protocol.add_success(
            key=new_defect_id,
            message=f"Defect '{new_defect_id}' created successfully in project '{project}'.",
            protocol_code=ProtocolCode.INSERT_SUCCESS,
        )
        logger.info("Created Excel defect '%s' in project '%s'", new_defect_id, project)
        return ProtocolledString(value=new_defect_id, protocol=protocol)

    def write_defect_data_to_excel(
        self,
        sync_context: SyncContext,
        defect_path: Path,
        effective_config: ExcelDefectClientConfig,
        header: dict[int, str],
        df_with_new_defect: pd.DataFrame,
    ):
        column_positions = get_column_mapping_for_config(effective_config, sync_context)
        if not column_positions:
            return

        sheet_name = resolve_visible_sheet_name(defect_path, effective_config)

        with pd.ExcelWriter(defect_path, engine="openpyxl") as writer:
            for col_idx, col_names in column_positions.items():
                col_name = col_names[0]
                if col_name not in df_with_new_defect.columns:
                    continue
                original_header = header.get(col_idx + 1, col_name)

                # --- STEP 1: Write ONLY the Header ---
                header_only_df = (
                    df_with_new_defect[[col_name]]
                    .iloc[0:0]
                    .rename(columns={col_name: original_header})
                )
                header_only_df.to_excel(
                    writer,
                    sheet_name=sheet_name,
                    startcol=col_idx,
                    startrow=effective_config.defects_data_header_line - 1,
                    index=False,
                    header=True,
                )

                # --- STEP 2: Write ONLY the Values ---
                df_with_new_defect[[col_name]].to_excel(
                    writer,
                    sheet_name=sheet_name,
                    startcol=col_idx,
                    startrow=effective_config.defects_data_starting_line - 1,
                    index=False,
                    header=False,
                )

    def add_defect_to_dataframe(
        self,
        defect: Defect,
        effective_config: ExcelDefectClientConfig,
        df: pd.DataFrame,
        protocol: Protocol,
    ) -> pd.DataFrame:
        prefix = effective_config.id_prefix
        numeric_ids = [
            int(id_val.replace(prefix, ""))
            for id_val in df["id"]
            if id_val.startswith(prefix) and id_val[len(prefix) :].isdigit()
        ]
        max_int = (max(numeric_ids) if numeric_ids else 0) + 1

        defect_info_data_frame = pd.DataFrame(
            {
                "id": [effective_config.id_prefix + str(max_int)],
                "title": [defect.title],
                "description": [defect.description],
                "reporter": [defect.reporter],
                "status": [defect.status],
                "classification": [defect.classification],
                "priority": [defect.priority],
                "lastEdited": [self._format_last_edited(defect.lastEdited, effective_config)],
                "references": [
                    effective_config.references_seperator.join(
                        defect.references if defect.references else []
                    )
                ],
            }
        )

        if defect.userDefinedFields:
            for udf in defect.userDefinedFields:
                # TODO: check if is an udf which has to be stored
                defect_info_data_frame[udf.name] = udf.value

        return pd.concat([df, defect_info_data_frame], ignore_index=True)

    def update_defect(
        self, project: str, defect_id: str, defect: Defect, sync_context: SyncContext
    ) -> Protocol:
        del defect_id, defect, sync_context

        protocol = Protocol()
        if self._get_config_value("readonly", project):
            protocol.add_error(
                project,
                "Excel client is configured as read-only.",
                protocol_code=ProtocolCode.PUBLISH_ACCESS_ERROR,
            )
            return protocol

        protocol.add_general_error(
            "Excel write operations are not implemented.",
            protocol_code=ProtocolCode.PUBLISH_ERROR,
        )
        return protocol

    def delete_defect(
        self, project: str, defect_id: str, defect: Defect, sync_context: SyncContext
    ) -> Protocol:
        del defect_id, defect, sync_context

        protocol = Protocol()
        if self._get_config_value("readonly", project):
            protocol.add_error(
                project,
                "Excel client is configured as read-only.",
                protocol_code=ProtocolCode.PUBLISH_ACCESS_ERROR,
            )
            return protocol

        protocol.add_general_error(
            "Excel write operations are not implemented.",
            protocol_code=ProtocolCode.PUBLISH_ERROR,
        )
        return protocol

    def get_defect_extended(
        self, project: str, defect_id: str, sync_context: SyncContext
    ) -> DefectWithAttributes:
        defects = self.get_defects(project, sync_context)
        for defect in defects.value:
            if defect.id.root != defect_id:
                continue

            attributes = {
                field.name: field.value or ""
                for field in defect.userDefinedFields or []
                if field.value is not None
            }
            defect_data = defect.model_dump(mode="json")
            defect_data["attributes"] = ExtendedAttributes(**attributes)
            return DefectWithAttributes.model_validate(defect_data)

        raise NotFound(f"Defect '{defect_id}' not found in project '{project}'.")

    def get_user_defined_attributes(self, project: str | None) -> list[UserDefinedAttribute]:
        udfs: list[UserDefinedAttribute] = []
        for udf in self._get_config_value("udfs", project) or []:
            boolean_value = None
            string_value = udf.value
            if udf.type is ValueType.BOOLEAN and udf.value is not None:
                boolean_value = self._parse_boolean_udf_value(
                    udf.value,
                    udf.trueValue,
                    udf.falseValue,
                )
                string_value = None
            udfs.append(
                UserDefinedAttribute(
                    name=udf.name,
                    valueType=udf.type,
                    mustField=udf.required,
                    stringValue=string_value,
                    booleanValue=boolean_value,
                )
            )
        return udfs

    def before_sync(self, project: str, sync_type: str, sync_context: SyncContext) -> Protocol:
        del sync_type, sync_context

        protocol = Protocol()
        protocol.add_success(
            project,
            "Excel client does not require pre-sync actions.",
            protocol_code=ProtocolCode.PUBLISH_SUCCESS,
        )
        return protocol

    def after_sync(self, project: str, sync_type: str, sync_context: SyncContext) -> Protocol:
        del sync_type, sync_context

        protocol = Protocol()
        protocol.add_success(
            project,
            "Excel client does not require post-sync actions.",
            protocol_code=ProtocolCode.PUBLISH_SUCCESS,
        )
        return protocol

    def supports_changes_timestamps(self) -> bool:
        return self.config.lastedit_column_no > 0

    def correct_sync_results(self, project: str, body: Results) -> Results:
        del project
        return body

    def _get_config_value(self, attr: str, project: str | None = None) -> Any:
        """
        Retrieve a configuration value, optionally project-specific, falling back to global config.
        Args:
            attr (str): The attribute name to retrieve.
            project (str | None): The project name, if any.
        Returns:
            The value of the attribute, or None if not found.
        """
        if project and project in self.config.projects:
            project_config = self.config.projects[project]
            value = getattr(project_config, attr, None)
            if value is not None:
                logger.debug("Using project-specific config for '%s.%s'", project, attr)
                return value  # type: ignore
        logger.debug("Using global config for '%s'", attr)
        return getattr(self.config, attr, None)  # type: ignore

    def _get_buffer_cleanup_interval_seconds(self, config: ExcelDefectClientConfig) -> float:
        return float(getattr(config, "buffer_cleanup_interval_minutes", 0) or 0) * 60

    def _start_buffer_cleanup_thread(self) -> None:
        interval_seconds = self._get_buffer_cleanup_interval_seconds(self.config)
        max_age_seconds, _ = self._get_buffer_limits(self.config)

        if interval_seconds <= 0 or max_age_seconds <= 0:
            return

        def _cleanup_loop() -> None:
            while True:
                time.sleep(interval_seconds)
                try:
                    with self._buffer_lock:
                        self._purge_expired_entries(max_age_seconds)
                except Exception as exc:
                    logger.warning("Buffer cleanup task failed: %s", exc)

        thread = threading.Thread(target=_cleanup_loop, name="excel-buffer-cleanup", daemon=True)
        thread.start()

    def _get_effective_config(self, project: str | None) -> ExcelDefectClientConfig:
        if not project or project not in self.config.projects:
            return self.config

        merged_config = self.config.model_dump()
        merged_config.update(self.config.projects[project].model_dump(exclude_none=True))
        merged_config["projects"] = self.config.projects
        return ExcelDefectClientConfig.model_validate(merged_config)

    def _build_defects_from_dataframe(
        self,
        df: pd.DataFrame,
        config: ExcelDefectClientConfig,
        protocol: Protocol,
    ) -> list[DefectWithID]:
        defects: list[DefectWithID] = []
        first_data_row = config.defects_data_starting_line

        for row_offset, (_, row) in enumerate(df.iterrows()):
            row_number = first_data_row + row_offset
            defect_id = self._row_value(row, "id")
            if not defect_id:
                protocol.add_error(
                    key=str(row_number),
                    message=f"Skipping row {row_number}: missing defect id.",
                    protocol_code=ProtocolCode.IMPORT_ERROR,
                )
                continue

            try:
                defects.append(self._build_defect_from_row(row, config, protocol))
            except Exception as exc:
                logger.warning(
                    "Skipping invalid Excel defect '%s' at row %d: %s",
                    defect_id,
                    row_number,
                    exc,
                )
                protocol.add_error(
                    key=defect_id,
                    message=f"Skipping defect '{defect_id}' at row {row_number}: {exc}",
                    protocol_code=ProtocolCode.IMPORT_ERROR,
                )

        return defects

    def _build_defect_from_row(
        self,
        row: pd.Series,
        config: ExcelDefectClientConfig,
        protocol: Protocol,
    ) -> DefectWithID:
        defect_id = self._row_value(row, "id")
        return DefectWithID(
            id=DefectID(root=defect_id),
            title=self._optional_row_value(row, "title"),
            description=self._optional_row_value(row, "description"),
            reporter=self._optional_row_value(row, "reporter"),
            status=self._row_value(row, "status"),
            classification=self._row_value(row, "classification"),
            priority=self._row_value(row, "priority"),
            userDefinedFields=self._build_user_defined_fields(row, config),
            lastEdited=self._parse_last_edited(
                self._row_value(row, "lastEdited"),
                config,
                defect_id,
                protocol,
            ),
            references=self._split_references(self._row_value(row, "references"), config),
            principal=Login(username="", password=""),
        )

    def _build_user_defined_fields(
        self,
        row: pd.Series,
        config: ExcelDefectClientConfig,
    ) -> list[UserDefinedFieldProperties]:
        result: list[UserDefinedFieldProperties] = []
        for udf in config.udfs:
            has_column_value = udf.name in row.index
            value = self._row_value(row, udf.name) if has_column_value else udf.value
            if not has_column_value and value is None:
                continue
            result.append(
                UserDefinedFieldProperties(
                    name=udf.name,
                    value=value,
                    mustField=udf.required,
                )
            )
        return result

    def _enforce_buffer_size_limit(self, max_size_bytes: int) -> None:
        if max_size_bytes <= 0 or self._buffer_size_bytes <= max_size_bytes:
            return

        target_size_bytes = int(max_size_bytes * 0.8)
        removed = 0

        for key, entry in sorted(
            self._buffer_catalog.items(), key=lambda item: item[1].last_accessed_at
        ):
            if self._buffer_size_bytes <= target_size_bytes:
                break
            self._buffer_catalog.pop(key)
            self._buffer_size_bytes -= entry.size_bytes
            removed += 1

        if removed:
            logger.info(
                "Evicted %d buffered dataframe(s) to enforce size limit. Total buffer: %.2f MiB",
                removed,
                self._buffer_size_bytes / (1024**2),
            )

    def _format_last_edited(
        self,
        value: datetime | None,
        config: ExcelDefectClientConfig,
    ) -> str:
        if value is None:
            return ""
        format_string = self._to_python_datetime_format(config.simple_date_format)
        if format_string:
            return value.strftime(format_string)
        return value.isoformat()

    def _parse_last_edited(
        self,
        raw_value: str,
        config: ExcelDefectClientConfig,
        defect_id: str,
        protocol: Protocol,
    ) -> datetime:
        if not raw_value:
            protocol.add_warning(
                key=defect_id,
                message="Missing lastEdited value; using the current UTC timestamp.",
                protocol_code=ProtocolCode.IMPORT_WARNING,
            )
            return datetime.now(timezone.utc)

        format_string = self._to_python_datetime_format(config.simple_date_format)
        format_mismatch_detected = False
        if format_string:
            try:
                return pd.to_datetime(
                    raw_value,
                    format=format_string,
                    utc=True,
                ).to_pydatetime()
            except ValueError:
                format_mismatch_detected = True
                logger.debug(
                    "Could not parse '%s' with configured Excel date format '%s'.",
                    raw_value,
                    config.simple_date_format,
                )

        parsed_fallback = pd.to_datetime(raw_value, errors="coerce", utc=False)
        if not pd.isna(parsed_fallback):
            if format_mismatch_detected:
                self._add_general_warning_once(
                    protocol,
                    (
                        f"Configured Excel date format '{config.simple_date_format}' did not "
                        "match one or more lastEdited values. Automatic date parsing was used."
                    ),
                    ProtocolCode.IMPORT_WARNING,
                )
            parsed_dt = parsed_fallback.to_pydatetime()
            if parsed_dt.tzinfo is None:
                parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
            return parsed_dt.astimezone(timezone.utc)

        protocol.add_warning(
            key=defect_id,
            message=(f"Invalid lastEdited value '{raw_value}'; using the current UTC timestamp."),
            protocol_code=ProtocolCode.IMPORT_WARNING,
        )
        return datetime.now(timezone.utc)

    @staticmethod
    def _to_python_datetime_format(simple_date_format: str | None) -> str | None:
        if not simple_date_format:
            return None

        python_format = simple_date_format
        python_format = python_format.replace("yyyy", "%Y")
        python_format = python_format.replace("yy", "%y")
        python_format = python_format.replace("dd", "%d")
        python_format = python_format.replace("HH", "%H")
        python_format = python_format.replace("hh", "%I")
        python_format = python_format.replace("ss", "%S")
        python_format = python_format.replace("MM", "%m")
        if "HH" in simple_date_format or "hh" in simple_date_format:
            python_format = python_format.replace("mm", "%M")
        else:
            python_format = python_format.replace("mm", "%m")
        return python_format

    @staticmethod
    def _row_value(row: pd.Series, field_name: str) -> str:
        if field_name not in row.index:
            return ""
        value = row[field_name]
        return "" if value is None else str(value).strip()

    def _optional_row_value(self, row: pd.Series, field_name: str) -> str | None:
        value = self._row_value(row, field_name)
        return value or None

    @staticmethod
    def _split_references(raw_value: str, config: ExcelDefectClientConfig) -> list[str]:
        separator = config.references_seperator or ";"
        if not raw_value:
            return []
        return [part.strip() for part in raw_value.split(separator) if part.strip()]

    @staticmethod
    def _parse_boolean_udf_value(
        raw_value: str,
        true_value: str | None,
        false_value: str | None,
    ) -> bool | None:
        normalized = raw_value.strip().lower()
        normalized_true = (true_value or "true").strip().lower()
        normalized_false = (false_value or "false").strip().lower()

        if normalized == normalized_true:
            return True
        if normalized == normalized_false:
            return False
        return None

    @staticmethod
    def _add_general_warning_once(
        protocol: Protocol,
        message: str,
        protocol_code: ProtocolCode,
    ) -> None:
        existing_warnings = protocol.generalWarnings or []
        if any(
            entry.message == message and entry.code == protocol_code for entry in existing_warnings
        ):
            return
        protocol.add_general_warning(message, protocol_code=protocol_code)

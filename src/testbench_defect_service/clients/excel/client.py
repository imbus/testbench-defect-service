import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pandas as pd

from testbench_defect_service.clients.abstract_client import AbstractDefectClient
from testbench_defect_service.clients.excel.config import ExcelDefectClientConfig
from testbench_defect_service.clients.excel.file_utils import (
    read_data_frame_from_file_path,
    write_defect_data_to_csv,
    write_defect_data_to_excel,
)
from testbench_defect_service.clients.excel.utils import (
    add_defect_to_dataframe,
    add_general_warning_once,
    check_defect_transitions,
    create_defect_data_frame,
    optional_row_value,
    parse_boolean_udf_value,
    read_header_columns_from_file_path,
    row_value,
    split_references,
    to_python_datetime_format,
    validate_control_fields,
)
from testbench_defect_service.log import logger
from testbench_defect_service.models.defects import (
    Defect,
    DefectFieldSyncOption,
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
        logger.debug("Checking login for project '%s'", project)
        if project is None:
            return self.config.excel_file_path.exists()

        try:
            self._get_file_path(project)
        except FileNotFoundError:
            logger.debug("Login check failed: project '%s' not found", project)
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
            logger.debug(
                "Excel base path '%s' does not exist; returning empty project list",
                self.config.excel_file_path,
            )
            return []
        projects = sorted(p.name for p in self.config.excel_file_path.iterdir() if p.is_dir())
        logger.debug("Found %d project(s) under '%s'", len(projects), self.config.excel_file_path)
        return projects

    def get_control_fields(self, project: str | None) -> dict[str, list[str]]:
        control_fields = {}
        for field in self._get_config_value("control_fields", project) or []:
            control_fields[field.name] = field.values
        logger.debug("Returning %d control field(s) for project '%s'", len(control_fields), project)
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

        defects = self._build_defects_from_dataframe(df, effective_config, sync_context, protocol)
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
                logger.debug("Resolved Excel file for project '%s': '%s'", project, file)
                return file
        raise FileNotFoundError(
            f"No '{expected_file_suffix}' file found for project '{project}' in '{project_path}'."
        )

    def get_defects_batch(
        self, project: str, defect_ids: list[DefectID], sync_context: SyncContext
    ) -> ProtocolledDefectSet:
        logger.debug(
            "Fetching batch of %d defect(s) by ID for project '%s'",
            len(defect_ids),
            project,
        )
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

    def create_defect(  # noqa: PLR0911
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

        effective_config = self._get_effective_config(project)
        if not validate_control_fields(defect, effective_config, sync_context, protocol):
            return ProtocolledString(value="", protocol=protocol)

        try:
            defect_path = self._get_file_path(project=project)
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

        df_with_new_defect = add_defect_to_dataframe(defect, effective_config, df, protocol)
        new_defect_id = str(df_with_new_defect.iloc[-1]["id"])

        try:
            if effective_config.file_type in [".xlsx", ".xls"]:
                write_defect_data_to_excel(
                    sync_context, defect_path, effective_config, header, df_with_new_defect
                )
            if effective_config.file_type in [".csv", ".txt"]:
                write_defect_data_to_csv(
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

    def update_defect(  # noqa: PLR0911
        self, project: str, defect_id: str, defect: Defect, sync_context: SyncContext
    ) -> Protocol:
        logger.debug("Updating defect '%s' in project '%s'", defect_id, project)
        protocol = Protocol()

        if self._get_config_value("readonly", project):
            protocol.add_error(
                defect_id,
                "Excel client is configured as read-only.",
                protocol_code=ProtocolCode.INSERT_ACCESS_ERROR,
            )
            return protocol

        effective_config = self._get_effective_config(project)
        if not validate_control_fields(defect, effective_config, sync_context, protocol):
            return protocol

        try:
            defect_path = self._get_file_path(project=project)
            header = read_header_columns_from_file_path(defect_path, effective_config)
            df = self._get_dataframe(defect_path, effective_config, sync_context, protocol)
        except FileNotFoundError as exc:
            protocol.add_general_error(str(exc), protocol_code=ProtocolCode.PROJECT_NOT_FOUND)
            return protocol
        except (OSError, ValueError) as exc:
            protocol.add_general_error(str(exc), protocol_code=ProtocolCode.READ_ACCESS_ERROR)
            return protocol

        row_idx = df.index[df["id"] == defect_id]
        if row_idx.empty:
            protocol.add_error(
                defect_id,
                f"Defect '{defect_id}' not found in project '{project}'.",
                protocol_code=ProtocolCode.DEFECT_NOT_FOUND,
            )
            logger.warning(
                "Update failed: defect '%s' not found in project '%s'", defect_id, project
            )
            return protocol

        if not check_defect_transitions(defect, df, effective_config, protocol):
            return protocol
        new_row_df = create_defect_data_frame(defect, effective_config, defect_id, protocol)
        new_row_df.index = row_idx
        df.update(new_row_df)

        try:
            if effective_config.file_type in [".xlsx", ".xls"]:
                write_defect_data_to_excel(sync_context, defect_path, effective_config, header, df)
            if effective_config.file_type in [".csv", ".txt"]:
                write_defect_data_to_csv(sync_context, defect_path, effective_config, header, df)
        except (OSError, ValueError) as exc:
            protocol.add_error(defect_id, str(exc), protocol_code=ProtocolCode.UPDATE_ERROR)
            logger.error(
                "Failed to update defect '%s' in project '%s': %s", defect_id, project, exc
            )
            return protocol

        protocol.add_success(
            key=defect_id,
            message=f"Defect '{defect_id}' updated successfully in project '{project}'.",
            protocol_code=ProtocolCode.UPDATE_SUCCESS,
        )
        logger.info("Updated Excel defect '%s' in project '%s'", defect_id, project)
        return protocol

    def delete_defect(
        self, project: str, defect_id: str, defect: Defect, sync_context: SyncContext
    ) -> Protocol:
        logger.debug("Deleting defect '%s' from project '%s'", defect_id, project)
        protocol = Protocol()
        if self._get_config_value("readonly", project):
            protocol.add_error(
                defect_id,
                "Excel client is configured as read-only.",
                protocol_code=ProtocolCode.INSERT_ACCESS_ERROR,
            )
            return protocol

        try:
            defect_path = self._get_file_path(project=project)
            effective_config = self._get_effective_config(project)
            header = read_header_columns_from_file_path(defect_path, effective_config)
            df = self._get_dataframe(defect_path, effective_config, sync_context, protocol)
        except FileNotFoundError as exc:
            protocol.add_general_error(str(exc), protocol_code=ProtocolCode.PROJECT_NOT_FOUND)
            return protocol
        except (OSError, ValueError) as exc:
            protocol.add_general_error(str(exc), protocol_code=ProtocolCode.READ_ACCESS_ERROR)
            return protocol

        row_idx = df.index[df["id"] == defect_id]
        if row_idx.empty:
            protocol.add_error(
                defect_id,
                f"Defect '{defect_id}' not found in project '{project}'.",
                protocol_code=ProtocolCode.DEFECT_NOT_FOUND,
            )
            logger.warning(
                "Delete failed: defect '%s' not found in project '%s'", defect_id, project
            )
            return protocol

        df = df.drop(index=row_idx)

        try:
            if effective_config.file_type in [".xlsx", ".xls"]:
                write_defect_data_to_excel(sync_context, defect_path, effective_config, header, df)
            if effective_config.file_type in [".csv", ".txt"]:
                write_defect_data_to_csv(sync_context, defect_path, effective_config, header, df)
        except (OSError, ValueError) as exc:
            protocol.add_general_error(str(exc), protocol_code=ProtocolCode.PUBLISH_ERROR)
            logger.error(
                "Failed to delete defect '%s' from project '%s': %s", defect_id, project, exc
            )
            return protocol

        protocol.add_success(
            key=defect_id,
            message=f"Defect '{defect_id}' deleted successfully from project '{project}'.",
            protocol_code=ProtocolCode.PUBLISH_SUCCESS,
        )
        logger.info("Deleted Excel defect '%s' from project '%s'", defect_id, project)
        return protocol

    def get_defect_extended(
        self, project: str, defect_id: str, sync_context: SyncContext
    ) -> DefectWithAttributes:
        try:
            defect_path = self._get_file_path(project=project)
            effective_config = self._get_effective_config(project)
            df = self._get_dataframe(defect_path, effective_config, sync_context)
        except FileNotFoundError as exc:
            raise FileNotFoundError from exc
        except (OSError, ValueError) as exc:
            raise Exception from exc

        single_defect_df = df.loc[df["id"] == defect_id]
        defect = self._build_defects_from_dataframe(
            single_defect_df, effective_config, sync_context
        )[0]

        return self._build_defect_with_attributes(defect, project, single_defect_df)

    def _build_defect_with_attributes(
        self,
        defect: DefectWithID,
        project: str,
        df: pd.DataFrame,
    ) -> DefectWithAttributes:
        data = defect.model_dump()
        attribute_fields = self._get_config_value("attributes", project=project) or []
        attributes = {}
        for col in df.columns:
            if col in attribute_fields:
                attributes.update({col: df[col].iloc[0]})

        data["attributes"] = ExtendedAttributes(**attributes)
        return DefectWithAttributes.model_validate(data)

    def get_user_defined_attributes(self, project: str | None) -> list[UserDefinedAttribute]:
        udfs: list[UserDefinedAttribute] = []
        for udf in self._get_config_value("udfs", project) or []:
            boolean_value = None
            string_value = udf.value
            if udf.type is ValueType.BOOLEAN and udf.value is not None:
                boolean_value = parse_boolean_udf_value(
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
        # TODO: implement
        logger.debug("before_sync called for project '%s' (sync_type: '%s')", project, sync_type)
        del sync_type, sync_context

        protocol = Protocol()
        protocol.add_success(
            project,
            "Excel client does not require pre-sync actions.",
            protocol_code=ProtocolCode.PUBLISH_SUCCESS,
        )
        return protocol

    def after_sync(self, project: str, sync_type: str, sync_context: SyncContext) -> Protocol:
        # TODO: implement
        logger.debug("after_sync called for project '%s' (sync_type: '%s')", project, sync_type)
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
        # TODO: implement
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
        logger.info(
            "Started Excel buffer cleanup thread (interval: %.0f s, max age: %.0f s)",
            interval_seconds,
            max_age_seconds,
        )

    def _get_effective_config(self, project: str | None) -> ExcelDefectClientConfig:
        if not project or project not in self.config.projects:
            logger.debug("Using global config for project '%s'", project)
            return self.config

        logger.debug("Merging project-specific config for project '%s'", project)
        merged_config = self.config.model_dump()
        merged_config.update(self.config.projects[project].model_dump(exclude_none=True))
        merged_config["projects"] = self.config.projects
        return ExcelDefectClientConfig.model_validate(merged_config)

    def _build_defects_from_dataframe(
        self,
        df: pd.DataFrame,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
        protocol: Protocol | None = None,
    ) -> list[DefectWithID]:
        defects: list[DefectWithID] = []
        first_data_row = config.defects_data_starting_line

        for row_offset, (_, row) in enumerate(df.iterrows()):
            row_number = first_data_row + row_offset
            defect_id = row_value(row, "id")
            if not defect_id:
                if protocol:
                    protocol.add_error(
                        key=str(row_number),
                        message=f"Skipping row {row_number}: missing defect id.",
                        protocol_code=ProtocolCode.IMPORT_ERROR,
                    )
                continue

            try:
                defects.append(self._build_defect_from_row(row, config, sync_context, protocol))
            except Exception as exc:
                logger.warning(
                    "Skipping invalid Excel defect '%s' at row %d: %s",
                    defect_id,
                    row_number,
                    exc,
                )
                if protocol:
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
        sync_context: SyncContext,
        protocol: Protocol | None = None,
    ) -> DefectWithID:
        defect_id = row_value(row, "id")
        return DefectWithID(
            id=DefectID(root=defect_id),
            title=optional_row_value(row, "title"),
            description=optional_row_value(row, "description"),
            reporter=optional_row_value(row, "reporter"),
            status=row_value(row, "status"),
            classification=row_value(row, "classification"),
            priority=row_value(row, "priority"),
            userDefinedFields=self._build_user_defined_fields(
                row, config, sync_context.udaSyncOptions or {}
            ),
            lastEdited=self._parse_last_edited(
                row_value(row, "lastEdited"),
                config,
                defect_id,
                protocol,
            ),
            references=split_references(row_value(row, "references"), config),
            principal=Login(username="", password=""),
        )

    def _build_user_defined_fields(
        self,
        row: pd.Series,
        config: ExcelDefectClientConfig,
        sync_options: dict[str, DefectFieldSyncOption],
    ) -> list[UserDefinedFieldProperties]:
        result: list[UserDefinedFieldProperties] = []
        for udf in config.udfs:
            if udf.name not in sync_options:
                continue
            has_column_value = udf.name in row.index
            value = row_value(row, udf.name) if has_column_value else udf.value
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

    def _parse_last_edited(
        self,
        raw_value: str,
        config: ExcelDefectClientConfig,
        defect_id: str,
        protocol: Protocol | None = None,
    ) -> datetime:
        if not raw_value:
            if protocol:
                protocol.add_warning(
                    key=defect_id,
                    message="Missing lastEdited value; using the current UTC timestamp.",
                    protocol_code=ProtocolCode.IMPORT_WARNING,
                )
            return datetime.now(timezone.utc)

        format_string = to_python_datetime_format(config.simple_date_format)
        format_mismatch_detected = False
        if format_string:
            try:
                return cast(
                    datetime,
                    pd.to_datetime(
                        raw_value,
                        format=format_string,
                        utc=True,
                    ).to_pydatetime(),
                )
            except ValueError:
                format_mismatch_detected = True
                logger.debug(
                    "Could not parse '%s' with configured Excel date format '%s'.",
                    raw_value,
                    config.simple_date_format,
                )

        parsed_fallback = pd.to_datetime(raw_value, errors="coerce", utc=False)
        if not pd.isna(parsed_fallback):
            if format_mismatch_detected and protocol:
                add_general_warning_once(
                    protocol,
                    (
                        f"Configured Excel date format '{config.simple_date_format}' did not "
                        "match one or more lastEdited values. Automatic date parsing was used."
                    ),
                    ProtocolCode.IMPORT_WARNING,
                )
            parsed_dt = cast(datetime, parsed_fallback.to_pydatetime())
            if parsed_dt.tzinfo is None:
                parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
            return parsed_dt.astimezone(timezone.utc)

        if protocol:
            protocol.add_warning(
                key=defect_id,
                message=(
                    f"Invalid lastEdited value '{raw_value}'; using the current UTC timestamp."
                ),
                protocol_code=ProtocolCode.IMPORT_WARNING,
            )
        return datetime.now(timezone.utc)

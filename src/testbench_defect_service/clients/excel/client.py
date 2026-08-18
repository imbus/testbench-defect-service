import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pandas as pd
from pydantic import ValidationError
from sanic import NotFound, ServerError

from testbench_defect_service.clients.abstract_client import AbstractDefectClient
from testbench_defect_service.clients.excel.config import ExcelDefectClientConfig, ProjectConfig
from testbench_defect_service.clients.excel.file_utils import (
    read_data_frame_from_file_path,
    write_defect_data,
)
from testbench_defect_service.clients.excel.locking import lock_defect_file
from testbench_defect_service.clients.excel.utils import (
    add_defect_to_dataframe,
    add_general_warning_once,
    check_defect_transitions,
    create_defect_data_frame,
    describe_ambiguous_id,
    describe_duplicated_id_rows,
    describe_write_error,
    duplicated_ids,
    is_blank_row,
    optional_row_value,
    parse_boolean_udf_value,
    read_header_columns_from_file_path,
    row_value,
    split_references,
    to_python_datetime_format,
    validate_control_fields,
)
from testbench_defect_service.clients.utils import (
    execute_sync_hook,
    load_properties_config_from_path,
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


@dataclass(frozen=True)
class DefectFileTarget:
    """The file one mutation operates on, together with the config that addresses it."""

    project: str
    path: Path
    config: ExcelDefectClientConfig


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

        defects = self._build_defects_from_dataframe(
            df, effective_config, sync_context, protocol, file_name=defect_path.name
        )
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

    def _resolve_target(self, project: str, config: ExcelDefectClientConfig) -> DefectFileTarget:
        return DefectFileTarget(
            project=project,
            path=self._get_file_path(project=project),
            config=config,
        )

    def _read_dataframe_from_disk(
        self,
        target: DefectFileTarget,
        sync_context: SyncContext,
        protocol: Protocol | None = None,
    ) -> pd.DataFrame:
        """Read the file as it stands on disk right now.

        A mutation derives the next defect id, and the row it rewrites, from this frame. A
        buffered frame would be a frame another writer has already superseded, and the buffer
        only notices that through st_mtime - too coarse to rely on over a network share.
        """
        self._invalidate_buffer(target.path)
        return self._get_dataframe(target.path, target.config, sync_context, protocol)

    def _invalidate_buffer(self, file_path: Path) -> None:
        """Drop every buffered frame for this file, whichever sync context produced it."""
        key_prefix = f"{file_path.as_posix()}|"
        with self._buffer_lock:
            stale_keys = [key for key in self._buffer_catalog if key.startswith(key_prefix)]
            for key in stale_keys:
                entry = self._buffer_catalog.pop(key)
                self._buffer_size_bytes -= entry.size_bytes

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

    def _resolve_project_path(self, project: str) -> Path:
        """Resolve a project directory and ensure it stays below the configured Excel path."""
        base_path = self.config.excel_file_path.resolve()
        project_path = (self.config.excel_file_path / project).resolve()
        if not project_path.is_relative_to(base_path):
            logger.warning("Rejected project name '%s': resolves outside '%s'", project, base_path)
            raise FileNotFoundError(
                f"Project '{project}' does not exist below '{self.config.excel_file_path}'."
            )
        return project_path

    def _get_file_path(self, project: str) -> Path:
        project_path = self._resolve_project_path(project)
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
            return ProtocolledString(value=None, protocol=protocol)

        effective_config = self._get_effective_config(project)
        if not validate_control_fields(defect, effective_config, sync_context, protocol):
            return ProtocolledString(value=None, protocol=protocol)

        try:
            target = self._resolve_target(project, effective_config)
        except FileNotFoundError as exc:
            protocol.add_general_error(str(exc), protocol_code=ProtocolCode.PROJECT_NOT_FOUND)
            return ProtocolledString(value=None, protocol=protocol)

        try:
            with lock_defect_file(target.path):
                return self._create_defect_in_locked_file(target, defect, sync_context, protocol)
        except TimeoutError as exc:
            logger.error("Failed to create defect in project '%s': %s", project, exc)
            protocol.add_general_error(str(exc), protocol_code=ProtocolCode.INSERT_ERROR)
            return ProtocolledString(value=None, protocol=protocol)

    def _create_defect_in_locked_file(
        self,
        target: DefectFileTarget,
        defect: Defect,
        sync_context: SyncContext,
        protocol: Protocol,
    ) -> ProtocolledString:
        try:
            header = read_header_columns_from_file_path(target.path, target.config)
            df = self._read_dataframe_from_disk(target, sync_context, protocol)
        except (OSError, ValueError) as exc:
            protocol.add_general_error(str(exc), protocol_code=ProtocolCode.READ_ACCESS_ERROR)
            return ProtocolledString(value=None, protocol=protocol)

        if protocol.generalErrors:
            return ProtocolledString(value=None, protocol=protocol)

        df_with_new_defect = add_defect_to_dataframe(defect, target.config, df, protocol)
        new_defect_id = str(df_with_new_defect.iloc[-1]["id"])

        try:
            write_defect_data(sync_context, target.path, target.config, header, df_with_new_defect)
        except (OSError, ValueError) as exc:
            message = describe_write_error(exc, target.path)
            protocol.add_general_error(message, protocol_code=ProtocolCode.INSERT_ERROR)
            logger.error("Failed to create defect in project '%s': %s", target.project, exc)
            return ProtocolledString(value=None, protocol=protocol)

        self._invalidate_buffer(target.path)
        protocol.add_success(
            key=new_defect_id,
            message=(
                f"Defect '{new_defect_id}' created successfully in project '{target.project}'."
            ),
            protocol_code=ProtocolCode.INSERT_SUCCESS,
        )
        logger.info("Created Excel defect '%s' in project '%s'", new_defect_id, target.project)
        return ProtocolledString(value=new_defect_id, protocol=protocol)

    def update_defect(
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
            target = self._resolve_target(project, effective_config)
        except FileNotFoundError as exc:
            protocol.add_general_error(str(exc), protocol_code=ProtocolCode.PROJECT_NOT_FOUND)
            return protocol

        try:
            with lock_defect_file(target.path):
                return self._update_defect_in_locked_file(
                    target, defect_id, defect, sync_context, protocol
                )
        except TimeoutError as exc:
            logger.error(
                "Failed to update defect '%s' in project '%s': %s", defect_id, project, exc
            )
            protocol.add_error(defect_id, str(exc), protocol_code=ProtocolCode.PUBLISH_ERROR)
            return protocol

    def _update_defect_in_locked_file(
        self,
        target: DefectFileTarget,
        defect_id: str,
        defect: Defect,
        sync_context: SyncContext,
        protocol: Protocol,
    ) -> Protocol:
        try:
            header = read_header_columns_from_file_path(target.path, target.config)
            df = self._read_dataframe_from_disk(target, sync_context, protocol)
        except (OSError, ValueError) as exc:
            protocol.add_general_error(str(exc), protocol_code=ProtocolCode.READ_ACCESS_ERROR)
            return protocol

        row_idx = df.index[df["id"] == defect_id]
        if row_idx.empty:
            protocol.add_error(
                defect_id,
                f"Defect '{defect_id}' not found in project '{target.project}'.",
                protocol_code=ProtocolCode.DEFECT_NOT_FOUND,
            )
            logger.warning(
                "Update failed: defect '%s' not found in project '%s'", defect_id, target.project
            )
            return protocol

        if len(row_idx) > 1:
            protocol.add_error(
                defect_id,
                f"Cannot update defect '{defect_id}': "
                f"{describe_ambiguous_id(df, target.config, defect_id)}",
                protocol_code=ProtocolCode.PUBLISH_ERROR,
            )
            logger.warning(
                "Update refused: defect '%s' is used by %d rows in project '%s'",
                defect_id,
                len(row_idx),
                target.project,
            )
            return protocol

        if not check_defect_transitions(
            defect, df.loc[row_idx], target.config, sync_context, protocol
        ):
            return protocol
        new_row_df = create_defect_data_frame(defect, target.config, defect_id, protocol)
        new_row_df.index = row_idx
        updated_df = df.copy()
        updated_df.update(new_row_df)

        try:
            write_defect_data(sync_context, target.path, target.config, header, updated_df)
        except (OSError, ValueError) as exc:
            message = describe_write_error(exc, target.path)
            protocol.add_error(defect_id, message, protocol_code=ProtocolCode.PUBLISH_ERROR)
            logger.error(
                "Failed to update defect '%s' in project '%s': %s", defect_id, target.project, exc
            )
            return protocol

        self._invalidate_buffer(target.path)
        protocol.add_success(
            key=defect_id,
            message=f"Defect '{defect_id}' updated successfully in project '{target.project}'.",
            protocol_code=ProtocolCode.UPDATE_SUCCESS,
        )
        logger.info("Updated Excel defect '%s' in project '%s'", defect_id, target.project)
        return protocol

    def delete_defect(
        self, project: str, defect_id: str, defect: Defect, sync_context: SyncContext
    ) -> Protocol:
        logger.debug("Deleting defect '%s' from project '%s'", defect_id, project)
        del defect
        protocol = Protocol()
        if self._get_config_value("readonly", project):
            protocol.add_error(
                defect_id,
                "Excel client is configured as read-only.",
                protocol_code=ProtocolCode.INSERT_ACCESS_ERROR,
            )
            return protocol

        try:
            target = self._resolve_target(project, self._get_effective_config(project))
        except FileNotFoundError as exc:
            protocol.add_general_error(str(exc), protocol_code=ProtocolCode.PROJECT_NOT_FOUND)
            return protocol

        try:
            with lock_defect_file(target.path):
                return self._delete_defect_in_locked_file(target, defect_id, sync_context, protocol)
        except TimeoutError as exc:
            logger.error(
                "Failed to delete defect '%s' from project '%s': %s", defect_id, project, exc
            )
            protocol.add_general_error(str(exc), protocol_code=ProtocolCode.PUBLISH_ERROR)
            return protocol

    def _delete_defect_in_locked_file(
        self,
        target: DefectFileTarget,
        defect_id: str,
        sync_context: SyncContext,
        protocol: Protocol,
    ) -> Protocol:
        try:
            header = read_header_columns_from_file_path(target.path, target.config)
            df = self._read_dataframe_from_disk(target, sync_context, protocol)
        except (OSError, ValueError) as exc:
            protocol.add_general_error(str(exc), protocol_code=ProtocolCode.READ_ACCESS_ERROR)
            return protocol

        row_idx = df.index[df["id"] == defect_id]
        if row_idx.empty:
            protocol.add_error(
                defect_id,
                f"Defect '{defect_id}' not found in project '{target.project}'.",
                protocol_code=ProtocolCode.DEFECT_NOT_FOUND,
            )
            logger.warning(
                "Delete failed: defect '%s' not found in project '%s'", defect_id, target.project
            )
            return protocol

        if len(row_idx) > 1:
            # Dropping every match would delete rows the user never asked about.
            protocol.add_error(
                defect_id,
                f"Cannot delete defect '{defect_id}': "
                f"{describe_ambiguous_id(df, target.config, defect_id)}",
                protocol_code=ProtocolCode.PUBLISH_ERROR,
            )
            logger.warning(
                "Delete refused: defect '%s' is used by %d rows in project '%s'",
                defect_id,
                len(row_idx),
                target.project,
            )
            return protocol

        df = df.drop(index=row_idx)

        try:
            write_defect_data(sync_context, target.path, target.config, header, df)
        except (OSError, ValueError) as exc:
            message = describe_write_error(exc, target.path)
            protocol.add_general_error(message, protocol_code=ProtocolCode.PUBLISH_ERROR)
            logger.error(
                "Failed to delete defect '%s' from project '%s': %s",
                defect_id,
                target.project,
                exc,
            )
            return protocol

        self._invalidate_buffer(target.path)
        protocol.add_success(
            key=defect_id,
            message=(f"Defect '{defect_id}' deleted successfully from project '{target.project}'."),
            protocol_code=ProtocolCode.PUBLISH_SUCCESS,
        )
        logger.info("Deleted Excel defect '%s' from project '%s'", defect_id, target.project)
        return protocol

    def get_defect_extended(
        self, project: str, defect_id: str, sync_context: SyncContext
    ) -> DefectWithAttributes:
        try:
            defect_path = self._get_file_path(project=project)
            effective_config = self._get_effective_config(project)
            df = self._get_dataframe(defect_path, effective_config, sync_context)
        except FileNotFoundError as exc:
            raise NotFound(str(exc)) from exc
        except (OSError, ValueError) as exc:
            logger.error("Failed to read defect '%s' for project '%s': %s", defect_id, project, exc)
            raise ServerError(
                f"Unable to read defect '{defect_id}' for project '{project}': {exc}"
            ) from exc

        single_defect_df = df.loc[df["id"] == defect_id]
        defects = self._build_defects_from_dataframe(
            single_defect_df, effective_config, sync_context
        )
        if not defects:
            logger.warning(
                "Extended view failed: defect '%s' not found in project '%s'", defect_id, project
            )
            raise NotFound(f"Defect '{defect_id}' was not found in project '{project}'.")

        return self._build_defect_with_attributes(defects[0], project, single_defect_df)

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
        commands = self._get_config_value("commands", project=project)
        return execute_sync_hook(project, sync_type, "presync", commands)

    def after_sync(self, project: str, sync_type: str, sync_context: SyncContext) -> Protocol:
        commands = self._get_config_value("commands", project=project)
        return execute_sync_hook(project, sync_type, "postsync", commands)

    def supports_changes_timestamps(self) -> bool:
        return self.config.lastedit_column_no > 0

    def correct_sync_results(self, project: str, body: Results) -> Results:
        # due to limitations of the Excel client, we cannot guarantee to filter out defects with
        # incorrect fields, so we return the body as-is.
        # Additionally, the reason why the defect was filtered out could not be propagated
        # to the user.
        return body

    def _get_config_value(self, attr: str, project: str | None = None) -> Any:
        """
        Retrieve a configuration value, optionally project-specific, falling back to global config.

        This reads the *effective* config rather than `config.projects` directly. Reading the
        latter skipped `<Project>.properties` entirely, so a file overriding e.g. `fileType`
        silently did nothing while the same key set in `config.toml` worked.

        Args:
            attr (str): The attribute name to retrieve.
            project (str | None): The project name, if any.
        Returns:
            The value of the attribute, or None if not found.
        """
        return getattr(self._get_effective_config(project), attr, None)  # type: ignore

    def _get_buffer_cleanup_interval_seconds(self, config: ExcelDefectClientConfig) -> float:
        return float(getattr(config, "buffer_cleanup_interval_minutes", 0) or 0) * 60

    def _start_buffer_cleanup_thread(self) -> None:
        """Size the cleanup thread from the global config *and* every project override.

        A project can enable buffering that the global config leaves off. Sizing the thread from
        `self.config` alone meant those entries were only ever purged lazily, on the next read of
        that same project - so a project buffered once and never read again kept its frame for the
        life of the process. The tick is the shortest interval anyone asked for; the age is the
        longest, so this never purges an entry earlier than its own config allows. Each project's
        exact age is still enforced on read, by `_purge_expired_entries` in `_get_dataframe`.

        The project list is every directory on disk plus every configured block: a project can be
        configured by its own `<Project>.properties` file with no entry in `config.toml` at all,
        and one can have a `config.toml` block before its directory exists.
        """
        projects = sorted(set(self.get_projects()) | set(self.config.projects))
        configs = [self.config, *(self._get_effective_config(p) for p in projects)]
        intervals = [
            seconds
            for config in configs
            if (seconds := self._get_buffer_cleanup_interval_seconds(config)) > 0
        ]
        max_ages = [
            seconds for config in configs if (seconds := self._get_buffer_limits(config)[0]) > 0
        ]

        if not intervals or not max_ages:
            return

        interval_seconds = min(intervals)
        max_age_seconds = max(max_ages)

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

    def _load_project_properties(self, project: str) -> ProjectConfig | None:
        """Read the optional `<Project>.properties` file beside the project's data.

        Existence of the file is the switch - there is nothing to enable. It is re-read on every
        call, which costs a `stat()` plus a parse and buys live reload; cache it by
        `(path, mtime)` if it ever shows up in a hot path.
        """
        try:
            project_path = self._resolve_project_path(project)
        except FileNotFoundError:
            return None

        properties_path = project_path / f"{project}.properties"
        if not properties_path.is_file():
            return None

        try:
            data = load_properties_config_from_path(properties_path)
        except ImportError as exc:
            # The raising loader, not `utils.config.load_properties_config`: that one prints to
            # stdout and returns `{}`, which makes a broken file indistinguishable from no file.
            logger.warning(
                "Ignoring unreadable '%s'; project '%s' keeps its configured values: %s",
                properties_path.name,
                project,
                exc.__cause__ or exc,
            )
            return None
        if not data:
            return None

        try:
            return ProjectConfig.model_validate(data)
        except ValidationError as exc:
            logger.warning(
                "Ignoring invalid '%s'; project '%s' keeps its configured values: %s",
                properties_path.name,
                project,
                exc,
            )
            return None

    def _get_effective_config(self, project: str | None) -> ExcelDefectClientConfig:
        """Layer the project's overrides onto the global config, nearest source last.

        Global config, then the `[projects.<name>]` block, then `<Project>.properties`: the file
        lives next to the data it describes, so it is the more local statement and wins where both
        name the same key. Keys a layer leaves unset fall through to the one below - which is what
        `exclude_none=True` buys, and why every field of `ProjectConfig` must stay defaultless.
        """
        if not project:
            logger.debug("Using global config for project '%s'", project)
            return self.config

        layers = (self.config.projects.get(project), self._load_project_properties(project))
        overrides = [override for override in layers if override is not None]
        if not overrides:
            logger.debug("Using global config for project '%s'", project)
            return self.config

        logger.debug("Merging project-specific config for project '%s'", project)
        merged_config = self.config.model_dump()
        for override in overrides:
            merged_config.update(override.model_dump(exclude_none=True))
        merged_config["projects"] = self.config.projects
        return ExcelDefectClientConfig.model_validate(merged_config)

    def _report_ambiguous_ids(
        self,
        df: pd.DataFrame,
        config: ExcelDefectClientConfig,
        protocol: Protocol | None,
    ) -> set[str]:
        """Name every id that more than one row claims, and return them so they get skipped.

        An id on several rows identifies no single defect. Importing one of them would leave the
        others as stale copies that no later sync can reconcile. The rows stay in the file: they
        are the user's to repair, and this way one of them is not quietly picked as the truth.
        """
        ambiguous_ids = duplicated_ids(df)
        if not ambiguous_ids or protocol is None:
            return ambiguous_ids

        for duplicate_id, location in describe_duplicated_id_rows(df, config).items():
            message = (
                f"Skipping defect '{duplicate_id}': {location}. Remove the duplicate rows so "
                "the defect can be identified."
            )
            logger.warning(message)
            protocol.add_error(
                key=duplicate_id,
                message=message,
                protocol_code=ProtocolCode.IMPORT_ERROR,
            )
        return ambiguous_ids

    def _build_defects_from_dataframe(
        self,
        df: pd.DataFrame,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
        protocol: Protocol | None = None,
        file_name: str | None = None,
    ) -> list[DefectWithID]:
        defects: list[DefectWithID] = []
        first_data_row = config.defects_data_starting_line
        skipped_empty_rows = 0
        ambiguous_ids = self._report_ambiguous_ids(df, config, protocol)

        for row_offset, (_, row) in enumerate(df.iterrows()):
            row_number = first_data_row + row_offset
            if is_blank_row(row):
                # Layout, not data: an empty row carries nothing to import.
                skipped_empty_rows += 1
                continue
            defect_id = row_value(row, "id")
            if not defect_id:
                if protocol:
                    protocol.add_error(
                        key=str(row_number),
                        message=(
                            f"Skipping row {row_number}: it carries content but no defect id."
                        ),
                        protocol_code=ProtocolCode.IMPORT_ERROR,
                    )
                continue
            if defect_id in ambiguous_ids:
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

        if skipped_empty_rows and protocol:
            location = f" in '{file_name}'" if file_name else ""
            logger.debug("Skipped %d empty row(s)%s", skipped_empty_rows, location)
            protocol.add_general_warning(
                f"Skipped {skipped_empty_rows} empty row(s){location}.",
                protocol_code=ProtocolCode.IMPORT_WARNING,
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

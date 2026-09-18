import json
import subprocess
from pathlib import Path

from sanic.exceptions import InvalidUsage, NotFound, ServerError

from testbench_defect_service.clients.abstract_client import AbstractDefectClient
from testbench_defect_service.clients.jsonl.config import JsonlDefectClientConfig
from testbench_defect_service.clients.jsonl.utils import (
    add_missing_defect_warnings,
    append_defect_to_jsonl,
    build_protocol_result,
    find_defect_by_id,
    find_defects_files,
    parse_defects_from_file,
    parse_requested_defects,
    remove_defect_from_list,
    update_defect_in_list,
    validate_defect,
    validate_udf_structure,
    write_defects_to_file,
)
from testbench_defect_service.log import logger
from testbench_defect_service.models.defects import (
    Defect,
    DefectID,
    DefectWithAttributes,
    DefectWithID,
    ExtendedAttributes,
    LocalSyncActions,
    Protocol,
    ProtocolCode,
    ProtocolledDefectSet,
    ProtocolledString,
    RemoteSyncActions,
    Results,
    Settings,
    SyncContext,
    UserDefinedAttribute,
)


class JsonlDefectClient(AbstractDefectClient):
    CONFIG_CLASS = JsonlDefectClientConfig

    def __init__(self, config: JsonlDefectClientConfig):
        self.config = config

    def check_login(self, project: str | None) -> bool:
        logger.info(f"Checking login for project: {project if project else 'all projects'}")
        if project:
            project_path = self._get_project_path(project)
            exists = project_path.exists()
            logger.debug(f"Project path '{project_path}' exists: {exists}")
            return bool(exists)
        exists = self.config.defects_path.exists()
        logger.debug(f"Defects path '{self.config.defects_path}' exists: {exists}")
        return bool(exists)

    def get_settings(self) -> Settings:
        logger.info("Retrieving JSONL client settings")
        settings = Settings(
            name=self.config.name,
            description=self.config.description,
            readonly=self.config.readonly,
        )
        logger.debug(f"Settings: name={settings.name}, readonly={settings.readonly}")
        return settings

    def get_projects(self) -> list[str]:
        logger.info("Retrieving list of projects")
        if not self.config.defects_path.exists():
            logger.warning(f"Defects path '{self.config.defects_path}' does not exist")
            return []
        projects = [
            project_dir.name
            for project_dir in self.config.defects_path.iterdir()
            if project_dir.is_dir()
        ]
        logger.info(f"Found {len(projects)} projects: {projects}")
        return projects

    def get_control_fields(self, project: str | None) -> dict[str, list[str]]:
        logger.info(f"Retrieving control fields for project: {project}")
        control_fields = self._get_config_value("control_fields", project=project)
        if control_fields is None:
            logger.debug(f"No control fields configured for project: {project}")
            return {}

        if not isinstance(control_fields, dict):
            logger.error("Control fields configuration must be a dictionary")
            raise InvalidUsage("Control fields configuration must be a dictionary.")

        normalized_fields: dict[str, list[str]] = {}
        for field_key, field_values in control_fields.items():
            if not isinstance(field_values, list):
                logger.error(f"Control field '{field_key}' must have a list of allowed values")
                raise InvalidUsage(
                    f"Control field '{field_key}' must have a list of allowed values."
                )
            normalized_fields[field_key] = [str(value) for value in field_values]
        logger.debug(f"Control fields for project '{project}': {list(normalized_fields.keys())}")
        return normalized_fields

    def get_defects(self, project: str, sync_context: SyncContext) -> ProtocolledDefectSet:
        logger.info(f"Retrieving all defects for project: {project}")
        self._get_project_path(project)
        defects: list[DefectWithID] = []
        protocol = Protocol()

        try:
            defect_files = find_defects_files(
                defects_path=self.config.defects_path, project=project
            )
        except FileNotFoundError:
            logger.error(f"No defect files found for project {project}")
            protocol.add_general_error(
                protocol_code=ProtocolCode.PROJECT_NOT_FOUND,
                message=f"No defect files found for project {project}.",
            )
            return build_protocol_result(defects, protocol)

        if not defect_files:
            logger.warning(f"No defect files found for project {project}")
            protocol.add_general_error(
                protocol_code=ProtocolCode.NO_DEFECT_FOUND,
                message=f"No defect files found for project {project}.",
            )
            return build_protocol_result(defects, protocol)

        logger.debug(f"Reading defects from file: {defect_files[0]}")
        defects = parse_defects_from_file(defect_files[0], project, protocol)
        logger.info(f"Retrieved {len(defects)} defects for project: {project}")

        return build_protocol_result(defects, protocol)

    def get_defects_batch(
        self, project: str, defect_ids: list[DefectID], sync_context: SyncContext
    ) -> ProtocolledDefectSet:
        logger.info(f"Retrieving batch of {len(defect_ids)} defects for project: {project}")
        self._get_project_path(project)
        protocol = Protocol()
        defects: list[DefectWithID] = []

        # Normalize requested IDs to strings
        requested_defect_ids = {
            str(getattr(defect_id, "root", defect_id))
            for defect_id in defect_ids
            if getattr(defect_id, "root", defect_id)
        }
        logger.debug(f"Requested defect IDs: {requested_defect_ids}")

        try:
            defect_files = find_defects_files(
                defects_path=self.config.defects_path, project=project
            )
        except FileNotFoundError:
            logger.error(f"No defect files found for project {project}")
            protocol.add_general_error(
                protocol_code=ProtocolCode.PROJECT_NOT_FOUND,
                message=f"No defect files found for project {project}.",
            )
            return build_protocol_result(defects, protocol)

        defects = parse_requested_defects(defect_files[0], requested_defect_ids, project, protocol)

        # Check for missing defects
        add_missing_defect_warnings(requested_defect_ids, defects, project, protocol)
        logger.info(
            f"Retrieved {len(defects)} out of {len(requested_defect_ids)} requested defects"
        )
        return build_protocol_result(defects, protocol)

    def create_defect(
        self, project: str, defect: Defect, sync_context: SyncContext
    ) -> ProtocolledString:
        logger.info(f"Creating new defect in project: {project}")
        self._ensure_writable()

        defect_files = self._get_defect_files_or_raise(project)
        defect_data = Defect(**defect.model_dump(mode="json", exclude_none=True))
        logger.debug(f"Creating defect with data: {defect_data}")

        try:
            result = append_defect_to_jsonl(
                project=project, jsonl_file=defect_files[0], defect=defect_data
            )
            logger.info(f"Successfully created defect with ID: {result}")
            return result
        except OSError as exc:
            logger.error(f"Failed to write defect file for project {project}: {exc}")
            raise ServerError(f"Unable to write defect file for project {project}.") from exc

    def update_defect(
        self, project: str, defect_id: str, defect: Defect, sync_context: SyncContext
    ) -> Protocol:
        logger.info(f"Updating defect '{defect_id}' in project: {project}")
        self._ensure_writable()
        protocol = Protocol()

        if not defect_id:
            logger.warning("Cannot update defect: defect is not synchronized yet")
            protocol.add_warning(
                key=str(defect_id),
                protocol_code=ProtocolCode.DEFECT_NOT_FOUND,
                message="Defect is not synchronized yet and cannot be updated.",
            )
            return protocol

        defect_files = self._get_defect_files_or_raise(project)

        updated_defect = DefectWithID(**defect.model_dump(), id=DefectID(defect_id))

        updated_defects, found = update_defect_in_list(defect_files[0], updated_defect, protocol)

        if not found:
            logger.error(f"Defect with id '{defect_id}' not found in project {project}")
            protocol.add_general_error(
                protocol_code=ProtocolCode.DEFECT_NOT_FOUND,
                message=f"Defect with id '{defect_id}' not found in project {project}.",
            )
            return protocol

        write_defects_to_file(defect_files[0], updated_defects, project)

        protocol.add_success(
            key=str(project),
            message=f"Defect '{defect_id}' updated successfully in project {project}.",
            protocol_code=ProtocolCode.PUBLISH_SUCCESS,
        )
        logger.info(f"Successfully updated defect '{defect_id}' in project: {project}")

        return protocol

    def delete_defect(
        self, project: str, defect_id: str, defect: Defect, sync_context: SyncContext
    ) -> Protocol:
        logger.info(f"Deleting defect '{defect_id}' from project: {project}")
        self._ensure_writable()
        protocol = Protocol()

        if not defect_id:
            logger.warning("Cannot delete defect: defect is not synchronized yet")
            protocol.add_general_error(
                protocol_code=ProtocolCode.NO_DEFECT_FOUND,
                message="Defect is not synchronized yet and cannot be deleted.",
            )
            return protocol

        defect_files = self._get_defect_files_or_raise(project)

        remaining_defects, deleted_defect = remove_defect_from_list(
            defect_files[0], defect_id, protocol
        )

        if deleted_defect is None:
            logger.error(f"Defect with id {defect_id} not found in project {project}")
            protocol.add_general_error(
                protocol_code=ProtocolCode.NO_DEFECT_FOUND,
                message=f"Defect with id {defect_id} not found in project {project}",
            )
            return protocol

        write_defects_to_file(defect_files[0], remaining_defects, project)

        protocol.add_success(
            key=str(project),
            message=(f"Defect '{defect_id}' deleted successfully from project {project}."),
            protocol_code=ProtocolCode.PUBLISH_SUCCESS,
        )
        logger.info(f"Successfully deleted defect '{defect_id}' from project: {project}")

        return protocol

    def get_defect_extended(
        self, project: str, defect_id: str, sync_context: SyncContext
    ) -> DefectWithAttributes:
        logger.info(
            f"Retrieving extended defect information for defect '{defect_id}' in project: {project}"
        )

        if not defect_id:
            logger.warning(
                "Cannot retrieve extended defect info: defect has not been synchronized yet"
            )

        defect_files = self._get_defect_files_or_raise(project)
        defect = find_defect_by_id(defect_files[0], defect_id, project)
        logger.debug(f"Found defect '{defect_id}', building extended attributes")
        return self._build_defect_with_attributes(defect=defect, project=project)

    def get_user_defined_attributes(self, project: str | None) -> list[UserDefinedAttribute]:
        logger.info(f"Retrieving user-defined attributes for project: {project}")
        if project:
            udf_file_path = self._get_project_path(project) / "UserDefinedAttributes.json"
        else:
            udf_file_path = self.config.defects_path / "UserDefinedAttributes.json"

        if not udf_file_path.exists():
            logger.debug(f"No UDF file found for project {project}")
            return []

        logger.debug(f"Reading UDF definitions from: {udf_file_path}")
        with udf_file_path.open("r") as file:
            udf_definitions = json.load(file)
            validate_udf_structure(udf_definitions)

        udfs = [
            UserDefinedAttribute(
                name=udf["name"],
                valueType=udf["valueType"],
                mustField=udf.get("mustField", None),
                lastEdited=udf.get("lastEdited", None),
                stringValue=udf.get("stringValue", None),
                booleanValue=udf.get("booleanValue", None),
            )
            for udf in udf_definitions
        ]
        logger.info(f"Retrieved {len(udfs)} user-defined attributes for project: {project}")
        return udfs

    def before_sync(self, project: str, sync_type: str, sync_context: SyncContext) -> Protocol:
        logger.info(f"Executing pre-sync hook for project '{project}' with sync type: {sync_type}")
        return self._execute_sync_hook(project, sync_type, "presync")

    def after_sync(self, project: str, sync_type: str, sync_context: SyncContext) -> Protocol:
        logger.info(f"Executing post-sync hook for project '{project}' with sync type: {sync_type}")
        return self._execute_sync_hook(project, sync_type, "postsync")

    def supports_changes_timestamps(self) -> bool:
        logger.debug(f"Supports changes timestamps: {self.config.supports_changes_timestamps}")
        return bool(self.config.supports_changes_timestamps)

    def correct_sync_results(self, project: str, body: Results) -> Results:
        """Validate and correct proposed sync changes before applying them."""
        logger.info("Validating and correcting sync changes")

        corrected_results = Results(
            local=body.local.model_copy(deep=True) if body.local else None,
            remote=body.remote.model_copy(deep=True) if body.remote else None,
        )

        if corrected_results.local:
            self._validate_and_filter_actions(corrected_results.local, project=project)
        if corrected_results.remote:
            self._validate_and_filter_actions(corrected_results.remote, project=project)
        logger.info("Successfully validated and corrected sync changes")

        return corrected_results

    # Private helper methods
    def _get_project_path(self, project: str) -> Path:
        """Resolve a project path and ensure it stays within the defects directory."""
        resolved = (self.config.defects_path / project).resolve()
        if not resolved.is_relative_to(self.config.defects_path.resolve()):
            raise InvalidUsage(f"Invalid project name: {project}")
        return resolved

    def _ensure_writable(self):
        """Ensure the client is not in read-only mode."""
        if self.config.readonly:
            logger.error("Attempted write operation in read-only mode")
            raise InvalidUsage("Cannot modify defects when the JSONL client is in read-only mode.")

    def _get_defect_files_or_raise(self, project: str) -> list[Path]:
        """Get defect files or raise NotFound exception."""
        self._get_project_path(project)
        try:
            files = find_defects_files(defects_path=self.config.defects_path, project=project)
            logger.debug(f"Found {len(files)} defect file(s) for project: {project}")
            return files
        except FileNotFoundError as exc:
            logger.error(f"No defect files found for project {project}")
            raise NotFound(f"No defect files found for project {project}.") from exc

    def _build_defect_with_attributes(
        self, defect: DefectWithID, project: str
    ) -> DefectWithAttributes:
        """Build a DefectWithAttributes from a DefectWithID."""
        defect_data = defect.model_dump()
        attributes: dict[str, str] = {}

        attribute_fields = self._get_config_value("attributes", project=project) or []

        for attribute_name in attribute_fields:
            # Check direct attributes
            attribute_value = getattr(defect, attribute_name, None)
            if attribute_value is not None:
                attributes[attribute_name] = str(attribute_value)
            else:
                # Check user-defined fields
                user_defined_fields = getattr(defect, "userDefinedFields", None) or []
                for udf in user_defined_fields:
                    if udf.name == attribute_name:
                        attributes[attribute_name] = str(udf.value)
                        break

        defect_data["attributes"] = ExtendedAttributes(**attributes)
        return DefectWithAttributes.model_validate(defect_data)

    def _execute_sync_hook(self, project: str, sync_type: str, hook_type: str) -> Protocol:
        """Execute a pre-sync or post-sync hook command."""
        logger.debug(
            f"Executing {hook_type} hook for project '{project}' with sync type: {sync_type}"
        )
        protocol = Protocol()
        commands = self._get_config_value("commands", project=project)

        hook_commands = getattr(commands, hook_type, None)
        command_str = getattr(hook_commands, sync_type, None) if hook_commands else None

        if not command_str:
            logger.debug(f"No {hook_type} command configured for project '{project}'")
            protocol.add_success(
                key=str(project),
                protocol_code=ProtocolCode.PUBLISH_SUCCESS,
                message=f"{hook_type.capitalize()} hook acknowledged; no command configured.",
            )
            return protocol

        command_path = Path(command_str)
        logger.debug(f"Validating {hook_type} hook command: {command_path}")

        # Validate command file extension
        if command_path.suffix.lower() not in {".bat", ".sh", ".exe"}:
            logger.warning(f"{hook_type} hook '{command_path.name}' has unsupported file extension")
            return protocol

        # Check if command exists
        if not command_path.exists():
            logger.warning(f"{hook_type} hook command file does not exist: {command_path}")
            return protocol

        # Execute command
        logger.info(f"Executing {hook_type} hook command: {command_path}")
        try:
            subprocess.run([str(command_path), project, sync_type], check=True)
            logger.info(f"{hook_type} hook '{command_path.name}' executed successfully")
            protocol.add_success(
                key=str(project),
                protocol_code=ProtocolCode.PUBLISH_SUCCESS,
                message=(
                    f"{hook_type.capitalize()} hook '{command_path.name}' executed successfully."
                ),
            )
        except subprocess.CalledProcessError as exc:
            logger.error(
                f"{hook_type} hook '{command_path.name}' failed with return code {exc.returncode}"
            )
            protocol.add_general_error(
                protocol_code=ProtocolCode.PUBLISH_ERROR,
                message=(
                    f"{hook_type.capitalize()} hook '{command_path.name}'"
                    f" failed with return code {exc.returncode}."
                ),
            )
        except OSError as exc:
            logger.error(f"{hook_type} hook '{command_path.name}' could not be executed: {exc}")
            protocol.add_general_error(
                protocol_code=ProtocolCode.PUBLISH_ERROR,
                message=(
                    f"{hook_type.capitalize()} hook '{command_path.name}' "
                    f"could not be executed: {exc}."
                ),
            )

        return protocol

    def _validate_and_filter_actions(
        self,
        actions: RemoteSyncActions | LocalSyncActions,
        project: str,
    ):
        """Validate and filter create/update actions based on control fields."""
        control_fields = self._get_config_value("control_fields", project=project) or {}

        for action_name in ("create", "update"):
            action_items = getattr(actions, action_name) or []
            valid_items = [
                defect for defect in action_items if validate_defect(defect, control_fields)
            ]
            filtered_count = len(action_items) - len(valid_items)
            if filtered_count > 0:
                logger.warning(f"Filtered out {filtered_count} invalid {action_name} action(s)")
            logger.debug(
                f"Validated {len(valid_items)} out of {len(action_items)} {action_name} action(s)"
            )
            setattr(actions, action_name, valid_items)

    def _get_config_value(self, attr: str, project: str | None = None):
        """
        Retrieve a configuration value, optionally project-specific, falling back to global config.
        """
        if project and project in self.config.projects:
            project_config = self.config.projects[project]
            project_value = getattr(project_config, attr, None)
            if project_value is not None:
                return project_value

        return getattr(self.config, attr, None)

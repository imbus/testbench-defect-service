from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from jira import Project
from jira.resources import IssueType, Priority, Status
from sanic import NotFound, ServerError

from testbench_defect_service.clients.abstract_client import AbstractDefectClient
from testbench_defect_service.clients.jira.config import JiraDefectClientConfig
from testbench_defect_service.clients.jira.jira_client import JiraClient
from testbench_defect_service.clients.jira.utils import (
    build_project_dict,
    create_defect_from_issue,
    extract_changelog_attributes,
    extract_static_attributes,
    extract_valuetype_from_issue_field,
)
from testbench_defect_service.log import logger
from testbench_defect_service.models.defects import (
    Defect,
    DefectID,
    DefectWithAttributes,
    DefectWithID,
    ExtendedAttributes,
    LocalSyncActions,
    Login,
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


class JiraDefectClient(AbstractDefectClient):
    CONFIG_CLASS = JiraDefectClientConfig

    def __init__(self, config: JiraDefectClientConfig):
        self.config = config
        self._jira_client: JiraClient | None = None
        self._projects: dict[str, Project] = {}

    @property
    def jira_client(self) -> JiraClient:
        if self._jira_client is None:
            self._jira_client = JiraClient(self.config)
        return self._jira_client

    @property
    def projects(self) -> dict[str, Project]:
        """Return a dict mapping project name (fmt: "{project.name} ({project.key})") to Project."""
        if not self._projects:
            logger.debug("Loading projects from Jira API")
            projects = self.jira_client.fetch_projects()
            self._projects = build_project_dict(projects)
            logger.info("Loaded %d projects from Jira", len(self._projects))
        else:
            logger.debug("Using cached projects data (%d projects)", len(self._projects))
        return self._projects

    def check_login(self, project: str | None) -> bool:
        try:
            self.jira_client.jira.myself()
        except (ValueError, RuntimeError) as exc:
            logger.error("Failed to authenticate to Jira: %s", exc)
            return False
        except Exception as exc:
            logger.error("Unhandled exception during Jira authentication: %s", exc)
            return False

        if project and project not in self.projects:
            logger.error(
                'Project "%s" not found or access denied with current credentials', project
            )
            return False
        return True

    def get_settings(self) -> Settings:
        return Settings(
            name=self.config.name,
            description=(
                "Service enabling communication between the Testbench "
                "defect manager wrapper and a Jira instance"
            ),
            readonly=self.config.readonly,
        )

    def get_projects(self) -> list[str]:
        return list(self.projects.keys())

    def get_control_fields(self, project: str | None) -> dict[str, list[str]]:
        if project:
            try:
                project_key = self.projects[project].key
            except KeyError as exc:
                logger.error("Unknown project '%s' requested", project)
                raise NotFound(f"Project '{project}' not found or access denied") from exc

            meta = self.jira_client.fetch_issues_fields(project_key)
        else:
            meta = self.jira_client.fetch_issues_fields()
            project_key = None

        if not self.jira_client.use_issuetypes_endpoint:
            projects = meta.get("projects", [])
            if not projects:
                return {}
            issue_types = projects[0].get("issuetypes", [])
        else:
            issue_types = None
            projects = []

        control_fields: dict[str, list[str]] = {}

        control_fields_name = self._get_config_value("control_fields", project=project).copy()
        if self.jira_client.use_issuetypes_endpoint:
            self.extract_control_field_values_jdc(project_key, control_fields, control_fields_name)
        else:
            for it in issue_types:
                self._extract_control_field_values(project, control_fields_name, control_fields, it)

        if "classification" in control_fields_name:
            self._add_class_issue_type_names(
                control_fields_name, control_fields, issue_types, project_key
            )

        if "status" in control_fields_name:
            self._add_control_field_statuses(
                control_fields_name, projects, control_fields, project_key
            )

        if control_fields_name != []:
            logger.warning(
                (
                    "Some configured control fields were not found in Jira "
                    "metadata for project '%s'. Remaining fields: %s"
                ),
                project,
                control_fields_name,
            )

        return control_fields

    def extract_control_field_values_jdc(self, project_key, control_fields, control_fields_name):
        for field in self.jira_client.fetch_project_issue_fields(project_key):
            if field.name in control_fields_name or field.fieldId in control_fields_name:
                if not field.allowedValues:
                    continue
                control_field_values = []
                for value in field.allowedValues:
                    control_field_values.append(value.name)
                control_fields[field.name] = control_field_values
                if field.name in control_fields_name:
                    control_fields_name.remove(field.name)
                else:
                    control_fields_name.remove(field.fieldId)

    def _add_class_issue_type_names(
        self,
        control_fields_name: Any,
        control_fields: dict[str, list[str]],
        issue_types: list[Any] | None = None,
        project_key: str | None = None,
    ):
        control_field_values = []
        if self.jira_client.use_issuetypes_endpoint:
            issue_types = self.jira_client.jira.project_issue_types(
                project_key or "", maxResults=100
            )
            for issue_type in issue_types or []:
                control_field_values.append(str(issue_type.name))
        else:
            for issue_type in issue_types or []:
                control_field_values.append(str(issue_type["name"]))
        control_fields["classification"] = control_field_values
        control_fields_name.remove("classification")

    def _add_control_field_statuses(
        self,
        control_fields_name: Any,
        projects: list,
        control_fields: dict[str, list[str]],
        project_key,
    ):
        # Try the project-specific endpoint first — returns only statuses
        # that actually belong to this project's workflows.
        control_field_values = self.jira_client.fetch_project_statuses(project_key)

        if not control_field_values:
            # Fallback: use global statuses() and filter by project scope
            logger.warning(
                "Project-specific statuses endpoint returned no results for '%s'; "
                "falling back to global statuses()",
                project_key,
            )
            statuses = self.jira_client.jira.statuses()
            control_field_values = []
            project_id = projects[0].get("id") if projects else None
            for status in statuses:
                try:
                    has_scope = hasattr(status, "scope") and status.scope
                    if has_scope and status.scope.project.id == project_id:
                        control_field_values.append(str(status))
                except AttributeError:
                    # Status has incomplete scope info — include it as fallback
                    control_field_values.append(str(status))

        control_fields["status"] = control_field_values
        control_fields_name.remove("status")

    def _extract_control_field_values(
        self,
        project: str | None,
        control_fields_name: Any,
        control_fields: dict[str, list[str]],
        issue_type: dict,
    ):
        for _, field_content in issue_type.get("fields", {}).items():
            field_name = field_content.get("name", "")
            field_id = field_content.get("key", "")
            if field_name in control_fields_name or field_id in control_fields_name:
                if field_content.get("allowedValues", {}):
                    control_field_values = []
                    for value in field_content.get("allowedValues", {}):
                        control_field_values.append(value.get("name", ""))

                    control_fields[field_name] = control_field_values
                    if field_name in control_fields_name:
                        control_fields_name.remove(field_name)
                    else:
                        control_fields_name.remove(field_id)

                else:
                    logger.warning(
                        "Control field '%s' in project '%s' has no allowedValues; "
                        "it may be of an incompatible type. Schema: %s",
                        field_name,
                        project,
                        field_content.get("schema", {}),
                    )

    def get_defects(self, project: str, sync_context: SyncContext) -> ProtocolledDefectSet:
        protocol = Protocol()
        defects: list[DefectWithID] = []
        try:
            jql_query = str(self.config.defect_jql).format(project=self.projects[project].key)
            logger.debug("Fetching defects for project '%s' with JQL '%s'", project, jql_query)
            issues = self.jira_client.fetch_issues_by_jql(jql_query)
            if not issues:
                logger.info("No issues found for project '%s'", project)
                protocol.add_general_error(
                    protocol_code=ProtocolCode.NO_DEFECT_FOUND,
                    message=f"No issues found for project '{project}' using configured JQL.",
                )
            fields = self.jira_client.fetch_all_custom_fields(project=self.projects[project].key)
            logger.debug("Processing %d issues for project '%s'", len(issues), project)

            for issue in issues:
                try:
                    defects.append(create_defect_from_issue(issue, fields))
                except (ValueError, KeyError, AttributeError, TypeError) as exc:
                    logger.error(
                        "Failed to convert issue '%s' to defect", getattr(issue, "key", "<unknown>")
                    )
                    protocol.add_error(
                        str(getattr(issue, "key", "<unknown>")),
                        f"Failed to convert issue to defect: {exc}",
                        protocol_code=ProtocolCode.INSERT_ERROR,
                    )
            logger.debug(
                "Successfully converted %d/%d issues to defects", len(defects), len(issues)
            )
        except KeyError as exc:
            logger.error("Unknown project '%s' requested", project)
            protocol.add_general_error(
                f"Unknown project '{project}': {exc}", protocol_code=ProtocolCode.PROJECT_NOT_FOUND
            )
        except (RuntimeError, OSError) as exc:
            logger.error("Unexpected error while fetching defects for project '%s'", project)
            protocol.add_general_error(
                f"Failed to fetch defects for project '{project}': {exc}",
                protocol_code=ProtocolCode.INSERT_ERROR,
            )

        return ProtocolledDefectSet(value=defects, protocol=protocol)

    def get_defects_batch(
        self, project: str, defect_ids: list[DefectID], sync_context: SyncContext
    ) -> ProtocolledDefectSet:
        protocol = Protocol()
        defects: list[DefectWithID] = []
        try:
            project_key = self.projects[project].key
        except KeyError as exc:
            logger.error("Unknown project '%s' requested while creating defect", project)
            protocol.add_general_error(
                f"Unknown project '{project}': {exc}", protocol_code=ProtocolCode.PROJECT_NOT_FOUND
            )
            return ProtocolledDefectSet(value=[], protocol=protocol)

        logger.info("Processing batch of %d defect IDs for project '%s'", len(defect_ids), project)
        fields = self.jira_client.fetch_all_custom_fields(project=project_key)
        for defect_id in defect_ids:
            defect_identifier = defect_id.root
            if not defect_identifier:
                continue
            try:
                issue = self.jira_client.fetch_issue(str(defect_identifier), fields="*all")
                if issue is None:
                    logger.warning("Issue with id '%s' not found", defect_identifier)
                    protocol.add_warning(
                        str(defect_identifier),
                        "Issue not found in Jira",
                        protocol_code=ProtocolCode.DEFECT_NOT_FOUND,
                    )
                    continue

                try:
                    defect = create_defect_from_issue(issue, fields)
                    defects.append(defect)
                except (ValueError, KeyError, AttributeError, TypeError) as exc:
                    logger.error(
                        "Failed to convert Jira issue '%s' to defect",
                        getattr(issue, "key", defect_identifier),
                    )
                    protocol.add_error(
                        defect_identifier,
                        f"Failed to convert Jira issue to defect: {exc}",
                        protocol_code=ProtocolCode.INSERT_ERROR,
                    )
            except (RuntimeError, OSError) as exc:
                logger.error("Failed to fetch Jira issue '%s'", defect_identifier)
                protocol.add_error(
                    defect_identifier,
                    f"Failed to fetch Jira issue: {exc}",
                    protocol_code=ProtocolCode.INSERT_ERROR,
                )

        logger.info(
            "Batch processing complete: %d/%d defects loaded successfully",
            len(defects),
            len(defect_ids),
        )
        return ProtocolledDefectSet(value=defects, protocol=protocol)

    def _resolve_jira_client(self, project: str, principal: Login) -> JiraClient:
        """Return the appropriate JiraClient for a write operation.

        Uses shared auth when explicitly configured, when auth_type is oauth1
        (which doesn't support per-user auth), or when enable_shared_auth is
        not configured (None). Uses per-user auth only when explicitly disabled.
        """
        shared = self._get_config_value("enable_shared_auth", project=project)
        if shared is not False or self.config.auth_type == "oauth1":
            logger.debug("Using shared authentication for project '%s'", project)
            return self.jira_client
        logger.debug("Using per-user authentication for project '%s'", project)
        return JiraClient(self.config, principal)

    def create_defect(
        self, project: str, defect: Defect, sync_context: SyncContext
    ) -> ProtocolledString:
        protocol = Protocol()
        issue_key = ""
        jira_client = self._resolve_jira_client(project, defect.principal)

        if self._get_config_value("readonly", project=project):
            protocol.add_error(
                project,
                (
                    f"Cannot create issue because the Jira project '{project}' "
                    "has been configured as read-only"
                ),
                protocol_code=ProtocolCode.INSERT_ACCESS_ERROR,
            )
            return ProtocolledString(value="", protocol=protocol)

        try:
            project_key = self.projects[project].key
        except KeyError as exc:
            logger.error("Unknown project '%s' requested while creating defect", project)
            protocol.add_general_error(
                f"Unknown project '{project}': {exc}", protocol_code=ProtocolCode.PROJECT_NOT_FOUND
            )
            return ProtocolledString(value="", protocol=protocol)

        try:
            issue = jira_client.create_issue(project_key, defect)
            issue_key = str(getattr(issue, "key", ""))
            logger.info("Successfully created issue '%s' in project '%s'", issue_key, project)
            protocol.add_success(
                issue_key or project_key,
                "Defect created successfully in Jira",
                protocol_code=ProtocolCode.INSERT_SUCCESS,
            )
        except (RuntimeError, ValueError, KeyError, AttributeError, TypeError) as exc:
            logger.error("Failed to create Jira issue for project '%s': %s", project_key, exc)
            protocol.add_general_error(
                "Failed to create Jira issue", protocol_code=ProtocolCode.INSERT_ERROR
            )

        return ProtocolledString(value=issue_key, protocol=protocol)

    def update_defect(
        self, project: str, defect_id: str, defect: Defect, sync_context: SyncContext
    ) -> Protocol:
        protocol = Protocol()
        jira_client = self._resolve_jira_client(project, defect.principal)

        if self._get_config_value("readonly", project=project):
            protocol.add_error(
                project,
                (
                    f"Cannot update issue because the Jira project '{project}' "
                    "has been configured as read-only"
                ),
                protocol_code=ProtocolCode.PUBLISH_ERROR,
            )
            return protocol
        try:
            project_key = self.projects[project].key
        except KeyError as exc:
            logger.error("Unknown project '%s' requested while updating defect", project)
            protocol.add_general_error(
                f"Unknown project '{project}': {exc}", protocol_code=ProtocolCode.PROJECT_NOT_FOUND
            )
            return protocol

        try:
            issue = jira_client.fetch_issue(defect_id)
            if not issue:
                logger.debug(
                    "No matching issue found for project '%s' and defect '%s'",
                    project_key,
                    defect.title,
                )
                protocol.add_general_error(
                    "No matching issues found to update", protocol_code=ProtocolCode.NO_DEFECT_FOUND
                )
                return protocol

            jira_client.update_issue(project_key, issue, defect)
            logger.info("Successfully updated issue '%s' in project '%s'", issue.key, project)
            protocol.add_success(
                issue.key, "Issue updated successfully", protocol_code=ProtocolCode.PUBLISH_SUCCESS
            )
        except (RuntimeError, OSError, ValueError, KeyError, AttributeError, TypeError) as exc:
            logger.error("Failed to update Jira issues for project '%s': %s", project_key, exc)
            protocol.add_general_error(
                "Failed to update Jira issues",
                protocol_code=ProtocolCode.PUBLISH_ERROR,
            )

        return protocol

    def delete_defect(
        self, project: str, defect_id: str, defect: Defect, sync_context: SyncContext
    ) -> Protocol:
        protocol = Protocol()
        jira_client = self._resolve_jira_client(project, defect.principal)

        if self._get_config_value("readonly", project=project):
            protocol.add_error(
                project,
                (
                    f"Cannot delete the issue because the Jira project '{project}' "
                    "has been configured as read-only"
                ),
                protocol_code=ProtocolCode.PUBLISH_ERROR,
            )
            return protocol
        try:
            project_key = self.projects[project].key
        except KeyError as exc:
            logger.error("Unknown project '%s' requested while deleting defect", project)
            protocol.add_general_error(
                f"Unknown project '{project}': {exc}", protocol_code=ProtocolCode.PROJECT_NOT_FOUND
            )
            return protocol

        try:
            issue = jira_client.fetch_issue(defect_id)
            if not issue:
                logger.debug(
                    "No matching issue found for project '%s' and defect '%s'",
                    project_key,
                    defect_id,
                )
                protocol.add_general_error(
                    "No matching issues found to delete", protocol_code=ProtocolCode.NO_DEFECT_FOUND
                )
                return protocol

            jira_client.delete_issue(issue)
            logger.info("Successfully deleted issue '%s' from project '%s'", issue.key, project)
            protocol.add_success(
                issue.key, "Issue deleted successfully", protocol_code=ProtocolCode.PUBLISH_SUCCESS
            )
        except (RuntimeError, OSError, ValueError, KeyError, AttributeError, TypeError) as exc:
            logger.error("Failed to delete Jira issues for project '%s': %s", project_key, exc)
            protocol.add_general_error(
                "Failed to delete Jira issues", protocol_code=ProtocolCode.PUBLISH_ERROR
            )

        return protocol

    def get_defect_extended(
        self, project: str, defect_id: str, sync_context: SyncContext
    ) -> DefectWithAttributes:
        # add the history to the project so can show what hast changed since the last Sync
        try:
            project_key = self.projects[project].key

            issue = self.jira_client.fetch_issue(defect_id, fields="*all", expand="changelog")
            if issue is None:
                logger.warning("Issue with id '%s' not found", defect_id)
                raise NotFound(f"Issue with id '{defect_id}' not found in Jira")

            fields = self.jira_client.fetch_issue_fields(project_key, issue)

            converted_list = [{"id": item} for item in list(fields.keys())]
            fields_values = list(fields.values())

            fields_list: list[dict[Any, Any]] = [
                {**d1, **d2} for d1, d2 in zip(converted_list, fields_values, strict=False)
            ]

            try:
                defect = create_defect_from_issue(issue, fields_list)
                return self._build_defect_with_attributes(
                    defect=defect,
                    project=project,
                    changelog=issue.changelog,
                    fields=fields_list,
                    sync_context=sync_context,
                )
            except (ValueError, KeyError, AttributeError, TypeError) as exc:
                logger.error("Failed to convert issue '%s' to defect with attributes", defect_id)
                raise ServerError(
                    f"Defect '{defect_id}' could not be converted to detailed attributes: {exc}"
                ) from exc

        except (NotFound, ServerError):
            raise
        except Exception as exc:
            logger.error(
                "Unexpected error while reading defect '%s' for project '%s'", defect_id, project
            )
            raise ServerError(
                f"Unable to read defect '{defect_id}' for project '{project}': {exc}"
            ) from exc

    def get_user_defined_attributes(self, project: str | None) -> list[UserDefinedAttribute]:
        if not project:
            logger.debug("No Project parameter for fetching UDFs")
            project_key = None
        else:
            try:
                project_key = self.projects[project].key
            except KeyError as exc:
                logger.error("Unknown project '%s' requested while fetching UDFs", project)
                raise NotFound(f"Project '{project}' not found or access denied") from exc
        return [
            UserDefinedAttribute(
                name=field["name"],
                valueType=extract_valuetype_from_issue_field(field),
                mustField=getattr(field, "required", None),
            )
            for field in self.jira_client.fetch_all_custom_fields(project=project_key)
        ]

    def before_sync(self, project: str, sync_type: str, sync_context: SyncContext) -> Protocol:
        return self._execute_sync_hook(project, sync_type, "presync")

    def after_sync(self, project: str, sync_type: str, sync_context: SyncContext) -> Protocol:
        return self._execute_sync_hook(project, sync_type, "postsync")

    def supports_changes_timestamps(self) -> bool:
        return self.config.supports_changes_timestamps

    def correct_sync_results(self, project: str, body: Results) -> Results:
        """Validate and correct proposed sync changes before applying them."""
        corrected_results = Results(
            local=body.local.model_copy(deep=True) if body.local else None,
            remote=body.remote.model_copy(deep=True) if body.remote else None,
        )
        if corrected_results.local:
            self._validate_and_filter_actions(body.local, corrected_results.local, project)
        if corrected_results.remote:
            self._validate_and_filter_actions(body.remote, corrected_results.remote, project)
        return corrected_results

    def _build_defect_with_attributes(
        self,
        defect: DefectWithID,
        project: str,
        changelog: Any,
        fields: list[dict[Any, Any]],
        sync_context: SyncContext,
    ) -> DefectWithAttributes:
        data = defect.model_dump()
        attribute_fields = self._get_config_value("attributes", project=project) or []
        attributes: dict[str, str] = {}
        if self._get_config_value("show_change_history", project=project):
            extract_changelog_attributes(
                changelog, fields, attribute_fields, attributes, sync_context
            )
        else:
            attributes = extract_static_attributes(defect, attribute_fields)

        data["attributes"] = ExtendedAttributes(**attributes)
        return DefectWithAttributes.model_validate(data)

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

    def _execute_sync_hook(self, project: str, sync_type: str, hook_type: str) -> Protocol:
        """Execute a pre-sync or post-sync hook command."""
        protocol = Protocol()
        commands = self._get_config_value("commands", project=project)

        hook_commands = getattr(commands, hook_type, None)
        command_str = getattr(hook_commands, sync_type, None) if hook_commands else None

        if not command_str:
            protocol.add_success(
                key=str(project),
                message=f"{hook_type.capitalize()} hook acknowledged; no command configured.",
                protocol_code=ProtocolCode.PUBLISH_SUCCESS,
            )
            return protocol

        command_path = Path(command_str)

        # Validate command file extension
        if command_path.suffix.lower() not in {".bat", ".sh", ".exe"}:
            logger.warning(
                "Hook '%s' has unsupported file extension '%s', only .bat, .sh, .exe supported",
                command_path.name,
                command_path.suffix,
            )
            return protocol

        # Check if command exists
        if not command_path.exists():
            logger.warning("Hook command path does not exist: %s", command_path)
            return protocol

        # Execute command
        logger.info(
            "Executing %s hook '%s' for project '%s'", hook_type, command_path.name, project
        )
        try:
            subprocess.run(
                [str(command_path), str(project), str(sync_type)],
                check=True,
            )
            logger.info(
                "%s hook '%s' completed successfully", hook_type.capitalize(), command_path.name
            )
            protocol.add_success(
                key=str(project),
                message=(
                    f"{hook_type.capitalize()} hook '{command_path.name}' executed successfully."
                ),
                protocol_code=ProtocolCode.PUBLISH_SUCCESS,
            )
        except subprocess.CalledProcessError as exc:
            protocol.add_general_error(
                protocol_code=ProtocolCode.PUBLISH_ERROR,
                message=(
                    f"{hook_type.capitalize()} hook '{command_path.name}'"
                    f" failed with return code {exc.returncode}."
                ),
            )
        except OSError as exc:
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
        source: RemoteSyncActions | LocalSyncActions | None,
        target: RemoteSyncActions | LocalSyncActions,
        project: str,
    ) -> None:
        """Validate and filter create/update actions based on control fields."""
        statuses = self.jira_client.jira.statuses()
        priorities = self.jira_client.jira.priorities()
        issue_types = self.jira_client.jira.issue_types()
        project_control_fields = self.get_control_fields(project)

        for action_name in ("create", "update"):
            action_items = getattr(source, action_name) or []
            valid_items = [
                defect
                for defect in action_items
                if self.validate_defect(
                    defect,
                    project_control_fields,
                    statuses,
                    priorities,
                    issue_types,
                )
            ]
            rejected_count = len(action_items) - len(valid_items)
            if rejected_count > 0:
                logger.warning(
                    "Validation filtered out %d/%d defects for action '%s'",
                    rejected_count,
                    len(action_items),
                    action_name,
                )
            else:
                logger.info(
                    "All %d defects validated successfully for action '%s'",
                    len(valid_items),
                    action_name,
                )
            setattr(target, action_name, valid_items)

    def validate_defect(
        self,
        defect: Defect | DefectWithID,
        control_field: dict[str, list[str]],
        statuses: list[Status],
        priorities: list[Priority],
        issue_types: list[IssueType],
    ) -> bool:
        """
        Validate a defect object used in create/update sync operations in Jira.

        Performs multi-level validation:
        1. **Mandatory Field Check**: Ensures required fields are present and non-empty
        2. **Jira Metadata Validation**: Verifies status, priority, and classification match Jira
        3. **Control Field Constraint Check**: Validates custom fields against allowed values

        Required Fields (always checked):
            - status: Must exist in Jira workflows for the project
            - classification: Must match an issue type in Jira
            - priority: Must exist in Jira priorities
            - lastEdited: Must be a valid timestamp (non-empty)
            - principal: Must contain valid authentication info (non-empty)

        Jira-Specific Validation:
            - status: Validated against statuses parameter (from Jira API)
            - classification: Validated against issue_types parameter
            - priority: Validated against priorities parameter

        Control Field Constraints:
            Custom fields defined in control_field dict are validated against their allowed values.
            This allows for project-specific or field-specific constraints beyond Jira's defaults.

        Args:
            defect: Defect or DefectWithID object to validate
            control_field: Dict mapping field names to lists of allowed values
            statuses: List of Jira Status objects from JIRA API
            priorities: List of Jira Priority objects from JIRA API
            issue_types: List of Jira IssueType objects from JIRA API

        Returns:
            True  → defect is valid and can be synced to Jira
            False → defect is invalid and should be rejected
        """

        # Required according to OpenAPI spec:
        required_fields = ["status", "classification", "priority", "lastEdited", "principal"]

        # Check missing mandatory fields
        for field in required_fields:
            if getattr(defect, field, None) in (None, ""):
                return False

        # Validate status against Jira workflows
        if getattr(defect, "status", None) not in {status.name for status in statuses}:
            return False
        control_field = {k: v for k, v in control_field.items() if k.lower() != "status"}

        # Validate priority against Jira priorities
        if getattr(defect, "priority", None) not in {priority.name for priority in priorities}:
            return False
        control_field = {
            k: v
            for k, v in control_field.items()
            if k.lower() != "priorität" and k.lower() != "priority"
        }

        # Validate classification (issue type) against Jira issue types
        if getattr(defect, "classification", None) not in {
            issue_type.name for issue_type in issue_types
        }:
            return False
        control_field = {k: v for k, v in control_field.items() if k.lower() != "classification"}

        # Validate remaining custom control fields
        for field, allowed_values in control_field.items():
            actual_value = getattr(defect, field, None)
            if actual_value not in allowed_values:
                logger.debug(
                    "Defect validation failed: field '%s' has value '%s' "
                    "which is not in allowed values: %s",
                    field,
                    actual_value,
                    allowed_values,
                )
                return False
        return True

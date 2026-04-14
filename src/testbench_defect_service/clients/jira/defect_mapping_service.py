from __future__ import annotations

from typing import Any

from jira import JIRA, JIRAError

from testbench_defect_service.clients.jira.html_to_jira import convert_html_to_jira_markup
from testbench_defect_service.clients.jira.utils import FieldInfo
from testbench_defect_service.log import logger
from testbench_defect_service.models.defects import Defect


class DefectToJiraMapper:
    def __init__(self, jira: JIRA):
        self.jira = jira

    def map_defect_to_jira_issue(
        self, defect: Defect, issue_metadata: dict[str, Any]
    ) -> dict[str, Any]:
        """Convert a ``Defect`` model into Jira ``create_issue()`` fields (Cloud API).

        Args:
            defect: The Defect model to convert.
            issue_metadata: Jira metadata with project and issue-type information.
        """
        issue_type = self._get_issue_type(defect.classification, issue_metadata)
        allowed = self._extract_allowed_fields_cloud(issue_type)
        return {"fields": self._build_issue_fields(defect, allowed)}

    def map_defect_to_jira_data_center_issue(self, defect: Defect, fields: list) -> dict[str, Any]:
        """Convert a ``Defect`` model into Jira ``create_issue()`` fields (Data Center API)."""
        allowed = [FieldInfo(key=f.fieldId, name=f.name, metadata=f.schema) for f in fields]
        return {"fields": self._build_issue_fields(defect, allowed)}

    def _build_issue_fields(self, defect: Defect, allowed: list[FieldInfo]) -> dict[str, Any]:
        """Build the Jira issue *fields* dict from a ``Defect`` and *allowed* field list.

        Args:
            defect: The Defect model to convert.
            allowed: List of fields accepted by the target Jira project/issue type.
            reporter_key: The key used inside the reporter object.
                ``"id"`` for Cloud (accountId), ``"name"`` for Data Center (username).
        """
        fields: dict[str, Any] = {}
        # User-defined fields
        if defect.userDefinedFields:
            for udf in defect.userDefinedFields:
                if udf.value:
                    self._set_field(fields, udf.name, udf.value, allowed)

        # Standard fields
        self._set_field(fields, "summary", str(defect.title) or "", allowed)
        self._set_field(
            fields,
            "description",
            convert_html_to_jira_markup(str(defect.description)) or "",
            allowed,
        )

        self._set_field(fields, "priority", str(defect.priority), allowed)
        self._set_field(fields, "issuetype", str(defect.classification), allowed)
        if defect.reporter:
            self._set_field(
                fields,
                "reporter",
                defect.reporter,
                allowed,
            )
        return {k: v for k, v in fields.items() if v is not None}

    def _set_field(
        self,
        fields: dict[str, Any],
        key: str,
        value: Any,
        allowed: list[FieldInfo],
    ) -> None:
        """Add a single field to *fields* with proper formatting."""
        if value is None:
            return

        info = self._find_field(key, allowed)

        if not info:
            return

        formatted = self._format_value_by_type(value, info.metadata)
        if formatted is not None:
            fields[info.key] = formatted

    def _find_field(self, key: str, allowed: list[FieldInfo]) -> FieldInfo | None:
        """Find a ``FieldInfo`` whose *key* or *name* matches *key*."""
        return next((f for f in allowed if key in (f.key, f.name)), None)

    def _get_issue_type(
        self, classification: str, issue_metadata: dict[str, Any]
    ) -> dict[str, Any]:
        """Return the issue-type dict matching *classification* from *issue_metadata*.

        Raises:
            ValueError: If no projects found in metadata or the issue type is missing.
        """
        projects = issue_metadata.get("projects", [])
        if not projects:
            raise ValueError("No projects found in issue metadata")

        for it in projects[0].get("issuetypes", []):
            if it.get("name") == classification:
                return dict(it)

        raise ValueError(f"Issue type '{classification}' not found in project metadata")

    def _format_value_by_type(self, value: Any, field_metadata: Any) -> Any:  # noqa: PLR0911
        """Format *value* according to the field's schema type."""
        field_type, allowed_values = self._extract_type_info(field_metadata)
        if field_type in {"string", "date"}:
            return value
        if field_type == "array":
            values = (
                [item.strip() for item in value.split(",")] if isinstance(value, str) else value
            )
            if getattr(field_metadata, "items", None) in {"component", "version"}:
                return [{"name": item} for item in values]
            return values
        if field_type == "number":
            try:
                return float(value)
            except (ValueError, TypeError):
                return None
        if field_type == "option" and allowed_values:
            return self._find_option_by_value(value, allowed_values)
        if field_type in {"user"}:
            try:
                return self.get_user_id(value)
            except ValueError:
                pass
        if field_type in {"priority", "issuetype", "any"}:
            return {"name": value}
        return None

    def _extract_type_info(self, field_metadata: Any) -> tuple[str | None, list | None]:
        """Return ``(field_type, allowed_values)`` from *field_metadata*."""
        if isinstance(field_metadata, dict):
            schema = field_metadata.get("schema", {})
            return schema.get("type"), field_metadata.get("allowedValues")
        if field_metadata is not None:
            return getattr(field_metadata, "type", None), getattr(
                field_metadata, "allowedValues", None
            )
        return None, None

    def _find_option_by_value(
        self, value: Any, allowed_values: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Return ``{"id": …}`` for the matching option, or ``{"name": value}``."""
        for av in allowed_values:
            if value == av.get("value"):
                return {"id": av.get("id")}
        return {"name": value}

    def _extract_allowed_fields_cloud(self, issue_type: dict[str, Any]) -> list[FieldInfo]:
        """Extract allowed fields from a Cloud issue-type dict, including metadata."""
        return [
            FieldInfo(key=field_key, name=field_value.get("name", ""), metadata=field_value)
            for field_key, field_value in issue_type.get("fields", {}).items()
            if field_key and field_value.get("name")
        ]

    def get_user_id(self, user: str) -> dict[str, str]:
        if not self.jira._is_cloud:
            try:
                users = self.jira.search_users(user=user)
                if not users:
                    logger.warning("No user found for query: %s", user)
                    raise ValueError(f"User '{user}' not found in Jira")
                found_user = users[0]
                user_name = str(getattr(found_user, "name", None) or found_user.key)
                if len(users) > 1:
                    logger.debug(
                        "Multiple users found for query '%s', using first match: %s",
                        user,
                        user_name,
                    )
                else:
                    logger.debug("Resolved user '%s' to name: %s", user, user_name)
                return {"name": user_name}
            except JIRAError as e:
                logger.error("Error searching for user '%s': %s", user, e)
                raise
            except (IndexError, AttributeError) as e:
                logger.warning("Unable to retrieve name for user '%s': %s", user, e)
                raise ValueError(f"User '{user}' not found or invalid") from e
        try:
            users = self.jira.search_users(query=user)
            if not users:
                logger.warning("No user found for query: %s", user)
                raise ValueError(f"User '{user}' not found in Jira")
            account_id = str(users[0].accountId)
            if len(users) > 1:
                logger.debug(
                    "Multiple users found for query '%s', using first match: %s",
                    user,
                    account_id,
                )
            else:
                logger.debug("Resolved user '%s' to account ID: %s", user, account_id)
            return {"id": account_id}
        except JIRAError as e:
            logger.error("Error searching for user '%s': %s", user, e)
            raise
        except (IndexError, AttributeError) as e:
            logger.warning("Unable to retrieve accountId for user '%s': %s", user, e)
            raise ValueError(f"User '{user}' not found or invalid") from e

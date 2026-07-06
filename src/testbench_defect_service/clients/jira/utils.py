from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple

import jira
from jira import Issue
from jira.resources import Project

from testbench_defect_service.log import logger
from testbench_defect_service.models.defects import (
    DefectID,
    DefectWithID,
    Login,
    SyncContext,
    UserDefinedFieldProperties,
    ValueType,
)


class FieldInfo(NamedTuple):
    """A Jira field with its key, display name, and optional schema/metadata."""

    key: str
    name: str
    metadata: dict[str, Any] | Any = None


def build_project_dict(projects: list[Project]) -> dict[str, Project]:
    """Build a dictionary of projects keyed by ``"Name (KEY)"``."""
    return {f"{project.name} ({project.key})": project for project in projects}


def extract_valuetype_from_issue_field(field: dict[str, Any]) -> ValueType:
    """Return ``ValueType.BOOLEAN`` or ``ValueType.STRING`` for a Jira issue-field schema."""
    if field.get("schema", {}).get("type") == "boolean":
        return ValueType.BOOLEAN
    return ValueType.STRING


def create_defect_from_issue(
    issue: Issue, fields: list[dict[str, Any]], jira_server_url: str, sync_context: SyncContext
) -> DefectWithID:
    """Convert a Jira *issue* into a ``DefectWithID`` model.

    Args:
        issue: The Jira issue object to convert.
        fields: Field metadata dicts (keys ``'id'`` and ``'name'``) for user-defined fields.
    """
    return DefectWithID(
        id=DefectID(root=str(issue.key)),
        title=issue.fields.summary,
        description=issue.fields.description,
        reporter=_safe_display_name(issue.fields.creator),
        status=_get_control_field_value(sync_context.statusAttribute, issue.fields, fields),
        classification=_get_control_field_value(sync_context.classAttribute, issue.fields, fields),
        priority=_get_control_field_value(sync_context.priorityAttribute, issue.fields, fields),
        userDefinedFields=_extract_user_defined_fields(issue, fields, sync_context),
        lastEdited=datetime.fromisoformat(jira_datetime_to_iso(issue.fields.updated)),
        # TODO: reaktivate them
        references=_extract_references(issue),
        principal=Login(username="", password=""),
    )


def _get_control_field_value(
    controll_field: str | None, issue_fields: Any, meta_fields: Any
) -> str:
    """Return a readable value for *controll_field* if the key exists in *fields*."""
    if not controll_field:
        return ""

    field_values = _to_field_dict(issue_fields)
    key = _resolve_control_field_key(controll_field, field_values, meta_fields)
    if key is None:
        return ""
    return _stringify_control_value(field_values.get(key))


def _to_field_dict(fields: Any) -> dict[str, Any]:
    """Convert Jira field container objects to a plain dictionary."""
    if isinstance(fields, dict):
        return fields
    try:
        values = vars(fields)
    except TypeError:
        return {}
    return values if isinstance(values, dict) else {}


def _resolve_control_field_key(
    controll_field: str, field_values: dict[str, Any], meta_fields
) -> str | None:
    """Resolve a configured control field to an existing Jira field key."""
    if controll_field in field_values:
        return controll_field
    for field in meta_fields:
        if field.get("name", None) == controll_field:
            return str(field.get("id", None))
    return None


def _stringify_control_value(value: Any) -> str:
    """Normalize Jira field objects/dicts to string values."""
    if value is None:
        return ""
    if isinstance(value, dict):
        for nested_key in ("name", "value", "id"):
            nested_value = value.get(nested_key)
            if nested_value is not None:
                return str(nested_value)
    elif hasattr(value, "name") and value.name is not None:
        return str(value.name)
    return str(value)


def _extract_user_defined_fields(
    issue: Issue,
    fields: list[dict[str, Any]],
    sync_context: SyncContext,
) -> list[UserDefinedFieldProperties]:
    """Build user-defined field properties from *issue*."""
    result: list[UserDefinedFieldProperties] = []
    for field in fields:
        if not sync_context.udaSyncOptions or field["name"] not in sync_context.udaSyncOptions:
            continue
        value = getattr(issue.fields, field["id"], None)
        if "<jira.resources.PropertyHolder object at" in str(
            value
        ) or "com.atlassian.greenhopper" in str(value):
            continue

        if "<JIRA" in str(value):
            if isinstance(value, list):
                formatted_value = []
                for elem in value:
                    formatted_value.append(str(elem))
                value = formatted_value
            elif isinstance(value, jira.resources.TimeTracking):
                value = value.timeSpent if hasattr(value, "timeSpent") else None

        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            value = ", ".join(value)

        result.append(
            UserDefinedFieldProperties(
                name=field["name"],
                value=str(value) if value is not None else "",
            )
        )
    return result


def _safe_display_name(obj: Any) -> str:
    """Return ``obj.displayName`` or ``""`` if *obj* is ``None``."""
    return obj.displayName if obj else ""


def _extract_references(issue: Issue) -> list[str]:
    """Return attachment URLs / filenames from *issue*."""
    attachments = getattr(issue.fields, "attachment", None)
    if not attachments:
        attachment_urls = []
    else:
        attachment_urls = [
            att.content if hasattr(att, "content") else str(att) for att in attachments
        ]
    return [issue.permalink(), *attachment_urls]


def jira_datetime_to_iso(date_str: str) -> str:
    """Convert a Jira datetime string to ISO 8601 format."""
    return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%f%z").isoformat()


def iso8601_to_unix_timestamp(date_string: str) -> float:
    """Convert an ISO 8601 datetime string to a Unix timestamp."""
    return datetime.strptime(date_string, "%Y-%m-%dT%H:%M:%S.%f%z").timestamp()


def ensure_issuetype_format(issuetype_data: dict[Any, Any], issue_metadata: dict[str, Any]) -> None:
    """Ensure the ``issuetype`` field in *issuetype_data* is a dict with an ``id``."""
    if "issuetype" not in issuetype_data:
        return

    issuetype = issuetype_data["issuetype"]

    if isinstance(issuetype, str):
        issuetype_data["issuetype"] = {"name": issuetype}
        return

    if isinstance(issuetype, dict) and "name" in issuetype and "id" not in issuetype:
        _resolve_issuetype_id(issuetype_data, issuetype["name"], issue_metadata)


def _resolve_issuetype_id(
    issuetype_data: dict[Any, Any], name: str, issue_metadata: dict[str, Any]
) -> None:
    """Try to resolve an issue-type *name* to its Jira ID."""
    try:
        projects = issue_metadata.get("projects", [])
        if not projects:
            return
        issue_types = projects[0].get("issuetypes", [])
        match = next((it for it in issue_types if it.get("name") == name), None)
        if match:
            issuetype_data["issuetype"] = {"id": match["id"]}
    except (KeyError, TypeError) as exc:
        logger.warning("Failed to resolve issue type '%s' to ID: %s", name, exc)


def get_attribute_name_from_field(
    fields: list[dict[str, Any]], item: Any, attribute_fields: list[str]
) -> str:
    """Determine attribute name from *item*, if it's in *attribute_fields*."""
    field_id = getattr(item, "fieldId", None) or getattr(item, "field", None)
    if field_id is None:
        return ""
    if field_id in attribute_fields:
        return str(field_id)
    for field in fields:
        try:
            if field_id == "summary" and "title" in attribute_fields:
                return "title"
            if field["id"] == field_id and field["id"] in attribute_fields:
                return str(field["name"])
        except (KeyError, AttributeError, TypeError):
            continue
    return ""


def extract_changelog_attributes(
    changelog: Any,
    fields: Any,
    attribute_fields: list[str],
    attributes: dict[str, str],
    sync_context: SyncContext,
) -> None:
    """Populate *attributes* with changes from *changelog* newer than the last sync."""
    last_sync_ts = (
        datetime.fromisoformat(str(sync_context.lastSync)).timestamp()
        if sync_context.lastSync is not None
        else 0.0
    )

    for change in reversed(changelog.histories):
        change_ts = iso8601_to_unix_timestamp(change.created)
        if change_ts <= last_sync_ts:
            continue
        for item in change.items:
            attr_name = get_attribute_name_from_field(fields, item, attribute_fields)
            if attr_name:
                dt_obj = datetime.fromisoformat(change.created)
                timestamp_str = dt_obj.strftime("%d.%m.%Y %H:%M:%S")
                key = f"{str(attr_name).capitalize()}: {timestamp_str}"
                attributes[key] = f"{item.fromString} → {item.toString}"


def extract_static_attributes(  # noqa: C901
    defect: DefectWithID,
    attribute_fields: list[str],
    issue: Issue,
    fields: list[dict[Any, Any]],
) -> dict[str, str]:
    """Return a dict of attribute values from *defect* for the given *attribute_fields*."""
    attributes: dict[str, str] = {}
    for field in fields:
        if field["name"] not in attribute_fields:
            continue
        value = getattr(issue.fields, field["id"], None)
        if "<jira.resources.PropertyHolder object at" in str(
            value
        ) or "com.atlassian.greenhopper" in str(value):
            continue

        if "<JIRA" in str(value):
            if isinstance(value, list):
                formatted_value = []
                for elem in value:
                    formatted_value.append(str(elem))
                value = formatted_value
            elif isinstance(value, jira.resources.TimeTracking):
                value = value.timeSpent if hasattr(value, "timeSpent") else None

        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            value = ", ".join(value)

        attributes[field["name"]] = str(value) if value is not None else ""

    for attr in attribute_fields:
        value = getattr(defect, attr, None)
        if value is not None:
            attributes[attr] = str(value)
            continue
        for uda in getattr(defect, "userDefinedFields", None) or []:
            if uda.name == attr:
                attributes[attr] = str(uda.value)
                break
    return attributes

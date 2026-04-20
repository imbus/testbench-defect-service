"""Unit tests for Jira client utility functions."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from testbench_defect_service.clients.jira.utils import (
    build_project_dict,
    create_defect_from_issue,
    ensure_issuetype_format,
    extract_changelog_attributes,
    extract_static_attributes,
    extract_valuetype_from_issue_field,
    get_attribute_name_from_field,
    iso8601_to_unix_timestamp,
    jira_datetime_to_iso,
)
from testbench_defect_service.models.defects import (
    DefectWithID,
    SyncContext,
    ValueType,
)


@pytest.mark.unit
class TestBuildProjectDict:
    """Tests for build_project_dict function."""

    def test_build_project_dict_single_project(self, mock_jira_project):
        """Test building dictionary from single project."""
        projects = [mock_jira_project]
        result = build_project_dict(projects)

        assert len(result) == 1
        assert "Test Project (TEST)" in result
        assert result["Test Project (TEST)"] == mock_jira_project

    def test_build_project_dict_multiple_projects(self):
        """Test building dictionary from multiple projects."""
        project1 = Mock()
        project1.name = "Project One"
        project1.key = "P1"

        project2 = Mock()
        project2.name = "Project Two"
        project2.key = "P2"

        projects = [project1, project2]
        result = build_project_dict(projects)

        assert len(result) == 2
        assert "Project One (P1)" in result
        assert "Project Two (P2)" in result
        assert result["Project One (P1)"] == project1
        assert result["Project Two (P2)"] == project2

    def test_build_project_dict_empty_list(self):
        """Test building dictionary from empty list."""
        result = build_project_dict([])
        assert result == {}


@pytest.mark.unit
class TestExtractValueTypeFromIssueField:
    """Tests for extract_valuetype_from_issue_field function."""

    def test_extract_valuetype_boolean(self):
        """Test extracting boolean value type."""
        field = {"schema": {"type": "boolean"}}
        result = extract_valuetype_from_issue_field(field)
        assert result == ValueType.BOOLEAN

    def test_extract_valuetype_string(self):
        """Test extracting string value type."""
        field = {"schema": {"type": "string"}}
        result = extract_valuetype_from_issue_field(field)
        assert result == ValueType.STRING

    def test_extract_valuetype_other(self):
        """Test extracting other value types defaults to STRING."""
        field = {"schema": {"type": "number"}}
        result = extract_valuetype_from_issue_field(field)
        assert result == ValueType.STRING

    def test_extract_valuetype_no_schema(self):
        """Test extracting value type when schema is missing."""
        field = {}
        result = extract_valuetype_from_issue_field(field)
        assert result == ValueType.STRING


@pytest.mark.unit
class TestCreateDefectFromIssue:
    """Tests for create_defect_from_issue function."""

    def test_create_defect_from_issue_basic(self, mock_jira_issue, sample_field_metadata):
        """Test creating defect from Jira issue."""
        mock_jira_issue.fields.customfield_10001 = "Custom Value 1"
        mock_jira_issue.fields.customfield_10002 = "Custom Value 2"
        mock_jira_issue.fields.customfield_10003 = True

        result = create_defect_from_issue(mock_jira_issue, sample_field_metadata)

        assert isinstance(result, DefectWithID)
        assert result.id.root == "TEST-123"
        assert result.title == "Test Issue Summary"
        assert result.description == "Test Issue Description"
        assert result.status == "Open"
        assert result.priority == "High"
        assert result.classification == "Bug"
        assert result.reporter == "John Doe"
        assert len(result.references) == 2

    def test_create_defect_from_issue_with_list_values(self, mock_jira_issue):
        """Test creating defect when field values are lists."""
        fields = [{"id": "customfield_10001", "name": "Labels"}]
        mock_jira_issue.fields.customfield_10001 = ["label1", "label2", "label3"]

        result = create_defect_from_issue(mock_jira_issue, fields)

        udf = next((f for f in result.userDefinedFields if f.name == "Labels"), None)
        assert udf is not None
        assert udf.value == "label1, label2, label3"

    def test_create_defect_from_issue_missing_fields(self, mock_jira_issue):
        """Test creating defect when some fields are missing."""
        mock_jira_issue.fields.status = None
        mock_jira_issue.fields.priority = None

        fields = [{"id": "customfield_10001", "name": "Custom Field"}]
        result = create_defect_from_issue(mock_jira_issue, fields)

        assert result.status == ""
        assert result.priority == ""

    def test_create_defect_from_issue_none_custom_field(self, mock_jira_issue):
        """Test creating defect when custom field value is None."""
        fields = [{"id": "customfield_10099", "name": "Missing Field"}]
        type(mock_jira_issue.fields).customfield_10099 = property(lambda self: None)

        result = create_defect_from_issue(mock_jira_issue, fields)

        udf = next((f for f in result.userDefinedFields if f.name == "Missing Field"), None)
        assert udf is not None
        assert udf.value == ""


@pytest.mark.unit
class TestJiraDatetimeToIso:
    """Tests for jira_datetime_to_iso function."""

    def test_jira_datetime_to_iso_basic(self):
        """Test converting Jira datetime to ISO format."""
        jira_date = "2024-01-15T10:30:45.123000+0000"
        result = jira_datetime_to_iso(jira_date)

        assert result == "2024-01-15T10:30:45.123000+00:00"

    def test_jira_datetime_to_iso_different_timezone(self):
        """Test converting Jira datetime with different timezone."""
        jira_date = "2024-06-20T14:25:30.456000+0200"
        result = jira_datetime_to_iso(jira_date)

        assert result == "2024-06-20T14:25:30.456000+02:00"


@pytest.mark.unit
class TestEnsureIssuetypeFormat:
    """Tests for ensure_issuetype_format function."""

    def test_ensure_issuetype_format_string_to_object(self, sample_issue_metadata):
        """Test converting string issuetype to object."""
        data = {"issuetype": "Bug"}
        ensure_issuetype_format(data, sample_issue_metadata)

        assert isinstance(data["issuetype"], dict)
        assert "name" in data["issuetype"]

    def test_ensure_issuetype_format_name_to_id(self, sample_issue_metadata):
        """Test converting issuetype name to ID."""
        data = {"issuetype": {"name": "Bug"}}
        ensure_issuetype_format(data, sample_issue_metadata)

        assert "id" in data["issuetype"]
        assert data["issuetype"]["id"] == "1"

    def test_ensure_issuetype_format_already_has_id(self, sample_issue_metadata):
        """Test when issuetype already has ID."""
        data = {"issuetype": {"id": "1", "name": "Bug"}}
        ensure_issuetype_format(data, sample_issue_metadata)

        assert data["issuetype"]["id"] == "1"

    def test_ensure_issuetype_format_no_issuetype(self, sample_issue_metadata):
        """Test when no issuetype field present."""
        data = {"summary": "Test"}
        ensure_issuetype_format(data, sample_issue_metadata)

        assert "issuetype" not in data

    def test_ensure_issuetype_format_invalid_name(self, sample_issue_metadata):
        """Test with invalid issue type name."""
        data = {"issuetype": {"name": "NonExistent"}}
        ensure_issuetype_format(data, sample_issue_metadata)

        assert data["issuetype"].get("name") == "NonExistent"


@pytest.mark.unit
class TestIso8601ToUnixTimestamp:
    """Tests for iso8601_to_unix_timestamp function."""

    def test_iso8601_to_unix_timestamp_basic(self):
        """Test converting ISO 8601 to Unix timestamp."""
        iso_date = "2024-01-15T10:30:45.123000+00:00"
        result = iso8601_to_unix_timestamp(iso_date)

        assert isinstance(result, float)
        assert result > 0

        dt = datetime.fromtimestamp(result, tz=timezone.utc)

        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15

    def test_iso8601_to_unix_timestamp_different_timezone(self):
        """Test with different timezone."""
        iso_date = "2024-06-20T14:25:30.456000+02:00"
        result = iso8601_to_unix_timestamp(iso_date)

        assert isinstance(result, float)
        assert result > 0


@pytest.mark.unit
class TestGetAttributeNameFromField:
    """Tests for get_attribute_name_from_field function."""

    def test_get_attribute_name_from_field_direct_match(self):
        """Test when field ID is directly in attribute fields."""
        fields = [{"id": "customfield_10001", "name": "Custom Field"}]
        item = Mock()
        item.fieldId = "customfield_10001"
        attribute_fields = ["customfield_10001", "priority"]

        result = get_attribute_name_from_field(fields, item, attribute_fields)

        assert result == "customfield_10001"

    def test_get_attribute_name_from_field_summary_to_title(self):
        """Test mapping summary field to title."""
        fields = [{"id": "summary", "name": "Summary"}]
        item = Mock()
        item.fieldId = "summary"
        attribute_fields = ["title"]

        result = get_attribute_name_from_field(fields, item, attribute_fields)

        assert result == "title"

    def test_get_attribute_name_from_field_by_name(self):
        """Test finding field by name in metadata."""
        fields = [{"id": "customfield_10001", "name": "Custom Field"}]
        item = Mock()
        item.fieldId = "customfield_10001"
        attribute_fields = ["customfield_10001"]

        result = get_attribute_name_from_field(fields, item, attribute_fields)

        assert result == "customfield_10001"

    def test_get_attribute_name_from_field_not_found(self):
        """Test when field is not in allowed attributes."""
        fields = [{"id": "customfield_10001", "name": "Custom Field"}]
        item = Mock()
        item.fieldId = "customfield_10099"
        attribute_fields = ["priority", "status"]

        result = get_attribute_name_from_field(fields, item, attribute_fields)

        assert result == ""


@pytest.mark.unit
class TestExtractChangelogAttributes:
    """Tests for extract_changelog_attributes function."""

    def test_extract_changelog_attributes_basic(self):
        """Test extracting attributes from changelog."""
        changelog = Mock()

        change = Mock()
        change.created = "2024-01-20T10:00:00.000000+00:00"

        item = Mock()
        item.fieldId = "priority"
        item.fromString = "Low"
        item.toString = "High"

        change.items = [item]
        changelog.histories = [change]

        fields = [{"id": "priority", "name": "Priority"}]
        attribute_fields = ["priority"]
        attributes = {}

        sync_context = SyncContext(
            lastSync=datetime(2024, 1, 15, tzinfo=timezone.utc),
            projects=["TEST"],
        )

        extract_changelog_attributes(changelog, fields, attribute_fields, attributes, sync_context)

        assert len(attributes) > 0
        assert any("Priority:" in key for key in attributes)
        assert any("Low → High" in value for value in attributes.values())

    def test_extract_changelog_attributes_before_sync(self):
        """Test that changes before last sync are ignored."""
        changelog = Mock()

        change = Mock()
        change.created = "2024-01-10T10:00:00.000000+00:00"

        item = Mock()
        item.fieldId = "priority"
        item.fromString = "Low"
        item.toString = "High"

        change.items = [item]
        changelog.histories = [change]

        fields = [{"id": "priority", "name": "Priority"}]
        attribute_fields = ["priority"]
        attributes = {}

        sync_context = SyncContext(
            lastSync=datetime(2024, 1, 15, tzinfo=timezone.utc),
            projects=["TEST"],
        )

        extract_changelog_attributes(changelog, fields, attribute_fields, attributes, sync_context)

        # Should not extract changes before sync date
        assert len(attributes) == 0


@pytest.mark.unit
class TestExtractStaticAttributes:
    """Tests for extract_static_attributes function."""

    def test_extract_static_attributes_standard_fields(self, sample_defect_with_id):
        """Test extracting standard attributes."""
        attribute_fields = ["title", "status", "priority"]

        result = extract_static_attributes(sample_defect_with_id, attribute_fields)

        assert "title" in result
        assert result["title"] == "Sample Defect"
        assert "status" in result
        assert result["status"] == "Open"
        assert "priority" in result
        assert result["priority"] == "High"

    def test_extract_static_attributes_user_defined_fields(self, sample_defect_with_id):
        """Test extracting user-defined field attributes."""
        attribute_fields = ["Custom Field 1", "Custom Field 2"]

        result = extract_static_attributes(sample_defect_with_id, attribute_fields)

        assert "Custom Field 1" in result
        assert result["Custom Field 1"] == "Value 1"
        assert "Custom Field 2" in result
        assert result["Custom Field 2"] == "Value 2"

    def test_extract_static_attributes_mixed(self, sample_defect_with_id):
        """Test extracting both standard and user-defined attributes."""
        attribute_fields = ["title", "Custom Field 1"]

        result = extract_static_attributes(sample_defect_with_id, attribute_fields)

        assert "title" in result
        assert "Custom Field 1" in result

    def test_extract_static_attributes_missing_field(self, sample_defect_with_id):
        """Test extracting non-existent attributes."""
        attribute_fields = ["nonexistent"]

        result = extract_static_attributes(sample_defect_with_id, attribute_fields)

        assert "nonexistent" not in result

    def test_extract_static_attributes_empty_list(self, sample_defect_with_id):
        """Test with empty attribute list."""
        result = extract_static_attributes(sample_defect_with_id, [])

        assert result == {}

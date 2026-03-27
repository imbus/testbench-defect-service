"""Unit tests for DefectToJiraMapper."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import Mock

import pytest
from jira import JIRAError

from testbench_defect_service.clients.jira.defect_mapping_service import DefectToJiraMapper
from testbench_defect_service.clients.jira.utils import FieldInfo
from testbench_defect_service.models.defects import Defect, Login, UserDefinedFieldProperties


def _make_defect(**overrides) -> Defect:
    """Return a minimal valid ``Defect`` with optional field overrides."""
    defaults: dict[str, Any] = {
        "title": "Test title",
        "description": "Test description",
        "reporter": None,
        "status": "Open",
        "classification": "Bug",
        "priority": "Medium",
        "userDefinedFields": [],
        "lastEdited": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "references": [],
        "principal": Login(username="user", password="pass"),
    }
    defaults.update(overrides)
    return Defect(**defaults)


def _cloud_jira() -> Mock:
    jira = Mock()
    jira._is_cloud = True
    jira._version = (9, 0, 0)
    return jira


def _dc_jira(version: tuple = (9, 0, 0)) -> Mock:
    jira = Mock()
    jira._is_cloud = False
    jira._version = version
    return jira


def _allowed(key: str, name: str, field_type: str = "string", allowed_values=None) -> FieldInfo:
    meta = {"schema": {"type": field_type}, "name": name}
    if allowed_values is not None:
        meta["allowedValues"] = allowed_values
    return FieldInfo(key=key, name=name, metadata=meta)


def _minimal_issue_metadata(classification: str = "Bug") -> dict:
    return {
        "projects": [
            {
                "issuetypes": [
                    {
                        "name": classification,
                        "fields": {
                            "summary": {"name": "Summary", "schema": {"type": "string"}},
                            "description": {"name": "Description", "schema": {"type": "string"}},
                            "priority": {"name": "Priority", "schema": {"type": "priority"}},
                            "issuetype": {"name": "Issue Type", "schema": {"type": "issuetype"}},
                            "reporter": {"name": "Reporter", "schema": {"type": "user"}},
                        },
                    }
                ]
            }
        ]
    }


@pytest.fixture
def cloud_mapper() -> DefectToJiraMapper:
    return DefectToJiraMapper(_cloud_jira())


@pytest.fixture
def dc_mapper() -> DefectToJiraMapper:
    """Data Center mapper where use_issuetypes_endpoint is True (>= 8.4.0)."""
    return DefectToJiraMapper(_dc_jira(version=(9, 0, 0)))


@pytest.fixture
def dc_old_mapper() -> DefectToJiraMapper:
    """Data Center mapper where use_issuetypes_endpoint is False (< 8.4.0)."""
    return DefectToJiraMapper(_dc_jira(version=(8, 3, 0)))


@pytest.mark.unit
class TestMapDefectToJiraIssue:
    def test_returns_fields_key(self, cloud_mapper):
        defect = _make_defect()
        result = cloud_mapper.map_defect_to_jira_issue(defect, _minimal_issue_metadata())
        assert "fields" in result

    def test_summary_and_description_mapped(self, cloud_mapper):
        defect = _make_defect(title="My Summary", description="My Desc")
        result = cloud_mapper.map_defect_to_jira_issue(defect, _minimal_issue_metadata())
        assert result["fields"]["summary"] == "My Summary"
        assert result["fields"]["description"] == "My Desc"

    def test_priority_mapped_as_name_dict(self, cloud_mapper):
        defect = _make_defect(priority="High")
        result = cloud_mapper.map_defect_to_jira_issue(defect, _minimal_issue_metadata())
        assert result["fields"]["priority"] == {"name": "High"}

    def test_issuetype_mapped_as_name_dict(self, cloud_mapper):
        defect = _make_defect(classification="Bug")
        result = cloud_mapper.map_defect_to_jira_issue(defect, _minimal_issue_metadata())
        assert result["fields"]["issuetype"] == {"name": "Bug"}

    def test_reporter_looked_up_when_present(self, cloud_mapper):
        cloud_mapper.jira.search_users.return_value = [Mock(accountId="acc-1")]
        defect = _make_defect(reporter="john")
        result = cloud_mapper.map_defect_to_jira_issue(defect, _minimal_issue_metadata())
        assert result["fields"]["reporter"] == {"id": "acc-1"}

    def test_no_reporter_field_when_reporter_none(self, cloud_mapper):
        defect = _make_defect(reporter=None)
        result = cloud_mapper.map_defect_to_jira_issue(defect, _minimal_issue_metadata())
        assert "reporter" not in result["fields"]

    def test_raises_when_no_projects(self, cloud_mapper):
        defect = _make_defect()
        with pytest.raises(ValueError, match="No projects found"):
            cloud_mapper.map_defect_to_jira_issue(defect, {"projects": []})

    def test_raises_when_classification_missing(self, cloud_mapper):
        defect = _make_defect(classification="Unknown")
        with pytest.raises(ValueError, match="Issue type 'Unknown' not found"):
            cloud_mapper.map_defect_to_jira_issue(defect, _minimal_issue_metadata("Bug"))


@pytest.mark.unit
class TestMapDefectToJiraDataCenterIssue:
    def _make_dc_field(self, field_id: str, name: str, field_type: str = "string"):
        f = Mock()
        f.fieldId = field_id
        f.name = name
        f.schema = Mock(type=field_type)
        return f

    def test_returns_fields_key(self, dc_mapper):
        defect = _make_defect()
        fields = [
            self._make_dc_field("summary", "Summary"),
            self._make_dc_field("description", "Description"),
        ]
        result = dc_mapper.map_defect_to_jira_data_center_issue(defect, fields)
        assert "fields" in result

    def test_summary_mapped(self, dc_mapper):
        defect = _make_defect(title="DC Summary")
        fields = [self._make_dc_field("summary", "Summary")]
        result = dc_mapper.map_defect_to_jira_data_center_issue(defect, fields)
        assert result["fields"]["summary"] == "DC Summary"

    def test_unknown_fields_ignored(self, dc_mapper):
        defect = _make_defect()
        fields = [self._make_dc_field("summary", "Summary")]
        result = dc_mapper.map_defect_to_jira_data_center_issue(defect, fields)
        assert "description" not in result["fields"]


@pytest.mark.unit
class TestGetIssueType:
    def test_returns_matching_issue_type(self, cloud_mapper):
        metadata = _minimal_issue_metadata("Story")
        result = cloud_mapper._get_issue_type("Story", metadata)
        assert result["name"] == "Story"

    def test_raises_on_empty_projects(self, cloud_mapper):
        with pytest.raises(ValueError, match="No projects found"):
            cloud_mapper._get_issue_type("Bug", {"projects": []})

    def test_raises_on_missing_issue_type(self, cloud_mapper):
        with pytest.raises(ValueError, match="Issue type 'Epic' not found"):
            cloud_mapper._get_issue_type("Epic", _minimal_issue_metadata("Bug"))


@pytest.mark.unit
class TestFindField:
    def test_find_by_key(self, cloud_mapper):
        allowed = [FieldInfo(key="summary", name="Summary")]
        result = cloud_mapper._find_field("summary", allowed)
        assert result is not None
        assert result.key == "summary"

    def test_find_by_name(self, cloud_mapper):
        allowed = [FieldInfo(key="customfield_001", name="My Custom Field")]
        result = cloud_mapper._find_field("My Custom Field", allowed)
        assert result is not None
        assert result.key == "customfield_001"

    def test_returns_none_when_not_found(self, cloud_mapper):
        allowed = [FieldInfo(key="summary", name="Summary")]
        result = cloud_mapper._find_field("nonexistent", allowed)
        assert result is None


@pytest.mark.unit
class TestSetField:
    def test_sets_string_field(self, cloud_mapper):
        fields: dict = {}
        allowed = [_allowed("summary", "Summary", "string")]
        cloud_mapper._set_field(fields, "summary", "Hello", allowed)
        assert fields["summary"] == "Hello"

    def test_ignores_none_value(self, cloud_mapper):
        fields: dict = {}
        allowed = [_allowed("summary", "Summary", "string")]
        cloud_mapper._set_field(fields, "summary", None, allowed)
        assert "summary" not in fields

    def test_ignores_unknown_field(self, cloud_mapper):
        fields: dict = {}
        allowed = [_allowed("summary", "Summary", "string")]
        cloud_mapper._set_field(fields, "nonexistent", "value", allowed)
        assert "nonexistent" not in fields


@pytest.mark.unit
class TestFormatValueByType:
    def test_string_type_returns_value(self, cloud_mapper):
        meta = {"schema": {"type": "string"}}
        assert cloud_mapper._format_value_by_type("hello", meta) == "hello"

    def test_date_type_returns_value(self, cloud_mapper):
        meta = {"schema": {"type": "date"}}
        assert cloud_mapper._format_value_by_type("2024-01-01", meta) == "2024-01-01"

    def test_number_type_converts_to_float(self, cloud_mapper):
        meta = {"schema": {"type": "number"}}
        assert cloud_mapper._format_value_by_type("3.14", meta) == 3.14

    def test_number_type_returns_none_on_invalid(self, cloud_mapper):
        meta = {"schema": {"type": "number"}}
        assert cloud_mapper._format_value_by_type("not_a_number", meta) is None

    def test_priority_type_returns_name_dict(self, cloud_mapper):
        meta = {"schema": {"type": "priority"}}
        assert cloud_mapper._format_value_by_type("High", meta) == {"name": "High"}

    def test_issuetype_type_returns_name_dict(self, cloud_mapper):
        meta = {"schema": {"type": "issuetype"}}
        assert cloud_mapper._format_value_by_type("Bug", meta) == {"name": "Bug"}

    def test_any_type_returns_name_dict(self, cloud_mapper):
        meta = {"schema": {"type": "any"}}
        assert cloud_mapper._format_value_by_type("val", meta) == {"name": "val"}

    def test_unknown_type_returns_none(self, cloud_mapper):
        meta = {"schema": {"type": "unknown_custom_type"}}
        assert cloud_mapper._format_value_by_type("val", meta) is None

    def test_array_type_splits_csv_string(self, cloud_mapper):
        meta = {"schema": {"type": "array"}}
        result = cloud_mapper._format_value_by_type("a, b, c", meta)
        assert result == ["a", "b", "c"]

    def test_array_type_passes_list_through(self, cloud_mapper):
        meta = {"schema": {"type": "array"}}
        result = cloud_mapper._format_value_by_type(["x", "y"], meta)
        assert result == ["x", "y"]

    def test_array_component_returns_name_dicts(self, cloud_mapper):
        meta = Mock()
        meta.get = lambda k, d=None: {"type": "array"}.get(k, d)
        meta.items = "component"
        cloud_mapper._extract_type_info = lambda m: ("array", None)
        field_meta = Mock()
        field_meta.items = "component"
        result = cloud_mapper._format_value_by_type("comp1, comp2", field_meta)
        assert result == [{"name": "comp1"}, {"name": "comp2"}]

    def test_option_type_matches_value(self, cloud_mapper):
        allowed_values = [{"id": "10", "value": "In Progress"}, {"id": "20", "value": "Done"}]
        meta = {"schema": {"type": "option"}, "allowedValues": allowed_values}
        assert cloud_mapper._format_value_by_type("In Progress", meta) == {"id": "10"}

    def test_option_type_falls_back_to_name(self, cloud_mapper):
        allowed_values = [{"id": "10", "value": "In Progress"}]
        meta = {"schema": {"type": "option"}, "allowedValues": allowed_values}
        assert cloud_mapper._format_value_by_type("Unknown", meta) == {"name": "Unknown"}

    def test_user_type_cloud_returns_account_id(self, cloud_mapper):
        user_mock = Mock(accountId="acc-42")
        cloud_mapper.jira.search_users.return_value = [user_mock]
        meta = {"schema": {"type": "user"}}
        result = cloud_mapper._format_value_by_type("alice", meta)
        assert result == {"id": "acc-42"}

    def test_user_type_cloud_returns_none_on_value_error(self, cloud_mapper):
        cloud_mapper.jira.search_users.return_value = []
        meta = {"schema": {"type": "user"}}
        result = cloud_mapper._format_value_by_type("ghost", meta)
        assert result is None

    def test_user_type_dc_returns_name(self, dc_mapper):
        user_mock = Mock()
        user_mock.name = "dc_user"
        user_mock.key = "dc_user"
        dc_mapper.jira.search_users.return_value = [user_mock]
        meta = {"schema": {"type": "user"}}
        result = dc_mapper._format_value_by_type("dc_user", meta)
        assert result == {"name": "dc_user"}


@pytest.mark.unit
class TestExtractTypeInfo:
    def test_dict_with_schema(self, cloud_mapper):
        meta = {"schema": {"type": "string"}, "allowedValues": [{"id": "1"}]}
        field_type, allowed = cloud_mapper._extract_type_info(meta)
        assert field_type == "string"
        assert allowed == [{"id": "1"}]

    def test_dict_without_schema(self, cloud_mapper):
        meta = {}
        field_type, allowed = cloud_mapper._extract_type_info(meta)
        assert field_type is None
        assert allowed is None

    def test_object_with_type_attribute(self, cloud_mapper):
        meta = Mock()
        meta.type = "number"
        meta.allowedValues = []
        field_type, allowed = cloud_mapper._extract_type_info(meta)
        assert field_type == "number"
        assert allowed == []

    def test_none_returns_none_none(self, cloud_mapper):
        field_type, allowed = cloud_mapper._extract_type_info(None)
        assert field_type is None
        assert allowed is None


@pytest.mark.unit
class TestFindOptionByValue:
    def test_finds_matching_option(self, cloud_mapper):
        avs = [{"id": "1", "value": "alpha"}, {"id": "2", "value": "beta"}]
        assert cloud_mapper._find_option_by_value("beta", avs) == {"id": "2"}

    def test_returns_name_fallback_when_not_found(self, cloud_mapper):
        avs = [{"id": "1", "value": "alpha"}]
        assert cloud_mapper._find_option_by_value("gamma", avs) == {"name": "gamma"}

    def test_empty_allowed_values(self, cloud_mapper):
        assert cloud_mapper._find_option_by_value("x", []) == {"name": "x"}


@pytest.mark.unit
class TestExtractAllowedFieldsCloud:
    def test_extracts_named_fields(self, cloud_mapper):
        issue_type = {
            "fields": {
                "summary": {"name": "Summary", "schema": {"type": "string"}},
                "customfield_001": {"name": "Custom", "schema": {"type": "option"}},
            }
        }
        result = cloud_mapper._extract_allowed_fields_cloud(issue_type)
        keys = {f.key for f in result}
        names = {f.name for f in result}
        assert "summary" in keys
        assert "customfield_001" in keys
        assert "Summary" in names
        assert "Custom" in names

    def test_skips_fields_without_name(self, cloud_mapper):
        issue_type = {
            "fields": {
                "summary": {"name": "Summary"},
                "empty_field": {},
            }
        }
        result = cloud_mapper._extract_allowed_fields_cloud(issue_type)
        assert all(f.key != "empty_field" for f in result)

    def test_empty_fields_returns_empty_list(self, cloud_mapper):
        assert cloud_mapper._extract_allowed_fields_cloud({"fields": {}}) == []


@pytest.mark.unit
class TestGetUserId:
    # --- Cloud (use_issuetypes_endpoint=False) ---

    def test_cloud_returns_account_id(self, cloud_mapper):
        user = Mock(accountId="cloud-123")
        cloud_mapper.jira.search_users.return_value = [user]
        result = cloud_mapper.get_user_id("alice")
        assert result == {"id": "cloud-123"}
        cloud_mapper.jira.search_users.assert_called_once_with(query="alice")

    def test_cloud_raises_when_no_users(self, cloud_mapper):
        cloud_mapper.jira.search_users.return_value = []
        with pytest.raises(ValueError, match="not found in Jira"):
            cloud_mapper.get_user_id("ghost")

    def test_cloud_raises_on_jira_error(self, cloud_mapper):
        cloud_mapper.jira.search_users.side_effect = JIRAError("API error")
        with pytest.raises(JIRAError):
            cloud_mapper.get_user_id("alice")

    def test_cloud_raises_on_missing_account_id(self, cloud_mapper):
        user = Mock(spec=[])
        cloud_mapper.jira.search_users.return_value = [user]
        with pytest.raises((ValueError, AttributeError)):
            cloud_mapper.get_user_id("alice")

    # --- Data Center (use_issuetypes_endpoint=True) ---

    def test_dc_returns_name(self, dc_mapper):
        user = Mock()
        user.name = "dc_alice"
        user.key = "dc_alice"
        dc_mapper.jira.search_users.return_value = [user]
        result = dc_mapper.get_user_id("alice")
        assert result == {"name": "dc_alice"}
        dc_mapper.jira.search_users.assert_called_once_with(user="alice")

    def test_dc_falls_back_to_key_when_name_none(self, dc_mapper):
        user = Mock()
        user.name = None
        user.key = "fallback_key"
        dc_mapper.jira.search_users.return_value = [user]
        result = dc_mapper.get_user_id("bob")
        assert result == {"name": "fallback_key"}

    def test_dc_raises_when_no_users(self, dc_mapper):
        dc_mapper.jira.search_users.return_value = []
        with pytest.raises(ValueError, match="not found in Jira"):
            dc_mapper.get_user_id("nobody")

    def test_dc_raises_on_jira_error(self, dc_mapper):
        dc_mapper.jira.search_users.side_effect = JIRAError("server error")
        with pytest.raises(JIRAError):
            dc_mapper.get_user_id("alice")


@pytest.mark.unit
class TestBuildIssueFields:
    def test_user_defined_fields_included(self, cloud_mapper):
        udfs = [UserDefinedFieldProperties(name="My Label", value="foo")]
        defect = _make_defect(userDefinedFields=udfs)
        allowed = [_allowed("customfield_01", "My Label", "string")]
        result = cloud_mapper._build_issue_fields(defect, allowed)
        assert result.get("customfield_01") == "foo"

    def test_user_defined_field_with_none_value_skipped(self, cloud_mapper):
        udfs = [UserDefinedFieldProperties(name="Empty", value=None)]
        defect = _make_defect(userDefinedFields=udfs)
        allowed = [_allowed("customfield_02", "Empty", "string")]
        result = cloud_mapper._build_issue_fields(defect, allowed)
        assert "customfield_02" not in result

    def test_none_values_stripped_from_result(self, cloud_mapper):
        defect = _make_defect(description=None)
        allowed = [_allowed("summary", "Summary", "string")]
        result = cloud_mapper._build_issue_fields(defect, allowed)
        assert all(v is not None for v in result.values())

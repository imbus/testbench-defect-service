"""Unit tests for JiraDefectClient class methods."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import Any
from unittest.mock import Mock, patch

import pytest
from sanic import NotFound, ServerError

from testbench_defect_service.clients.jira.client import (  # type: ignore[import-untyped]
    JiraDefectClient,
)
from testbench_defect_service.clients.jira.config import (  # type: ignore[import-untyped]
    JiraDefectClientConfig,
    JiraProjectConfig,
    PhaseCommands,
    SyncCommandConfig,
)
from testbench_defect_service.clients.jira.jira_client import (  # type: ignore[import-untyped]
    JiraClient,
)
from testbench_defect_service.models.defects import (  # type: ignore[import-untyped]
    Defect,
    DefectID,
    DefectWithID,
    DefectWithLocalPk,
    ExtendedAttributes,
    KnownDefect,
    LocalSyncActions,
    Login,
    Protocol,
    ProtocolCode,
    ProtocolledDefectSet,
    RemoteSyncActions,
    Results,
    SyncContext,
    UserDefinedFieldProperties,
)


@pytest.fixture
def mock_jira_config():
    """Create a mock JiraDefectClientConfig."""
    with patch.dict(
        "os.environ", {"JIRA_USERNAME": "test@example.com", "JIRA_PASSWORD": "token123"}
    ):
        return JiraDefectClientConfig(
            server_url="https://test.atlassian.net",
            auth_type="basic",
            attributes=["title", "status", "priority"],
            control_fields=["status", "priority", "classification"],
            readonly=False,
            show_change_history=True,
        )


@pytest.fixture
def mock_jira_client_instance(mock_jira_config):
    """Create a JiraDefectClient instance with mocked dependencies."""
    with patch("testbench_defect_service.clients.jira.client.JiraClient"):
        client = JiraDefectClient(mock_jira_config)

        # Ensure the mock JiraClient defaults to Cloud mode
        client.jira_client.use_issuetypes_endpoint = False

        # Mock the projects property
        mock_project = Mock()
        mock_project.name = "Test Project"
        mock_project.key = "TEST"
        mock_project.id = "10001"
        client._projects = {"Test Project (TEST)": mock_project}

        yield client


@pytest.fixture
def sample_defect_with_id():
    """Create a sample DefectWithID for testing."""
    return DefectWithID(
        id=DefectID(root="TEST-123"),
        title="Test Bug",
        description="Test Description",
        status="Open",
        classification="Bug",
        priority="High",
        reporter="John Doe",
        lastEdited=datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc),
        references=["https://example.com/attachment.png"],
        principal=Login(username="test", password="test"),
        userDefinedFields=[UserDefinedFieldProperties(name="Environment", value="Production")],
    )


@pytest.fixture
def sample_defect():
    """Create a sample Defect for testing."""
    return Defect(
        title="Test Bug",
        description="Test Description",
        status="Open",
        classification="Bug",
        priority="High",
        reporter="John Doe",
        lastEdited=datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc),
        principal=Login(username="test", password="test"),
    )


@pytest.fixture
def sample_defect_with_local_pk():
    """Create a sample DefectWithLocalPk for testing."""
    return DefectWithLocalPk(
        localPk="local-123",
        title="Test Bug",
        description="Test Description",
        status="Open",
        classification="Bug",
        priority="High",
        reporter="John Doe",
        lastEdited=datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc),
        principal=Login(username="test", password="test"),
    )


@pytest.fixture
def sample_known_defect():
    """Create a sample KnownDefect for testing."""
    return KnownDefect(
        id=DefectID(root="TEST-123"),
        localPk="local-123",
        title="Test Bug",
        description="Test Description",
        status="Open",
        classification="Bug",
        priority="High",
        reporter="John Doe",
        lastEdited=datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc),
        principal=Login(username="test", password="test"),
    )


@pytest.fixture
def sync_context():
    """Create a sample SyncContext."""
    return SyncContext(lastSync=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc))


def _make_project_mock(name: str = "Test Project", key: str = "TEST") -> Mock:
    p = Mock()
    p.name = name
    p.key = key
    return p


def _make_defect_with_id(**overrides) -> DefectWithID:
    defaults: dict[str, Any] = {
        "id": DefectID(root="TEST-1"),
        "title": "Bug",
        "description": "desc",
        "status": "Open",
        "classification": "Bug",
        "priority": "High",
        "reporter": None,
        "userDefinedFields": [],
        "lastEdited": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "references": [],
        "principal": Login(username="u", password="p"),
    }
    defaults.update(overrides)
    return DefectWithID(**defaults)


def _make_defect(**overrides) -> Defect:
    defaults: dict[str, Any] = {
        "title": "Bug",
        "description": "desc",
        "status": "Open",
        "classification": "Bug",
        "priority": "High",
        "reporter": None,
        "userDefinedFields": [],
        "lastEdited": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "references": [],
        "principal": Login(username="u", password="p"),
    }
    defaults.update(overrides)
    return Defect(**defaults)


@pytest.mark.unit
class TestCheckLogin:
    """Tests for check_login."""

    def test_returns_true_when_auth_ok_no_project(self, mock_jira_client_instance):
        mock_jira_client_instance.jira_client.jira.myself.return_value = {"name": "me"}
        assert mock_jira_client_instance.check_login(None) is True

    def test_returns_true_when_project_found(self, mock_jira_client_instance):
        mock_jira_client_instance.jira_client.jira.myself.return_value = {"name": "me"}
        assert mock_jira_client_instance.check_login("Test Project (TEST)") is True

    def test_returns_false_when_project_not_found(self, mock_jira_client_instance):
        mock_jira_client_instance.jira_client.jira.myself.return_value = {"name": "me"}
        assert mock_jira_client_instance.check_login("Unknown Project") is False

    def test_returns_false_on_value_error(self, mock_jira_client_instance):
        mock_jira_client_instance.jira_client.jira.myself.side_effect = ValueError("no auth")
        assert mock_jira_client_instance.check_login(None) is False

    def test_returns_false_on_runtime_error(self, mock_jira_client_instance):
        mock_jira_client_instance.jira_client.jira.myself.side_effect = RuntimeError("fail")
        assert mock_jira_client_instance.check_login(None) is False

    def test_returns_false_on_unexpected_exception(self, mock_jira_client_instance):
        mock_jira_client_instance.jira_client.jira.myself.side_effect = Exception("unexpected")
        assert mock_jira_client_instance.check_login(None) is False


@pytest.mark.unit
class TestGetSettings:
    def test_returns_settings_with_config_values(self, mock_jira_client_instance):
        result = mock_jira_client_instance.get_settings()
        assert result.name == "Jira"
        assert result.readonly is False

    def test_readonly_reflected_in_settings(self, mock_jira_client_instance):
        mock_jira_client_instance.config.readonly = True
        result = mock_jira_client_instance.get_settings()
        assert result.readonly is True


@pytest.mark.unit
class TestGetProjects:
    def test_returns_list_of_project_names(self, mock_jira_client_instance):
        result = mock_jira_client_instance.get_projects()
        assert "Test Project (TEST)" in result
        assert isinstance(result, list)

    def test_empty_when_no_projects(self, mock_jira_client_instance):
        mock_jira_client_instance._projects = {}
        mock_jira_client_instance.jira_client.fetch_projects.return_value = []
        result = mock_jira_client_instance.get_projects()
        assert result == []


@pytest.mark.unit
class TestGetControlFields:
    """Tests for get_control_fields method."""

    def test_control_fields_empty_projects(self, mock_jira_client_instance):
        """Test acquiring control fields when metadata returns empty projects list."""
        mock_jira_client_instance.jira_client.fetch_issues_fields = Mock(
            return_value={"projects": []}
        )

        result = mock_jira_client_instance.get_control_fields("Test Project (TEST)")
        assert result == {}

    def test_control_fields_basic(self, mock_jira_client_instance):
        """Test acquiring basic control fields from project metadata."""
        meta = {
            "projects": [
                {
                    "id": "10001",
                    "key": "TEST",
                    "issuetypes": [
                        {
                            "name": "Bug",
                            "fields": {
                                "customfield_10001": {
                                    "name": "Severity",
                                    "allowedValues": [
                                        {"name": "Critical"},
                                        {"name": "Major"},
                                        {"name": "Minor"},
                                    ],
                                }
                            },
                        }
                    ],
                }
            ]
        }

        mock_jira_client_instance.jira_client.fetch_issues_fields = Mock(return_value=meta)
        mock_jira_client_instance.config.control_fields = ["Severity"]

        result = mock_jira_client_instance.get_control_fields("Test Project (TEST)")

        assert "Severity" in result
        assert result["Severity"] == ["Critical", "Major", "Minor"]

    def test_control_fields_with_classification(self, mock_jira_client_instance):
        """Test acquiring control fields including classification."""
        meta = {
            "projects": [
                {
                    "id": "10001",
                    "key": "TEST",
                    "issuetypes": [
                        {"name": "Bug", "fields": {}},
                        {"name": "Task", "fields": {}},
                        {"name": "Story", "fields": {}},
                    ],
                }
            ]
        }

        mock_jira_client_instance.jira_client.fetch_issues_fields = Mock(return_value=meta)
        mock_jira_client_instance.config.control_fields = ["classification"]

        with patch.object(
            mock_jira_client_instance, "_add_class_issue_type_names"
        ) as mock_add_class:
            mock_jira_client_instance.get_control_fields("Test Project (TEST)")
            mock_add_class.assert_called_once()

    def test_control_fields_with_status(self, mock_jira_client_instance):
        """Test acquiring control fields including status."""
        meta = {
            "projects": [
                {
                    "id": "10001",
                    "key": "TEST",
                    "issuetypes": [{"name": "Bug", "fields": {}}],
                }
            ]
        }

        mock_jira_client_instance.jira_client.fetch_issues_fields = Mock(return_value=meta)
        mock_jira_client_instance.config.control_fields = ["status"]

        with patch.object(
            mock_jira_client_instance, "_add_control_field_statuses"
        ) as mock_add_status:
            mock_jira_client_instance.get_control_fields("Test Project (TEST)")
            mock_add_status.assert_called_once()

    def test_control_fields_field_without_allowed_values(self, mock_jira_client_instance):
        """Test handling fields without allowedValues."""
        meta = {
            "projects": [
                {
                    "id": "10001",
                    "key": "TEST",
                    "issuetypes": [
                        {
                            "name": "Bug",
                            "fields": {
                                "customfield_10001": {
                                    "name": "Description",
                                    "schema": {"type": "string"},
                                }
                            },
                        }
                    ],
                }
            ]
        }

        mock_jira_client_instance.jira_client.fetch_issues_fields = Mock(return_value=meta)
        mock_jira_client_instance.config.control_fields = ["Description"]

        result = mock_jira_client_instance.get_control_fields("Test Project (TEST)")

        # Field without allowedValues should not be included
        assert "Description" not in result

    def test_control_fields_empty_fields(self, mock_jira_client_instance):
        """Test handling issue types with empty fields dict."""
        meta = {
            "projects": [
                {
                    "id": "10001",
                    "key": "TEST",
                    "issuetypes": [
                        {
                            "name": "Bug",
                            "fields": {},
                        }
                    ],
                }
            ]
        }

        mock_jira_client_instance.jira_client.fetch_issues_fields = Mock(return_value=meta)
        mock_jira_client_instance.config.control_fields = ["Severity"]

        result = mock_jira_client_instance.get_control_fields("Test Project (TEST)")
        assert isinstance(result, dict)

    def test_control_fields_multiple_issue_types(self, mock_jira_client_instance):
        """Test acquiring control fields from multiple issue types."""
        meta = {
            "projects": [
                {
                    "id": "10001",
                    "key": "TEST",
                    "issuetypes": [
                        {
                            "name": "Bug",
                            "fields": {
                                "customfield_10001": {
                                    "name": "Severity",
                                    "allowedValues": [{"name": "High"}, {"name": "Low"}],
                                }
                            },
                        },
                        {
                            "name": "Task",
                            "fields": {
                                "customfield_10002": {
                                    "name": "Priority",
                                    "allowedValues": [{"name": "P1"}, {"name": "P2"}],
                                }
                            },
                        },
                    ],
                }
            ]
        }

        mock_jira_client_instance.jira_client.fetch_issues_fields = Mock(return_value=meta)
        mock_jira_client_instance.config.control_fields = ["Severity", "Priority"]

        result = mock_jira_client_instance.get_control_fields("Test Project (TEST)")

        assert "Severity" in result
        assert "Priority" in result
        assert result["Severity"] == ["High", "Low"]
        assert result["Priority"] == ["P1", "P2"]

    def test_add_control_field_statuses_project_specific(self, mock_jira_client_instance):
        """Test _add_control_field_statuses uses project-specific endpoint."""
        # Simulate response from GET /rest/api/2/project/{key}/statuses
        mock_jira_client_instance.jira_client.fetch_project_statuses = Mock(
            return_value=["Defined", "Done", "In Progress", "Rejected"]
        )

        control_fields_name = ["status"]
        projects = [{"id": "10001", "key": "TEST"}]
        control_fields: dict[str, list[str]] = {}

        mock_jira_client_instance._add_control_field_statuses(
            control_fields_name, projects, control_fields, "TEST"
        )

        mock_jira_client_instance.jira_client.fetch_project_statuses.assert_called_once_with("TEST")
        assert "status" in control_fields
        assert control_fields["status"] == ["Defined", "Done", "In Progress", "Rejected"]
        assert "status" not in control_fields_name

    def test_add_control_field_statuses_fallback_to_global(self, mock_jira_client_instance):
        """Test _add_control_field_statuses falls back to global statuses() when project endpoint
        returns empty."""
        # Project-specific endpoint returns nothing
        mock_jira_client_instance.jira_client.fetch_project_statuses = Mock(return_value=[])

        # Setup global statuses fallback
        mock_status_scoped = Mock()
        mock_status_scoped.__str__ = Mock(return_value="Open")
        mock_status_scoped.scope.project.id = "10001"

        mock_status_scoped_2 = Mock()
        mock_status_scoped_2.__str__ = Mock(return_value="Closed")
        mock_status_scoped_2.scope.project.id = "10001"

        mock_jira_client_instance.jira_client.jira.statuses = Mock(
            return_value=[mock_status_scoped, mock_status_scoped_2]
        )

        control_fields_name = ["status"]
        projects = [{"id": "10001", "key": "TEST"}]
        control_fields: dict[str, list[str]] = {}

        mock_jira_client_instance._add_control_field_statuses(
            control_fields_name, projects, control_fields, "TEST"
        )

        assert "status" in control_fields
        assert "Open" in control_fields["status"]
        assert "Closed" in control_fields["status"]
        assert "status" not in control_fields_name

    def test_control_fields_with_status_calls_add_statuses(self, mock_jira_client_instance):
        """Test get_control_fields calls _add_control_field_statuses with project_key."""
        meta = {
            "projects": [
                {
                    "id": "10001",
                    "key": "TEST",
                    "issuetypes": [{"name": "Bug", "fields": {}}],
                }
            ]
        }

        mock_jira_client_instance.jira_client.fetch_issues_fields = Mock(return_value=meta)
        mock_jira_client_instance.config.control_fields = ["status"]

        with patch.object(
            mock_jira_client_instance, "_add_control_field_statuses"
        ) as mock_add_status:
            mock_jira_client_instance.get_control_fields("Test Project (TEST)")
            mock_add_status.assert_called_once_with(
                ["status"],
                [{"id": "10001", "key": "TEST", "issuetypes": [{"name": "Bug", "fields": {}}]}],
                {},
                "TEST",
            )


@pytest.mark.unit
class TestGetDefects:
    def _setup(self):
        mock_issue = Mock()
        mock_issue.key = "TEST-1"
        mock_issue.fields.summary = "Bug"
        mock_issue.fields.description = "desc"
        mock_issue.fields.updated = "2024-01-01T00:00:00.000+0000"
        mock_issue.fields.status.name = "Open"
        mock_issue.fields.priority.name = "High"
        mock_issue.fields.issuetype.name = "Bug"
        mock_issue.fields.creator = Mock()
        mock_issue.fields.creator.displayName = "Alice"
        mock_issue.fields.attachment = []
        return mock_issue

    def test_returns_defects_for_valid_project(self, mock_jira_client_instance, sync_context):
        mock_issue = self._setup()
        mock_jira_client_instance.jira_client.fetch_issues_by_jql.return_value = [mock_issue]
        mock_jira_client_instance.jira_client.fetch_all_custom_fields.return_value = []

        with patch("testbench_defect_service.clients.jira.client.create_defect_from_issue") as m:
            m.return_value = _make_defect_with_id()
            result = mock_jira_client_instance.get_defects("Test Project (TEST)", sync_context)

        assert isinstance(result, ProtocolledDefectSet)
        assert len(result.value) == 1

    def test_adds_error_protocol_when_issue_conversion_fails(
        self, mock_jira_client_instance, sync_context
    ):
        mock_issue = self._setup()
        mock_jira_client_instance.jira_client.fetch_issues_by_jql.return_value = [mock_issue]
        mock_jira_client_instance.jira_client.fetch_all_custom_fields.return_value = []

        with patch(
            "testbench_defect_service.clients.jira.client.create_defect_from_issue",
            side_effect=ValueError("bad"),
        ):
            result = mock_jira_client_instance.get_defects("Test Project (TEST)", sync_context)

        assert result.protocol.errors

    def test_returns_general_error_for_unknown_project(
        self, mock_jira_client_instance, sync_context
    ):
        result = mock_jira_client_instance.get_defects("Unknown Project", sync_context)
        assert result.protocol.generalErrors

    def test_adds_general_error_when_no_issues_found(self, mock_jira_client_instance, sync_context):
        mock_jira_client_instance.jira_client.fetch_issues_by_jql.return_value = []
        mock_jira_client_instance.jira_client.fetch_all_custom_fields.return_value = []

        result = mock_jira_client_instance.get_defects("Test Project (TEST)", sync_context)
        assert result.protocol.generalErrors


@pytest.mark.unit
class TestGetDefectsBatch:
    def test_returns_defects_for_valid_ids(self, mock_jira_client_instance, sync_context):
        mock_issue = Mock()
        mock_issue.key = "TEST-1"
        mock_jira_client_instance.jira_client.fetch_issue.return_value = mock_issue
        mock_jira_client_instance.jira_client.fetch_all_custom_fields.return_value = []

        with patch("testbench_defect_service.clients.jira.client.create_defect_from_issue") as m:
            m.return_value = _make_defect_with_id()
            result = mock_jira_client_instance.get_defects_batch(
                "Test Project (TEST)", [DefectID(root="TEST-1")], sync_context
            )

        assert len(result.value) == 1

    def test_adds_warning_when_issue_not_found(self, mock_jira_client_instance, sync_context):
        mock_jira_client_instance.jira_client.fetch_issue.return_value = None
        mock_jira_client_instance.jira_client.fetch_all_custom_fields.return_value = []

        result = mock_jira_client_instance.get_defects_batch(
            "Test Project (TEST)", [DefectID(root="MISSING-1")], sync_context
        )
        assert result.protocol.warnings

    def test_returns_error_for_unknown_project(self, mock_jira_client_instance, sync_context):
        result = mock_jira_client_instance.get_defects_batch(
            "Unknown Project", [DefectID(root="X-1")], sync_context
        )
        assert result.protocol.generalErrors

    def test_skips_empty_defect_ids(self, mock_jira_client_instance, sync_context):
        mock_jira_client_instance.jira_client.fetch_all_custom_fields.return_value = []
        result = mock_jira_client_instance.get_defects_batch(
            "Test Project (TEST)", [None], sync_context
        )
        mock_jira_client_instance.jira_client.fetch_issue.assert_not_called()
        assert result.value == []

    def test_adds_error_when_conversion_fails(self, mock_jira_client_instance, sync_context):
        mock_issue = Mock()
        mock_issue.key = "TEST-1"
        mock_jira_client_instance.jira_client.fetch_issue.return_value = mock_issue
        mock_jira_client_instance.jira_client.fetch_all_custom_fields.return_value = []

        with patch(
            "testbench_defect_service.clients.jira.client.create_defect_from_issue",
            side_effect=ValueError("bad"),
        ):
            result = mock_jira_client_instance.get_defects_batch(
                "Test Project (TEST)", [DefectID(root="TEST-1")], sync_context
            )
        assert result.protocol.errors


@pytest.mark.unit
class TestCreateDefect:
    def test_creates_issue_and_returns_key(self, mock_jira_client_instance, sync_context):
        defect = _make_defect()
        mock_issue = Mock()
        mock_issue.key = "TEST-99"
        with patch("testbench_defect_service.clients.jira.client.JiraClient") as mock_jira:
            per_user = Mock()
            per_user.create_issue.return_value = mock_issue
            mock_jira.return_value = per_user

            result = mock_jira_client_instance.create_defect(
                "Test Project (TEST)", defect, sync_context
            )
        assert result.value == "TEST-99"
        assert result.protocol.successes

    def test_returns_error_for_readonly_project(self, mock_jira_client_instance, sync_context):
        mock_jira_client_instance.config.readonly = True
        defect = _make_defect()

        result = mock_jira_client_instance.create_defect(
            "Test Project (TEST)", defect, sync_context
        )
        assert result.protocol.errors
        assert result.value == ""

    def test_returns_error_for_unknown_project(self, mock_jira_client_instance, sync_context):
        defect = _make_defect()

        result = mock_jira_client_instance.create_defect("Unknown Project", defect, sync_context)
        assert result.protocol.generalErrors

    def test_returns_error_on_create_failure(self, mock_jira_client_instance, sync_context):
        defect = _make_defect()
        mock_jira_client_instance.jira_client.create_issue.side_effect = ValueError("fail")

        result = mock_jira_client_instance.create_defect(
            "Test Project (TEST)", defect, sync_context
        )
        assert result.protocol.generalErrors

    def test_uses_shared_auth_when_configured(self, mock_jira_client_instance, sync_context):
        mock_jira_client_instance.config.projects["Test Project (TEST)"] = JiraProjectConfig(
            enable_shared_auth=True
        )
        defect = _make_defect()
        mock_issue = Mock()
        mock_issue.key = "TEST-1"
        mock_jira_client_instance.jira_client.create_issue.return_value = mock_issue

        with patch("testbench_defect_service.clients.jira.client.JiraClient") as mock_jira:
            result = mock_jira_client_instance.create_defect(
                "Test Project (TEST)", defect, sync_context
            )
            mock_jira.assert_not_called()

        assert result.value == "TEST-1"

    def test_uses_per_user_auth_by_default(self, mock_jira_client_instance, sync_context):
        defect = _make_defect()
        with patch("testbench_defect_service.clients.jira.client.JiraClient") as mock_jira:
            per_user_client = Mock()
            per_user_client.create_issue.return_value = Mock(key="TEST-2")
            mock_jira.return_value = per_user_client

            result = mock_jira_client_instance.create_defect(
                "Test Project (TEST)", defect, sync_context
            )
            mock_jira.assert_called_once()

        assert result.value == "TEST-2"


@pytest.mark.unit
class TestUpdateDefect:
    def test_updates_issue_successfully(self, mock_jira_client_instance, sync_context):
        mock_jira_client_instance.config.projects["Test Project (TEST)"] = JiraProjectConfig(
            enable_shared_auth=True
        )
        defect = _make_defect()
        mock_issue = Mock()
        mock_issue.key = "TEST-1"
        mock_jira_client_instance.jira_client.fetch_issue.return_value = mock_issue

        result = mock_jira_client_instance.update_defect(
            "Test Project (TEST)", "TEST-1", defect, sync_context
        )
        mock_jira_client_instance.jira_client.update_issue.assert_called_once()
        assert result.successes

    def test_returns_error_for_readonly_project(self, mock_jira_client_instance, sync_context):
        mock_jira_client_instance.config.readonly = True
        defect = _make_defect()

        result = mock_jira_client_instance.update_defect(
            "Test Project (TEST)", "TEST-1", defect, sync_context
        )
        assert result.errors

    def test_returns_error_for_unknown_project(self, mock_jira_client_instance, sync_context):
        defect = _make_defect()
        result = mock_jira_client_instance.update_defect(
            "Unknown Project", "X-1", defect, sync_context
        )
        assert result.generalErrors

    def test_returns_error_when_issue_not_found(self, mock_jira_client_instance, sync_context):
        defect = _make_defect()
        mock_jira_client_instance.jira_client.fetch_issue.return_value = None

        result = mock_jira_client_instance.update_defect(
            "Test Project (TEST)", "TEST-1", defect, sync_context
        )
        assert result.generalErrors

    def test_returns_error_on_update_failure(self, mock_jira_client_instance, sync_context):
        defect = _make_defect()
        mock_issue = Mock()
        mock_issue.key = "TEST-1"
        mock_jira_client_instance.jira_client.fetch_issue.return_value = mock_issue
        mock_jira_client_instance.jira_client.update_issue.side_effect = ValueError("fail")

        result = mock_jira_client_instance.update_defect(
            "Test Project (TEST)", "TEST-1", defect, sync_context
        )
        assert result.generalErrors


@pytest.mark.unit
class TestDeleteDefect:
    def test_deletes_issue_successfully(self, mock_jira_client_instance, sync_context):
        mock_jira_client_instance.config.projects["Test Project (TEST)"] = JiraProjectConfig(
            enable_shared_auth=True
        )
        defect = _make_defect()
        mock_issue = Mock()
        mock_issue.key = "TEST-1"
        mock_jira_client_instance.jira_client.fetch_issue.return_value = mock_issue

        result = mock_jira_client_instance.delete_defect(
            "Test Project (TEST)", "TEST-1", defect, sync_context
        )
        mock_jira_client_instance.jira_client.delete_issue.assert_called_once_with(mock_issue)
        assert result.successes

    def test_returns_error_for_readonly_project(self, mock_jira_client_instance, sync_context):
        mock_jira_client_instance.config.readonly = True
        defect = _make_defect()

        result = mock_jira_client_instance.delete_defect(
            "Test Project (TEST)", "TEST-1", defect, sync_context
        )
        assert result.errors

    def test_returns_error_for_unknown_project(self, mock_jira_client_instance, sync_context):
        defect = _make_defect()
        result = mock_jira_client_instance.delete_defect(
            "Unknown Project", "X-1", defect, sync_context
        )
        assert result.generalErrors

    def test_returns_error_when_issue_not_found(self, mock_jira_client_instance, sync_context):
        defect = _make_defect()
        mock_jira_client_instance.jira_client.fetch_issue.return_value = None

        result = mock_jira_client_instance.delete_defect(
            "Test Project (TEST)", "TEST-1", defect, sync_context
        )
        assert result.generalErrors

    def test_returns_error_on_delete_failure(self, mock_jira_client_instance, sync_context):
        defect = _make_defect()
        mock_issue = Mock()
        mock_issue.key = "TEST-1"
        mock_jira_client_instance.jira_client.fetch_issue.return_value = mock_issue
        mock_jira_client_instance.jira_client.delete_issue.side_effect = ValueError("fail")

        result = mock_jira_client_instance.delete_defect(
            "Test Project (TEST)", "TEST-1", defect, sync_context
        )
        assert result.generalErrors


@pytest.mark.unit
class TestGetDefectExtended:
    def _setup_issue(self):
        issue = Mock()
        issue.key = "TEST-1"
        issue.changelog = Mock(histories=[])
        issue.fields.summary = "Bug"
        issue.fields.description = "desc"
        issue.fields.updated = "2024-01-01T00:00:00.000+0000"
        issue.fields.status.name = "Open"
        issue.fields.priority.name = "High"
        issue.fields.issuetype.name = "Bug"
        issue.fields.creator = Mock(displayName="Alice")
        issue.fields.attachment = []
        return issue

    def test_returns_defect_with_attributes(self, mock_jira_client_instance, sync_context):
        issue = self._setup_issue()
        mock_jira_client_instance.jira_client.fetch_issue.return_value = issue
        mock_jira_client_instance.jira_client.fetch_issue_fields.return_value = {}
        mock_jira_client_instance.config.show_change_history = False

        with patch("testbench_defect_service.clients.jira.client.create_defect_from_issue") as m:
            m.return_value = _make_defect_with_id()
            result = mock_jira_client_instance.get_defect_extended(
                "Test Project (TEST)", "TEST-1", sync_context
            )

        assert result.attributes is not None

    def test_raises_not_found_when_issue_missing(self, mock_jira_client_instance, sync_context):
        mock_jira_client_instance.jira_client.fetch_issue.return_value = None

        with pytest.raises(NotFound):
            mock_jira_client_instance.get_defect_extended(
                "Test Project (TEST)", "MISSING-1", sync_context
            )

    def test_raises_server_error_on_conversion_failure(
        self, mock_jira_client_instance, sync_context
    ):
        issue = self._setup_issue()
        mock_jira_client_instance.jira_client.fetch_issue.return_value = issue
        mock_jira_client_instance.jira_client.fetch_issue_fields.return_value = {}

        with (
            patch(
                "testbench_defect_service.clients.jira.client.create_defect_from_issue",
                side_effect=ValueError("bad"),
            ),
            pytest.raises(ServerError),
        ):
            mock_jira_client_instance.get_defect_extended(
                "Test Project (TEST)", "TEST-1", sync_context
            )


@pytest.mark.unit
class TestGetUserDefinedAttributes:
    def test_returns_user_defined_attributes(self, mock_jira_client_instance):
        mock_jira_client_instance.jira_client.fetch_all_custom_fields.return_value = [
            {"name": "Environment", "schema": {"type": "string"}},
            {"name": "Team", "schema": {"type": "string"}},
        ]
        result = mock_jira_client_instance.get_user_defined_attributes("Test Project (TEST)")
        assert len(result) == 2
        names = {attr.name for attr in result}
        assert "Environment" in names
        assert "Team" in names

    def test_raises_not_found_when_no_project(self, mock_jira_client_instance):
        with pytest.raises(NotFound):
            mock_jira_client_instance.get_user_defined_attributes(None)

    def test_raises_not_found_for_unknown_project(self, mock_jira_client_instance):
        with pytest.raises(NotFound):
            mock_jira_client_instance.get_user_defined_attributes("Unknown Project")

    def test_returns_empty_list_when_no_custom_fields(self, mock_jira_client_instance):
        mock_jira_client_instance.jira_client.fetch_all_custom_fields.return_value = []
        result = mock_jira_client_instance.get_user_defined_attributes("Test Project (TEST)")
        assert result == []


@pytest.mark.unit
class TestSyncHooks:
    def test_before_sync_delegates_to_execute_hook(self, mock_jira_client_instance):
        sync_type = "manual"
        sync_context = SyncContext(lastSync=datetime(2024, 1, 1, tzinfo=timezone.utc))

        result = mock_jira_client_instance.before_sync(
            "Test Project (TEST)", sync_type, sync_context
        )
        assert isinstance(result, Protocol)

    def test_after_sync_delegates_to_execute_hook(self, mock_jira_client_instance):
        sync_type = "manual"
        sync_context = SyncContext(lastSync=datetime(2024, 1, 1, tzinfo=timezone.utc))

        result = mock_jira_client_instance.after_sync(
            "Test Project (TEST)", sync_type, sync_context
        )
        assert isinstance(result, Protocol)


@pytest.mark.unit
class TestSupportsChangesTimestamps:
    def test_delegates_to_config(self, mock_jira_client_instance):
        mock_jira_client_instance.config.supports_changes_timestamps = True
        assert mock_jira_client_instance.supports_changes_timestamps() is True

    def test_returns_false_when_config_false(self, mock_jira_client_instance):
        mock_jira_client_instance.config.supports_changes_timestamps = False
        assert mock_jira_client_instance.supports_changes_timestamps() is False


@pytest.mark.unit
class TestCorrectSyncResults:
    def _make_known_defect(self, issue_type: str = "Bug") -> KnownDefect:
        return KnownDefect(
            id=DefectID(root="TEST-1"),
            localPk="local-1",
            title="Bug",
            description="desc",
            status="Open",
            classification=issue_type,
            priority="High",
            lastEdited=datetime(2024, 1, 1, tzinfo=timezone.utc),
            principal=Login(username="u", password="p"),
        )

    def _mock_jira_resources(self, mock_client):
        status = Mock()
        status.name = "Open"
        priority = Mock()
        priority.name = "High"
        issue_type = Mock()
        issue_type.name = "Bug"
        mock_client.jira_client.jira.statuses.return_value = [status]
        mock_client.jira_client.jira.priorities.return_value = [priority]
        mock_client.jira_client.jira.issue_types.return_value = [issue_type]

    def test_returns_results_object(self, mock_jira_client_instance):
        self._mock_jira_resources(mock_jira_client_instance)
        mock_jira_client_instance.jira_client.fetch_issues_fields.return_value = {}

        body = Results(
            local=LocalSyncActions(create=[], update=[], delete=[]),
            remote=RemoteSyncActions(create=[], update=[], delete=[]),
        )
        result = mock_jira_client_instance.correct_sync_results("Test Project (TEST)", body)
        assert isinstance(result, Results)

    def test_valid_defects_are_kept(self, mock_jira_client_instance):
        self._mock_jira_resources(mock_jira_client_instance)
        mock_jira_client_instance.jira_client.fetch_issues_fields.return_value = {}

        known = self._make_known_defect()
        body = Results(
            local=LocalSyncActions(create=[known], update=[], delete=[]),
            remote=None,
        )
        result = mock_jira_client_instance.correct_sync_results("Test Project (TEST)", body)
        assert len(result.local.create) == 1

    def test_invalid_defects_are_filtered_out(self, mock_jira_client_instance):
        self._mock_jira_resources(mock_jira_client_instance)
        mock_jira_client_instance.jira_client.fetch_issues_fields.return_value = {}

        invalid = self._make_known_defect(issue_type="UnknownType")
        body = Results(
            local=LocalSyncActions(create=[invalid], update=[], delete=[]),
            remote=None,
        )
        result = mock_jira_client_instance.correct_sync_results("Test Project (TEST)", body)
        assert result.local.create == []

    def test_none_local_and_remote_handled(self, mock_jira_client_instance):
        body = Results(local=None, remote=None)
        result = mock_jira_client_instance.correct_sync_results("Test Project (TEST)", body)
        assert result.local is None
        assert result.remote is None


@pytest.mark.unit
class TestGetConfigValue:
    """Tests for _get_config_value method."""

    def test_get_global_config_value(self, mock_jira_client_instance):
        """Test retrieving global configuration value."""
        result = mock_jira_client_instance._get_config_value("readonly")
        assert result is False

    def test_get_project_specific_config_value(self, mock_jira_client_instance):
        """Test retrieving project-specific configuration value."""
        # Add project-specific config
        mock_jira_client_instance.config.projects["Test Project (TEST)"] = JiraProjectConfig(
            readonly=True
        )

        result = mock_jira_client_instance._get_config_value(
            "readonly", project="Test Project (TEST)"
        )
        assert result is True

    def test_get_config_value_fallback_to_global(self, mock_jira_client_instance):
        """Test fallback to global config when project config doesn't have the attribute."""
        mock_jira_client_instance.config.projects["Test Project (TEST)"] = JiraProjectConfig()

        result = mock_jira_client_instance._get_config_value(
            "readonly", project="Test Project (TEST)"
        )
        assert result is False

    def test_get_config_value_nonexistent_attribute(self, mock_jira_client_instance):
        """Test retrieving non-existent attribute returns None."""
        result = mock_jira_client_instance._get_config_value("nonexistent_attr")
        assert result is None

    def test_get_config_value_for_nonexistent_project(self, mock_jira_client_instance):
        """Test retrieving config for non-existent project falls back to global."""
        result = mock_jira_client_instance._get_config_value(
            "readonly", project="Nonexistent Project"
        )
        assert result is False


@pytest.mark.unit
class TestBuildDefectWithAttributes:
    """Tests for _build_defect_with_attributes method."""

    def test_build_with_static_attributes(
        self, mock_jira_client_instance, sample_defect_with_id, sync_context
    ):
        """Test building defect with static attributes (no change history)."""
        mock_jira_client_instance.config.show_change_history = False

        fields = [
            {"id": "status", "name": "Status"},
            {"id": "priority", "name": "Priority"},
        ]

        result = mock_jira_client_instance._build_defect_with_attributes(
            defect=sample_defect_with_id,
            project="Test Project (TEST)",
            changelog=None,
            fields=fields,
            sync_context=sync_context,
        )

        assert isinstance(result.attributes, ExtendedAttributes)
        assert result.id == sample_defect_with_id.id
        assert result.title == sample_defect_with_id.title

    def test_build_with_changelog_attributes(
        self, mock_jira_client_instance, sample_defect_with_id, sync_context
    ):
        """Test building defect with changelog attributes."""
        mock_jira_client_instance.config.show_change_history = True

        # Mock changelog
        mock_changelog = Mock()
        mock_changelog.histories = []

        fields = [
            {"id": "status", "name": "Status"},
            {"id": "priority", "name": "Priority"},
        ]

        with patch(
            "testbench_defect_service.clients.jira.client.extract_changelog_attributes"
        ) as mock_extract:
            mock_extract.return_value = None

            result = mock_jira_client_instance._build_defect_with_attributes(
                defect=sample_defect_with_id,
                project="Test Project (TEST)",
                changelog=mock_changelog,
                fields=fields,
                sync_context=sync_context,
            )

            assert isinstance(result.attributes, ExtendedAttributes)
            mock_extract.assert_called_once()

    def test_build_preserves_defect_data(
        self, mock_jira_client_instance, sample_defect_with_id, sync_context
    ):
        """Test that building preserves all defect data."""
        mock_jira_client_instance.config.show_change_history = False

        result = mock_jira_client_instance._build_defect_with_attributes(
            defect=sample_defect_with_id,
            project="Test Project (TEST)",
            changelog=None,
            fields=[],
            sync_context=sync_context,
        )

        assert result.title == sample_defect_with_id.title
        assert result.description == sample_defect_with_id.description
        assert result.status == sample_defect_with_id.status
        assert result.priority == sample_defect_with_id.priority


@pytest.mark.unit
class TestExecuteSyncHook:
    """Tests for _execute_sync_hook method."""

    def test_execute_hook_no_command_configured(self, mock_jira_client_instance):
        """Test executing hook when no command is configured."""
        sync_type = "manual"

        protocol = mock_jira_client_instance._execute_sync_hook(
            project="Test Project (TEST)", sync_type=sync_type, hook_type="presync"
        )

        assert "Test Project (TEST)" in protocol.successes
        assert len(protocol.successes["Test Project (TEST)"]) == 1
        assert "no command configured" in protocol.successes["Test Project (TEST)"][0].message

    def test_execute_hook_unsupported_extension(self, mock_jira_client_instance, tmp_path):
        """Test executing hook with unsupported file extension."""
        # Create a test file with unsupported extension
        test_script = tmp_path / "script.txt"
        test_script.write_text("echo test")

        # Configure hook
        mock_jira_client_instance.config.commands = PhaseCommands(
            presync=SyncCommandConfig(manual=str(test_script))
        )

        sync_type = "manual"

        protocol = mock_jira_client_instance._execute_sync_hook(
            project="Test Project (TEST)", sync_type=sync_type, hook_type="presync"
        )

        # Should return empty protocol (warning logged)
        assert not protocol.successes or len(protocol.successes) == 0
        assert not protocol.errors or len(protocol.errors) == 0

    def test_execute_hook_nonexistent_file(self, mock_jira_client_instance):
        """Test executing hook when file doesn't exist."""
        # Configure hook with non-existent file
        mock_jira_client_instance.config.commands = PhaseCommands(
            presync=SyncCommandConfig(manual="/nonexistent/script.bat")
        )

        sync_type = "manual"

        protocol = mock_jira_client_instance._execute_sync_hook(
            project="Test Project (TEST)", sync_type=sync_type, hook_type="presync"
        )

        # Should return empty protocol (warning logged)
        assert not protocol.successes or len(protocol.successes) == 0
        assert not protocol.errors or len(protocol.errors) == 0

    @patch("subprocess.run")
    def test_execute_hook_success(self, mock_subprocess, mock_jira_client_instance, tmp_path):
        """Test successful hook execution."""
        # Create a test script
        test_script = tmp_path / "script.bat"
        test_script.write_text("@echo off\necho Success")

        # Configure hook
        mock_jira_client_instance.config.commands = PhaseCommands(
            postsync=SyncCommandConfig(scheduled=str(test_script))
        )

        sync_type = "scheduled"

        protocol = mock_jira_client_instance._execute_sync_hook(
            project="Test Project (TEST)", sync_type=sync_type, hook_type="postsync"
        )

        assert "Test Project (TEST)" in protocol.successes
        assert len(protocol.successes["Test Project (TEST)"]) == 1
        assert "executed successfully" in protocol.successes["Test Project (TEST)"][0].message
        assert protocol.successes["Test Project (TEST)"][0].code == ProtocolCode.PUBLISH_SUCCESS
        mock_subprocess.assert_called_once()

    @patch("subprocess.run")
    def test_execute_hook_command_failure(
        self, mock_subprocess, mock_jira_client_instance, tmp_path
    ):
        """Test hook execution when command fails."""
        # Create a test script
        test_script = tmp_path / "script.sh"
        test_script.write_text("#!/bin/bash\nexit 1")

        # Configure hook
        mock_jira_client_instance.config.commands = PhaseCommands(
            presync=SyncCommandConfig(manual=str(test_script))
        )

        # Mock subprocess to raise CalledProcessError
        mock_subprocess.side_effect = subprocess.CalledProcessError(1, "cmd")

        sync_type = "manual"

        protocol = mock_jira_client_instance._execute_sync_hook(
            project="Test Project (TEST)", sync_type=sync_type, hook_type="presync"
        )

        assert len(protocol.generalErrors) == 1
        assert "failed with return code" in protocol.generalErrors[0].message
        assert protocol.generalErrors[0].code == ProtocolCode.PUBLISH_ERROR

    @patch("subprocess.run")
    def test_execute_hook_os_error(self, mock_subprocess, mock_jira_client_instance, tmp_path):
        """Test hook execution when OS error occurs."""
        # Create a test script
        test_script = tmp_path / "script.exe"
        test_script.write_text("test")

        # Configure hook
        mock_jira_client_instance.config.commands = PhaseCommands(
            presync=SyncCommandConfig(partial=str(test_script))
        )

        # Mock subprocess to raise OSError
        mock_subprocess.side_effect = OSError("Permission denied")

        sync_type = "partial"

        protocol = mock_jira_client_instance._execute_sync_hook(
            project="Test Project (TEST)", sync_type=sync_type, hook_type="presync"
        )

        assert len(protocol.generalErrors) == 1
        assert "could not be executed" in protocol.generalErrors[0].message

    def test_execute_hook_project_specific_command(self, mock_jira_client_instance, tmp_path):
        """Test executing project-specific hook command."""
        # Create test script
        test_script = tmp_path / "project_script.bat"
        test_script.write_text("echo test")

        # Configure project-specific hook
        mock_jira_client_instance.config.projects["Test Project (TEST)"] = JiraProjectConfig(
            commands=PhaseCommands(postsync=SyncCommandConfig(manual=str(test_script)))
        )

        sync_type = "manual"

        with patch("subprocess.run"):
            protocol = mock_jira_client_instance._execute_sync_hook(
                project="Test Project (TEST)", sync_type=sync_type, hook_type="postsync"
            )

            assert "Test Project (TEST)" in protocol.successes
            assert len(protocol.successes["Test Project (TEST)"]) == 1


@pytest.mark.unit
class TestValidateDefect:
    """Tests for validate_defect method."""

    def test_validate_defect_valid(self, mock_jira_client_instance, sample_defect):
        """Test validation of a valid defect."""
        # Mock Jira resources
        mock_status = Mock()
        mock_status.name = "Open"

        mock_priority = Mock()
        mock_priority.name = "High"

        mock_issue_type = Mock()
        mock_issue_type.name = "Bug"

        control_fields = {}

        result = mock_jira_client_instance.validate_defect(
            defect=sample_defect,
            control_field=control_fields,
            statuses=[mock_status],
            priorities=[mock_priority],
            issue_types=[mock_issue_type],
        )

        assert result is True

    def test_validate_defect_missing_status(self, mock_jira_client_instance):
        """Test validation fails when status is missing."""
        defect = Defect(
            title="Test",
            description="Test",
            status="",
            classification="Bug",
            priority="High",
            lastEdited=datetime.now(timezone.utc),
            principal=Login(username="test", password="test"),
        )

        result = mock_jira_client_instance.validate_defect(
            defect=defect,
            control_field={},
            statuses=[],
            priorities=[],
            issue_types=[],
        )

        assert result is False

    def test_validate_defect_missing_classification(self, mock_jira_client_instance):
        """Test validation fails when classification is missing."""
        # Create a defect without required fields to cause validation failure
        defect = Defect(
            title="Test",
            description="Test",
            status="Open",
            classification="",
            priority="High",
            lastEdited=datetime.now(timezone.utc),
            principal=Login(username="test", password="test"),
        )

        result = mock_jira_client_instance.validate_defect(
            defect=defect,
            control_field={},
            statuses=[],
            priorities=[],
            issue_types=[],
        )

        assert result is False

    def test_validate_defect_invalid_status(self, mock_jira_client_instance, sample_defect):
        """Test validation fails when status is not in Jira statuses."""
        mock_status = Mock()
        mock_status.name = "Closed"

        mock_priority = Mock()
        mock_priority.name = "High"

        mock_issue_type = Mock()
        mock_issue_type.name = "Bug"

        result = mock_jira_client_instance.validate_defect(
            defect=sample_defect,
            control_field={},
            statuses=[mock_status],
            priorities=[mock_priority],
            issue_types=[mock_issue_type],
        )

        assert result is False

    def test_validate_defect_invalid_priority(self, mock_jira_client_instance, sample_defect):
        """Test validation fails when priority is not in Jira priorities."""
        mock_status = Mock()
        mock_status.name = "Open"

        mock_priority = Mock()
        mock_priority.name = "Low"

        mock_issue_type = Mock()
        mock_issue_type.name = "Bug"

        result = mock_jira_client_instance.validate_defect(
            defect=sample_defect,
            control_field={},
            statuses=[mock_status],
            priorities=[mock_priority],
            issue_types=[mock_issue_type],
        )

        assert result is False

    def test_validate_defect_invalid_classification(self, mock_jira_client_instance, sample_defect):
        """Test validation fails when classification is not in Jira issue types."""
        mock_status = Mock()
        mock_status.name = "Open"

        mock_priority = Mock()
        mock_priority.name = "High"

        mock_issue_type = Mock()
        mock_issue_type.name = "Story"

        result = mock_jira_client_instance.validate_defect(
            defect=sample_defect,
            control_field={},
            statuses=[mock_status],
            priorities=[mock_issue_type],
            issue_types=[mock_issue_type],
        )

        assert result is False

    def test_validate_defect_control_field_violation(self, mock_jira_client_instance):
        """Test validation fails when control field constraint is violated."""
        # Create a mock defect that has the severity attribute
        defect = Mock(spec=Defect)
        defect.title = "Test Bug"
        defect.description = "Test Description"
        defect.status = "Open"
        defect.classification = "Bug"
        defect.priority = "High"
        defect.reporter = "John Doe"
        defect.lastEdited = datetime.now(timezone.utc)
        defect.principal = Login(username="test", password="test")
        defect.severity = "Minor"

        mock_status = Mock()
        mock_status.name = "Open"

        mock_priority = Mock()
        mock_priority.name = "High"

        mock_issue_type = Mock()
        mock_issue_type.name = "Bug"

        # Add control field that defect doesn't satisfy
        control_fields = {"severity": ["Critical", "Major"]}

        result = mock_jira_client_instance.validate_defect(
            defect=defect,
            control_field=control_fields,
            statuses=[mock_status],
            priorities=[mock_priority],
            issue_types=[mock_issue_type],
        )

        assert result is False

    def test_validate_defect_with_defect_with_id(
        self, mock_jira_client_instance, sample_defect_with_id
    ):
        """Test validation works with DefectWithID objects."""
        mock_status = Mock()
        mock_status.name = "Open"

        mock_priority = Mock()
        mock_priority.name = "High"

        mock_issue_type = Mock()
        mock_issue_type.name = "Bug"

        result = mock_jira_client_instance.validate_defect(
            defect=sample_defect_with_id,
            control_field={},
            statuses=[mock_status],
            priorities=[mock_priority],
            issue_types=[mock_issue_type],
        )

        assert result is True


@pytest.mark.unit
class TestValidateAndFilterActions:
    """Tests for _validate_and_filter_actions method."""

    def test_filter_all_valid_defects(
        self, mock_jira_client_instance, sample_defect_with_local_pk, sample_known_defect
    ):
        """Test filtering when all defects are valid."""
        source = RemoteSyncActions(
            create=[sample_defect_with_local_pk],
            update=[sample_known_defect],
        )
        target = RemoteSyncActions()

        # Mock the validation methods
        mock_jira_client_instance.jira_client.fetch_issues_fields = Mock(
            return_value={"projects": []}
        )
        mock_jira_client_instance.jira_client.jira.statuses = Mock(return_value=[])
        mock_jira_client_instance.jira_client.jira.priorities = Mock(return_value=[])
        mock_jira_client_instance.jira_client.jira.issue_types = Mock(return_value=[])

        with patch.object(mock_jira_client_instance, "validate_defect", return_value=True):  # noqa: SIM117
            with patch.object(mock_jira_client_instance, "get_control_fields", return_value={}):
                mock_jira_client_instance._validate_and_filter_actions(
                    source, target, "Test Project (TEST)"
                )

        assert len(target.create) == 1
        assert len(target.update) == 1

    def test_filter_invalid_defects(
        self, mock_jira_client_instance, sample_defect_with_local_pk, sample_known_defect
    ):
        """Test filtering when some defects are invalid."""
        invalid_defect_create = DefectWithLocalPk(
            localPk="local-invalid",
            title="Invalid",
            description="Invalid",
            status="",
            classification="Bug",
            priority="High",
            lastEdited=datetime.now(timezone.utc),
            principal=Login(username="test", password="test"),
        )

        invalid_defect_update = KnownDefect(
            id=DefectID(root="TEST-456"),
            localPk="local-invalid-2",
            title="Invalid",
            description="Invalid",
            status="",
            classification="Bug",
            priority="High",
            lastEdited=datetime.now(timezone.utc),
            principal=Login(username="test", password="test"),
        )

        source = RemoteSyncActions(
            create=[sample_defect_with_local_pk, invalid_defect_create],
            update=[sample_known_defect, invalid_defect_update],
        )
        target = RemoteSyncActions()

        # Mock the validation methods
        mock_jira_client_instance.jira_client.fetch_issues_fields = Mock(
            return_value={"projects": []}
        )
        mock_jira_client_instance.jira_client.jira.statuses = Mock(return_value=[])
        mock_jira_client_instance.jira_client.jira.priorities = Mock(return_value=[])
        mock_jira_client_instance.jira_client.jira.issue_types = Mock(return_value=[])

        def validate_side_effect(defect, *args, **kwargs):
            return defect.status != ""

        with (
            patch.object(
                mock_jira_client_instance, "validate_defect", side_effect=validate_side_effect
            ),
            patch.object(mock_jira_client_instance, "get_control_fields", return_value={}),
        ):
            mock_jira_client_instance._validate_and_filter_actions(
                source, target, "Test Project (TEST)"
            )

        assert len(target.create) == 1
        assert len(target.update) == 1
        assert target.create[0] == sample_defect_with_local_pk

    def test_filter_empty_actions(self, mock_jira_client_instance):
        """Test filtering with empty action lists."""
        source = RemoteSyncActions(create=None, update=None)
        target = RemoteSyncActions()

        # Mock the validation methods
        mock_jira_client_instance.jira_client.fetch_issues_fields = Mock(
            return_value={"projects": []}
        )
        mock_jira_client_instance.jira_client.jira.statuses = Mock(return_value=[])
        mock_jira_client_instance.jira_client.jira.priorities = Mock(return_value=[])
        mock_jira_client_instance.jira_client.jira.issue_types = Mock(return_value=[])

        with patch.object(mock_jira_client_instance, "get_control_fields", return_value={}):
            mock_jira_client_instance._validate_and_filter_actions(
                source, target, "Test Project (TEST)"
            )

        assert target.create == []
        assert target.update == []

    def test_filter_local_sync_actions(
        self, mock_jira_client_instance, sample_defect_with_id, sample_known_defect
    ):
        """Test filtering works with LocalSyncActions."""
        source = LocalSyncActions(
            create=[sample_defect_with_id],
            update=[sample_known_defect],
        )
        target = LocalSyncActions()

        # Mock the validation methods
        mock_jira_client_instance.jira_client.fetch_issues_fields = Mock(
            return_value={"projects": []}
        )
        mock_jira_client_instance.jira_client.jira.statuses = Mock(return_value=[])
        mock_jira_client_instance.jira_client.jira.priorities = Mock(return_value=[])
        mock_jira_client_instance.jira_client.jira.issue_types = Mock(return_value=[])

        with patch.object(mock_jira_client_instance, "validate_defect", return_value=True):  # noqa: SIM117
            with patch.object(mock_jira_client_instance, "get_control_fields", return_value={}):
                mock_jira_client_instance._validate_and_filter_actions(
                    source, target, "Test Project (TEST)"
                )

        assert len(target.create) == 1
        assert len(target.update) == 1


@pytest.mark.unit
class TestAddClassIssueTypeNames:
    """Tests for _add_class_issue_type_names method on JiraDefectClient."""

    def test_add_class_issue_type_names_cloud_mode(self, mock_jira_client_instance):
        """Test populating classification from issue-type list (Cloud/non-issuetypes endpoint)."""
        mock_jira_client_instance.jira_client.use_issuetypes_endpoint = False

        control_fields_name = ["classification", "priority"]
        control_fields: dict = {}
        issue_types = [{"name": "Bug"}, {"name": "Task"}, {"name": "Story"}]

        mock_jira_client_instance._add_class_issue_type_names(
            control_fields_name, control_fields, issue_types=issue_types
        )

        assert control_fields["classification"] == ["Bug", "Task", "Story"]
        assert "classification" not in control_fields_name

    def test_add_class_issue_type_names_jdc_mode(self, mock_jira_client_instance):
        """Test populating classification from project_issue_types (Data Center endpoint)."""
        mock_jira_client_instance.jira_client.use_issuetypes_endpoint = True

        mock_it1 = Mock()
        mock_it1.name = "Bug"
        mock_it2 = Mock()
        mock_it2.name = "Task"
        mock_jira_client_instance.jira_client.jira.project_issue_types = Mock(
            return_value=[mock_it1, mock_it2]
        )

        control_fields_name = ["classification"]
        control_fields: dict = {}

        mock_jira_client_instance._add_class_issue_type_names(
            control_fields_name, control_fields, project_key="TEST"
        )

        assert control_fields["classification"] == ["Bug", "Task"]
        assert "classification" not in control_fields_name
        mock_jira_client_instance.jira_client.jira.project_issue_types.assert_called_once_with(
            "TEST", maxResults=100
        )

    def test_add_class_issue_type_names_empty_list(self, mock_jira_client_instance):
        """Test with empty issue types list."""
        mock_jira_client_instance.jira_client.use_issuetypes_endpoint = False

        control_fields_name = ["classification"]
        control_fields: dict = {}

        mock_jira_client_instance._add_class_issue_type_names(
            control_fields_name, control_fields, issue_types=[]
        )

        assert control_fields["classification"] == []
        assert "classification" not in control_fields_name


@pytest.mark.unit
class TestExtractControlFieldValuesJdc:
    """Tests for extract_control_field_values_jdc method on JiraDefectClient."""

    def test_extracts_matching_fields_by_name(self, mock_jira_client_instance):
        """Test that fields matching by name are extracted."""
        av1, av2, av3 = Mock(), Mock(), Mock()
        av1.name, av2.name, av3.name = "Critical", "Major", "Minor"
        mock_field = Mock()
        mock_field.name = "Severity"
        mock_field.fieldId = "customfield_10001"
        mock_field.allowedValues = [av1, av2, av3]

        mock_jira_client_instance.jira_client.fetch_project_issue_fields = Mock(
            return_value=[mock_field]
        )

        control_fields_name = ["Severity"]
        control_fields: dict = {}

        mock_jira_client_instance.extract_control_field_values_jdc(
            "TEST", control_fields, control_fields_name
        )

        assert control_fields["Severity"] == ["Critical", "Major", "Minor"]
        assert "Severity" not in control_fields_name

    def test_extracts_matching_fields_by_id(self, mock_jira_client_instance):
        """Test that fields matching by fieldId are extracted.

        Note: the source removes from control_fields_name by field.name, so the caller
        must include the field name (not just the fieldId) in control_fields_name when
        the match happens via fieldId.
        """
        av1, av2 = Mock(), Mock()
        av1.name, av2.name = "High", "Low"
        mock_field = Mock()
        mock_field.name = "Severity"
        mock_field.fieldId = "customfield_10001"
        mock_field.allowedValues = [av1, av2]

        mock_jira_client_instance.jira_client.fetch_project_issue_fields = Mock(
            return_value=[mock_field]
        )

        # Include both fieldId and field name so removal by name succeeds
        control_fields_name = ["customfield_10001", "Severity"]
        control_fields: dict = {}

        mock_jira_client_instance.extract_control_field_values_jdc(
            "TEST", control_fields, control_fields_name
        )

        assert "Severity" in control_fields
        assert control_fields["Severity"] == ["High", "Low"]
        assert "Severity" not in control_fields_name

    def test_skips_non_matching_fields(self, mock_jira_client_instance):
        """Test that unrelated fields are ignored."""
        mock_field = Mock()
        mock_field.name = "UnrelatedField"
        mock_field.fieldId = "customfield_99999"
        mock_field.allowedValues = [Mock(name="X")]

        mock_jira_client_instance.jira_client.fetch_project_issue_fields = Mock(
            return_value=[mock_field]
        )

        control_fields_name = ["Severity"]
        control_fields: dict = {}

        mock_jira_client_instance.extract_control_field_values_jdc(
            "TEST", control_fields, control_fields_name
        )

        assert control_fields == {}
        assert "Severity" in control_fields_name  # unchanged

    def test_empty_field_list(self, mock_jira_client_instance):
        """Test with no project issue fields returned."""
        mock_jira_client_instance.jira_client.fetch_project_issue_fields = Mock(return_value=[])

        control_fields_name = ["Severity"]
        control_fields: dict = {}

        mock_jira_client_instance.extract_control_field_values_jdc(
            "TEST", control_fields, control_fields_name
        )

        assert control_fields == {}


class TestFetchProjectStatuses:
    """Tests for JiraClient.fetch_project_statuses."""

    def test_fetch_project_statuses_extracts_unique_names(self):
        """Test fetch_project_statuses returns unique sorted status names across issue types."""
        api_response = [
            {
                "id": "10002",
                "name": "Task",
                "subtask": False,
                "statuses": [
                    {"name": "Open", "id": "1"},
                    {"name": "In Progress", "id": "3"},
                    {"name": "Done", "id": "10001"},
                ],
            },
            {
                "id": "10004",
                "name": "Bug",
                "subtask": False,
                "statuses": [
                    {"name": "Open", "id": "1"},
                    {"name": "In Progress", "id": "3"},
                    {"name": "Rejected", "id": "10050"},
                    {"name": "Done", "id": "10001"},
                ],
            },
        ]

        with patch(
            "testbench_defect_service.clients.jira.jira_client.JiraClient.__init__",
            return_value=None,
        ):
            client = JiraClient.__new__(JiraClient)
            client.jira = Mock()
            client.jira._get_json = Mock(return_value=api_response)

            result = client.fetch_project_statuses("TEST")

            client.jira._get_json.assert_called_once_with("project/TEST/statuses")
            assert result == ["Done", "In Progress", "Open", "Rejected"]

    def test_fetch_project_statuses_empty_response(self):
        """Test graceful handling of empty response."""
        with patch(
            "testbench_defect_service.clients.jira.jira_client.JiraClient.__init__",
            return_value=None,
        ):
            client = JiraClient.__new__(JiraClient)
            client.jira = Mock()
            client.jira._get_json = Mock(return_value=[])

            result = client.fetch_project_statuses("TEST")

            assert result == []

    def test_fetch_project_statuses_api_error(self):
        """Test graceful handling when API call fails."""
        with patch(
            "testbench_defect_service.clients.jira.jira_client.JiraClient.__init__",
            return_value=None,
        ):
            client = JiraClient.__new__(JiraClient)
            client.jira = Mock()
            client.jira._get_json = Mock(side_effect=Exception("API Error"))

            result = client.fetch_project_statuses("TEST")

            assert result == []

    def test_fetch_project_statuses_real_response_structure(self):
        """Test realistic Jira response structure matching /rest/api/2/project/{key}/statuses."""
        api_response = [
            {
                "self": "https://example.atlassian.net/rest/api/2/issuetype/10002",
                "id": "10002",
                "name": "Task",
                "subtask": False,
                "statuses": [
                    {
                        "self": "https://example.atlassian.net/rest/api/2/status/10050",
                        "description": "Rejected by PO",
                        "iconUrl": "https://example.atlassian.net/images/icons/statuses/generic.png",
                        "name": "Zurückgewiesen",
                        "untranslatedName": "Rejected",
                        "id": "10050",
                        "statusCategory": {
                            "id": 3,
                            "key": "done",
                            "colorName": "green",
                            "name": "Fertig",
                        },
                    },
                    {
                        "self": "https://example.atlassian.net/rest/api/2/status/10031",
                        "name": "Defined",
                        "untranslatedName": "Defined",
                        "id": "10031",
                        "statusCategory": {"id": 2, "key": "new"},
                    },
                    {
                        "self": "https://example.atlassian.net/rest/api/2/status/10001",
                        "name": "Fertig",
                        "untranslatedName": "Done",
                        "id": "10001",
                        "statusCategory": {"id": 3, "key": "done"},
                    },
                ],
            },
            {
                "self": "https://example.atlassian.net/rest/api/2/issuetype/10000",
                "id": "10000",
                "name": "Epic",
                "subtask": False,
                "statuses": [
                    {
                        "name": "Zu erledigen",
                        "untranslatedName": "To Do",
                        "id": "10000",
                        "statusCategory": {"id": 2, "key": "new"},
                    },
                    {
                        "name": "In Arbeit",
                        "untranslatedName": "In Progress",
                        "id": "3",
                        "statusCategory": {"id": 4, "key": "indeterminate"},
                    },
                    {
                        "name": "Fertig",
                        "untranslatedName": "Done",
                        "id": "10001",
                        "statusCategory": {"id": 3, "key": "done"},
                    },
                ],
            },
        ]

        with patch(
            "testbench_defect_service.clients.jira.jira_client.JiraClient.__init__",
            return_value=None,
        ):
            client = JiraClient.__new__(JiraClient)
            client.jira = Mock()
            client.jira._get_json = Mock(return_value=api_response)

            result = client.fetch_project_statuses("TEST")

            # "Fertig" appears in both issue types but should be deduplicated
            assert result == [
                "Defined",
                "Fertig",
                "In Arbeit",
                "Zu erledigen",
                "Zurückgewiesen",
            ]

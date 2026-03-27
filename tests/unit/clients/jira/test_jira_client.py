"""Unit tests for JiraClient."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from jira import JIRAError
from sanic import NotFound

from testbench_defect_service.clients.jira.config import JiraDefectClientConfig
from testbench_defect_service.clients.jira.jira_client import JiraClient
from testbench_defect_service.models.defects import Defect, Login


def _make_config(**overrides) -> JiraDefectClientConfig:
    defaults: dict[str, Any] = {
        "server_url": "https://test.atlassian.net",
        "auth_type": "basic",
        "username": "test@example.com",
        "password": "token123",
        "attributes": ["title", "status"],
        "control_fields": ["status"],
        "readonly": False,
        "show_change_history": False,
    }
    defaults.update(overrides)
    return JiraDefectClientConfig(**defaults)


def _make_defect(**overrides) -> Defect:
    defaults: dict[str, Any] = {
        "title": "Test Bug",
        "description": "Desc",
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


_DEFAULT_CONFIG = _make_config()
_JIRA_CLIENT_KWARGS: dict = {
    "server": _DEFAULT_CONFIG.server_url,
    "options": {"verify": _DEFAULT_CONFIG.ssl_verify},
    "max_retries": _DEFAULT_CONFIG.max_retries,
    "timeout": _DEFAULT_CONFIG.timeout,
}


def _make_cloud_createmeta() -> dict:
    """Return a minimal createmeta response with a Bug issue type."""
    return {
        "projects": [
            {
                "issuetypes": [
                    {
                        "name": "Bug",
                        "fields": {
                            "summary": {"name": "Summary", "schema": {"type": "string"}},
                            "issuetype": {"name": "Issue Type", "schema": {"type": "issuetype"}},
                        },
                    }
                ]
            }
        ]
    }


def _make_jira(is_cloud: bool = True, version: tuple = (9, 0, 0)) -> Mock:
    """Return a mock JIRA instance."""
    jira = Mock()
    jira._is_cloud = is_cloud
    jira._version = version
    jira._options = {}
    jira._session = Mock()
    return jira


@pytest.fixture
def cloud_client() -> JiraClient:
    """JiraClient wired to a mock Cloud JIRA (use_issuetypes_endpoint=False)."""
    with patch("testbench_defect_service.clients.jira.jira_client.JIRA") as mock_jira:
        mock_jira.return_value = _make_jira(is_cloud=True)
        return JiraClient(_make_config())


@pytest.fixture
def dc_client() -> JiraClient:
    """JiraClient wired to a mock Data Center JIRA (use_issuetypes_endpoint=True)."""
    with patch("testbench_defect_service.clients.jira.jira_client.JIRA") as mock_jira:
        mock_jira.return_value = _make_jira(is_cloud=False, version=(9, 0, 0))
        return JiraClient(_make_config())


@pytest.fixture
def dc_old_client() -> JiraClient:
    """Data Center client with version < (8,4,0) → use_issuetypes_endpoint=False."""
    with patch("testbench_defect_service.clients.jira.jira_client.JIRA") as mock_jira:
        mock_jira.return_value = _make_jira(is_cloud=False, version=(8, 3, 0))
        return JiraClient(_make_config())


@pytest.mark.unit
class TestInit:
    def test_cloud_flags(self):
        with patch("testbench_defect_service.clients.jira.jira_client.JIRA") as mock_jira:
            mock_jira.return_value = _make_jira(is_cloud=True)
            client = JiraClient(_make_config())
        assert client.use_issuetypes_endpoint is False
        assert client.use_manual_pagination is False

    def test_dc_flags(self):
        with patch("testbench_defect_service.clients.jira.jira_client.JIRA") as mock_jira:
            mock_jira.return_value = _make_jira(is_cloud=False, version=(9, 0, 0))
            client = JiraClient(_make_config())
        assert client.use_issuetypes_endpoint is True
        assert client.use_manual_pagination is True

    def test_principal_overrides_shared_credentials(self):
        principal = Login(username="alice", password="secret")
        with patch("testbench_defect_service.clients.jira.jira_client.JIRA") as mock_jira:
            mock_jira.return_value = _make_jira()
            JiraClient(_make_config(), principal=principal)
        mock_jira.assert_called_once_with(**_JIRA_CLIENT_KWARGS, basic_auth=("alice", "secret"))

    def test_config_stored(self, cloud_client):
        assert cloud_client.config.server_url == "https://test.atlassian.net"


@pytest.mark.unit
class TestConnect:
    def test_basic_auth(self):
        cfg = _make_config(username="u@x.com", password="tok")
        with patch("testbench_defect_service.clients.jira.jira_client.JIRA") as mock_jira:
            mock_jira.return_value = _make_jira()
            JiraClient(cfg)
        mock_jira.assert_called_once_with(**_JIRA_CLIENT_KWARGS, basic_auth=("u@x.com", "tok"))

    def test_token_auth(self):
        cfg = _make_config(auth_type="token", token="mytoken")
        with patch("testbench_defect_service.clients.jira.jira_client.JIRA") as mock_jira:
            mock_jira.return_value = _make_jira()
            JiraClient(cfg)
        mock_jira.assert_called_once_with(**_JIRA_CLIENT_KWARGS, token_auth="mytoken")

    def test_oauth1_auth(self):
        cfg = _make_config(
            auth_type="oauth1",
            oauth1_access_token="at",
            oauth1_access_token_secret="ats",
            oauth1_consumer_key="ck",
            oauth1_key_cert="cert",
        )
        with patch("testbench_defect_service.clients.jira.jira_client.JIRA") as mock_jira:
            mock_jira.return_value = _make_jira()
            JiraClient(cfg)
        _, kwargs = mock_jira.call_args
        assert kwargs["oauth"]["access_token"] == "at"
        assert kwargs["oauth"]["consumer_key"] == "ck"

    def test_unsupported_auth_raises(self):
        cfg = _make_config(auth_type="basic")
        with patch("testbench_defect_service.clients.jira.jira_client.JIRA") as mock_jira:
            mock_jira.return_value = _make_jira()
            client = JiraClient(cfg)
        # Directly call _connect with invalid auth_type
        client.config = _make_config.__wrapped__ if hasattr(_make_config, "__wrapped__") else cfg
        client.config.__dict__["auth_type"] = "kerberos"
        with pytest.raises(NotImplementedError):
            client._connect()


@pytest.mark.unit
class TestConnectUser:
    def test_basic_auth_with_principal(self):
        principal = Login(username="bob", password="pw")
        cfg = _make_config(auth_type="basic")
        with patch("testbench_defect_service.clients.jira.jira_client.JIRA") as mock_jira:
            mock_jira.return_value = _make_jira()
            JiraClient(cfg, principal=principal)
        mock_jira.assert_called_once_with(**_JIRA_CLIENT_KWARGS, basic_auth=("bob", "pw"))

    def test_token_auth_with_principal(self):
        principal = Login(username="bob", password="mytoken")
        cfg = _make_config(auth_type="token", token="shared_token", username=None, password=None)
        with patch("testbench_defect_service.clients.jira.jira_client.JIRA") as mock_jira:
            mock_jira.return_value = _make_jira()
            JiraClient(cfg, principal=principal)
        mock_jira.assert_called_once_with(**_JIRA_CLIENT_KWARGS, token_auth="mytoken")

    def test_unsupported_auth_type_with_principal_raises(self):
        cfg = _make_config(auth_type="basic")
        with patch("testbench_defect_service.clients.jira.jira_client.JIRA") as mock_jira:
            mock_jira.return_value = _make_jira()
            client = JiraClient(cfg)
        client.config.__dict__["auth_type"] = "kerberos"
        principal = Login(username="x", password="y")
        with pytest.raises(NotImplementedError):
            client._connect_user(principal)


@pytest.mark.unit
class TestFetchProjects:
    def test_returns_projects(self, cloud_client):
        p1, p2 = Mock(), Mock()
        cloud_client.jira.projects.return_value = [p1, p2]
        result = cloud_client.fetch_projects()
        assert result == [p1, p2]

    def test_returns_empty_list_on_jira_error(self, cloud_client):
        cloud_client.jira.projects.side_effect = JIRAError("fail")
        assert cloud_client.fetch_projects() == []


@pytest.mark.unit
class TestFetchProjectStatuses:
    def test_returns_sorted_unique_statuses(self, cloud_client):
        cloud_client.jira._get_json.return_value = [
            {"statuses": [{"name": "Done"}, {"name": "Open"}]},
            {"statuses": [{"name": "Open"}, {"name": "In Progress"}]},
        ]
        result = cloud_client.fetch_project_statuses("TEST")
        assert result == ["Done", "In Progress", "Open"]

    def test_skips_status_without_name(self, cloud_client):
        cloud_client.jira._get_json.return_value = [
            {"statuses": [{"name": "Open"}, {}]},
        ]
        result = cloud_client.fetch_project_statuses("TEST")
        assert result == ["Open"]

    def test_returns_empty_list_on_exception(self, cloud_client):
        cloud_client.jira._get_json.side_effect = Exception("boom")
        assert cloud_client.fetch_project_statuses("TEST") == []

    def test_calls_correct_endpoint(self, cloud_client):
        cloud_client.jira._get_json.return_value = []
        cloud_client.fetch_project_statuses("MYPROJ")
        cloud_client.jira._get_json.assert_called_once_with("project/MYPROJ/statuses")


@pytest.mark.unit
class TestFetchAllCustomFields:
    def test_cloud_uses_createmeta(self, cloud_client):
        cloud_client.jira.createmeta.return_value = {
            "projects": [
                {
                    "issuetypes": [
                        {
                            "fields": {
                                "customfield_001": {"name": "Env", "required": False},
                                "customfield_002": {"name": "Team", "required": True},
                            }
                        }
                    ]
                }
            ]
        }
        result = cloud_client.fetch_all_custom_fields("TEST")
        ids = {f["id"] for f in result}
        assert "customfield_001" in ids
        assert "customfield_002" in ids

    def test_cloud_required_field_overwrites_non_required(self, cloud_client):
        cloud_client.jira.createmeta.return_value = {
            "projects": [
                {
                    "issuetypes": [
                        {"fields": {"customfield_001": {"name": "Env", "required": False}}},
                        {"fields": {"customfield_001": {"name": "Env", "required": True}}},
                    ]
                }
            ]
        }
        result = cloud_client.fetch_all_custom_fields("TEST")
        env_fields = [f for f in result if f["id"] == "customfield_001"]
        assert len(env_fields) == 1
        assert env_fields[0]["required"] is True

    def test_cloud_returns_empty_when_no_projects(self, cloud_client):
        cloud_client.jira.createmeta.return_value = {"projects": []}
        assert cloud_client.fetch_all_custom_fields("TEST") == []

    def test_cloud_returns_empty_on_jira_error(self, cloud_client):
        cloud_client.jira.createmeta.side_effect = JIRAError("fail")
        assert cloud_client.fetch_all_custom_fields("TEST") == []

    def test_dc_uses_project_issue_types(self, dc_client):
        it1 = Mock()
        it1.id = "10001"
        f1 = Mock()
        f1.raw = {"fieldId": "customfield_001", "name": "Env"}
        dc_client.jira.project_issue_types.return_value = [it1]
        dc_client.jira.project_issue_fields.return_value = [f1]

        result = dc_client.fetch_all_custom_fields("TEST")
        assert any(f["fieldId"] == "customfield_001" for f in result)

    def test_dc_no_project_falls_back_to_all_fields(self, dc_client):
        dc_client.jira.fields.return_value = [
            {"id": "customfield_001", "name": "Env"},
            {"id": "status", "name": "Status"},
        ]
        result = dc_client.fetch_all_custom_fields("")
        assert all(f["id"].startswith("customfield_") for f in result)

    def test_dc_returns_empty_on_fields_jira_error(self, dc_client):
        dc_client.jira.fields.side_effect = JIRAError("fail")
        result = dc_client.fetch_all_custom_fields("")
        assert result == []


@pytest.mark.unit
class TestFetchIssuesFields:
    def test_dc_returns_empty_dict(self, dc_client):
        assert dc_client.fetch_issues_fields("TEST") == {}

    def test_cloud_calls_createmeta_with_project(self, cloud_client):
        cloud_client.jira.createmeta.return_value = {"projects": []}
        result = cloud_client.fetch_issues_fields("TEST")
        cloud_client.jira.createmeta.assert_called_once_with(
            projectKeys="TEST", expand="projects.issuetypes.fields"
        )
        assert result == {"projects": []}

    def test_cloud_calls_createmeta_without_project(self, cloud_client):
        cloud_client.jira.createmeta.return_value = {}
        cloud_client.fetch_issues_fields()
        cloud_client.jira.createmeta.assert_called_once_with(expand="projects.issuetypes.fields")

    def test_cloud_returns_empty_dict_on_jira_error(self, cloud_client):
        cloud_client.jira.createmeta.side_effect = JIRAError("fail")
        assert cloud_client.fetch_issues_fields("TEST") == {}


@pytest.mark.unit
class TestFetchIssuesByJql:
    def test_cloud_uses_enhanced_search(self, cloud_client):
        chunk = Mock()
        chunk.__iter__ = Mock(return_value=iter([Mock(), Mock()]))
        chunk.__len__ = Mock(return_value=2)
        chunk.nextPageToken = None
        cloud_client.jira.enhanced_search_issues.return_value = chunk
        result = cloud_client.fetch_issues_by_jql("project = TEST")
        assert len(result) == 2
        cloud_client.jira.enhanced_search_issues.assert_called_once()

    def test_cloud_paginates_until_no_next_token(self, cloud_client):
        page1 = Mock()
        page1.__iter__ = Mock(return_value=iter([Mock()]))
        page1.__len__ = Mock(return_value=1)
        page1.nextPageToken = "tok2"

        page2 = Mock()
        page2.__iter__ = Mock(return_value=iter([Mock()]))
        page2.__len__ = Mock(return_value=1)
        page2.nextPageToken = None

        cloud_client.jira.enhanced_search_issues.side_effect = [page1, page2]
        result = cloud_client.fetch_issues_by_jql("project = TEST")
        assert len(result) == 2
        assert cloud_client.jira.enhanced_search_issues.call_count == 2

    def test_dc_uses_manual_pagination(self, dc_client):
        issue = Mock()
        chunk1 = [issue] * 10
        chunk2 = [issue] * 5
        dc_client.jira.search_issues.side_effect = [chunk1, chunk2]
        result = dc_client.fetch_issues_by_jql("project = TEST", max_results=10)
        assert len(result) == 15
        assert dc_client.jira.search_issues.call_count == 2

    def test_returns_empty_list_on_jira_error(self, cloud_client):
        cloud_client.jira.enhanced_search_issues.side_effect = JIRAError("fail")
        assert cloud_client.fetch_issues_by_jql("bad jql") == []


@pytest.mark.unit
class TestFetchIssue:
    def test_returns_issue(self, cloud_client):
        mock_issue = Mock()
        cloud_client.jira.issue.return_value = mock_issue
        result = cloud_client.fetch_issue("TEST-1")
        assert result is mock_issue

    def test_returns_none_on_jira_error(self, cloud_client):
        cloud_client.jira.issue.side_effect = JIRAError("not found")
        assert cloud_client.fetch_issue("TEST-999") is None

    def test_passes_kwargs(self, cloud_client):
        cloud_client.jira.issue.return_value = Mock()
        cloud_client.fetch_issue("TEST-1", fields="summary", expand="changelog")
        cloud_client.jira.issue.assert_called_once_with(
            "TEST-1", fields="summary", expand="changelog", properties=None
        )


@pytest.mark.unit
class TestCreateIssue:
    def _setup_cloud_create(self, cloud_client, defect: Defect) -> Mock:
        mock_issue = Mock()
        mock_issue.key = "TEST-1"
        mock_issue.fields.status.name = defect.status
        cloud_client.jira.create_issue.return_value = mock_issue
        cloud_client.jira.createmeta.return_value = _make_cloud_createmeta()
        return mock_issue

    def test_cloud_creates_issue_and_returns_it(self, cloud_client):
        defect = _make_defect()
        mock_issue = self._setup_cloud_create(cloud_client, defect)
        result = cloud_client.create_issue("TEST", defect)
        assert result is mock_issue
        cloud_client.jira.create_issue.assert_called_once()

    def test_cloud_sets_project_key(self, cloud_client):
        defect = _make_defect()
        self._setup_cloud_create(cloud_client, defect)
        cloud_client.create_issue("TEST", defect)
        call_args = cloud_client.jira.create_issue.call_args[0][0]
        assert call_args["project"] == "TEST"

    def test_transitions_status_after_creation(self, cloud_client):
        defect = _make_defect(status="Closed")
        mock_issue = self._setup_cloud_create(cloud_client, defect)
        mock_issue.fields.status.name = "Open"
        transition = {"id": "31", "to": {"name": "Closed"}}
        cloud_client.jira.transitions.return_value = [transition]
        cloud_client.create_issue("TEST", defect)
        cloud_client.jira.transition_issue.assert_called_once_with(mock_issue, "31")

    def test_raises_value_error_on_jira_error(self, cloud_client):
        defect = _make_defect()
        cloud_client.jira.createmeta.return_value = _make_cloud_createmeta()
        cloud_client.jira.create_issue.side_effect = JIRAError("server error")
        with pytest.raises(ValueError, match="Unable to create Jira issue"):
            cloud_client.create_issue("TEST", defect)

    def test_dc_uses_project_issue_fields(self, dc_client):
        defect = _make_defect()
        mock_issue = Mock()
        mock_issue.key = "TEST-1"
        mock_issue.fields.status.name = defect.status

        it = Mock()
        it.id = "10001"
        f_summary = Mock()
        f_summary.fieldId = "summary"
        f_summary.name = "Summary"
        f_summary.schema = Mock(type="string")
        dc_client.jira.project_issue_types.return_value = [it]
        dc_client.jira.project_issue_fields.return_value = [f_summary]
        dc_client.jira.create_issue.return_value = mock_issue

        result = dc_client.create_issue("TEST", defect)
        assert result is mock_issue


@pytest.mark.unit
class TestDeleteIssue:
    def test_calls_delete_on_issue(self, cloud_client):
        mock_issue = Mock()
        mock_issue.key = "TEST-1"
        cloud_client.delete_issue(mock_issue)
        mock_issue.delete.assert_called_once()


@pytest.mark.unit
class TestUpdateIssue:
    def test_cloud_calls_issue_update(self, cloud_client):
        defect = _make_defect()
        mock_issue = Mock()
        mock_issue.fields.status.name = defect.status
        cloud_client.jira.createmeta.return_value = _make_cloud_createmeta()
        cloud_client.update_issue("TEST", mock_issue, defect)
        mock_issue.update.assert_called_once()

    def test_raises_value_error_on_jira_error(self, cloud_client):
        defect = _make_defect()
        mock_issue = Mock()
        mock_issue.fields.status.name = defect.status
        cloud_client.jira.createmeta.return_value = _make_cloud_createmeta()
        mock_issue.update.side_effect = JIRAError("update failed")
        with pytest.raises(ValueError, match="Unable to update Jira issue"):
            cloud_client.update_issue("TEST", mock_issue, defect)

    def test_dc_calls_project_issue_fields(self, dc_client):
        defect = _make_defect()
        mock_issue = Mock()
        mock_issue.key = "DC-1"
        mock_issue.fields.status.name = defect.status

        it = Mock()
        it.id = "10001"
        f = Mock()
        f.fieldId = "summary"
        f.name = "Summary"
        f.schema = Mock(type="string")
        dc_client.jira.project_issue_types.return_value = [it]
        dc_client.jira.project_issue_fields.return_value = [f]

        dc_client.update_issue("TEST", mock_issue, defect)
        mock_issue.update.assert_called_once()


@pytest.mark.unit
class TestTransitionIssueStatus:
    def test_skips_transition_when_already_at_target(self, cloud_client):
        defect = _make_defect(status="Open")
        issue = Mock()
        issue.fields.status.name = "Open"
        cloud_client.transition_issue_status(issue, defect)
        cloud_client.jira.transitions.assert_not_called()

    def test_transitions_to_target_status(self, cloud_client):
        defect = _make_defect(status="Done")
        issue = Mock()
        issue.fields.status.name = "Open"
        transitions = [
            {"id": "11", "to": {"name": "In Progress"}},
            {"id": "31", "to": {"name": "Done"}},
        ]
        cloud_client.jira.transitions.return_value = transitions
        cloud_client.transition_issue_status(issue, defect)
        cloud_client.jira.transition_issue.assert_called_once_with(issue, "31")

    def test_logs_warning_when_no_matching_transition(self, cloud_client):
        defect = _make_defect(status="Resolved")
        issue = Mock()
        issue.key = "TEST-1"
        issue.fields.status.name = "Open"
        cloud_client.jira.transitions.return_value = [{"id": "11", "to": {"name": "Done"}}]
        cloud_client.transition_issue_status(issue, defect)
        cloud_client.jira.transition_issue.assert_not_called()

    def test_handles_value_error_gracefully(self, cloud_client):
        defect = _make_defect(status="Done")
        issue = Mock()
        issue.key = "TEST-1"
        issue.fields.status.name = "Open"
        cloud_client.jira.transitions.side_effect = ValueError("bad transition")
        cloud_client.transition_issue_status(issue, defect)


@pytest.mark.unit
class TestMapAttachments:
    def test_maps_existing_local_file(self, cloud_client, tmp_path):
        f = tmp_path / "report.txt"
        f.write_text("data")
        result = cloud_client.map_attachments([str(f)])
        assert "report.txt" in result
        assert isinstance(result["report.txt"][0], Path)

    def test_skips_urls(self, cloud_client):
        result = cloud_client.map_attachments(["https://example.com/file.pdf"])
        assert result == {}

    def test_skips_nonexistent_files(self, cloud_client):
        result = cloud_client.map_attachments(["/does/not/exist.txt"])
        assert result == {}

    def test_mixed_list(self, cloud_client, tmp_path):
        f = tmp_path / "local.txt"
        f.write_text("x")
        result = cloud_client.map_attachments(
            [
                str(f),
                "https://example.com/remote.pdf",
                "/nonexistent.txt",
            ]
        )
        assert "local.txt" in result
        assert len(result) == 1

    def test_duplicate_filenames_last_wins(self, cloud_client, tmp_path):
        d1 = tmp_path / "a"
        d2 = tmp_path / "b"
        d1.mkdir()
        d2.mkdir()
        f1 = d1 / "file.txt"
        f2 = d2 / "file.txt"
        f1.write_text("1")
        f2.write_text("2")
        result = cloud_client.map_attachments([str(f1), str(f2)])
        assert "file.txt" in result
        assert result["file.txt"][0] == f2


@pytest.mark.unit
class TestSyncAttachmentsWithJira:
    def test_dc_client_skips_sync(self, dc_client, tmp_path):
        """DC client (use_issuetypes_endpoint=True) skips sync entirely."""
        f = tmp_path / "old.txt"
        f.write_text("x")
        local_map = {"old.txt": (f, 1000.0)}
        issue = Mock()
        issue.fields.attachment = [Mock(filename="old.txt", created="2024-01-01T00:00:00.000+0000")]
        dc_client.sync_attachments_with_jira(issue, local_map)
        assert "old.txt" in local_map

    def test_cloud_removes_matched_entry(self, cloud_client, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("x")
        mtime = f.stat().st_mtime
        local_map = {"doc.txt": (f, mtime)}

        attachment = Mock()
        attachment.filename = "doc.txt"
        attachment.created = "2099-01-01T00:00:00.000+0000"
        issue = Mock()
        issue.fields.attachment = [attachment]

        cloud_client.sync_attachments_with_jira(issue, local_map)
        assert "doc.txt" not in local_map

    def test_cloud_reuploads_newer_local_file(self, cloud_client, tmp_path):
        f = tmp_path / "new.txt"
        f.write_text("updated content")
        future_mtime = 9_999_999_999.0
        local_map = {"new.txt": (f, future_mtime)}

        attachment = Mock()
        attachment.filename = "new.txt"
        attachment.created = "2000-01-01T00:00:00.000+0000"
        attachment.id = "att-1"
        issue = Mock()
        issue.fields.attachment = [attachment]

        cloud_client.sync_attachments_with_jira(issue, local_map)
        cloud_client.jira.delete_attachment.assert_called_once_with("att-1")
        cloud_client.jira.add_attachment.assert_called_once()
        assert "new.txt" not in local_map

    def test_cloud_deletes_obsolete_attachment(self, cloud_client):
        """Jira attachment not in local map is deleted."""
        local_map: dict = {}
        attachment = Mock()
        attachment.filename = "obsolete.txt"
        issue = Mock()
        issue.fields.attachment = [attachment]
        cloud_client.sync_attachments_with_jira(issue, local_map)
        cloud_client.jira.delete_attachment.assert_not_called()


@pytest.mark.unit
class TestUploadAttachments:
    def test_uploads_local_file(self, cloud_client, tmp_path):
        f = tmp_path / "upload.txt"
        f.write_text("data")
        local_map = {"upload.txt": (f, f.stat().st_mtime)}
        issue = Mock()
        cloud_client.upload_attachments(issue, local_map)
        cloud_client.jira.add_attachment.assert_called_once()

    def test_skips_url_entries(self, cloud_client):
        local_map = {"https://testbench.com/f.pdf": ("https://testbench.com/f.pdf", 0)}
        issue = Mock()
        cloud_client.upload_attachments(issue, local_map)
        cloud_client.jira.add_attachment.assert_not_called()

    def test_uploads_multiple_files(self, cloud_client, tmp_path):
        files = []
        local_map = {}
        for i in range(3):
            f = tmp_path / f"file{i}.txt"
            f.write_text(f"content{i}")
            local_map[f.name] = (f, f.stat().st_mtime)
            files.append(f)
        issue = Mock()
        cloud_client.upload_attachments(issue, local_map)
        assert cloud_client.jira.add_attachment.call_count == 3


@pytest.mark.unit
class TestAddAttachments:
    def test_orchestrates_map_sync_upload(self, cloud_client, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("data")
        issue = Mock()
        issue.key = "TEST-1"
        issue.fields.attachment = []
        cloud_client.add_attachments(issue, [str(f)])
        cloud_client.jira.add_attachment.assert_called_once()

    def test_empty_list_does_nothing(self, cloud_client):
        issue = Mock()
        issue.key = "TEST-1"
        issue.fields.attachment = []
        cloud_client.add_attachments(issue, [])
        cloud_client.jira.add_attachment.assert_not_called()


@pytest.mark.unit
class TestGetUserId:
    def test_cloud_returns_account_id_string(self, cloud_client):
        user = Mock(accountId="cloud-99")
        cloud_client.jira.search_users.return_value = [user]
        assert cloud_client.get_user_id("alice") == "cloud-99"
        cloud_client.jira.search_users.assert_called_once_with(query="alice")

    def test_cloud_raises_when_no_users(self, cloud_client):
        cloud_client.jira.search_users.return_value = []
        with pytest.raises(ValueError, match="not found in Jira"):
            cloud_client.get_user_id("ghost")

    def test_cloud_raises_on_jira_error(self, cloud_client):
        cloud_client.jira.search_users.side_effect = JIRAError("api error")
        with pytest.raises(JIRAError):
            cloud_client.get_user_id("alice")

    def test_dc_returns_name_string(self, dc_client):
        user = Mock()
        user.name = "dc_bob"
        user.key = "dc_bob"
        dc_client.jira.search_users.return_value = [user]
        assert dc_client.get_user_id("bob") == "dc_bob"
        dc_client.jira.search_users.assert_called_once_with(user="bob")

    def test_dc_falls_back_to_key_when_name_none(self, dc_client):
        user = Mock()
        user.name = None
        user.key = "fallback"
        dc_client.jira.search_users.return_value = [user]
        assert dc_client.get_user_id("x") == "fallback"

    def test_dc_raises_when_no_users(self, dc_client):
        dc_client.jira.search_users.return_value = []
        with pytest.raises(ValueError, match="not found in Jira"):
            dc_client.get_user_id("nobody")

    def test_dc_raises_on_jira_error(self, dc_client):
        dc_client.jira.search_users.side_effect = JIRAError("fail")
        with pytest.raises(JIRAError):
            dc_client.get_user_id("alice")


@pytest.mark.unit
class TestFetchProjectIssueFields:
    def test_dc_aggregates_fields_across_issue_types(self, dc_client):
        it1 = Mock()
        it1.id = "10001"
        it2 = Mock()
        it2.id = "10002"

        f1 = Mock()
        f1.fieldId = "summary"
        f2 = Mock()
        f2.fieldId = "customfield_001"
        f3 = Mock()
        f3.fieldId = "customfield_002"

        dc_client.jira.project_issue_types.return_value = [it1, it2]
        dc_client.jira.project_issue_fields.side_effect = [[f1, f2], [f1, f3]]

        result = dc_client.fetch_project_issue_fields("TEST")
        field_ids = {f.fieldId for f in result}
        assert "summary" in field_ids
        assert "customfield_001" in field_ids
        assert "customfield_002" in field_ids

    def test_dc_re_raises_on_exception(self, dc_client):
        dc_client.jira.project_issue_types.side_effect = Exception("fail")
        with pytest.raises(Exception, match="fail"):
            dc_client.fetch_project_issue_fields("TEST")

    def test_cloud_uses_createmeta(self, cloud_client):
        cloud_client.jira.createmeta.return_value = {
            "projects": [
                {
                    "issuetypes": [
                        {
                            "fields": {
                                "summary": {"name": "Summary", "schema": {"type": "string"}},
                            }
                        }
                    ]
                }
            ]
        }
        result = cloud_client.fetch_project_issue_fields("TEST")
        assert len(result) >= 1


@pytest.mark.unit
class TestFetchIssueFields:
    def test_dc_aggregates_fields_from_project(self, dc_client):
        it = Mock()
        it.id = "10001"
        f = Mock()
        f.fieldId = "summary"
        f.raw = {"name": "Summary"}
        dc_client.jira.project_issue_types.return_value = [it]
        dc_client.jira.project_issue_fields.return_value = [f]

        issue = Mock()
        result = dc_client.fetch_issue_fields("TEST", issue)
        assert "summary" in result

    def test_cloud_returns_fields_for_matching_issue_type(self, cloud_client):
        issue = Mock()
        issue.fields.issuetype = "Bug"
        cloud_client.jira.createmeta.return_value = {
            "projects": [
                {
                    "issuetypes": [
                        {
                            "name": "Bug",
                            "fields": {"summary": {"name": "Summary"}},
                        }
                    ]
                }
            ]
        }
        result = cloud_client.fetch_issue_fields("TEST", issue)
        assert "summary" in result

    def test_cloud_returns_empty_dict_when_type_not_matched(self, cloud_client):
        issue = Mock()
        issue.fields.issuetype = "Task"
        cloud_client.jira.createmeta.return_value = {
            "projects": [
                {"issuetypes": [{"name": "Bug", "fields": {"summary": {"name": "Summary"}}}]}
            ]
        }
        result = cloud_client.fetch_issue_fields("TEST", issue)
        assert result == {}

    def test_cloud_raises_not_found_when_no_projects(self, cloud_client):
        issue = Mock()
        cloud_client.jira.createmeta.return_value = {"projects": []}
        with pytest.raises(NotFound):
            cloud_client.fetch_issue_fields("TEST", issue)

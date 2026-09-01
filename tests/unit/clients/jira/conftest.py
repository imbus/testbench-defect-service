"""Pytest configuration and shared fixtures for Jira client tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import Mock

import pytest
from jira import Issue
from jira.resources import Project

from testbench_defect_service.models.defects import (
    Defect,
    DefectID,
    DefectWithID,
    Login,
    UserDefinedFieldProperties,
)

#: The issue fields the fake Jira issues expose.  ``Mock(spec=...)`` is built from
#: this list so that reading any *other* field raises ``AttributeError`` instead of
#: handing out a truthy child Mock: a field renamed in the production mapping then
#: fails loudly here rather than leaking a Mock into the defect model.  Individual
#: tests can still assign extra attributes (e.g. ``customfield_10001``), because
#: ``spec`` restricts reads, not writes.
JIRA_ISSUE_FIELD_NAMES = [
    "summary",
    "description",
    "updated",
    "status",
    "priority",
    "issuetype",
    "reporter",
    "attachment",
]


@pytest.fixture
def mock_jira_project() -> Mock:
    """Create a mock Jira Project object."""
    project = Mock(spec=Project)
    project.name = "Test Project"
    project.key = "TEST"
    return project


@pytest.fixture
def mock_jira_issue() -> Mock:
    """Create a mock Jira Issue object with typical fields."""
    issue = Mock(spec=Issue)
    issue.key = "TEST-123"

    # Mock fields
    issue.fields = Mock(spec=JIRA_ISSUE_FIELD_NAMES)
    issue.fields.summary = "Test Issue Summary"
    issue.fields.description = "Test Issue Description"
    issue.fields.updated = "2024-01-15T10:30:45.123000+0000"

    # Mock status
    issue.fields.status = Mock(spec=["name"])
    issue.fields.status.name = "Open"

    # Mock priority
    issue.fields.priority = Mock(spec=["name"])
    issue.fields.priority.name = "High"

    # Mock issue type
    issue.fields.issuetype = Mock(spec=["name"])
    issue.fields.issuetype.name = "Bug"

    # Mock reporter
    issue.fields.reporter = Mock(spec=["displayName"])
    issue.fields.reporter.displayName = "John Doe"

    # Mock attachments -- no ``id`` unless a test adds one, so the site_url branch
    # of _extract_references falls back the way it would for a real attachment.
    attachment1 = Mock(spec=["content"])
    attachment1.content = "https://example.com/attachment1.png"
    attachment2 = Mock(spec=["content"])
    attachment2.content = "https://example.com/attachment2.pdf"
    issue.fields.attachment = [attachment1, attachment2]

    # Mock permalink
    issue.permalink.return_value = "https://test.atlassian.net/browse/TEST-123"

    return issue


@pytest.fixture
def sample_field_metadata() -> list[dict[str, Any]]:
    """Create sample field metadata for testing."""
    return [
        {"id": "customfield_10001", "name": "Custom Field 1"},
        {"id": "customfield_10002", "name": "Custom Field 2"},
        {"id": "customfield_10003", "name": "Boolean Field"},
    ]


@pytest.fixture
def sample_issue_metadata() -> dict[str, Any]:
    """Create sample issue metadata for testing."""
    return {
        "projects": [
            {
                "key": "TEST",
                "name": "Test Project",
                "issuetypes": [
                    {
                        "id": "1",
                        "name": "Bug",
                        "fields": {
                            "summary": {
                                "key": "summary",
                                "name": "Summary",
                                "required": True,
                                "schema": {"type": "string"},
                            },
                            "description": {
                                "key": "description",
                                "name": "Description",
                                "required": False,
                                "schema": {"type": "string"},
                            },
                            "priority": {
                                "key": "priority",
                                "name": "Priority",
                                "required": False,
                                "schema": {"type": "priority"},
                                "allowedValues": [
                                    {"id": "1", "value": "High"},
                                    {"id": "2", "value": "Medium"},
                                    {"id": "3", "value": "Low"},
                                ],
                            },
                            "issuetype": {
                                "key": "issuetype",
                                "name": "Issue Type",
                                "required": True,
                                "schema": {"type": "issuetype"},
                            },
                            "reporter": {
                                "key": "reporter",
                                "name": "Reporter",
                                "required": False,
                                "schema": {"type": "user"},
                            },
                            "customfield_10001": {
                                "key": "customfield_10001",
                                "name": "Custom Field 1",
                                "required": False,
                                "schema": {"type": "string"},
                            },
                            "customfield_10002": {
                                "key": "customfield_10002",
                                "name": "Tags",
                                "required": False,
                                "schema": {"type": "array", "items": "string"},
                            },
                        },
                    },
                    {
                        "id": "2",
                        "name": "Task",
                        "fields": {},
                    },
                ],
            }
        ]
    }


@pytest.fixture
def sample_defect() -> Any:
    """Create a sample Defect object for testing."""
    return Defect(
        title="Sample Defect",
        description="Sample Description",
        reporter="user123",
        status="Open",
        classification="Bug",
        priority="High",
        userDefinedFields=[
            UserDefinedFieldProperties(name="Custom Field 1", value="Value 1"),
            UserDefinedFieldProperties(name="Tags", value="tag1, tag2, tag3"),
        ],
        lastEdited=datetime.now(timezone.utc),
        principal=Login(username="test", password="test"),
    )


@pytest.fixture
def sample_defect_with_id() -> Any:
    """Create a sample DefectWithID object for testing."""

    return DefectWithID(
        id=DefectID(root="TEST-123"),
        title="Sample Defect",
        description="Sample Description",
        reporter="John Doe",
        status="Open",
        classification="Bug",
        priority="High",
        userDefinedFields=[
            UserDefinedFieldProperties(name="Custom Field 1", value="Value 1"),
            UserDefinedFieldProperties(name="Custom Field 2", value="Value 2"),
        ],
        lastEdited=datetime.now(timezone.utc),
        references=["https://example.com/file1.png"],
        principal=Login(username="test", password="test"),
    )

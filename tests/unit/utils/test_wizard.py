from typing import Any, Literal, cast, get_args
from unittest.mock import MagicMock, patch

import pytest

from testbench_defect_service.clients.jira.config import JiraDefectClientConfig
from testbench_defect_service.utils.wizard import (
    get_env_sourced_field_names,
    get_env_value,
    prompt_literal_field,
)

_WIZARD = "testbench_defect_service.utils.wizard"

_AUTH_TYPE = Literal[
    "basic",
    "oauth2 2LO",
    "oauth2 2LO (service account)",
    "oauth2 3LO",
    "oauth2 3LO (user account)",
]

_AUTH_WIZARD_CHOICES = [
    "basic",
    "oauth2 2LO (service account)",
    "oauth2 3LO (user account)",
]


def _select_mock() -> MagicMock:
    questionary = MagicMock()
    questionary.select.return_value.ask.return_value = "basic"
    return questionary


@pytest.mark.unit
def test_prompt_literal_field_defaults_to_all_literal_values() -> None:
    questionary = _select_mock()
    with patch(f"{_WIZARD}.questionary", questionary):
        prompt_literal_field(cast(Any, _AUTH_TYPE), "Auth", "basic")

    kwargs = questionary.select.call_args.kwargs
    assert kwargs["choices"] == list(get_args(_AUTH_TYPE))


@pytest.mark.unit
def test_prompt_literal_field_restricts_to_wizard_choices() -> None:
    questionary = _select_mock()
    with patch(f"{_WIZARD}.questionary", questionary):
        prompt_literal_field(cast(Any, _AUTH_TYPE), "Auth", "basic", _AUTH_WIZARD_CHOICES)

    kwargs = questionary.select.call_args.kwargs
    assert kwargs["choices"] == _AUTH_WIZARD_CHOICES


@pytest.mark.unit
@pytest.mark.parametrize(
    ("stored_value", "expected_default"),
    [
        ("oauth2 2LO", "oauth2 2LO (service account)"),
        ("oauth2 3LO", "oauth2 3LO (user account)"),
        ("oauth2 2LO (service account)", "oauth2 2LO (service account)"),
        ("basic", "basic"),
        (None, "basic"),
    ],
)
def test_prompt_literal_field_maps_short_alias_to_displayed_default(
    stored_value: str | None, expected_default: str
) -> None:
    questionary = _select_mock()
    with patch(f"{_WIZARD}.questionary", questionary):
        prompt_literal_field(cast(Any, _AUTH_TYPE), "Auth", stored_value, _AUTH_WIZARD_CHOICES)

    kwargs = questionary.select.call_args.kwargs
    assert kwargs["default"] == expected_default


@pytest.mark.unit
def test_jira_auth_type_wizard_choices_show_descriptive_oauth2_labels() -> None:
    extra = JiraDefectClientConfig.model_fields["auth_type"].json_schema_extra
    assert isinstance(extra, dict)
    choices = extra["wizard_choices"]
    assert isinstance(choices, list)
    string_choices = [choice for choice in choices if isinstance(choice, str)]
    assert "oauth2 2LO (service account)" in string_choices
    assert "oauth2 3LO (user account)" in string_choices
    assert "oauth2 2LO" not in string_choices
    assert "oauth2 3LO" not in string_choices


@pytest.fixture
def _no_jira_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("JIRA_PASSWORD", "JIRA_PASSWORD_FILE", "JIRA_USERNAME", "JIRA_USERNAME_FILE"):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.unit
@pytest.mark.usefixtures("_no_jira_env")
def test_get_env_value_reports_file_variable_for_credential_field(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("JIRA_PASSWORD_FILE", "/run/secrets/does-not-need-to-exist")
    field_info = JiraDefectClientConfig.model_fields["password"]
    assert get_env_value(field_info) == (
        "JIRA_PASSWORD_FILE",
        "/run/secrets/does-not-need-to-exist",
    )


@pytest.mark.unit
@pytest.mark.usefixtures("_no_jira_env")
def test_get_env_value_plain_variable_wins_over_file_variable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JIRA_PASSWORD", "plain")
    monkeypatch.setenv("JIRA_PASSWORD_FILE", "/run/secrets/pw")
    assert get_env_value(JiraDefectClientConfig.model_fields["password"]) == (
        "JIRA_PASSWORD",
        "plain",
    )


@pytest.mark.unit
@pytest.mark.usefixtures("_no_jira_env")
def test_get_env_value_ignores_file_variable_for_non_credential_field(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("JIRA_USERNAME_FILE", "/run/secrets/user")
    assert get_env_value(JiraDefectClientConfig.model_fields["username"]) == (
        "JIRA_USERNAME",
        None,
    )


@pytest.mark.unit
@pytest.mark.usefixtures("_no_jira_env")
def test_env_sourced_field_names_include_file_sourced_credentials(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("JIRA_PASSWORD_FILE", "/run/secrets/pw")
    assert "password" in get_env_sourced_field_names(JiraDefectClientConfig)

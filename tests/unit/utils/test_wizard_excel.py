"""Wizard behaviour for the Excel client configuration.

The wizard drives ``questionary`` interactively, so these tests swap it for a scripted
stand-in that answers prompts by matching on the question text and records everything
that was asked.
"""

from typing import Any

import pytest
import questionary

from testbench_defect_service.clients.excel.config import (
    ExcelDefectClientConfig,
    ProjectConfig,
    UserDefiendAttributes,
)
from testbench_defect_service.models.config import PhaseCommands
from testbench_defect_service.utils import wizard

EXCEL_PATH_RULE = ("path to the excel file", "defects.xlsx")


class WizardStuckError(AssertionError):
    """Raised when the wizard keeps asking questions the script does not resolve."""


class WizardScript:
    """Answers wizard prompts from substring rules and records what was asked.

    Each rule is a ``(substring, answer)`` pair. For every prompt the first rule whose
    substring occurs in the question text is consumed and its answer returned, so listing
    the same substring twice answers two successive occurrences differently. Unmatched
    prompts fall back to the question's own default (``False`` for confirmations).
    """

    def __init__(self, rules: list[tuple[str, Any]] | None = None, max_prompts: int = 200):
        self._rules = list(rules or [])
        self._max_prompts = max_prompts
        self.prompts: list[tuple[str, str]] = []

    def _answer(self, kind: str, message: str, fallback: Any) -> Any:
        self.prompts.append((kind, message))
        if len(self.prompts) > self._max_prompts:
            raise WizardStuckError(
                f"wizard asked more than {self._max_prompts} questions; "
                f"last question was {message!r}"
            )
        for index, (needle, answer) in enumerate(self._rules):
            if needle.lower() in message.lower():
                del self._rules[index]
                return answer
        return fallback

    def messages(self) -> list[str]:
        return [message for _, message in self.prompts]

    def matching(self, needle: str) -> list[str]:
        return [message for message in self.messages() if needle.lower() in message.lower()]

    def kinds_for(self, needle: str) -> list[str]:
        return [kind for kind, message in self.prompts if needle.lower() in message.lower()]

    def install(self, monkeypatch: pytest.MonkeyPatch) -> "WizardScript":
        script = self

        class _Answer:
            def __init__(self, value: Any):
                self._value = value

            def ask(self) -> Any:
                return self._value

        def _make(kind: str, fallback: Any):
            def _prompt(message: str, *_args: Any, **kwargs: Any) -> _Answer:
                default = kwargs.get("default", fallback)
                return _Answer(script._answer(kind, message, default))

            return _prompt

        for module in (questionary, wizard):
            monkeypatch.setattr(module, "text", _make("text", ""), raising=False)
            monkeypatch.setattr(module, "path", _make("path", ""), raising=False)
            monkeypatch.setattr(module, "password", _make("password", ""), raising=False)
            monkeypatch.setattr(module, "confirm", _make("confirm", False), raising=False)
            monkeypatch.setattr(module, "select", _make("select", None), raising=False)
            monkeypatch.setattr(module, "checkbox", _make("checkbox", []), raising=False)
        return self


class TestTransitionsAreControlFieldOnly:
    def test_top_level_transitions_are_not_prompted(self, monkeypatch):
        script = WizardScript([EXCEL_PATH_RULE]).install(monkeypatch)
        result = wizard.prompt_model_fields(ExcelDefectClientConfig)

        assert script.matching("transition") == []
        assert result is not None
        assert "transitions" not in result

    def test_project_level_transitions_are_not_prompted(self, monkeypatch):
        script = WizardScript().install(monkeypatch)
        result = wizard.prompt_model_fields(ProjectConfig)

        assert script.matching("transition") == []
        assert result is not None
        assert "transitions" not in result

    def test_control_field_still_prompts_for_its_transitions(self, monkeypatch):
        script = WizardScript(
            [
                EXCEL_PATH_RULE,
                ("add a Control Field", True),
                ("Control field name", "status"),
                ("Column number in the Excel file for this field", "7"),
                ("Allowed values", "Open,Closed"),
                ("add a state transition", True),
                ("From State", "Open"),
                ("To State", "Closed"),
            ]
        ).install(monkeypatch)
        result = wizard.prompt_model_fields(ExcelDefectClientConfig)

        assert result is not None
        assert result["control_fields"] == [
            {
                "name": "status",
                "column_number": 7,
                "values": ["Open", "Closed"],
                "transitions": [{"from_state": "Open", "to_state": "Closed"}],
            }
        ]
        assert "transitions" not in result

        transition_prompts = script.matching("transition")
        assert transition_prompts
        assert all("control field" in message.lower() for message in transition_prompts)

    def test_existing_legacy_transitions_are_preserved(self, monkeypatch):
        """Hiding a field from the wizard must not silently discard its configured value."""
        existing = {
            "excel_file_path": "defects.xlsx",
            "transitions": [{"from_state": "Open", "to_state": "Closed"}],
        }
        WizardScript([EXCEL_PATH_RULE]).install(monkeypatch)
        result = wizard.prompt_model_fields(ExcelDefectClientConfig, existing_config=existing)

        assert result is not None
        assert result["transitions"] == [{"from_state": "Open", "to_state": "Closed"}]

    def test_a_skipped_field_without_an_existing_value_stays_absent(self, monkeypatch):
        WizardScript([EXCEL_PATH_RULE]).install(monkeypatch)
        result = wizard.prompt_model_fields(
            ExcelDefectClientConfig, existing_config={"excel_file_path": "defects.xlsx"}
        )

        assert result is not None
        assert "transitions" not in result


class TestCommandsPrompt:
    def test_commands_are_offered_once_at_client_level(self, monkeypatch):
        script = WizardScript([EXCEL_PATH_RULE]).install(monkeypatch)
        wizard.prompt_model_fields(ExcelDefectClientConfig)

        command_prompts = script.matching("sync hook")
        assert len(command_prompts) == 1
        assert command_prompts[0].startswith("Configure")

    def test_phase_commands_collect_both_phases(self, monkeypatch):
        script = WizardScript(
            [
                ("Configure 'Pre-sync hook scripts", True),
                ("scheduled sync", "presync_scheduled.bat"),
                ("manual sync", "presync_manual.bat"),
                ("partial sync", "presync_partial.bat"),
                ("Configure 'Post-sync hook scripts", True),
                ("scheduled sync", "postsync_scheduled.bat"),
            ]
        ).install(monkeypatch)
        result = wizard.prompt_model_fields(PhaseCommands)

        assert result == {
            "presync": {
                "scheduled": "presync_scheduled.bat",
                "manual": "presync_manual.bat",
                "partial": "presync_partial.bat",
            },
            "postsync": {"scheduled": "postsync_scheduled.bat"},
        }
        PhaseCommands.model_validate(result)
        assert all(".bat" in message for message in script.matching("sync (path to"))

    def test_command_prompts_state_that_a_script_path_is_expected(self, monkeypatch):
        script = WizardScript([("Configure 'Pre-sync hook scripts", True)]).install(monkeypatch)
        wizard.prompt_model_fields(PhaseCommands)

        hints = script.matching(".bat, .sh or .exe")
        assert len(hints) == 3, "scheduled, manual and partial should each name the expected file"

    def test_declining_a_phase_leaves_it_unset(self, monkeypatch):
        script = WizardScript().install(monkeypatch)
        result = wizard.prompt_model_fields(PhaseCommands)

        assert result == {}
        assert PhaseCommands.model_validate(result).presync is None
        assert len(script.matching("Pre-sync hook scripts")) == 1
        assert len(script.matching("Post-sync hook scripts")) == 1


class TestUserDefinedAttributePrompt:
    def test_value_type_is_offered_as_a_selection(self, monkeypatch):
        script = WizardScript(
            [
                ("Name of the user-defined attribute", "isBlocker"),
                ("Column number in the Excel file for this attribute", "9"),
                ("Value type", "BOOLEAN"),
                ("represents 'true'", "yes"),
                ("represents 'false'", "no"),
            ]
        ).install(monkeypatch)
        result = wizard.prompt_model_fields(UserDefiendAttributes)

        assert script.kinds_for("Value type") == ["select"]
        assert result is not None
        assert result["type"] == "BOOLEAN"
        UserDefiendAttributes.model_validate(result)

    def test_boolean_only_fields_are_skipped_for_string_attributes(self, monkeypatch):
        script = WizardScript(
            [
                ("Name of the user-defined attribute", "title"),
                ("Column number in the Excel file for this attribute", "2"),
                ("Value type", "STRING"),
            ]
        ).install(monkeypatch)
        result = wizard.prompt_model_fields(UserDefiendAttributes)

        assert result is not None
        assert "trueValue" not in result
        assert "falseValue" not in result
        assert script.matching("represents") == []

    def test_boolean_attributes_are_asked_for_their_cell_values(self, monkeypatch):
        script = WizardScript(
            [
                ("Name of the user-defined attribute", "isBlocker"),
                ("Column number in the Excel file for this attribute", "9"),
                ("Value type", "BOOLEAN"),
                ("represents 'true'", "yes"),
                ("represents 'false'", "no"),
            ]
        ).install(monkeypatch)
        result = wizard.prompt_model_fields(UserDefiendAttributes)

        assert result is not None
        assert result["trueValue"] == "yes"
        assert result["falseValue"] == "no"
        assert len(script.matching("represents")) == 2

import pytest
from pydantic import ValidationError

from testbench_defect_service.clients.excel.config import (
    ControlFields,
    Transition,
    _normalize_legacy_excel_config,
)


@pytest.mark.unit
class TestControlFieldTransitions:
    def test_defaults_to_no_transitions(self) -> None:
        control_field = ControlFields(name="status", column_number=4, values=["New", "Done"])

        assert control_field.transitions == []

    def test_accepts_transitions_between_declared_values(self) -> None:
        control_field = ControlFields(
            name="status",
            column_number=4,
            values=["New", "Done"],
            transitions=[Transition(from_state="New", to_state="Done")],
        )

        assert control_field.transitions == [Transition(from_state="New", to_state="Done")]

    def test_rejects_to_state_outside_values(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            ControlFields(
                name="status",
                column_number=4,
                values=["New", "Done"],
                transitions=[Transition(from_state="New", to_state="Don")],
            )

        message = str(excinfo.value)
        assert "status" in message
        assert "to_state 'Don'" in message
        assert "New, Done" in message

    def test_rejects_from_state_outside_values(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            ControlFields(
                name="status",
                column_number=4,
                values=["New", "Done"],
                transitions=[Transition(from_state="Nwe", to_state="Done")],
            )

        assert "from_state 'Nwe'" in str(excinfo.value)

    def test_skips_validation_when_values_is_empty(self) -> None:
        control_field = ControlFields(
            name="status",
            column_number=4,
            transitions=[Transition(from_state="New", to_state="Done")],
        )

        assert len(control_field.transitions) == 1

    def test_class_name_still_normalizes_to_classification(self) -> None:
        control_field = ControlFields(
            name="class",
            column_number=6,
            values=["Crash", "Other"],
            transitions=[Transition(from_state="Crash", to_state="Other")],
        )

        assert control_field.name == "classification"


@pytest.mark.unit
class TestLegacyTransitionNormalization:
    def _legacy_data(self, **overrides: str) -> dict[str, str]:
        data = {
            "controlFields": "status,priority",
            "status.columnNo": "4",
            "status.value": "New,InProgress,Done",
            "priority.columnNo": "5",
            "priority.value": "Low,High",
            "status.transition.number": "2",
            "status.transition1": "New-InProgress",
            "status.transition2": "InProgress-Done",
        }
        data.update(overrides)
        return data

    def test_status_transitions_land_on_the_status_control_field(self) -> None:
        normalized = _normalize_legacy_excel_config(self._legacy_data())

        by_name = {field["name"]: field for field in normalized["control_fields"]}
        assert by_name["status"]["transitions"] == [
            {"from_state": "New", "to_state": "InProgress"},
            {"from_state": "InProgress", "to_state": "Done"},
        ]
        assert "transitions" not in by_name["priority"]

    def test_priority_transitions_land_on_the_priority_control_field(self) -> None:
        normalized = _normalize_legacy_excel_config(
            self._legacy_data(**{"priority.transition1": "Low-High"})
        )

        by_name = {field["name"]: field for field in normalized["control_fields"]}
        assert by_name["priority"]["transitions"] == [{"from_state": "Low", "to_state": "High"}]
        assert len(by_name["status"]["transitions"]) == 2

    def test_class_prefix_normalizes_to_classification(self) -> None:
        data = {
            "controlFields": "class",
            "class.columnNo": "6",
            "class.value": "Crash,Other",
            "class.transition1": "Crash-Other",
        }

        normalized = _normalize_legacy_excel_config(data)

        by_name = {field["name"]: field for field in normalized["control_fields"]}
        assert by_name["classification"]["transitions"] == [
            {"from_state": "Crash", "to_state": "Other"}
        ]

    def test_transition_number_key_is_not_parsed_as_a_transition(self) -> None:
        normalized = _normalize_legacy_excel_config(self._legacy_data())

        by_name = {field["name"]: field for field in normalized["control_fields"]}
        assert len(by_name["status"]["transitions"]) == 2

    def test_orphan_prefix_is_dropped_and_the_rest_still_loads(self) -> None:
        normalized = _normalize_legacy_excel_config(
            self._legacy_data(**{"severity.transition1": "Low-High"})
        )

        by_name = {field["name"]: field for field in normalized["control_fields"]}
        assert set(by_name) == {"status", "priority"}
        assert len(by_name["status"]["transitions"]) == 2

    def test_explicit_control_fields_are_left_alone(self) -> None:
        data = {
            "control_fields": [{"name": "status", "column_number": 4, "values": ["New", "Done"]}],
            "status.transition1": "New-Done",
        }

        normalized = _normalize_legacy_excel_config(data)

        assert normalized["control_fields"][0]["transitions"] == [
            {"from_state": "New", "to_state": "Done"}
        ]

    def test_explicit_top_level_transitions_beat_a_legacy_key(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        data = {
            "control_fields": [{"name": "status", "column_number": 4, "values": ["New", "Done"]}],
            "transitions": [{"from_state": "New", "to_state": "Done"}],
            "status.transition1": "New-InProgress",
        }

        with caplog.at_level("WARNING", logger="testbench_defect_service"):
            normalized = _normalize_legacy_excel_config(data)

        assert normalized["transitions"] == [{"from_state": "New", "to_state": "Done"}]
        assert "transitions" not in normalized["control_fields"][0]
        assert any(
            "status" in record.message and "top-level" in record.message
            for record in caplog.records
        )

    def test_explicit_control_field_named_class_receives_its_transitions(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        data = {
            "control_fields": [{"name": "class", "column_number": 6, "values": ["Crash", "Other"]}],
            "class.transition1": "Crash-Other",
        }

        with caplog.at_level("WARNING", logger="testbench_defect_service"):
            normalized = _normalize_legacy_excel_config(data)

        assert normalized["control_fields"][0]["transitions"] == [
            {"from_state": "Crash", "to_state": "Other"}
        ]
        assert caplog.records == []

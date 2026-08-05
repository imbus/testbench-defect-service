import pytest
from pydantic import ValidationError

from testbench_defect_service.clients.excel.config import ControlFields, Transition


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

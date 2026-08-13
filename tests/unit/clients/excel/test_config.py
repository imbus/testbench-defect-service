from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import ValidationError

from testbench_defect_service.clients.excel.config import (
    ControlFields,
    ExcelDefectClientConfig,
    ProjectConfig,
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


@pytest.mark.unit
class TestLegacyScalarKeys:
    """Every legacy `.properties` scalar key must reach its field.

    The keys here are the ones `docs/clients/excel-client.md` documents, so this pins the
    published contract rather than whatever the loader happens to accept.
    """

    LEGACY_DATA: ClassVar[dict[str, str]] = {
        "systemName": "Legacy Excel",
        "excelFilePath": r"C:\defects\excel",
        "worksheetName": "Defects",
        "fileType": ".xlsx",
        "simpleDateFormat": "yyyy-MM-dd",
        "defects.header.line": "1",
        "defects.data.startingLine": "2",
        "separator": ";",
        "defect.id.columnNo": "1",
        "defect.title.columnNo": "2",
        "defect.references.columnNo": "3",
        "defect.discoverer.columnNo": "4",
        "defect.lastedit.columnNo": "5",
        "defect.description.columnNo": "6",
        "defect.references.separator": ",",
        "defect.id.prefix": "BUG",
        "defect.id.startingValue": "1",
        "defect.id.digitNumber": "4",
        "bufferCleanupIntervalMinutes": "2",
        "bufferMaxAgeMinutes": "30",
        "bufferMaxSizeMiB": "512",
    }

    EXPECTED: ClassVar[dict[str, object]] = {
        "system_name": "Legacy Excel",
        "worksheet_name": "Defects",
        "file_type": ".xlsx",
        "simple_date_format": "yyyy-MM-dd",
        "defects_data_header_line": 1,
        "defects_data_starting_line": 2,
        "separator": ";",
        "id_column_no": 1,
        "title_column_no": 2,
        "references_column_no": 3,
        "discoverer_column_no": 4,
        "lastedit_column_no": 5,
        "description_column_no": 6,
        "references_separator": ",",
        "id_prefix": "BUG",
        "defect_id_starting_value": "1",
        "defect_id_digit_numbers": 4,
        "buffer_cleanup_interval_minutes": 2.0,
        "buffer_max_age_minutes": 30.0,
        "buffer_max_size_mib": 512.0,
    }

    @pytest.mark.parametrize("field_name", sorted(EXPECTED))
    def test_client_config_reads_every_documented_legacy_key(self, field_name: str) -> None:
        config = ExcelDefectClientConfig.model_validate(self.LEGACY_DATA)

        assert getattr(config, field_name) == self.EXPECTED[field_name]

    def test_client_config_reads_the_legacy_file_path(self) -> None:
        config = ExcelDefectClientConfig.model_validate(self.LEGACY_DATA)

        assert config.excel_file_path == Path(r"C:\defects\excel")

    @pytest.mark.parametrize(
        "field_name",
        sorted(set(EXPECTED) - {"system_name"}),
    )
    def test_project_config_reads_every_documented_legacy_key(self, field_name: str) -> None:
        """`ProjectConfig` carries the same aliases so a project block can be legacy too."""
        project_config = ProjectConfig.model_validate(self.LEGACY_DATA)

        assert getattr(project_config, field_name) == self.EXPECTED[field_name]

    def test_snake_case_keys_win_over_a_legacy_key_for_the_same_field(self) -> None:
        """Both spellings present is ambiguous; the modern one has always taken precedence."""
        config = ExcelDefectClientConfig.model_validate(
            {**self.LEGACY_DATA, "id_column_no": 9, "lastedit_column_no": 8}
        )

        assert config.id_column_no == 9
        assert config.lastedit_column_no == 8

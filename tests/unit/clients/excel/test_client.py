from pathlib import Path

import pytest

from testbench_defect_service.clients.excel.client import ExcelDefectClient
from testbench_defect_service.clients.excel.config import ControlFields, ExcelDefectClientConfig
from testbench_defect_service.models.defects import ProtocolCode, SyncContext


@pytest.fixture
def excel_project_path(tmp_path: Path) -> Path:
    project_path = tmp_path / "demo"
    project_path.mkdir()
    (project_path / "defects.csv").write_text(
        "id,title,references,reporter,lastEdited,description,status\n"
        "D-1,Demo,,Alice,2024-01-01,Example,Open\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def config(excel_project_path: Path) -> ExcelDefectClientConfig:
    return ExcelDefectClientConfig(
        system_name="Excel",
        excel_file_path=excel_project_path,
        file_type=".csv",
        simple_date_format="yyyy-MM-dd",
        defects_data_header_line=1,
        defects_data_starting_line=2,
        separator=",",
        control_fields=[
            ControlFields(name="status", column_number=7, values=["Open", "Closed"]),
        ],
        id_column_no=1,
        title_column_no=2,
        references_column_no=3,
        discoverer_column_no=4,
        lastedit_column_no=5,
        description_column_no=6,
        references_separator=";",
        id_prefix="D-",
        defect_id_starting_value="1",
        defect_id_digit_numbers=4,
    )


@pytest.mark.unit
def test_get_defects_returns_empty_result_when_sync_control_field_mapping_is_missing(
    config: ExcelDefectClientConfig,
):
    client = ExcelDefectClient(config)

    result = client.get_defects(
        "demo",
        SyncContext(
            iTBProject="string",
            statusAttribute="status",
            priorityAttribute="priority",
            classAttribute="classification",
        ),
    )

    assert result.value == []
    assert result.protocol.generalErrors is not None
    assert [entry.code for entry in result.protocol.generalErrors] == [
        ProtocolCode.IMPORT_ERROR,
        ProtocolCode.IMPORT_ERROR,
    ]
    assert [entry.message for entry in result.protocol.generalErrors] == [
        "Cannot import Excel defects: sync attribute 'priority' for 'priority' is not configured in the Excel control fields.",  # noqa: E501
        "Cannot import Excel defects: sync attribute 'classification' for 'classification' is not configured in the Excel control fields.",  # noqa: E501
    ]
    assert not result.protocol.generalWarnings
    assert not result.protocol.successes

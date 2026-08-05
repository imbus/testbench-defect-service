from datetime import datetime, timezone
from pathlib import Path

import pytest

from testbench_defect_service.clients.excel.client import ExcelDefectClient
from testbench_defect_service.clients.excel.config import (
    ControlFields,
    ExcelDefectClientConfig,
    ProjectConfig,
    Transition,
)
from testbench_defect_service.models.defects import (
    Defect,
    Login,
    ProtocolCode,
    SyncContext,
)


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


@pytest.fixture
def syncable_project_path(tmp_path: Path) -> Path:
    project_path = tmp_path / "demo"
    project_path.mkdir()
    (project_path / "defects.csv").write_text(
        "id,title,references,reporter,lastEdited,description,status,priority,classification\n"
        "D-0001,Demo,,Alice,2024-01-01,Example,Open,High,Bug\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def syncable_config(syncable_project_path: Path) -> ExcelDefectClientConfig:
    return ExcelDefectClientConfig(
        system_name="Excel",
        excel_file_path=syncable_project_path,
        file_type=".csv",
        simple_date_format="yyyy-MM-dd",
        defects_data_header_line=1,
        defects_data_starting_line=2,
        separator=",",
        control_fields=[
            ControlFields(name="status", column_number=7, values=["Open", "Closed"]),
            ControlFields(name="priority", column_number=8, values=["High", "Low"]),
            ControlFields(name="classification", column_number=9, values=["Bug", "Feature"]),
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


@pytest.fixture
def sync_context() -> SyncContext:
    return SyncContext(
        iTBProject="itb",
        statusAttribute="status",
        priorityAttribute="priority",
        classAttribute="classification",
    )


@pytest.fixture
def defect() -> Defect:
    return Defect(
        title="Locked file defect",
        description="Created while the workbook was open",
        reporter="Alice",
        status="Open",
        priority="High",
        classification="Bug",
        lastEdited=datetime(2024, 5, 1, tzinfo=timezone.utc),
        references=[],
        principal=Login(username="", password=""),
    )


@pytest.mark.unit
def test_create_defect_returns_null_id_when_file_is_locked(
    syncable_config: ExcelDefectClientConfig,
    sync_context: SyncContext,
    defect: Defect,
    monkeypatch: pytest.MonkeyPatch,
):
    """TestBench reads `value` as an Option; an empty string becomes Some("") and trips its
    non-empty ID assertion, aborting the whole sync. A failed create must report null."""
    locked_path = syncable_config.excel_file_path / "demo" / "defects.csv"

    def raise_permission_error(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied", str(locked_path))

    monkeypatch.setattr(
        "testbench_defect_service.clients.excel.client.write_defect_data",
        raise_permission_error,
    )
    client = ExcelDefectClient(syncable_config)

    result = client.create_defect("demo", defect, sync_context)

    assert result.value is None
    assert result.protocol.generalErrors is not None
    assert [entry.code for entry in result.protocol.generalErrors] == [ProtocolCode.INSERT_ERROR]


@pytest.mark.unit
def test_create_defect_reports_locked_file_hint_when_permission_is_denied(
    syncable_config: ExcelDefectClientConfig,
    sync_context: SyncContext,
    defect: Defect,
    monkeypatch: pytest.MonkeyPatch,
):
    locked_path = syncable_config.excel_file_path / "demo" / "defects.csv"

    def raise_permission_error(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied", str(locked_path))

    monkeypatch.setattr(
        "testbench_defect_service.clients.excel.client.write_defect_data",
        raise_permission_error,
    )
    client = ExcelDefectClient(syncable_config)

    result = client.create_defect("demo", defect, sync_context)

    assert result.protocol.generalErrors is not None
    message = result.protocol.generalErrors[0].message
    assert message is not None
    assert "defects.csv" in message
    assert "open in another program" in message
    assert "close the file" in message.lower()


@pytest.mark.unit
def test_create_defect_explains_why_when_a_sync_attribute_has_no_control_field(
    syncable_config: ExcelDefectClientConfig,
    defect: Defect,
):
    """A failed create must never come back with an empty protocol: TestBench would report
    the defect as failed with no reason for the user to act on."""
    client = ExcelDefectClient(syncable_config)
    sync_context = SyncContext(
        iTBProject="itb",
        statusAttribute="status",
        priorityAttribute="priority",
        classAttribute="class",  # config exposes this control field as 'classification'
    )

    result = client.create_defect("demo", defect, sync_context)

    assert result.value is None
    assert result.protocol.errors
    assert "class" in result.protocol.errors
    message = result.protocol.errors["class"][0].message
    assert message is not None
    assert "not configured as a control field" in message


@pytest.mark.unit
def test_create_defect_returns_null_id_when_client_is_readonly(
    syncable_config: ExcelDefectClientConfig,
    sync_context: SyncContext,
    defect: Defect,
):
    syncable_config.readonly = True
    client = ExcelDefectClient(syncable_config)

    result = client.create_defect("demo", defect, sync_context)

    assert result.value is None


@pytest.mark.unit
def test_create_defect_returns_null_id_when_project_is_missing(
    syncable_config: ExcelDefectClientConfig,
    sync_context: SyncContext,
    defect: Defect,
):
    client = ExcelDefectClient(syncable_config)

    result = client.create_defect("nope", defect, sync_context)

    assert result.value is None
    assert result.protocol.generalErrors is not None


@pytest.mark.unit
def test_update_defect_does_not_poison_buffer_when_write_fails(
    syncable_config: ExcelDefectClientConfig,
    sync_context: SyncContext,
    defect: Defect,
    monkeypatch: pytest.MonkeyPatch,
):
    """A failed write leaves the file mtime untouched, so the buffered frame is never
    refreshed. It must therefore not carry changes that were never persisted."""
    syncable_config.buffer_max_age_minutes = 60
    syncable_config.buffer_max_size_mib = 64
    defect_path = syncable_config.excel_file_path / "demo" / "defects.csv"

    def raise_permission_error(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied", str(defect_path))

    monkeypatch.setattr(
        "testbench_defect_service.clients.excel.client.write_defect_data",
        raise_permission_error,
    )
    client = ExcelDefectClient(syncable_config)

    defect.status = "Closed"
    protocol = client.update_defect("demo", "D-0001", defect, sync_context)

    assert protocol.errors
    buffered = client.get_defects("demo", sync_context)
    assert [d.status for d in buffered.value] == ["Open"]


# ---------------------------------------------------------------------------
# File-format handling of the write path
# ---------------------------------------------------------------------------


def _make_format_project(tmp_path: Path, file_name: str, content: str) -> Path:
    project_path = tmp_path / "demo"
    project_path.mkdir()
    (project_path / file_name).write_text(content, encoding="utf-8")
    return tmp_path


def _make_format_config(
    base_path: Path,
    file_type: str,
    transitions: list[Transition] | None = None,
) -> ExcelDefectClientConfig:
    return ExcelDefectClientConfig(
        system_name="Excel",
        excel_file_path=base_path,
        file_type=file_type,
        simple_date_format="yyyy-MM-dd",
        defects_data_header_line=1,
        defects_data_starting_line=2,
        separator=",",
        control_fields=[
            ControlFields(
                name="status",
                column_number=3,
                values=["New", "InProgress", "Done", "Open", "Closed"],
            ),
        ],
        id_column_no=1,
        title_column_no=2,
        references_column_no=0,
        discoverer_column_no=0,
        lastedit_column_no=0,
        description_column_no=0,
        references_separator=";",
        id_prefix="D-",
        defect_id_starting_value="1",
        defect_id_digit_numbers=4,
        transitions=transitions or [],
    )


@pytest.fixture
def status_sync_context() -> SyncContext:
    return SyncContext(iTBProject="itb", statusAttribute="status")


@pytest.fixture
def status_defect() -> Defect:
    return Defect(
        title="New defect",
        description="A defect",
        reporter="Alice",
        status="Open",
        priority="High",
        classification="Bug",
        lastEdited=datetime(2024, 5, 1, tzinfo=timezone.utc),
        references=[],
        principal=Login(username="", password=""),
    )


@pytest.mark.unit
def test_create_defect_in_tsv_project_writes_to_file(
    tmp_path: Path,
    status_sync_context: SyncContext,
    status_defect: Defect,
):
    base_path = _make_format_project(
        tmp_path, "defects.tsv", "id\ttitle\tstatus\nD-0001\tDemo\tOpen\n"
    )
    client = ExcelDefectClient(_make_format_config(base_path, ".tsv"))

    result = client.create_defect("demo", status_defect, status_sync_context)

    assert result.value == "D-0002"
    content = (base_path / "demo" / "defects.tsv").read_text(encoding="utf-8")
    assert "D-0002" in content
    assert "D-0002\tNew defect\tOpen" in content


@pytest.mark.unit
def test_create_defect_writes_when_file_type_case_differs(
    tmp_path: Path,
    status_sync_context: SyncContext,
    status_defect: Defect,
):
    base_path = _make_format_project(tmp_path, "defects.csv", "id,title,status\nD-0001,Demo,Open\n")
    client = ExcelDefectClient(_make_format_config(base_path, ".CSV"))

    result = client.create_defect("demo", status_defect, status_sync_context)

    assert result.value == "D-0002"
    content = (base_path / "demo" / "defects.csv").read_text(encoding="utf-8")
    assert "D-0002" in content


@pytest.mark.unit
def test_get_defects_accepts_file_type_without_leading_dot(tmp_path: Path):
    base_path = _make_format_project(tmp_path, "defects.csv", "id,title\nD-0001,Demo\n")
    client = ExcelDefectClient(_make_format_config(base_path, "csv"))

    result = client.get_defects("demo", SyncContext(iTBProject="itb"))

    assert [d.id.root for d in result.value] == ["D-0001"]


@pytest.mark.unit
def test_delete_defect_removes_row_from_csv_file(
    tmp_path: Path,
    status_sync_context: SyncContext,
    status_defect: Defect,
):
    base_path = _make_format_project(
        tmp_path,
        "defects.csv",
        "id,title,status\nD-0001,Demo,Open\nD-0002,Gone,Open\n",
    )
    client = ExcelDefectClient(_make_format_config(base_path, ".csv"))

    protocol = client.delete_defect("demo", "D-0002", status_defect, status_sync_context)

    assert protocol.successes
    content = (base_path / "demo" / "defects.csv").read_text(encoding="utf-8")
    assert "D-0002" not in content
    assert "D-0001" in content


@pytest.mark.unit
def test_update_defect_validates_transition_against_target_row(
    tmp_path: Path,
    status_sync_context: SyncContext,
    status_defect: Defect,
):
    base_path = _make_format_project(
        tmp_path,
        "defects.csv",
        "id,title,status\nD-0001,Demo,New\nD-0002,Target,InProgress\n",
    )
    config = _make_format_config(
        base_path,
        ".csv",
        transitions=[Transition(from_state="InProgress", to_state="Done")],
    )
    client = ExcelDefectClient(config)
    status_defect.status = "Done"

    protocol = client.update_defect("demo", "D-0002", status_defect, status_sync_context)

    assert not protocol.warnings
    assert protocol.successes
    content = (base_path / "demo" / "defects.csv").read_text(encoding="utf-8")
    assert "Done" in content


@pytest.fixture
def project_path_with_empty_row(syncable_project_path: Path) -> Path:
    (syncable_project_path / "demo" / "defects.csv").write_text(
        "id,title,references,reporter,lastEdited,description,status,priority,classification\n"
        "D-0001,Demo,,Alice,2024-01-01,Example,Open,High,Bug\n"
        ",,,,,,,,\n"
        "D-0002,Second,,Bob,2024-01-02,Example,Open,High,Bug\n",
        encoding="utf-8",
    )
    return syncable_project_path


@pytest.fixture
def project_path_with_half_filled_row(syncable_project_path: Path) -> Path:
    (syncable_project_path / "demo" / "defects.csv").write_text(
        "id,title,references,reporter,lastEdited,description,status,priority,classification\n"
        "D-0001,Demo,,Alice,2024-01-01,Example,Open,High,Bug\n"
        ",Half a row,,Bob,2024-01-02,Example,Open,High,Bug\n",
        encoding="utf-8",
    )
    return syncable_project_path


@pytest.mark.unit
def test_get_defects_skips_empty_rows_and_warns_once(
    project_path_with_empty_row: Path,
    syncable_config: ExcelDefectClientConfig,
    sync_context: SyncContext,
):
    """One stray empty row used to return zero defects for the whole project."""
    client = ExcelDefectClient(syncable_config)

    result = client.get_defects("demo", sync_context)

    assert [defect.id.root for defect in result.value] == ["D-0001", "D-0002"]
    assert not result.protocol.generalErrors
    assert result.protocol.generalWarnings is not None
    assert [entry.message for entry in result.protocol.generalWarnings] == [
        "Skipped 1 empty row(s) in 'defects.csv'."
    ]
    assert [entry.code for entry in result.protocol.generalWarnings] == [
        ProtocolCode.IMPORT_WARNING
    ]


@pytest.mark.unit
def test_get_defects_warns_about_empty_rows_on_a_buffered_read(
    project_path_with_empty_row: Path,
    syncable_config: ExcelDefectClientConfig,
    sync_context: SyncContext,
):
    """The second read is served from the dataframe buffer; the warning must survive it."""
    client = ExcelDefectClient(syncable_config)

    client.get_defects("demo", sync_context)
    result = client.get_defects("demo", sync_context)

    assert [defect.id.root for defect in result.value] == ["D-0001", "D-0002"]
    assert result.protocol.generalWarnings is not None
    assert [entry.message for entry in result.protocol.generalWarnings] == [
        "Skipped 1 empty row(s) in 'defects.csv'."
    ]


@pytest.mark.unit
def test_get_defects_still_fails_on_a_row_with_content_but_no_id(
    project_path_with_half_filled_row: Path,
    syncable_config: ExcelDefectClientConfig,
    sync_context: SyncContext,
):
    """A half-filled row is a data error, not layout.

    Silently skipping it would lose a defect, so the reader still aborts the
    file and `get_defects` still reports a general READ_ACCESS_ERROR.
    """
    client = ExcelDefectClient(syncable_config)

    result = client.get_defects("demo", sync_context)

    assert result.value == []
    assert result.protocol.generalErrors is not None
    assert [entry.code for entry in result.protocol.generalErrors] == [
        ProtocolCode.READ_ACCESS_ERROR
    ]
    assert result.protocol.generalErrors[0].message is not None
    assert "'id': empty at row 3" in result.protocol.generalErrors[0].message


@pytest.mark.unit
def test_create_defect_leaves_an_interior_empty_row_untouched(
    project_path_with_empty_row: Path,
    syncable_config: ExcelDefectClientConfig,
    sync_context: SyncContext,
    defect: Defect,
):
    """Empty rows are preserved, so the new defect lands after them.

    Compacting the row away would shift every later defect up one line and
    re-pair any unmapped column with the wrong defect.
    """
    client = ExcelDefectClient(syncable_config)

    result = client.create_defect("demo", defect, sync_context)

    assert result.value == "D-0003"
    lines = (
        (project_path_with_empty_row / "demo" / "defects.csv")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert lines == [
        "id,title,references,reporter,lastEdited,description,status,priority,classification",
        "D-0001,Demo,,Alice,2024-01-01,Example,Open,High,Bug",
        ",,,,,,,,",
        "D-0002,Second,,Bob,2024-01-02,Example,Open,High,Bug",
        (
            "D-0003,Locked file defect,,Alice,2024-05-01,"
            "Created while the workbook was open,Open,High,Bug"
        ),
    ]


@pytest.mark.unit
def test_project_override_uses_its_own_control_field_transitions(
    config: ExcelDefectClientConfig,
) -> None:
    config.control_fields = [
        ControlFields(
            name="status",
            column_number=7,
            values=["Open", "Closed"],
            transitions=[Transition(from_state="Open", to_state="Closed")],
        )
    ]
    config.projects = {
        "demo": ProjectConfig(
            control_fields=[
                ControlFields(
                    name="status",
                    column_number=7,
                    values=["Open", "Blocked"],
                    transitions=[Transition(from_state="Open", to_state="Blocked")],
                )
            ],
            attributes=None,
        )
    }
    client = ExcelDefectClient(config)

    effective = client._get_effective_config("demo")

    status_field = next(field for field in effective.control_fields if field.name == "status")
    assert status_field.values == ["Open", "Blocked"]
    assert status_field.transitions == [Transition(from_state="Open", to_state="Blocked")]

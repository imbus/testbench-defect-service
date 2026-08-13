import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sanic import NotFound, ServerError

from testbench_defect_service.clients.excel.client import ExcelDefectClient
from testbench_defect_service.clients.excel.config import (
    ControlFields,
    ExcelDefectClientConfig,
    ProjectConfig,
    Transition,
)
from testbench_defect_service.models.config import PhaseCommands, SyncCommandConfig
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
# Clearing fields on update
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_update_defect_clears_fields_that_arrive_empty(
    syncable_config: ExcelDefectClientConfig,
    sync_context: SyncContext,
    defect: Defect,
):
    """TestBench sends the full defect state on update, so a title the user cleared arrives as
    null. Keeping the old cell would strand the file on a value nobody can see any more."""
    defect_path = syncable_config.excel_file_path / "demo" / "defects.csv"
    client = ExcelDefectClient(syncable_config)

    protocol = client.update_defect(
        "demo",
        "D-0001",
        defect.model_copy(update={"title": None, "description": None, "reporter": None}),
        sync_context,
    )

    assert not protocol.errors
    row = defect_path.read_text(encoding="utf-8").splitlines()[1].split(",")
    assert row[0] == "D-0001"
    assert row[1] == ""  # title
    assert row[3] == ""  # reporter
    assert row[5] == ""  # description


@pytest.mark.unit
def test_update_defect_leaves_columns_the_payload_never_mentions_untouched(
    syncable_config: ExcelDefectClientConfig,
    sync_context: SyncContext,
    defect: Defect,
):
    """An absent field means 'not synced' and must keep its cell; only a field that is present
    and empty clears one. Boolean UDFs rely on this - TestBench sends them as duplicate
    null-and-value entries, so a null must never be able to blank a cell on its own."""
    defect_path = syncable_config.excel_file_path / "demo" / "defects.csv"
    defect_path.write_text(
        "id,title,references,reporter,lastEdited,description,status,priority,classification,notes\n"
        "D-0001,Demo,,Alice,2024-01-01,Example,Open,High,Bug,keep me\n",
        encoding="utf-8",
    )
    client = ExcelDefectClient(syncable_config)

    client.update_defect("demo", "D-0001", defect.model_copy(update={"title": None}), sync_context)

    assert "keep me" in defect_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Extended defect view
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_defect_extended_raises_not_found_for_an_unknown_defect(
    syncable_config: ExcelDefectClientConfig,
    sync_context: SyncContext,
):
    client = ExcelDefectClient(syncable_config)

    with pytest.raises(NotFound) as excinfo:
        client.get_defect_extended("demo", "D-9999", sync_context)

    assert "D-9999" in str(excinfo.value)


@pytest.mark.unit
def test_get_defect_extended_names_the_missing_project(
    syncable_config: ExcelDefectClientConfig,
    sync_context: SyncContext,
):
    """The bare `raise FileNotFoundError from exc` dropped the message, leaving the caller with
    an empty exception and no way to tell a missing project from a missing file."""
    client = ExcelDefectClient(syncable_config)

    with pytest.raises(NotFound) as excinfo:
        client.get_defect_extended("nope", "D-0001", sync_context)

    assert "nope" in str(excinfo.value)


@pytest.mark.unit
def test_get_defect_extended_reports_why_a_read_failed(
    syncable_config: ExcelDefectClientConfig,
    sync_context: SyncContext,
    monkeypatch: pytest.MonkeyPatch,
):
    def raise_value_error(*_args, **_kwargs):
        raise ValueError("Uniqueness constraints violated in 'defects.csv'")

    monkeypatch.setattr(
        "testbench_defect_service.clients.excel.client.read_data_frame_from_file_path",
        raise_value_error,
    )
    client = ExcelDefectClient(syncable_config)

    with pytest.raises(ServerError) as excinfo:
        client.get_defect_extended("demo", "D-0001", sync_context)

    assert "Uniqueness constraints violated" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Concurrent writers
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_concurrent_creates_assign_a_distinct_id_to_every_defect(
    syncable_config: ExcelDefectClientConfig,
    sync_context: SyncContext,
    defect: Defect,
):
    """Every mutation is a read-modify-rewrite of the whole file. Writers that read the same
    frame all derive the same next id, and the last write wins - so defects go missing while
    each caller is told it succeeded."""
    writer_count = 4
    client = ExcelDefectClient(syncable_config)
    start = threading.Barrier(writer_count)
    created_ids: list[str | None] = []
    ids_lock = threading.Lock()

    def create(index: int) -> None:
        start.wait()
        new_defect = defect.model_copy(update={"title": f"D{index}"})
        result = client.create_defect("demo", new_defect, sync_context)
        with ids_lock:
            created_ids.append(result.value)

    threads = [threading.Thread(target=create, args=(index,)) for index in range(writer_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(x for x in created_ids if x is not None) == [
        "D-0002",
        "D-0003",
        "D-0004",
        "D-0005",
    ]


@pytest.mark.unit
def test_concurrent_creates_keep_every_written_defect_in_the_file(
    syncable_config: ExcelDefectClientConfig,
    sync_context: SyncContext,
    defect: Defect,
):
    writer_count = 4
    defect_path = syncable_config.excel_file_path / "demo" / "defects.csv"
    client = ExcelDefectClient(syncable_config)
    start = threading.Barrier(writer_count)

    def create(index: int) -> None:
        start.wait()
        client.create_defect("demo", defect.model_copy(update={"title": f"D{index}"}), sync_context)

    threads = [threading.Thread(target=create, args=(index,)) for index in range(writer_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    rows = defect_path.read_text(encoding="utf-8").splitlines()[1:]
    assert sorted(row.split(",")[1] for row in rows) == ["D0", "D1", "D2", "D3", "Demo"]


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


# ---------------------------------------------------------------------------
# Unusable rows
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_defects_imports_the_good_rows_when_one_id_is_duplicated(
    tmp_path: Path,
    status_sync_context: SyncContext,
):
    base_path = _make_format_project(
        tmp_path,
        "defects.csv",
        "id,title,status\nD-0001,First,Open\nD-0002,Ambiguous,Open\nD-0002,Also,Open\n"
        "D-0003,Last,Open\n",
    )
    client = ExcelDefectClient(_make_format_config(base_path, ".csv"))

    result = client.get_defects("demo", status_sync_context)

    assert [defect.id.root for defect in result.value] == ["D-0001", "D-0003"]
    assert result.protocol.errors is not None
    assert "D-0002" in result.protocol.errors


@pytest.mark.unit
def test_a_broken_row_does_not_block_updating_a_healthy_defect(
    tmp_path: Path,
    status_sync_context: SyncContext,
    status_defect: Defect,
):
    """The point of the change: a file with one unusable row stays repairable through the
    service instead of only by hand. The broken rows must survive the write untouched."""
    base_path = _make_format_project(
        tmp_path,
        "defects.csv",
        "id,title,status\nD-0001,Healthy,Open\nD-0002,Twin,Open\nD-0002,Twin,Open\n"
        ",Orphan title,Open\n",
    )
    client = ExcelDefectClient(_make_format_config(base_path, ".csv"))
    status_defect.title = "Repaired"

    protocol = client.update_defect("demo", "D-0001", status_defect, status_sync_context)

    assert protocol.successes
    lines = (base_path / "demo" / "defects.csv").read_text(encoding="utf-8").splitlines()
    assert lines[1] == "D-0001,Repaired,Open"
    assert lines[2] == "D-0002,Twin,Open"
    assert lines[3] == "D-0002,Twin,Open"
    assert lines[4] == ",Orphan title,Open"


@pytest.mark.unit
def test_update_defect_refuses_an_ambiguous_id(
    tmp_path: Path,
    status_sync_context: SyncContext,
    status_defect: Defect,
):
    """Writing to one of two rows carrying the same id would leave the other as a stale copy
    of the same defect, which no later sync can reconcile."""
    body = "id,title,status\nD-0002,Twin,Open\nD-0002,Twin,Open\n"
    base_path = _make_format_project(tmp_path, "defects.csv", body)
    client = ExcelDefectClient(_make_format_config(base_path, ".csv"))
    status_defect.title = "Repaired"

    protocol = client.update_defect("demo", "D-0002", status_defect, status_sync_context)

    assert not protocol.successes
    assert protocol.errors is not None
    assert "D-0002" in protocol.errors
    assert (base_path / "demo" / "defects.csv").read_text(encoding="utf-8") == body


@pytest.mark.unit
def test_delete_defect_refuses_an_ambiguous_id(
    tmp_path: Path,
    status_sync_context: SyncContext,
    status_defect: Defect,
):
    body = "id,title,status\nD-0002,Twin,Open\nD-0002,Twin,Open\n"
    base_path = _make_format_project(tmp_path, "defects.csv", body)
    client = ExcelDefectClient(_make_format_config(base_path, ".csv"))

    protocol = client.delete_defect("demo", "D-0002", status_defect, status_sync_context)

    assert not protocol.successes
    assert (base_path / "demo" / "defects.csv").read_text(encoding="utf-8") == body


# ---------------------------------------------------------------------------
# Defect ID numbering
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_first_defect_id_uses_the_configured_starting_value(
    tmp_path: Path,
    status_sync_context: SyncContext,
    status_defect: Defect,
):
    base_path = _make_format_project(tmp_path, "defects.csv", "id,title,status\n")
    config = _make_format_config(base_path, ".csv").model_copy(
        update={"defect_id_starting_value": "500"}
    )
    client = ExcelDefectClient(config)

    result = client.create_defect("demo", status_defect, status_sync_context)

    assert result.value == "D-0500"


@pytest.mark.unit
def test_starting_value_does_not_renumber_a_file_that_already_has_ids(
    tmp_path: Path,
    status_sync_context: SyncContext,
    status_defect: Defect,
):
    """The starting value says where numbering begins, not where it jumps to. A file that
    already carries IDs has its own numbering to continue."""
    base_path = _make_format_project(tmp_path, "defects.csv", "id,title,status\nD-0001,Demo,Open\n")
    config = _make_format_config(base_path, ".csv").model_copy(
        update={"defect_id_starting_value": "500"}
    )
    client = ExcelDefectClient(config)

    result = client.create_defect("demo", status_defect, status_sync_context)

    assert result.value == "D-0002"


@pytest.mark.unit
def test_unusable_starting_value_falls_back_to_one(
    tmp_path: Path,
    status_sync_context: SyncContext,
    status_defect: Defect,
    caplog: pytest.LogCaptureFixture,
):
    """The key was accepted but ignored for years, so a config may carry any leftover in it.
    Honouring it must not turn a working project into a failing one."""
    base_path = _make_format_project(tmp_path, "defects.csv", "id,title,status\n")
    config = _make_format_config(base_path, ".csv").model_copy(
        update={"defect_id_starting_value": "not a number"}
    )
    client = ExcelDefectClient(config)

    result = client.create_defect("demo", status_defect, status_sync_context)

    assert result.value == "D-0001"
    assert "not a number" in caplog.text


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
def test_get_defects_reports_a_row_with_content_but_no_id_and_imports_the_rest(
    project_path_with_half_filled_row: Path,
    syncable_config: ExcelDefectClientConfig,
    sync_context: SyncContext,
):
    """A half-filled row is a data error, not layout - but it is one row's error.

    Aborting the whole file over it left no way to repair anything through the service, so the
    row is reported against its row number and skipped while every other defect still syncs.
    Reporting is what keeps this from silently losing a defect.
    """
    client = ExcelDefectClient(syncable_config)

    result = client.get_defects("demo", sync_context)

    assert [defect.id.root for defect in result.value] == ["D-0001"]
    assert not result.protocol.generalErrors
    assert result.protocol.errors is not None
    assert "3" in result.protocol.errors
    assert [entry.code for entry in result.protocol.errors["3"]] == [ProtocolCode.IMPORT_ERROR]
    message = result.protocol.errors["3"][0].message
    assert message is not None
    assert "no defect id" in message


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


@pytest.mark.unit
class TestSyncHookCommands:
    """The wizard writes sync hooks to 'commands'; the client must read that same key."""

    @staticmethod
    def _script(tmp_path: Path) -> Path:
        script = tmp_path / "hook.bat"
        script.write_text("@echo off", encoding="utf-8")
        return script

    def test_before_sync_runs_the_configured_presync_command(
        self,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
        tmp_path: Path,
    ):
        script = self._script(tmp_path)
        config.commands = PhaseCommands(presync=SyncCommandConfig(manual=str(script)))
        client = ExcelDefectClient(config)

        with patch("testbench_defect_service.clients.utils.subprocess.run") as run:
            protocol = client.before_sync("demo", "manual", sync_context)

        run.assert_called_once_with([str(script), "demo", "manual"], check=True)
        assert protocol.successes

    def test_after_sync_runs_the_configured_postsync_command(
        self,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
        tmp_path: Path,
    ):
        script = self._script(tmp_path)
        config.commands = PhaseCommands(postsync=SyncCommandConfig(scheduled=str(script)))
        client = ExcelDefectClient(config)

        with patch("testbench_defect_service.clients.utils.subprocess.run") as run:
            protocol = client.after_sync("demo", "scheduled", sync_context)

        run.assert_called_once_with([str(script), "demo", "scheduled"], check=True)
        assert protocol.successes

    def test_project_commands_take_precedence_over_the_client_default(
        self,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
        tmp_path: Path,
    ):
        default_script = self._script(tmp_path)
        project_script = tmp_path / "project_hook.bat"
        project_script.write_text("@echo off", encoding="utf-8")

        config.commands = PhaseCommands(presync=SyncCommandConfig(manual=str(default_script)))
        config.projects = {
            "demo": ProjectConfig(
                commands=PhaseCommands(presync=SyncCommandConfig(manual=str(project_script)))
            )
        }
        client = ExcelDefectClient(config)

        with patch("testbench_defect_service.clients.utils.subprocess.run") as run:
            client.before_sync("demo", "manual", sync_context)

        run.assert_called_once_with([str(project_script), "demo", "manual"], check=True)

    def test_no_configured_command_is_acknowledged_without_running_anything(
        self,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        client = ExcelDefectClient(config)

        with patch("testbench_defect_service.clients.utils.subprocess.run") as run:
            protocol = client.before_sync("demo", "manual", sync_context)

        run.assert_not_called()
        assert protocol.successes


@pytest.fixture
def sandboxed_config(tmp_path: Path) -> ExcelDefectClientConfig:
    """A configured base directory with a readable sibling the client must not reach.

    Both directories hold a matching `.csv`, so a test that resolves outside the base finds a
    real file rather than a `FileNotFoundError` that would pass for the wrong reason.
    """
    base_path = tmp_path / "projects"
    (base_path / "demo").mkdir(parents=True)
    (base_path / "demo" / "defects.csv").write_text(
        "id,title,references,reporter,lastEdited,description,status,priority,classification\n"
        "D-0001,Demo,,Alice,2024-01-01,Example,Open,High,Bug\n",
        encoding="utf-8",
    )
    outside_path = tmp_path / "outside"
    outside_path.mkdir()
    (outside_path / "secrets.csv").write_text(
        "id,title,references,reporter,lastEdited,description,status,priority,classification\n"
        "D-9999,Secret,,Mallory,2024-01-01,Leaked,Open,High,Bug\n",
        encoding="utf-8",
    )
    return ExcelDefectClientConfig(
        system_name="Excel",
        excel_file_path=base_path,
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


@pytest.mark.unit
class TestProjectPathSandboxing:
    """`project` comes from the request, so it must not be able to name a directory.

    `Path.joinpath` honours `..` segments and discards the base entirely when the appended
    segment is absolute, so an unguarded join lets a caller read - and through update/delete,
    modify - spreadsheets anywhere on the host.
    """

    @pytest.mark.parametrize(
        "project",
        [
            "../outside",
            "..\\outside",
            "demo/../../outside",
            "./../outside",
        ],
        ids=["posix-parent", "windows-parent", "nested-parent", "dot-parent"],
    )
    def test_get_defects_rejects_a_project_that_escapes_the_base_directory(
        self,
        project: str,
        sandboxed_config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        client = ExcelDefectClient(sandboxed_config)

        result = client.get_defects(project, sync_context)

        assert result.value == []
        assert result.protocol.generalErrors is not None
        assert [entry.code for entry in result.protocol.generalErrors] == [
            ProtocolCode.PROJECT_NOT_FOUND
        ]

    def test_get_defects_rejects_an_absolute_project_path(
        self,
        tmp_path: Path,
        sandboxed_config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        """`joinpath` drops the base entirely when the segment is absolute.

        That is a separate escape from `..`, so it needs its own case.
        """
        client = ExcelDefectClient(sandboxed_config)

        result = client.get_defects(str(tmp_path / "outside"), sync_context)

        assert result.value == []
        assert result.protocol.generalErrors is not None
        assert [entry.code for entry in result.protocol.generalErrors] == [
            ProtocolCode.PROJECT_NOT_FOUND
        ]

    def test_check_login_rejects_an_escaping_project(
        self,
        sandboxed_config: ExcelDefectClientConfig,
    ):
        """`check_login` reads `project` from a query parameter, so no route regex applies."""
        client = ExcelDefectClient(sandboxed_config)

        assert client.check_login("../outside") is False

    def test_update_defect_rejects_an_escaping_project(
        self,
        sandboxed_config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        """The write paths resolve the same way, so the guard has to hold for them too."""
        client = ExcelDefectClient(sandboxed_config)
        defect = Defect(
            title="Injected",
            description="Injected",
            reporter="Mallory",
            status="Open",
            classification="Bug",
            priority="High",
            lastEdited=datetime(2024, 1, 1, tzinfo=timezone.utc),
            principal=Login(username="u", password="p"),
            references=[],
        )

        protocol = client.update_defect("../outside", "D-9999", defect, sync_context)

        assert protocol.generalErrors is not None
        assert [entry.code for entry in protocol.generalErrors] == [ProtocolCode.PROJECT_NOT_FOUND]
        assert (
            "D-9999,Secret"
            in (sandboxed_config.excel_file_path.parent / "outside" / "secrets.csv").read_text()
        )

    def test_a_legitimate_project_still_resolves(
        self,
        sandboxed_config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        client = ExcelDefectClient(sandboxed_config)

        result = client.get_defects("demo", sync_context)

        assert [defect.id.root for defect in result.value] == ["D-0001"]
        assert not result.protocol.generalErrors

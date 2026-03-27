"""Unit tests for JSONL client utility functions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sanic.exceptions import InvalidUsage, NotFound, ServerError

from testbench_defect_service.clients.jsonl.utils import (
    add_missing_defect_warnings,
    append_defect_to_jsonl,
    build_protocol_result,
    find_defect_by_id,
    find_defects_files,
    generate_defect_id,
    parse_defect_line,
    parse_defects_from_file,
    parse_requested_defects,
    remove_defect_from_list,
    update_defect_in_list,
    validate_defect,
    validate_udf_structure,
    write_defects_to_file,
)
from testbench_defect_service.models.defects import (
    Defect,
    DefectID,
    DefectWithID,
    Login,
    Protocol,
    ProtocolCode,
    ProtocolledDefectSet,
    ProtocolledString,
)


@pytest.fixture
def sample_defect() -> Defect:
    """Create a minimal valid Defect."""
    return Defect(
        title="Test Bug",
        description="A test bug description",
        reporter="tester",
        status="Open",
        classification="Bug",
        priority="High",
        lastEdited=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        principal=Login(username="user", password="pass"),
    )


@pytest.fixture
def sample_defect_with_id() -> DefectWithID:
    """Create a minimal valid DefectWithID."""
    return DefectWithID(
        id=DefectID(root="BUG-1"),
        title="Test Bug",
        description="A test bug description",
        reporter="tester",
        status="Open",
        classification="Bug",
        priority="High",
        lastEdited=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        principal=Login(username="user", password="pass"),
    )


def _write_jsonl(path: Path, defects: list[DefectWithID]) -> None:
    """Helper to write a list of DefectWithID objects to a JSONL file."""
    with path.open("w", encoding="utf-8") as f:
        for d in defects:
            f.write(json.dumps(d.model_dump(mode="json")) + "\n")


def _make_defect(defect_id: str, title: str = "Bug") -> DefectWithID:
    """Helper to create a DefectWithID with minimal boilerplate."""
    return DefectWithID(
        id=DefectID(root=defect_id),
        title=title,
        description="desc",
        status="Open",
        classification="Bug",
        priority="High",
        lastEdited=datetime(2024, 1, 1, tzinfo=timezone.utc),
        principal=Login(username="u", password="p"),
    )


@pytest.mark.unit
class TestFindDefectsFiles:
    def test_finds_jsonl_files(self, tmp_path: Path):
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        (project_dir / "bugs.jsonl").write_text("{}", encoding="utf-8")
        (project_dir / "tasks.jsonl").write_text("{}", encoding="utf-8")

        result = find_defects_files(tmp_path, "myproject")

        assert len(result) == 2
        assert all(p.suffix == ".jsonl" for p in result)

    def test_ignores_non_jsonl_files(self, tmp_path: Path):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / "readme.txt").write_text("hi", encoding="utf-8")
        (project_dir / "bugs.jsonl").write_text("{}", encoding="utf-8")

        result = find_defects_files(tmp_path, "proj")

        assert len(result) == 1
        assert result[0].name == "bugs.jsonl"

    def test_raises_when_no_jsonl_files(self, tmp_path: Path):
        project_dir = tmp_path / "empty"
        project_dir.mkdir()

        with pytest.raises(FileNotFoundError, match=r"No \.jsonl files found"):
            find_defects_files(tmp_path, "empty")

    def test_raises_when_directory_missing(self, tmp_path: Path):
        with pytest.raises((FileNotFoundError, OSError)):
            find_defects_files(tmp_path, "nonexistent")


@pytest.mark.unit
class TestGenerateDefectId:
    def test_generates_next_id(self, tmp_path: Path):
        jsonl_file = tmp_path / "bugs.jsonl"
        jsonl_file.write_text(
            '{"id": "BUG-1"}\n{"id": "BUG-3"}\n{"id": "BUG-2"}\n', encoding="utf-8"
        )

        result = generate_defect_id(jsonl_file, "BUG-")

        assert result == "BUG-4"

    def test_starts_at_one_for_empty_file(self, tmp_path: Path):
        jsonl_file = tmp_path / "bugs.jsonl"
        jsonl_file.write_text("", encoding="utf-8")

        result = generate_defect_id(jsonl_file, "BUG-")

        assert result == "BUG-1"


@pytest.mark.unit
class TestAppendDefectToJsonl:
    def test_appends_defect_and_returns_id(self, tmp_path: Path, sample_defect: Defect):
        jsonl_file = tmp_path / "bugs.jsonl"
        jsonl_file.write_text('{"id": "BUG-1"}\n', encoding="utf-8")

        result = append_defect_to_jsonl("testproj", jsonl_file, sample_defect)

        assert isinstance(result, ProtocolledString)
        assert result.value == "BUG-2"
        lines = jsonl_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        appended = json.loads(lines[1])
        assert appended["id"] == "BUG-2"
        assert appended["title"] == "Test Bug"

    def test_protocol_contains_success(self, tmp_path: Path, sample_defect: Defect):
        jsonl_file = tmp_path / "bugs.jsonl"
        jsonl_file.write_text('{"id": "BUG-1"}\n', encoding="utf-8")

        result = append_defect_to_jsonl("proj", jsonl_file, sample_defect)

        assert result.protocol.successes is not None
        assert "proj" in result.protocol.successes
        entry = result.protocol.successes["proj"][0]
        assert entry.code == ProtocolCode.INSERT_SUCCESS
        assert entry.message is not None
        assert "BUG-2" in entry.message


@pytest.mark.unit
class TestValidateDefect:
    def test_valid_defect_no_control_fields(self, sample_defect: Defect):
        assert validate_defect(sample_defect, {}) is True

    def test_valid_defect_with_matching_control_fields(self, sample_defect: Defect):
        control = {
            "status": ["Open", "Closed"],
            "priority": ["High", "Low"],
        }
        assert validate_defect(sample_defect, control) is True

    def test_invalid_status_not_in_control_fields(self, sample_defect: Defect):
        control = {"status": ["Closed", "Resolved"]}
        assert validate_defect(sample_defect, control) is False

    def test_missing_required_field_status(self):
        defect = Defect(
            title="X",
            status="",
            classification="Bug",
            priority="High",
            lastEdited=datetime.now(timezone.utc),
            principal=Login(username="u", password="p"),
        )
        assert validate_defect(defect, {}) is False

    def test_missing_required_field_classification(self):
        defect = Defect(
            title="X",
            status="Open",
            classification="",
            priority="High",
            lastEdited=datetime.now(timezone.utc),
            principal=Login(username="u", password="p"),
        )
        assert validate_defect(defect, {}) is False

    def test_missing_required_field_priority(self):
        defect = Defect(
            title="X",
            status="Open",
            classification="Bug",
            priority="",
            lastEdited=datetime.now(timezone.utc),
            principal=Login(username="u", password="p"),
        )
        assert validate_defect(defect, {}) is False

    def test_defect_with_id(self, sample_defect_with_id: DefectWithID):
        assert validate_defect(sample_defect_with_id, {}) is True

    def test_control_field_attribute_not_on_defect(self, sample_defect: Defect):
        control = {"nonexistent_field": ["value1", "value2"]}
        assert validate_defect(sample_defect, control) is False


@pytest.mark.unit
class TestBuildProtocolResult:
    def test_returns_protocolled_defect_set(self, sample_defect_with_id: DefectWithID):
        protocol = Protocol()
        protocol.add_success("key", "msg", ProtocolCode.IMPORT_SUCCESS)

        result = build_protocol_result([sample_defect_with_id], protocol)

        assert isinstance(result, ProtocolledDefectSet)
        assert len(result.value) == 1
        assert result.value[0].id.root == "BUG-1"
        assert result.protocol is protocol

    def test_empty_defects(self):
        protocol = Protocol()
        result = build_protocol_result([], protocol)

        assert result.value == []


@pytest.mark.unit
class TestParseDefectLine:
    def test_valid_json_line(self, sample_defect_with_id: DefectWithID):
        line = json.dumps(sample_defect_with_id.model_dump(mode="json"))
        protocol = Protocol()

        result = parse_defect_line(line, 1, "test.jsonl", protocol)

        assert result is not None
        assert result.id.root == "BUG-1"
        assert result.title == "Test Bug"

    def test_malformed_json_returns_none(self):
        protocol = Protocol()

        result = parse_defect_line("{bad json", 5, "broken.jsonl", protocol)

        assert result is None
        assert len(protocol.generalWarnings) == 1
        assert protocol.generalWarnings[0].code == ProtocolCode.IMPORT_WARNING
        assert "line 5" in protocol.generalWarnings[0].message

    def test_empty_line_returns_none(self):
        protocol = Protocol()

        result = parse_defect_line("", 1, "empty.jsonl", protocol)

        assert result is None


@pytest.mark.unit
class TestAddMissingDefectWarnings:
    def test_adds_warnings_for_missing_ids(self):
        protocol = Protocol()
        found = [_make_defect("BUG-1")]
        requested_ids = {"BUG-1", "BUG-2", "BUG-3"}

        add_missing_defect_warnings(requested_ids, found, "proj", protocol)

        assert "BUG-2" in protocol.warnings
        assert "BUG-3" in protocol.warnings
        assert "BUG-1" not in protocol.warnings

    def test_no_warnings_when_all_found(self):
        protocol = Protocol()
        found = [_make_defect("BUG-1")]

        add_missing_defect_warnings({"BUG-1"}, found, "proj", protocol)

        assert len(protocol.warnings) == 0

    def test_warning_protocol_code(self):
        protocol = Protocol()

        add_missing_defect_warnings({"BUG-99"}, [], "proj", protocol)

        entry = protocol.warnings["BUG-99"][0]
        assert entry.code == ProtocolCode.DEFECT_NOT_FOUND


@pytest.mark.unit
class TestUpdateDefectInList:
    def test_replaces_matching_defect(self, tmp_path: Path):
        original = _make_defect("BUG-1", title="Original")
        other = _make_defect("BUG-2", title="Other")
        jsonl_file = tmp_path / "bugs.jsonl"
        _write_jsonl(jsonl_file, [original, other])

        updated = _make_defect("BUG-1", title="Updated")
        protocol = Protocol()

        result, found = update_defect_in_list(jsonl_file, updated, protocol)

        assert len(result) == 2
        assert result[0].title == "Updated"
        assert result[1].title == "Other"
        assert found is True

    def test_preserves_all_when_no_match(self, tmp_path: Path):
        d1 = _make_defect("BUG-1")
        jsonl_file = tmp_path / "bugs.jsonl"
        _write_jsonl(jsonl_file, [d1])

        updated = _make_defect("BUG-999", title="Not present")
        protocol = Protocol()

        result, found = update_defect_in_list(jsonl_file, updated, protocol)

        assert len(result) == 1
        assert result[0].id.root == "BUG-1"
        assert found is False

    def test_handles_malformed_lines(self, tmp_path: Path):
        jsonl_file = tmp_path / "bugs.jsonl"
        d1 = _make_defect("BUG-1")
        with jsonl_file.open("w", encoding="utf-8") as f:
            f.write(json.dumps(d1.model_dump(mode="json")) + "\n")
            f.write("{bad json}\n")

        updated = _make_defect("BUG-1", title="Updated")
        protocol = Protocol()

        result, _ = update_defect_in_list(jsonl_file, updated, protocol)

        assert len(result) == 1
        assert protocol.generalWarnings is not None
        assert len(protocol.generalWarnings) == 1

    def test_raises_on_unreadable_file(self, tmp_path: Path):
        fake_path = tmp_path / "nonexistent.jsonl"
        protocol = Protocol()

        with pytest.raises(ServerError):
            update_defect_in_list(fake_path, _make_defect("BUG-1"), protocol)


@pytest.mark.unit
class TestRemoveDefectFromList:
    def test_removes_matching_defect(self, tmp_path: Path):
        d1 = _make_defect("BUG-1")
        d2 = _make_defect("BUG-2")
        jsonl_file = tmp_path / "bugs.jsonl"
        _write_jsonl(jsonl_file, [d1, d2])
        protocol = Protocol()

        remaining, deleted = remove_defect_from_list(jsonl_file, "BUG-1", protocol)

        assert len(remaining) == 1
        assert remaining[0].id.root == "BUG-2"
        assert deleted is not None
        assert deleted.id.root == "BUG-1"

    def test_returns_none_when_not_found(self, tmp_path: Path):
        d1 = _make_defect("BUG-1")
        jsonl_file = tmp_path / "bugs.jsonl"
        _write_jsonl(jsonl_file, [d1])
        protocol = Protocol()

        remaining, deleted = remove_defect_from_list(jsonl_file, "BUG-999", protocol)

        assert len(remaining) == 1
        assert deleted is None

    def test_handles_malformed_lines(self, tmp_path: Path):
        jsonl_file = tmp_path / "bugs.jsonl"
        d1 = _make_defect("BUG-1")
        with jsonl_file.open("w", encoding="utf-8") as f:
            f.write(json.dumps(d1.model_dump(mode="json")) + "\n")
            f.write("not valid json\n")
        protocol = Protocol()

        _, deleted = remove_defect_from_list(jsonl_file, "BUG-1", protocol)

        assert deleted is not None
        assert protocol.generalWarnings is not None
        assert len(protocol.generalWarnings) == 1

    def test_raises_on_unreadable_file(self, tmp_path: Path):
        protocol = Protocol()

        with pytest.raises(ServerError):
            remove_defect_from_list(tmp_path / "nope.jsonl", "BUG-1", protocol)


@pytest.mark.unit
class TestWriteDefectsToFile:
    def test_writes_defects_as_jsonl(self, tmp_path: Path):
        d1 = _make_defect("BUG-1", title="First")
        d2 = _make_defect("BUG-2", title="Second")
        out = tmp_path / "out.jsonl"

        write_defects_to_file(out, [d1, d2], "proj")

        lines = out.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["id"] == "BUG-1"
        assert json.loads(lines[1])["id"] == "BUG-2"

    def test_overwrites_existing_content(self, tmp_path: Path):
        out = tmp_path / "out.jsonl"
        out.write_text("old content\n", encoding="utf-8")
        d1 = _make_defect("BUG-1")

        write_defects_to_file(out, [d1], "proj")

        lines = out.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

    def test_writes_empty_file_for_no_defects(self, tmp_path: Path):
        out = tmp_path / "out.jsonl"

        write_defects_to_file(out, [], "proj")

        assert out.read_text(encoding="utf-8") == ""


@pytest.mark.unit
class TestFindDefectById:
    def test_finds_matching_defect(self, tmp_path: Path):
        d1 = _make_defect("BUG-1", title="First")
        d2 = _make_defect("BUG-2", title="Second")
        jsonl_file = tmp_path / "bugs.jsonl"
        _write_jsonl(jsonl_file, [d1, d2])

        result = find_defect_by_id(jsonl_file, "BUG-2", "proj")

        assert result.id.root == "BUG-2"
        assert result.title == "Second"

    def test_raises_not_found(self, tmp_path: Path):
        d1 = _make_defect("BUG-1")
        jsonl_file = tmp_path / "bugs.jsonl"
        _write_jsonl(jsonl_file, [d1])

        with pytest.raises(NotFound, match="BUG-999"):
            find_defect_by_id(jsonl_file, "BUG-999", "proj")

    def test_raises_invalid_usage_on_malformed_json(self, tmp_path: Path):
        jsonl_file = tmp_path / "bugs.jsonl"
        jsonl_file.write_text("{bad\n", encoding="utf-8")

        with pytest.raises(InvalidUsage, match="Malformed"):
            find_defect_by_id(jsonl_file, "BUG-1", "proj")

    def test_raises_server_error_on_unreadable(self, tmp_path: Path):
        with pytest.raises(ServerError):
            find_defect_by_id(tmp_path / "nope.jsonl", "BUG-1", "proj")


@pytest.mark.unit
class TestValidateUdfStructure:
    def test_valid_structure(self):
        udf = [
            {"name": "Environment", "valueType": "STRING"},
            {"name": "Reproducible", "valueType": "BOOLEAN"},
        ]
        validate_udf_structure(udf)

    def test_raises_on_non_list(self):
        with pytest.raises(ValueError, match="must contain a list"):
            validate_udf_structure({"name": "x", "valueType": "STRING"})

    def test_raises_on_non_dict_item(self):
        with pytest.raises(ValueError, match="list of dictionaries"):
            validate_udf_structure(["not a dict"])

    def test_raises_on_missing_name(self):
        with pytest.raises(ValueError, match="'name' and 'valueType'"):
            validate_udf_structure([{"valueType": "STRING"}])

    def test_raises_on_missing_value_type(self):
        with pytest.raises(ValueError, match="'name' and 'valueType'"):
            validate_udf_structure([{"name": "Env"}])


@pytest.mark.unit
class TestParseDefectsFromFile:
    def test_parses_all_defects(self, tmp_path: Path):
        d1 = _make_defect("BUG-1")
        d2 = _make_defect("BUG-2")
        jsonl_file = tmp_path / "bugs.jsonl"
        _write_jsonl(jsonl_file, [d1, d2])
        protocol = Protocol()

        result = parse_defects_from_file(jsonl_file, "proj", protocol)

        assert len(result) == 2
        assert protocol.successes is not None
        assert "BUG-1" in protocol.successes
        assert "BUG-2" in protocol.successes

    def test_skips_malformed_lines(self, tmp_path: Path):
        d1 = _make_defect("BUG-1")
        jsonl_file = tmp_path / "bugs.jsonl"
        with jsonl_file.open("w", encoding="utf-8") as f:
            f.write(json.dumps(d1.model_dump(mode="json")) + "\n")
            f.write("not json\n")
        protocol = Protocol()

        result = parse_defects_from_file(jsonl_file, "proj", protocol)

        assert len(result) == 1
        assert protocol.generalWarnings is not None
        assert len(protocol.generalWarnings) == 1

    def test_handles_empty_file(self, tmp_path: Path):
        jsonl_file = tmp_path / "bugs.jsonl"
        jsonl_file.write_text("", encoding="utf-8")
        protocol = Protocol()

        result = parse_defects_from_file(jsonl_file, "proj", protocol)

        assert result == []

    def test_handles_unreadable_file(self, tmp_path: Path):
        protocol = Protocol()

        result = parse_defects_from_file(tmp_path / "nope.jsonl", "proj", protocol)

        assert result == []
        assert protocol.generalErrors is not None
        assert len(protocol.generalErrors) == 1
        assert protocol.generalErrors[0].code == ProtocolCode.READ_ACCESS_ERROR


@pytest.mark.unit
class TestParseRequestedDefects:
    def test_returns_only_requested_ids(self, tmp_path: Path):
        d1 = _make_defect("BUG-1")
        d2 = _make_defect("BUG-2")
        d3 = _make_defect("BUG-3")
        jsonl_file = tmp_path / "bugs.jsonl"
        _write_jsonl(jsonl_file, [d1, d2, d3])
        protocol = Protocol()

        result = parse_requested_defects(jsonl_file, {"BUG-1", "BUG-3"}, "proj", protocol)

        assert len(result) == 2
        ids = {d.id.root for d in result}
        assert ids == {"BUG-1", "BUG-3"}

    def test_returns_empty_when_none_match(self, tmp_path: Path):
        d1 = _make_defect("BUG-1")
        jsonl_file = tmp_path / "bugs.jsonl"
        _write_jsonl(jsonl_file, [d1])
        protocol = Protocol()

        result = parse_requested_defects(jsonl_file, {"BUG-999"}, "proj", protocol)

        assert result == []

    def test_skips_malformed_lines(self, tmp_path: Path):
        d1 = _make_defect("BUG-1")
        jsonl_file = tmp_path / "bugs.jsonl"
        with jsonl_file.open("w", encoding="utf-8") as f:
            f.write("bad line\n")
            f.write(json.dumps(d1.model_dump(mode="json")) + "\n")
        protocol = Protocol()

        result = parse_requested_defects(jsonl_file, {"BUG-1"}, "proj", protocol)

        assert len(result) == 1
        assert protocol.generalWarnings is not None
        assert len(protocol.generalWarnings) == 1

    def test_handles_unreadable_file(self, tmp_path: Path):
        protocol = Protocol()

        result = parse_requested_defects(tmp_path / "nope.jsonl", {"BUG-1"}, "proj", protocol)

        assert result == []
        assert protocol.generalErrors is not None
        assert len(protocol.generalErrors) == 1

    def test_protocol_success_for_each_found(self, tmp_path: Path):
        d1 = _make_defect("BUG-1")
        d2 = _make_defect("BUG-2")
        jsonl_file = tmp_path / "bugs.jsonl"
        _write_jsonl(jsonl_file, [d1, d2])
        protocol = Protocol()

        parse_requested_defects(jsonl_file, {"BUG-1", "BUG-2"}, "proj", protocol)

        assert protocol.successes is not None
        assert "BUG-1" in protocol.successes
        assert "BUG-2" in protocol.successes
        assert protocol.successes["BUG-1"][0].code == ProtocolCode.IMPORT_SUCCESS

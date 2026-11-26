from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar
from unittest.mock import MagicMock, patch

import openpyxl
import pandas as pd
import pytest

from testbench_defect_service.clients.excel.config import (
    ExcelDefectClientConfig,
    UserDefiendAttributes,
)
from testbench_defect_service.clients.excel.file_utils import (
    _cell_value,
    delete_defect_row,
    map_boolean_values,
    read_data_frame_from_file_path,
    write_defect_row,
)
from testbench_defect_service.clients.excel.utils import is_blank_row
from testbench_defect_service.models.defects import Protocol, SyncContext, ValueType

_MODULE = "testbench_defect_service.clients.excel.file_utils"


@pytest.fixture
def config() -> ExcelDefectClientConfig:
    return ExcelDefectClientConfig(
        system_name="Excel",
        excel_file_path=Path(),
        file_type=".xlsx",
        simple_date_format="yyyy-MM-dd",
        defects_data_header_line=1,
        defects_data_starting_line=2,
        separator=",",
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
        control_fields=[],
    )


@pytest.fixture
def sync_context() -> SyncContext:
    return SyncContext()


@pytest.fixture
def df() -> pd.DataFrame:
    return pd.DataFrame({"id": ["D-1"], "title": ["Bug"]})


@pytest.fixture
def header() -> dict[int, str]:
    return {1: "Defect ID", 2: "Title"}


def _save_workbook(path: Path, rows: list[list[object]], sheet_name: str = "Sheet1") -> None:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    worksheet.title = sheet_name
    for row in rows:
        worksheet.append(row)
    workbook.save(path)


def _sheet(path: Path, sheet_name: str = "Sheet1"):
    return openpyxl.load_workbook(path)[sheet_name]


@pytest.mark.unit
class TestWriteDefectRowToExcel:
    """A write touches the row it is about and leaves every other cell as it was."""

    def test_update_writes_only_the_addressed_row(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        defect_path = tmp_path / "defects.xlsx"
        stamp = datetime(2024, 1, 2, 3, 4, 5)  # noqa: DTZ001 - Excel cells are naive
        _save_workbook(
            defect_path,
            [["id", "title", "notes"], ["D-1", "Bug", 7], ["D-2", "Other", stamp]],
        )

        write_defect_row(sync_context, defect_path, config, 0, {"title": "Changed"})

        sheet = _sheet(defect_path)
        assert [cell.value for cell in sheet[2]] == ["D-1", "Changed", 7]
        # The untouched row keeps its cell types - a date stays a date, not text.
        assert [cell.value for cell in sheet[3]] == ["D-2", "Other", stamp]

    def test_position_past_the_last_row_appends_a_defect(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        defect_path = tmp_path / "defects.xlsx"
        _save_workbook(defect_path, [["id", "title"], ["D-1", "Bug"], ["D-2", "Other"]])

        write_defect_row(sync_context, defect_path, config, 2, {"id": "D-3", "title": "New"})

        sheet = _sheet(defect_path)
        assert sheet.max_row == 4
        assert [cell.value for cell in sheet[2]] == ["D-1", "Bug"]
        assert [cell.value for cell in sheet[4]] == ["D-3", "New"]

    def test_existing_header_is_kept_and_a_missing_one_is_filled(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        defect_path = tmp_path / "defects.xlsx"
        _save_workbook(defect_path, [["Defect ID"], ["D-1"]])

        write_defect_row(sync_context, defect_path, config, 0, {"title": "Bug"})

        sheet = _sheet(defect_path)
        assert sheet["A1"].value == "Defect ID"
        assert sheet["B1"].value == "title"
        assert sheet["B2"].value == "Bug"

    def test_last_edited_becomes_a_date_cell_in_local_time(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        defect_path = tmp_path / "defects.xlsx"
        _save_workbook(defect_path, [["id", "title", "edited"], ["D-1", "Bug", None]])
        dated_config = config.model_copy(
            update={"lastedit_column_no": 3, "simple_date_format": "dd.MM.yyyy"}
        )
        edited = datetime(2026, 11, 26, 14, 30, 5, tzinfo=timezone.utc)

        write_defect_row(sync_context, defect_path, dated_config, 0, {"lastEdited": edited})

        cell = _sheet(defect_path)["C2"]
        # A real date with its time of day, shown in the configured format.
        assert cell.value == edited.astimezone().replace(tzinfo=None)
        assert cell.number_format == "dd.mm.yyyy"

    def test_empty_value_clears_the_cell(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        defect_path = tmp_path / "defects.xlsx"
        _save_workbook(defect_path, [["id", "title"], ["D-1", "Bug"]])

        write_defect_row(sync_context, defect_path, config, 0, {"title": ""})

        assert _sheet(defect_path)["B2"].value is None

    def test_xls_target_raises_and_leaves_the_file_untouched(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        defect_path = tmp_path / "existing.xls"
        original_bytes = b"\xd0\xcf\x11\xe0legacy-xls-content"
        defect_path.write_bytes(original_bytes)

        with pytest.raises(ValueError, match=r"\.xls"):
            write_defect_row(sync_context, defect_path, config, 0, {"title": "Bug"})
        with pytest.raises(ValueError, match=r"\.xls"):
            delete_defect_row(defect_path, config, 0)

        assert defect_path.read_bytes() == original_bytes

    @pytest.mark.parametrize("column_positions", [None, {}])
    def test_no_column_mapping_returns_without_touching_the_file(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
        column_positions: dict | None,
    ):
        defect_path = tmp_path / "defects.xlsx"
        _save_workbook(defect_path, [["id", "title"], ["D-1", "Bug"]])
        original_bytes = defect_path.read_bytes()

        with patch(f"{_MODULE}.get_column_mapping_for_config", return_value=column_positions):
            write_defect_row(sync_context, defect_path, config, 0, {"title": "Changed"})

        assert defect_path.read_bytes() == original_bytes

    def test_no_staging_file_is_left_behind(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        defect_path = tmp_path / "defects.xlsx"
        _save_workbook(defect_path, [["id", "title"], ["D-1", "Bug"]])

        write_defect_row(sync_context, defect_path, config, 0, {"title": "Changed"})

        assert [entry.name for entry in tmp_path.iterdir()] == ["defects.xlsx"]

    def test_failed_replace_keeps_the_file_and_removes_the_staging_file(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        """What happens while the file is open in Excel: the write is refused as a whole."""
        defect_path = tmp_path / "defects.xlsx"
        _save_workbook(defect_path, [["id", "title"], ["D-1", "Bug"]])
        original_bytes = defect_path.read_bytes()

        with (
            patch(f"{_MODULE}.Path.replace", side_effect=PermissionError(13, "denied")),
            pytest.raises(PermissionError),
        ):
            write_defect_row(sync_context, defect_path, config, 0, {"title": "Changed"})

        assert defect_path.read_bytes() == original_bytes
        assert [entry.name for entry in tmp_path.iterdir()] == ["defects.xlsx"]

    def test_delete_removes_the_whole_row_including_unmapped_columns(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
    ):
        defect_path = tmp_path / "defects.xlsx"
        _save_workbook(
            defect_path,
            [
                ["id", "title", "notes"],
                ["D-1", "Bug", "n1"],
                ["D-2", "Other", "n2"],
                ["D-3", "Third", "n3"],
            ],
        )

        delete_defect_row(defect_path, config, 1)

        sheet = _sheet(defect_path)
        assert sheet.max_row == 3
        assert [cell.value for cell in sheet[2]] == ["D-1", "Bug", "n1"]
        # The note moves up with its defect instead of staying behind for the next one.
        assert [cell.value for cell in sheet[3]] == ["D-3", "Third", "n3"]

    def test_row_position_counts_blank_rows_like_the_reader_does(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        """The position handed to the writer comes from the frame the reader built, so the
        two have to agree on where a row is - also past an empty row in the middle."""
        defect_path = tmp_path / "defects.xlsx"
        _save_workbook(
            defect_path,
            [["id", "title"], ["D-1", "Bug"], [None, None], ["D-2", "Other"]],
        )

        df = read_data_frame_from_file_path(defect_path, config, sync_context, Protocol())
        position = df["id"].tolist().index("D-2")
        write_defect_row(sync_context, defect_path, config, position, {"title": "Changed"})

        sheet = _sheet(defect_path)
        assert sheet["A4"].value == "D-2"
        assert sheet["B4"].value == "Changed"
        assert sheet["B2"].value == "Bug"


@pytest.mark.unit
class TestReadDataFrameFromFilePath:
    @pytest.fixture
    def file_path(self, tmp_path: Path) -> Path:
        path = tmp_path / "data.xlsx"
        path.touch()
        return path

    def test_returns_empty_dataframe_when_column_mapping_is_none(
        self,
        file_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        loaded_df = pd.DataFrame({"col_a": ["x", "y"], "col_b": ["1", "2"]})

        with (
            patch(f"{_MODULE}._load_dataframe", return_value=loaded_df),
            patch(f"{_MODULE}.get_column_mapping_for_config", return_value=None),
        ):
            result = read_data_frame_from_file_path(file_path, config, sync_context)

        assert result.empty
        assert list(result.columns) == list(loaded_df.columns)

    def test_returns_mapped_dataframe_on_happy_path(
        self,
        file_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        loaded_df = pd.DataFrame({"col_a": ["x"], "col_b": ["1"]})
        expected_df = pd.DataFrame({"id": ["x"], "title": ["1"]})
        valid_mapping = {0: ["id"], 1: ["title"]}

        with (
            patch(f"{_MODULE}._load_dataframe", return_value=loaded_df),
            patch(f"{_MODULE}.get_column_mapping_for_config", return_value=valid_mapping),
            patch(f"{_MODULE}._validate_column_mapping", return_value=valid_mapping),
            patch(f"{_MODULE}.map_boolean_values"),
            patch(f"{_MODULE}._apply_column_mapping", return_value=expected_df),
            patch(f"{_MODULE}._require_mapped_columns"),
        ):
            result = read_data_frame_from_file_path(file_path, config, sync_context)

        assert result is expected_df

    def test_map_boolean_values_is_called_with_mapped_df(
        self,
        file_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        loaded_df = pd.DataFrame({"Header text": ["x"]})
        mapped_df = pd.DataFrame({"id": ["x"]})
        valid_mapping = {0: ["id"]}

        with (
            patch(f"{_MODULE}._load_dataframe", return_value=loaded_df),
            patch(f"{_MODULE}.get_column_mapping_for_config", return_value=valid_mapping),
            patch(f"{_MODULE}._validate_column_mapping", return_value=valid_mapping),
            patch(f"{_MODULE}.map_boolean_values") as mock_map_bool,
            patch(f"{_MODULE}._apply_column_mapping", return_value=mapped_df),
            patch(f"{_MODULE}._require_mapped_columns"),
        ):
            read_data_frame_from_file_path(file_path, config, sync_context)

        mock_map_bool.assert_called_once_with(config, mapped_df)

    def test_required_columns_are_checked_against_the_mapped_frame(
        self,
        file_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        loaded_df = pd.DataFrame({"id": ["x"]})
        mapped_df = pd.DataFrame({"id": ["x"]})
        valid_mapping = {0: ["id"]}

        with (
            patch(f"{_MODULE}._load_dataframe", return_value=loaded_df),
            patch(f"{_MODULE}.get_column_mapping_for_config", return_value=valid_mapping),
            patch(f"{_MODULE}._validate_column_mapping", return_value=valid_mapping),
            patch(f"{_MODULE}.map_boolean_values"),
            patch(f"{_MODULE}._apply_column_mapping", return_value=mapped_df),
            patch(f"{_MODULE}._require_mapped_columns") as mock_require_columns,
        ):
            read_data_frame_from_file_path(file_path, config, sync_context)

        mock_require_columns.assert_called_once_with(mapped_df, file_path)

    def test_propagates_missing_required_column_error(
        self,
        file_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        loaded_df = pd.DataFrame({"id": [""]})
        mapped_df = pd.DataFrame({"id": [""]})
        valid_mapping = {0: ["id"]}

        with (
            patch(f"{_MODULE}._load_dataframe", return_value=loaded_df),
            patch(f"{_MODULE}.get_column_mapping_for_config", return_value=valid_mapping),
            patch(f"{_MODULE}._validate_column_mapping", return_value=valid_mapping),
            patch(f"{_MODULE}.map_boolean_values"),
            patch(f"{_MODULE}._apply_column_mapping", return_value=mapped_df),
            patch(
                f"{_MODULE}._require_mapped_columns",
                side_effect=ValueError("column not found"),
            ),
            pytest.raises(ValueError, match="column not found"),
        ):
            read_data_frame_from_file_path(file_path, config, sync_context)

    def test_protocol_is_passed_to_get_column_mapping(
        self,
        file_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        protocol = MagicMock(spec=Protocol)
        loaded_df = pd.DataFrame({"id": ["x"]})
        valid_mapping = {0: ["id"]}
        mapped_df = pd.DataFrame({"id": ["x"]})

        with (
            patch(f"{_MODULE}._load_dataframe", return_value=loaded_df),
            patch(
                f"{_MODULE}.get_column_mapping_for_config", return_value=valid_mapping
            ) as mock_get_mapping,
            patch(f"{_MODULE}._validate_column_mapping", return_value=valid_mapping),
            patch(f"{_MODULE}.map_boolean_values"),
            patch(f"{_MODULE}._apply_column_mapping", return_value=mapped_df),
            patch(f"{_MODULE}._require_mapped_columns"),
        ):
            read_data_frame_from_file_path(file_path, config, sync_context, protocol=protocol)

        mock_get_mapping.assert_called_once_with(config, sync_context, protocol)


# ---------------------------------------------------------------------------
# Format-specific behavior of the delimited writer
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWriteDefectRowToDelimited:
    NEW_DEFECT: ClassVar[dict[str, str]] = {"id": "D-2", "title": "New"}

    def test_semicolon_separator_preserves_file_structure(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        defect_path = tmp_path / "defects.csv"
        defect_path.write_text("id;title\nD-1;Bug\n", encoding="utf-8")
        semicolon_config = config.model_copy(update={"separator": ";"})

        write_defect_row(sync_context, defect_path, semicolon_config, 1, self.NEW_DEFECT)

        lines = defect_path.read_text(encoding="utf-8").splitlines()
        assert lines == ["id;title", "D-1;Bug", "D-2;New"]

    def test_update_changes_only_the_addressed_row(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        defect_path = tmp_path / "defects.csv"
        defect_path.write_text("id,title,notes\nD-1,Bug,007\nD-2,Other,N/A\n", encoding="utf-8")

        write_defect_row(sync_context, defect_path, config, 0, {"title": "Changed"})

        lines = defect_path.read_text(encoding="utf-8").splitlines()
        # Unmapped cells survive byte for byte: no "007" -> 7, no "N/A" -> empty.
        assert lines == ["id,title,notes", "D-1,Changed,007", "D-2,Other,N/A"]

    def test_windows_1252_file_is_written_back_in_same_encoding(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        defect_path = tmp_path / "defects.csv"
        defect_path.write_bytes("id,title\nD-1,Käfer\n".encode("windows-1252"))

        write_defect_row(sync_context, defect_path, config, 1, self.NEW_DEFECT)

        content = defect_path.read_bytes().decode("windows-1252")
        assert "Käfer" in content
        assert "D-2" in content

    def test_missing_separator_defaults_to_comma(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        defect_path = tmp_path / "defects.csv"
        defect_path.write_text("id,title\nD-1,Bug\n", encoding="utf-8")
        no_separator_config = config.model_copy(update={"separator": None})

        write_defect_row(sync_context, defect_path, no_separator_config, 1, self.NEW_DEFECT)

        lines = defect_path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "id,title"
        assert lines[2] == "D-2,New"

    def test_txt_file_keeps_unmapped_columns(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        defect_path = tmp_path / "defects.txt"
        defect_path.write_text("id,title,notes\nD-1,Bug,keep-me\n", encoding="utf-8")

        write_defect_row(sync_context, defect_path, config, 1, self.NEW_DEFECT)

        content = defect_path.read_text(encoding="utf-8")
        assert "keep-me" in content
        assert "D-2" in content

    def test_tsv_is_written_tab_separated(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        defect_path = tmp_path / "defects.tsv"
        defect_path.write_text("id\ttitle\nD-1\tBug\n", encoding="utf-8")

        write_defect_row(sync_context, defect_path, config, 1, self.NEW_DEFECT)

        lines = defect_path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "id\ttitle"
        assert lines[2] == "D-2\tNew"

    def test_last_edited_is_written_as_text_in_local_time(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        defect_path = tmp_path / "defects.csv"
        defect_path.write_text("id,title,edited\nD-1,Bug,\n", encoding="utf-8")
        dated_config = config.model_copy(
            update={"lastedit_column_no": 3, "simple_date_format": "dd.MM.yyyy HH:mm:ss"}
        )
        edited = datetime(2026, 11, 26, 14, 30, 5, tzinfo=timezone.utc)

        write_defect_row(sync_context, defect_path, dated_config, 0, {"lastEdited": edited})

        expected = edited.astimezone().strftime("%d.%m.%Y %H:%M:%S")
        assert defect_path.read_text(encoding="utf-8").splitlines()[1] == f"D-1,Bug,{expected}"

    def test_delete_removes_the_row_with_its_unmapped_columns(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
    ):
        defect_path = tmp_path / "defects.csv"
        defect_path.write_text(
            "id,title,notes\nD-1,Bug,n1\nD-2,Deleted,n2\nD-3,Third,n3\n",
            encoding="utf-8",
        )

        delete_defect_row(defect_path, config, 1)

        lines = defect_path.read_text(encoding="utf-8").splitlines()
        assert lines == ["id,title,notes", "D-1,Bug,n1", "D-3,Third,n3"]

    def test_no_staging_file_is_left_behind(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        defect_path = tmp_path / "defects.csv"
        defect_path.write_text("id,title\nD-1,Bug\n", encoding="utf-8")

        write_defect_row(sync_context, defect_path, config, 1, self.NEW_DEFECT)

        assert [entry.name for entry in tmp_path.iterdir()] == ["defects.csv"]

    def test_unsupported_suffix_raises_value_error(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        defect_path = tmp_path / "defects.ods"
        defect_path.write_text("irrelevant", encoding="utf-8")

        with pytest.raises(ValueError, match="Unsupported file format"):
            write_defect_row(sync_context, defect_path, config, 0, self.NEW_DEFECT)
        with pytest.raises(ValueError, match="Unsupported file format"):
            delete_defect_row(defect_path, config, 0)


# ---------------------------------------------------------------------------
# Format-specific behavior of the readers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoadDataFrameFormats:
    def test_last_edited_date_cell_keeps_its_time_of_day(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        """`simple_date_format` is how the column is displayed; the cell knows the time too.
        Cutting it off made a change later on the day of the last sync look older than it."""
        defect_path = tmp_path / "defects.xlsx"
        _save_workbook(
            defect_path,
            [
                ["id", "title", "edited", "due"],
                ["D-1", "Bug", datetime(2024, 1, 5, 13, 45, 10), datetime(2024, 2, 1, 8, 0)],  # noqa: DTZ001 - Excel cells are naive
            ],
        )
        date_config = config.model_copy(
            update={
                "lastedit_column_no": 3,
                "udfs": [UserDefiendAttributes(name="due", column=4, type=ValueType.STRING)],
            }
        )

        df = read_data_frame_from_file_path(defect_path, date_config, sync_context)

        assert df["lastEdited"].iloc[0] == "2024-01-05 13:45:10"
        # Any other date column is still rendered the way the file shows it.
        assert df["due"].iloc[0] == "2024-02-01"

    def test_boolean_udf_maps_when_header_differs_from_udf_name(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        defect_path = tmp_path / "defects.csv"
        defect_path.write_text("id,title,Fixed?\nD-1,Bug,yes\n", encoding="utf-8")
        udf_config = config.model_copy(
            update={
                "udfs": [
                    UserDefiendAttributes(
                        name="isFixed",
                        column=3,
                        type=ValueType.BOOLEAN,
                        trueValue="yes",
                        falseValue="no",
                    )
                ]
            }
        )

        df = read_data_frame_from_file_path(defect_path, udf_config, sync_context)

        assert df["isFixed"].iloc[0] == "true"


@pytest.mark.unit
class TestEmptyRowTolerance:
    """A separator-only row is layout, not data. It must not fail the whole file.

    Truly blank lines are already dropped by pandas (`skip_blank_lines=True`);
    the breaking case is `,,` which Excel, LibreOffice and this project's own
    CSV writer all emit.
    """

    def _write(self, tmp_path: Path, body: str) -> Path:
        file_path = tmp_path / "defects.csv"
        file_path.write_text(f"id,title\n{body}", encoding="utf-8")
        return file_path

    def test_empty_row_is_kept_in_the_frame_and_does_not_raise(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        file_path = self._write(tmp_path, "D-1,First\n,\nD-2,Second\n")

        df = read_data_frame_from_file_path(file_path, config, sync_context, Protocol())

        # The row is preserved: the frame stays positionally aligned with the file.
        assert df["id"].tolist() == ["D-1", "", "D-2"]

    def test_several_empty_rows_do_not_trip_the_uniqueness_check(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        file_path = self._write(tmp_path, "D-1,First\n,\n,\nD-2,Second\n")

        df = read_data_frame_from_file_path(file_path, config, sync_context, Protocol())

        assert df["id"].tolist() == ["D-1", "", "", "D-2"]


@pytest.mark.unit
class TestUnusableRowTolerance:
    """A row the service cannot identify is one bad row, not a bad file.

    Failing the read took the whole file down on every path, update and delete included, so
    the only way out was editing the file by hand. The rows stay in the frame: dropping them
    would shift every row below up on the next write and erase what the user has to repair.
    """

    def _write(self, tmp_path: Path, body: str) -> Path:
        file_path = tmp_path / "defects.csv"
        file_path.write_text(f"id,title\n{body}", encoding="utf-8")
        return file_path

    def test_row_with_blank_id_but_other_content_does_not_fail_the_file(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        file_path = self._write(tmp_path, "D-1,First\n,Only a title\nD-2,Second\n")

        df = read_data_frame_from_file_path(file_path, config, sync_context, Protocol())

        assert df["id"].tolist() == ["D-1", "", "D-2"]

    def test_duplicate_ids_do_not_fail_the_file(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        """The rows stay positionally aligned with the file, which is what keeps the next write
        from shifting the rows below them up and erasing what the user has to repair."""
        file_path = self._write(tmp_path, "D-1,First\n,\nD-1,Duplicate\n")

        df = read_data_frame_from_file_path(file_path, config, sync_context, Protocol())

        assert df["id"].tolist() == ["D-1", "", "D-1"]

    def test_missing_id_column_still_fails_the_file(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        """An unmapped id column is a configuration fault, not a row fault - nothing in the
        file can be identified, so there is no partial result worth returning."""
        file_path = self._write(tmp_path, "D-1,First\n")
        unmapped = config.model_copy(update={"id_column_no": 0})

        with pytest.raises(ValueError, match=r"'id'"):
            read_data_frame_from_file_path(file_path, unmapped, sync_context, Protocol())


@pytest.mark.unit
class TestBooleanUdfBlankPreservation:
    """An empty boolean cell is unset, not false.

    Coercing it to `falseValue` also re-fills an otherwise-empty row on the next
    write, which brings back the whole-file abort this feature removes.
    """

    @pytest.fixture
    def boolean_config(self, config: ExcelDefectClientConfig) -> ExcelDefectClientConfig:
        config.udfs = [
            UserDefiendAttributes(
                name="isOpen",
                column=3,
                type=ValueType.BOOLEAN,
                trueValue="1-yes",
                falseValue="2-no",
            )
        ]
        return config

    def test_read_mapping_keeps_blank_cells_blank(self, boolean_config: ExcelDefectClientConfig):
        df = pd.DataFrame({"isOpen": ["1-yes", "2-no", "", "   "]})

        map_boolean_values(boolean_config, df)

        assert df["isOpen"].tolist() == ["true", "false", "", ""]

    def test_write_mapping_keeps_blank_cells_blank(self, boolean_config: ExcelDefectClientConfig):
        written = [
            _cell_value(boolean_config, "isOpen", value, as_text=True)
            for value in ["true", "false", ""]
        ]

        assert written == ["1-yes", "2-no", ""]

    def test_blank_boolean_cell_round_trips_as_blank(self, boolean_config: ExcelDefectClientConfig):
        df = pd.DataFrame({"isOpen": ["1-yes", ""]})

        map_boolean_values(boolean_config, df)
        written = [
            _cell_value(boolean_config, "isOpen", value, as_text=True)
            for value in df["isOpen"].tolist()
        ]

        assert written == ["1-yes", ""]

    def test_cell_with_neither_label_is_not_turned_into_false(
        self, boolean_config: ExcelDefectClientConfig
    ):
        """'maybe' is not 'no'. Reporting it as false would hand TestBench a value nobody
        entered; the cell is passed on as it is and the defect builder reports it."""
        df = pd.DataFrame({"isOpen": ["1-yes", "maybe"]})

        map_boolean_values(boolean_config, df)

        assert df["isOpen"].tolist() == ["true", "maybe"]

    def test_labels_default_to_true_and_false(self, config: ExcelDefectClientConfig):
        """Without configured labels the cells hold 'true' and 'false', as in the legacy
        connector - not a blank for true and 'false' for everything read."""
        config.udfs = [UserDefiendAttributes(name="isOpen", column=3, type=ValueType.BOOLEAN)]
        df = pd.DataFrame({"isOpen": ["true", "false", ""]})

        map_boolean_values(config, df)

        assert df["isOpen"].tolist() == ["true", "false", ""]
        assert _cell_value(config, "isOpen", "true", as_text=True) == "true"
        assert _cell_value(config, "isOpen", "false", as_text=True) == "false"

    def test_empty_row_stays_blank_through_a_read_with_a_boolean_udf(
        self,
        tmp_path: Path,
        boolean_config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        file_path = tmp_path / "defects.csv"
        file_path.write_text(
            "id,title,isOpen\nD-1,First,1-yes\n,,\nD-2,Second,2-no\n", encoding="utf-8"
        )

        df = read_data_frame_from_file_path(file_path, boolean_config, sync_context, Protocol())

        assert df["isOpen"].tolist() == ["true", "", "false"]
        assert is_blank_row(df.iloc[1]) is True

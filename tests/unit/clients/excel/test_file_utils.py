from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from testbench_defect_service.clients.excel.config import ExcelDefectClientConfig
from testbench_defect_service.clients.excel.file_utils import (
    read_data_frame_from_file_path,
    write_defect_data_to_excel,
)
from testbench_defect_service.models.defects import Protocol, SyncContext

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
        seperator=",",
        id_column_no=1,
        title_column_no=2,
        references_column_no=0,
        discoverer_column_no=0,
        lastedit_column_no=0,
        description_column_no=0,
        references_seperator=";",
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


@pytest.mark.unit
class TestWriteDefectDataToExcel:
    def test_new_file_uses_write_mode(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
        df: pd.DataFrame,
        header: dict[int, str],
    ):
        defect_path = tmp_path / "output.xlsx"
        assert not defect_path.exists()

        with (
            patch(f"{_MODULE}.pd.ExcelWriter") as mock_excel_writer,
            patch(f"{_MODULE}.resolve_visible_sheet_name", return_value="Sheet1"),
            patch.object(pd.DataFrame, "to_excel"),
        ):
            write_defect_data_to_excel(sync_context, defect_path, config, header, df)

        mock_excel_writer.assert_called_once()
        call_kwargs = mock_excel_writer.call_args.kwargs
        assert call_kwargs["engine"] == "openpyxl"
        assert "mode" not in call_kwargs
        assert "if_sheet_exists" not in call_kwargs

    def test_existing_xlsx_uses_append_mode_with_overlay(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
        df: pd.DataFrame,
        header: dict[int, str],
    ):
        defect_path = tmp_path / "existing.xlsx"
        defect_path.write_bytes(b"")

        with (
            patch(f"{_MODULE}.pd.ExcelWriter") as mock_excel_writer,
            patch(f"{_MODULE}.resolve_visible_sheet_name", return_value="Sheet1"),
            patch.object(pd.DataFrame, "to_excel"),
        ):
            write_defect_data_to_excel(sync_context, defect_path, config, header, df)

        mock_excel_writer.assert_called_once()
        call_kwargs = mock_excel_writer.call_args.kwargs
        assert call_kwargs["engine"] == "openpyxl"
        assert call_kwargs["mode"] == "a"
        assert call_kwargs["if_sheet_exists"] == "overlay"

    def test_existing_xls_uses_write_mode(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
        df: pd.DataFrame,
        header: dict[int, str],
    ):
        defect_path = tmp_path / "existing.xls"
        defect_path.write_bytes(b"")

        with (
            patch(f"{_MODULE}.pd.ExcelWriter") as mock_excel_writer,
            patch(f"{_MODULE}.resolve_visible_sheet_name", return_value="Sheet1"),
            patch.object(pd.DataFrame, "to_excel"),
        ):
            write_defect_data_to_excel(sync_context, defect_path, config, header, df)

        mock_excel_writer.assert_called_once()
        call_kwargs = mock_excel_writer.call_args.kwargs
        assert call_kwargs["engine"] == "openpyxl"
        assert "mode" not in call_kwargs
        assert "if_sheet_exists" not in call_kwargs

    def test_none_column_positions_returns_early_without_writing(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
        df: pd.DataFrame,
        header: dict[int, str],
    ):
        defect_path = tmp_path / "output.xlsx"

        with (
            patch(f"{_MODULE}.get_column_mapping_for_config", return_value=None),
            patch(f"{_MODULE}.pd.ExcelWriter") as mock_excel_writer,
        ):
            write_defect_data_to_excel(sync_context, defect_path, config, header, df)

        mock_excel_writer.assert_not_called()

    def test_empty_column_positions_returns_early_without_writing(
        self,
        tmp_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
        df: pd.DataFrame,
        header: dict[int, str],
    ):
        defect_path = tmp_path / "output.xlsx"

        with (
            patch(f"{_MODULE}.get_column_mapping_for_config", return_value={}),
            patch(f"{_MODULE}.pd.ExcelWriter") as mock_excel_writer,
        ):
            write_defect_data_to_excel(sync_context, defect_path, config, header, df)

        mock_excel_writer.assert_not_called()


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
            patch(f"{_MODULE}._validate_required_column_values"),
            patch(f"{_MODULE}._validate_unique_constraints"),
        ):
            result = read_data_frame_from_file_path(file_path, config, sync_context)

        assert result is expected_df

    def test_map_boolean_values_is_called_with_loaded_df(
        self,
        file_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        loaded_df = pd.DataFrame({"id": ["x"]})
        valid_mapping = {0: ["id"]}

        with (
            patch(f"{_MODULE}._load_dataframe", return_value=loaded_df),
            patch(f"{_MODULE}.get_column_mapping_for_config", return_value=valid_mapping),
            patch(f"{_MODULE}._validate_column_mapping", return_value=valid_mapping),
            patch(f"{_MODULE}.map_boolean_values") as mock_map_bool,
            patch(f"{_MODULE}._apply_column_mapping", return_value=loaded_df),
            patch(f"{_MODULE}._validate_required_column_values"),
            patch(f"{_MODULE}._validate_unique_constraints"),
        ):
            read_data_frame_from_file_path(file_path, config, sync_context)

        mock_map_bool.assert_called_once_with(config, loaded_df)

    def test_validate_required_column_values_is_called(
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
            patch(f"{_MODULE}._validate_required_column_values") as mock_validate_required,
            patch(f"{_MODULE}._validate_unique_constraints"),
        ):
            read_data_frame_from_file_path(file_path, config, sync_context)

        mock_validate_required.assert_called_once_with(mapped_df, file_path, config)

    def test_validate_unique_constraints_is_called(
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
            patch(f"{_MODULE}._validate_required_column_values"),
            patch(f"{_MODULE}._validate_unique_constraints") as mock_validate_unique,
        ):
            read_data_frame_from_file_path(file_path, config, sync_context)

        mock_validate_unique.assert_called_once_with(mapped_df, file_path, config)

    def test_propagates_required_column_validation_error(
        self,
        file_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        loaded_df = pd.DataFrame({"id": [""]})
        mapped_df = pd.DataFrame({"id": [""]})
        valid_mapping = {0: ["id"]}

        with (  # noqa: SIM117
            patch(f"{_MODULE}._load_dataframe", return_value=loaded_df),
            patch(f"{_MODULE}.get_column_mapping_for_config", return_value=valid_mapping),
            patch(f"{_MODULE}._validate_column_mapping", return_value=valid_mapping),
            patch(f"{_MODULE}.map_boolean_values"),
            patch(f"{_MODULE}._apply_column_mapping", return_value=mapped_df),
            patch(
                f"{_MODULE}._validate_required_column_values",
                side_effect=ValueError("empty value"),
            ),
            patch(f"{_MODULE}._validate_unique_constraints"),
        ):
            with pytest.raises(ValueError, match="empty value"):
                read_data_frame_from_file_path(file_path, config, sync_context)

    def test_propagates_unique_constraint_error(
        self,
        file_path: Path,
        config: ExcelDefectClientConfig,
        sync_context: SyncContext,
    ):
        loaded_df = pd.DataFrame({"id": ["D-1", "D-1"]})
        mapped_df = pd.DataFrame({"id": ["D-1", "D-1"]})
        valid_mapping = {0: ["id"]}

        with (
            patch(f"{_MODULE}._load_dataframe", return_value=loaded_df),
            patch(f"{_MODULE}.get_column_mapping_for_config", return_value=valid_mapping),
            patch(f"{_MODULE}._validate_column_mapping", return_value=valid_mapping),
            patch(f"{_MODULE}.map_boolean_values"),
            patch(f"{_MODULE}._apply_column_mapping", return_value=mapped_df),
            patch(f"{_MODULE}._validate_required_column_values"),
            patch(
                f"{_MODULE}._validate_unique_constraints",
                side_effect=ValueError("duplicate id"),
            ),
            pytest.raises(ValueError, match="duplicate id"),
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
            patch(f"{_MODULE}._validate_required_column_values"),
            patch(f"{_MODULE}._validate_unique_constraints"),
        ):
            read_data_frame_from_file_path(file_path, config, sync_context, protocol=protocol)

        mock_get_mapping.assert_called_once_with(config, sync_context, protocol)

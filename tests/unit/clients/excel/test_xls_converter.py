"""Tests for the legacy ``.xls`` to ``.xlsx`` conversion behind ``migrate workbook``."""

from pathlib import Path

import pytest

from testbench_defect_service.clients.excel.xls_converter import (
    XLSX_FILE_FORMAT,
    ConversionStatus,
    convert_workbooks,
    find_xls_files,
)


class FakeWorkbook:
    """The handful of COM members the converter touches on an opened workbook."""

    def __init__(self, source: str, journal: list, fail_on_save: bool):
        self.source = source
        self.journal = journal
        self.fail_on_save = fail_on_save
        self.closed = False

    def SaveAs(self, path, FileFormat):  # noqa: N802, N803 - COM naming
        if self.fail_on_save:
            raise RuntimeError("Excel refused to save")
        self.journal.append(("saved", self.source, path, FileFormat))

    def Close(self, SaveChanges):  # noqa: N802, N803 - COM naming
        self.closed = True
        self.journal.append(("closed", self.source, SaveChanges))


class FakeWorkbooks:
    def __init__(self, excel):
        self._excel = excel

    def Open(self, path):  # noqa: N802 - COM naming
        self._excel.journal.append(("opened", path))
        if Path(path).name in self._excel.unopenable:
            raise RuntimeError("Excel could not open the file")
        workbook = FakeWorkbook(path, self._excel.journal, Path(path).name in self._excel.unsavable)
        self._excel.opened.append(workbook)
        return workbook


class FakeExcel:
    """Stands in for the ``Excel.Application`` COM object."""

    def __init__(self, unopenable=(), unsavable=()):
        self.journal: list = []
        self.opened: list[FakeWorkbook] = []
        self.unopenable = set(unopenable)
        self.unsavable = set(unsavable)
        self.Workbooks = FakeWorkbooks(self)


def make_xls(directory: Path, name: str) -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"legacy workbook")
    return path


@pytest.mark.unit
def test_converts_a_single_xls_file_to_a_sibling_xlsx(tmp_path):
    source = make_xls(tmp_path, "baseline.xls")
    excel = FakeExcel()

    results = convert_workbooks(source, excel)

    assert [r.status for r in results] == [ConversionStatus.CONVERTED]
    assert results[0].target == tmp_path / "baseline.xlsx"
    saved = ("saved", str(source), str(tmp_path / "baseline.xlsx"), XLSX_FILE_FORMAT)
    assert saved in excel.journal


@pytest.mark.unit
def test_converts_every_xls_below_a_folder_recursively(tmp_path):
    make_xls(tmp_path, "top.xls")
    make_xls(tmp_path / "nested", "inner.xls")
    make_xls(tmp_path / "nested" / "deeper", "deepest.xls")
    excel = FakeExcel()

    results = convert_workbooks(tmp_path, excel)

    assert {r.source.name for r in results} == {"top.xls", "inner.xls", "deepest.xls"}
    assert all(r.status is ConversionStatus.CONVERTED for r in results)


@pytest.mark.unit
def test_skips_a_workbook_whose_xlsx_already_exists(tmp_path):
    """The example folders already hold an .xlsx beside every .xls; never clobber one."""
    source = make_xls(tmp_path, "baseline.xls")
    (tmp_path / "baseline.xlsx").write_bytes(b"converted earlier")
    excel = FakeExcel()

    results = convert_workbooks(source, excel)

    assert [r.status for r in results] == [ConversionStatus.SKIPPED]
    assert excel.journal == []
    assert (tmp_path / "baseline.xlsx").read_bytes() == b"converted earlier"


@pytest.mark.unit
def test_ignores_files_that_are_not_legacy_workbooks(tmp_path):
    make_xls(tmp_path, "modern.xlsx")
    make_xls(tmp_path, "notes.txt")
    make_xls(tmp_path, "data.csv")

    assert find_xls_files(tmp_path) == []


@pytest.mark.unit
def test_ignores_the_lock_files_excel_leaves_beside_an_open_workbook(tmp_path):
    make_xls(tmp_path, "baseline.xls")
    make_xls(tmp_path, "~$baseline.xls")

    assert [p.name for p in find_xls_files(tmp_path)] == ["baseline.xls"]


@pytest.mark.unit
def test_finds_a_legacy_workbook_regardless_of_suffix_case(tmp_path):
    make_xls(tmp_path, "SHOUTING.XLS")

    assert [p.name for p in find_xls_files(tmp_path)] == ["SHOUTING.XLS"]


@pytest.mark.unit
def test_reports_a_failed_workbook_and_still_converts_the_rest(tmp_path):
    make_xls(tmp_path, "broken.xls")
    make_xls(tmp_path, "fine.xls")
    excel = FakeExcel(unopenable={"broken.xls"})

    results = convert_workbooks(tmp_path, excel)

    by_name = {r.source.name: r for r in results}
    assert by_name["broken.xls"].status is ConversionStatus.FAILED
    assert "Excel could not open the file" in by_name["broken.xls"].detail
    assert by_name["fine.xls"].status is ConversionStatus.CONVERTED


@pytest.mark.unit
def test_closes_the_workbook_even_when_saving_fails(tmp_path):
    """A workbook left open keeps a hidden Excel process alive after the batch."""
    make_xls(tmp_path, "unsavable.xls")
    excel = FakeExcel(unsavable={"unsavable.xls"})

    results = convert_workbooks(tmp_path, excel)

    assert results[0].status is ConversionStatus.FAILED
    assert all(workbook.closed for workbook in excel.opened)


@pytest.mark.unit
def test_never_saves_changes_back_into_the_legacy_file(tmp_path):
    make_xls(tmp_path, "baseline.xls")
    excel = FakeExcel()

    convert_workbooks(tmp_path, excel)

    closes = [entry for entry in excel.journal if entry[0] == "closed"]
    assert closes
    assert all(entry[2] is False for entry in closes)


@pytest.mark.unit
def test_a_folder_without_legacy_workbooks_converts_nothing(tmp_path):
    excel = FakeExcel()

    assert convert_workbooks(tmp_path, excel) == []
    assert excel.journal == []

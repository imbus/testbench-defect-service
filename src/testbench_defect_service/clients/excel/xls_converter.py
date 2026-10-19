"""Convert legacy ``.xls`` workbooks into ``.xlsx`` using Excel's own COM automation.

``pandas`` and ``openpyxl`` are already available and could read a legacy workbook, but a
round trip through a ``DataFrame`` keeps only the cell values: formatting, column widths
and formulas are all lost. Driving the installed Excel keeps the workbook intact, at the
cost of requiring Windows with Microsoft Excel -- which is why ``pywin32`` lives in the
optional ``convert`` extra and is imported lazily.

The conversion exists because :func:`..file_utils.write_defect_data_to_excel` refuses to
write to a legacy ``.xls`` file and tells the user to convert it first.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from testbench_defect_service.log import logger

# ``xlOpenXMLWorkbook`` -- the macro-free .xlsx format in Excel's XlFileFormat enumeration.
XLSX_FILE_FORMAT = 51

_LEGACY_SUFFIX = ".xls"
# Excel drops a "~$name.xls" owner file beside every workbook it has open.
_LOCK_FILE_PREFIX = "~$"

_MISSING_PYWIN32 = (
    "Converting .xls workbooks needs Excel automation, which is not installed.\n"
    "Install it with:  pip install testbench-defect-service[convert]"
)
_NO_EXCEL = (
    "Could not start Microsoft Excel ({error}).\n"
    "Converting .xls workbooks drives an installed Excel, so it only works on Windows "
    "with Microsoft Excel available."
)


class XlsConversionError(Exception):
    """Raised when the conversion cannot be started at all."""


class ConversionStatus(Enum):
    """What became of a single legacy workbook."""

    CONVERTED = "converted"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class ConversionResult:
    """The outcome for one ``.xls`` file."""

    source: Path
    target: Path
    status: ConversionStatus
    detail: str = ""


def find_xls_files(root: Path) -> list[Path]:
    """Return the legacy workbooks at *root*, which may be a single file or a folder.

    Folders are searched recursively. Excel's lock files are ignored -- they carry the
    ``.xls`` suffix but are not workbooks.
    """
    if root.is_file():
        return [root] if _is_legacy_workbook(root) else []
    return sorted(path for path in root.rglob("*") if path.is_file() and _is_legacy_workbook(path))


def _is_legacy_workbook(path: Path) -> bool:
    return path.suffix.lower() == _LEGACY_SUFFIX and not path.name.startswith(_LOCK_FILE_PREFIX)


def convert_workbooks(root: Path, excel: Any) -> list[ConversionResult]:
    """Convert every legacy workbook at *root* using the already-running *excel*.

    One failure does not abort the batch: a folder of workbooks should convert as far as
    it can and report the files it could not handle.
    """
    return [_convert_one(excel, source) for source in find_xls_files(root)]


def _convert_one(excel: Any, source: Path) -> ConversionResult:
    target = source.with_suffix(".xlsx")
    if target.exists():
        logger.debug("Skipping '%s': '%s' already exists", source, target.name)
        return ConversionResult(source, target, ConversionStatus.SKIPPED, "target already exists")

    workbook = None
    try:
        workbook = excel.Workbooks.Open(str(source.resolve()))
        workbook.SaveAs(str(target.resolve()), FileFormat=XLSX_FILE_FORMAT)
    except Exception as error:  # COM raises bare Exception subclasses
        logger.debug("Failed to convert '%s': %s", source, error)
        return ConversionResult(source, target, ConversionStatus.FAILED, str(error))
    finally:
        if workbook is not None:
            _close_quietly(workbook, source)

    return ConversionResult(source, target, ConversionStatus.CONVERTED)


def _close_quietly(workbook: Any, source: Path) -> None:
    """Close *workbook* discarding changes; a workbook left open keeps Excel alive."""
    try:
        workbook.Close(SaveChanges=False)
    except Exception as error:  # closing must never mask the real failure
        logger.debug("Could not close '%s' after conversion: %s", source, error)


@contextmanager
def excel_application() -> Iterator[Any]:
    """Start a hidden, dedicated Excel instance and quit it afterwards.

    ``DispatchEx`` asks for a separate process rather than attaching to an Excel the user
    already has open -- muting alerts on their session would be rude, and quitting it
    afterwards would close their workbooks.
    """
    try:
        import win32com.client  # noqa: PLC0415
    except ImportError as error:  # pragma: no cover - depends on the install
        raise XlsConversionError(_MISSING_PYWIN32) from error

    try:
        excel = win32com.client.DispatchEx("Excel.Application")
    except Exception as error:  # pywin32 raises com_error, not an OSError
        raise XlsConversionError(_NO_EXCEL.format(error=error)) from error

    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        yield excel
    finally:
        excel.Quit()

import contextlib

from testbench_defect_service.clients.abstract_client import AbstractDefectClient
from testbench_defect_service.clients.jsonl.client import JsonlDefectClient

try:  # noqa: SIM105
    from testbench_defect_service.clients.jira.client import JiraDefectClient
except ImportError:
    pass

with contextlib.suppress(ImportError):
    from testbench_defect_service.clients.excel.client import ExcelDefectClient

__all__ = [
    "AbstractDefectClient",
    "ExcelDefectClient",
    "JiraDefectClient",
    "JsonlDefectClient",
]

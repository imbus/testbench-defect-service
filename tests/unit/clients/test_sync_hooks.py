from pathlib import Path
from unittest.mock import patch

import pytest

from testbench_defect_service.clients.utils import execute_sync_hook, split_hook_command
from testbench_defect_service.models.config import PhaseCommands, SyncCommandConfig

_RUN = "testbench_defect_service.clients.utils.subprocess.run"


@pytest.mark.unit
class TestSplitHookCommand:
    def test_a_bare_script_path_may_contain_spaces(self) -> None:
        command = r"C:\Program Files\hooks\export.bat"

        assert split_hook_command(command) == [command]

    def test_a_quoted_command_line_is_split_and_unquoted(self) -> None:
        command = r'"C:\Program Files\hooks\export.bat" "%1" "a b" plain'

        assert split_hook_command(command) == [
            r"C:\Program Files\hooks\export.bat",
            "%1",
            "a b",
            "plain",
        ]

    def test_backslashes_of_a_windows_path_are_kept(self) -> None:
        assert split_hook_command(r"C:\hooks\export.bat %1") == [r"C:\hooks\export.bat", "%1"]

    def test_an_unclosed_quote_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="quotation"):
            split_hook_command('"C:\\hooks\\export.bat %1')


@pytest.mark.unit
class TestExecuteSyncHook:
    @staticmethod
    def _script(tmp_path: Path, name: str = "hook.bat") -> Path:
        script = tmp_path / name
        script.write_text("@echo off", encoding="utf-8")
        return script

    @staticmethod
    def _presync(command: str) -> PhaseCommands:
        return PhaseCommands(presync=SyncCommandConfig(manual=command))

    def test_a_bare_script_is_called_with_project_and_sync_type(self, tmp_path: Path) -> None:
        script = self._script(tmp_path)

        with patch(_RUN) as run:
            protocol = execute_sync_hook("demo", "manual", "presync", self._presync(str(script)))

        run.assert_called_once_with([str(script), "demo", "manual"], check=True)
        assert protocol.successes
        assert not protocol.generalErrors

    def test_configured_arguments_replace_the_default_ones(self, tmp_path: Path) -> None:
        """The legacy connectors ran exactly the command line that was configured."""
        script = self._script(tmp_path)
        defect_file = tmp_path / "demo" / "defects.xlsx"

        with patch(_RUN) as run:
            protocol = execute_sync_hook(
                "demo",
                "manual",
                "presync",
                self._presync(f'"{script}" "%1" "a b"'),
                defect_file=defect_file,
            )

        run.assert_called_once_with([str(script), str(defect_file), "a b"], check=True)
        assert protocol.successes

    def test_a_placeholder_without_a_defect_file_is_reported_and_nothing_runs(
        self, tmp_path: Path
    ) -> None:
        script = self._script(tmp_path)

        with patch(_RUN) as run:
            protocol = execute_sync_hook(
                "demo", "manual", "presync", self._presync(f'"{script}" "%1"')
            )

        run.assert_not_called()
        assert protocol.generalErrors
        assert "%1" in (protocol.generalErrors[0].message or "")

    def test_the_extension_of_the_script_is_checked_not_of_its_arguments(
        self, tmp_path: Path
    ) -> None:
        script = self._script(tmp_path, "hook.txt")

        with patch(_RUN) as run:
            protocol = execute_sync_hook(
                "demo", "manual", "presync", self._presync(f'"{script}" other.bat')
            )

        run.assert_not_called()
        assert protocol.generalErrors
        assert "unsupported" in (protocol.generalErrors[0].message or "")

    def test_a_missing_script_is_reported(self, tmp_path: Path) -> None:
        with patch(_RUN) as run:
            protocol = execute_sync_hook(
                "demo", "manual", "presync", self._presync(str(tmp_path / "missing.bat"))
            )

        run.assert_not_called()
        assert protocol.generalErrors
        assert "not found" in (protocol.generalErrors[0].message or "")

    def test_an_unparsable_command_is_reported(self) -> None:
        with patch(_RUN) as run:
            protocol = execute_sync_hook(
                "demo", "manual", "presync", self._presync('"C:\\hooks\\export.bat %1')
            )

        run.assert_not_called()
        assert protocol.generalErrors
        assert "could not be parsed" in (protocol.generalErrors[0].message or "")

    def test_no_command_for_the_sync_type_is_acknowledged(self, tmp_path: Path) -> None:
        script = self._script(tmp_path)

        with patch(_RUN) as run:
            protocol = execute_sync_hook("demo", "scheduled", "presync", self._presync(str(script)))

        run.assert_not_called()
        assert protocol.successes
        assert not protocol.generalErrors

"""Tests for the CLI group and the start command that are not covered by the wizard tests."""

import os

import pytest
from click.testing import CliRunner

from testbench_defect_service import cli as cli_module


@pytest.mark.unit
def test_cli_loads_dotenv_from_the_working_directory(tmp_path, monkeypatch):
    """The wizard writes ./.env, so the CLI must read ./.env, not one next to the package."""
    # setenv first so monkeypatch records the original state and restores it on teardown
    monkeypatch.setenv("PROBE_DOTENV_VAR", "")
    monkeypatch.delenv("PROBE_DOTENV_VAR")
    (tmp_path / ".env").write_text("PROBE_DOTENV_VAR=found\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    # The group callback runs before the subcommand's eager --help exits.
    result = CliRunner().invoke(cli_module.cli, ["init", "--help"])

    assert result.exit_code == 0
    assert os.environ["PROBE_DOTENV_VAR"] == "found"

"""Tests for the CLI group and the start command that are not covered by the wizard tests."""

import os
from types import SimpleNamespace
from unittest.mock import patch

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


@pytest.mark.unit
def test_start_configures_logging_before_building_app_config(tmp_path):
    """Credential warnings logged while AppConfig is built must use the configured handlers."""
    calls = []
    logging_config = object()

    def build_app_config(**_kwargs):
        calls.append("app_config")
        raise SystemExit(1)  # stop before the server is started

    with (
        patch.object(cli_module, "resolve_config_file_path", return_value=tmp_path / "c.toml"),
        patch.object(
            cli_module, "load_service_config", return_value=SimpleNamespace(logging=logging_config)
        ),
        patch.object(
            cli_module, "setup_logging", side_effect=lambda *_a, **_kw: calls.append("logging")
        ) as setup_logging,
        patch.object(cli_module, "AppConfig", side_effect=build_app_config),
    ):
        CliRunner().invoke(cli_module.start, ["--dev"])

    assert calls == ["logging", "app_config"]
    setup_logging.assert_called_once_with(logging_config, debug=True)

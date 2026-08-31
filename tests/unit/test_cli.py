"""Tests for the CLI commands that are not covered by the wizard tests."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from testbench_defect_service import cli as cli_module
from testbench_defect_service.utils import conf_converter, config_wizard

_AUTH_CONFIG = {"auth_type": "token", "token": "pat-123"}
_CREDENTIALS = ("password-hash", "password-salt")

_LEGACY_CONF_TEXT = """# legacy Jira wrapper configuration
wrapper.name: JiraWrapper
jira.baseUri: https://jira.example.com
jira.baseQuery: project = 'TB'
"""

_PREVIOUS_CONFIG = "# previous configuration\n"


@pytest.fixture
def legacy_conf(tmp_path):
    """A legacy Jira ``.conf`` file on disk, as the wrappers shipped it."""
    legacy_path = tmp_path / "jira.conf"
    legacy_path.write_text(_LEGACY_CONF_TEXT, encoding="utf-8")
    return legacy_path


@pytest.fixture
def answered_prompts():
    """Answer the two interactive steps of a Jira migration without a terminal."""
    with (
        patch.object(conf_converter, "prompt_service_credentials", return_value=_CREDENTIALS),
        patch.object(conf_converter, "prompt_jira_auth_config", return_value=_AUTH_CONFIG),
    ):
        yield


@pytest.fixture
def cancelled_auth():
    """The service login is given, but the Jira authentication setup is aborted."""
    with (
        patch.object(conf_converter, "prompt_service_credentials", return_value=_CREDENTIALS),
        patch.object(conf_converter, "prompt_jira_auth_config", return_value=None),
    ):
        yield


def answer_confirm(value: bool):
    """Patch the wizard's confirmation prompt to answer *value*."""
    return patch.object(
        config_wizard.questionary, "confirm", return_value=SimpleNamespace(ask=lambda: value)
    )


def run_migrate(legacy_path, config_path, *extra_args):
    return CliRunner().invoke(
        cli_module.migrate,
        ["--from", str(legacy_path), "--path", str(config_path), *extra_args],
    )


@pytest.mark.unit
def test_migrate_writes_the_converted_configuration(legacy_conf, tmp_path, answered_prompts):
    """The whole point of the command: a legacy file becomes a usable config.toml."""
    config_path = tmp_path / "config.toml"

    result = run_migrate(legacy_conf, config_path)

    assert result.exit_code == 0, result.output
    written = config_path.read_text(encoding="utf-8")
    assert conf_converter.JIRA_CLIENT_CLASS in written
    assert 'server_url = "https://jira.example.com"' in written


@pytest.mark.unit
def test_migrate_backs_up_an_existing_configuration(legacy_conf, tmp_path, answered_prompts):
    """An existing config is never silently discarded - it is renamed out of the way first."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(_PREVIOUS_CONFIG, encoding="utf-8")

    with answer_confirm(True):
        result = run_migrate(legacy_conf, config_path)

    assert result.exit_code == 0, result.output
    backups = list(tmp_path.glob("config.toml.backup*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == _PREVIOUS_CONFIG
    assert conf_converter.JIRA_CLIENT_CLASS in config_path.read_text(encoding="utf-8")


@pytest.mark.unit
def test_migrate_keeps_the_existing_configuration_when_declined(
    legacy_conf, tmp_path, answered_prompts
):
    """Declining the backup prompt must leave the existing configuration exactly as it was."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(_PREVIOUS_CONFIG, encoding="utf-8")

    with answer_confirm(False):
        result = run_migrate(legacy_conf, config_path)

    assert result.exit_code == 0, result.output
    assert config_path.read_text(encoding="utf-8") == _PREVIOUS_CONFIG
    assert not list(tmp_path.glob("config.toml.backup*"))


@pytest.mark.unit
def test_migrate_reports_a_cancelled_conversion_without_a_traceback(
    legacy_conf, tmp_path, cancelled_auth
):
    """A cancelled prompt is a user decision, not a crash, so it must not spill a traceback."""
    config_path = tmp_path / "config.toml"

    result = run_migrate(legacy_conf, config_path)

    assert result.exit_code != 0
    assert "cancelled" in result.output.lower()
    assert "Traceback" not in result.output
    assert not config_path.exists()


@pytest.mark.unit
def test_migrate_leaves_an_existing_configuration_intact_when_cancelled(
    legacy_conf, tmp_path, cancelled_auth
):
    """A cancelled migration must be a no-op: the service still has to start afterwards."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(_PREVIOUS_CONFIG, encoding="utf-8")

    result = run_migrate(legacy_conf, config_path)

    assert result.exit_code != 0
    assert config_path.read_text(encoding="utf-8") == _PREVIOUS_CONFIG
    assert not list(tmp_path.glob("config.toml.backup*"))


@pytest.mark.unit
def test_migrate_asks_for_the_source_type_when_the_extension_is_unknown(tmp_path):
    """Guessing the format would produce the wrong client, so the command asks for --type."""
    legacy_path = tmp_path / "wrapper.txt"
    legacy_path.write_text(_LEGACY_CONF_TEXT, encoding="utf-8")
    config_path = tmp_path / "config.toml"

    result = run_migrate(legacy_path, config_path)

    assert result.exit_code != 0
    assert "source type" in result.output
    assert not config_path.exists()


@pytest.mark.unit
def test_migrate_converts_an_unknown_extension_when_the_type_is_given(tmp_path, answered_prompts):
    """``--type`` is the escape hatch for wrapper files that were renamed."""
    legacy_path = tmp_path / "wrapper.txt"
    legacy_path.write_text(_LEGACY_CONF_TEXT, encoding="utf-8")
    config_path = tmp_path / "config.toml"

    result = run_migrate(legacy_path, config_path, "--type", "jira")

    assert result.exit_code == 0, result.output
    assert conf_converter.JIRA_CLIENT_CLASS in config_path.read_text(encoding="utf-8")


@pytest.mark.unit
def test_migrate_rejects_an_inconsistent_file_without_writing_anything(tmp_path, answered_prompts):
    """An inconsistent legacy file must abort with an explanation, not migrate halfway."""
    legacy_path = tmp_path / "jira.conf"
    legacy_path.write_text(
        "jira.baseUri: https://one.example.com\njira.baseUri: https://two.example.com\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(_PREVIOUS_CONFIG, encoding="utf-8")

    result = run_migrate(legacy_path, config_path)

    assert result.exit_code != 0
    assert "jira.baseUri" in result.output
    assert "Traceback" not in result.output
    assert config_path.read_text(encoding="utf-8") == _PREVIOUS_CONFIG
    assert not list(tmp_path.glob("config.toml.backup*"))


@pytest.mark.unit
def test_migrate_names_the_line_it_could_not_read(tmp_path, answered_prompts):
    """A file the parser chokes on has to say where, so the user can fix that line."""
    legacy_path = tmp_path / "jira.conf"
    legacy_path.write_text("wrapper.name: X\nthis line has no separator\n", encoding="utf-8")
    config_path = tmp_path / "config.toml"

    result = run_migrate(legacy_path, config_path)

    assert result.exit_code != 0
    assert "jira.conf line 2" in result.output
    assert not config_path.exists()


@pytest.mark.unit
def test_migrate_is_registered_on_the_cli():
    """A command that is not registered is unreachable, which is the bug being fixed."""
    assert "migrate" in cli_module.cli.commands

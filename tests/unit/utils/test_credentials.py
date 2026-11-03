"""Tests for Jira credential sources (environment, _FILE) in utils/credentials.py."""

import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, Field

from testbench_defect_service.clients.jira.config import JiraDefectClientConfig
from testbench_defect_service.utils import credentials

CREDENTIAL_ENV_VARS = [
    "JIRA_PASSWORD",
    "JIRA_BEARER_TOKEN",
    "JIRA_OAUTH2_CLIENT_SECRET",
    "JIRA_OAUTH1_ACCESS_TOKEN",
    "JIRA_OAUTH1_ACCESS_TOKEN_SECRET",
    "JIRA_OAUTH1_KEY_CERT",
]


@pytest.fixture(autouse=True)
def _clean_jira_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in [*CREDENTIAL_ENV_VARS, "JIRA_OAUTH2_REFRESH_TOKEN", "JIRA_USERNAME"]:
        monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv(f"{var}_FILE", raising=False)


@pytest.mark.unit
def test_credential_fields_lists_sensitive_non_excluded_jira_fields():
    assert credentials.credential_fields(JiraDefectClientConfig) == {
        "password": "JIRA_PASSWORD",
        "token": "JIRA_BEARER_TOKEN",
        "oauth2_client_secret": "JIRA_OAUTH2_CLIENT_SECRET",
        "oauth1_access_token": "JIRA_OAUTH1_ACCESS_TOKEN",
        "oauth1_access_token_secret": "JIRA_OAUTH1_ACCESS_TOKEN_SECRET",
        "oauth1_key_cert": "JIRA_OAUTH1_KEY_CERT",
    }


@pytest.mark.unit
def test_credential_fields_is_empty_for_models_without_credentials():
    class Plain(BaseModel):
        path: str = Field("x", json_schema_extra={"env_var": "PLAIN_PATH"})

    assert credentials.credential_fields(Plain) == {}


@pytest.mark.unit
def test_read_credential_prefers_plain_variable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JIRA_PASSWORD", "plain-secret")
    assert credentials.read_credential_from_env("JIRA_PASSWORD") == (
        "plain-secret",
        "JIRA_PASSWORD",
    )


@pytest.mark.unit
def test_read_credential_returns_none_when_unset_or_empty(monkeypatch: pytest.MonkeyPatch):
    assert credentials.read_credential_from_env("JIRA_PASSWORD") == (None, None)
    monkeypatch.setenv("JIRA_PASSWORD", "")
    assert credentials.read_credential_from_env("JIRA_PASSWORD") == (None, None)


@pytest.mark.unit
def test_read_credential_from_file_strips_one_trailing_newline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    secret_file = tmp_path / "pw"
    secret_file.write_bytes(b"file-secret\r\n")
    monkeypatch.setenv("JIRA_PASSWORD_FILE", str(secret_file))
    assert credentials.read_credential_from_env("JIRA_PASSWORD") == (
        "file-secret",
        "JIRA_PASSWORD_FILE",
    )
    secret_file.write_bytes(b"two\n\n")
    assert credentials.read_credential_from_env("JIRA_PASSWORD")[0] == "two\n"
    secret_file.write_bytes(b"two\r\n\r\n")
    assert credentials.read_credential_from_env("JIRA_PASSWORD")[0] == "two\r\n"


@pytest.mark.unit
def test_read_credential_keeps_pem_content_as_is(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pem = tmp_path / "key.pem"
    pem.write_bytes(b"-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----\n")
    monkeypatch.setenv("JIRA_OAUTH1_KEY_CERT_FILE", str(pem))
    value, _ = credentials.read_credential_from_env("JIRA_OAUTH1_KEY_CERT")
    assert value is not None
    assert value.endswith("-----END RSA PRIVATE KEY-----\n")


@pytest.mark.unit
def test_empty_plain_variable_with_file_is_not_a_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    secret_file = tmp_path / "pw"
    secret_file.write_text("file-secret")
    monkeypatch.setenv("JIRA_PASSWORD", "")
    monkeypatch.setenv("JIRA_PASSWORD_FILE", str(secret_file))
    assert credentials.read_credential_from_env("JIRA_PASSWORD")[0] == "file-secret"


@pytest.mark.unit
def test_both_variable_and_file_set_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    secret_file = tmp_path / "pw"
    secret_file.write_text("file-secret")
    monkeypatch.setenv("JIRA_PASSWORD", "plain-secret")
    monkeypatch.setenv("JIRA_PASSWORD_FILE", str(secret_file))
    with pytest.raises(credentials.CredentialSourceError) as excinfo:
        credentials.read_credential_from_env("JIRA_PASSWORD")
    assert (
        str(excinfo.value)
        == "Both JIRA_PASSWORD and JIRA_PASSWORD_FILE are set; unset one of them."
    )
    assert "plain-secret" not in str(excinfo.value)
    assert "file-secret" not in str(excinfo.value)


@pytest.mark.parametrize("make_target", ["missing", "directory"])
@pytest.mark.unit
def test_unreadable_file_is_refused_naming_the_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_target: str
):
    target = tmp_path / "pw"
    if make_target == "directory":
        target.mkdir()
    monkeypatch.setenv("JIRA_PASSWORD_FILE", str(target))
    with pytest.raises(credentials.CredentialSourceError) as excinfo:
        credentials.read_credential_from_env("JIRA_PASSWORD")
    message = str(excinfo.value)
    assert message.startswith(f"JIRA_PASSWORD_FILE points to '{target}', which cannot be read: ")
    assert message.endswith(".")


@pytest.mark.unit
def test_non_utf8_file_is_refused_without_leaking_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target = tmp_path / "pw"
    target.write_bytes(b"\xff\xfe")
    monkeypatch.setenv("JIRA_PASSWORD_FILE", str(target))
    with pytest.raises(credentials.CredentialSourceError) as excinfo:
        credentials.read_credential_from_env("JIRA_PASSWORD")
    assert str(excinfo.value).startswith(
        f"JIRA_PASSWORD_FILE points to '{target}', which cannot be read: "
    )
    assert "\xff" not in str(excinfo.value)


@pytest.mark.parametrize("content", [b"", b"\n", b"\r\n"])
@pytest.mark.unit
def test_empty_file_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes):
    target = tmp_path / "pw"
    target.write_bytes(content)
    monkeypatch.setenv("JIRA_PASSWORD_FILE", str(target))
    with pytest.raises(credentials.CredentialSourceError) as excinfo:
        credentials.read_credential_from_env("JIRA_PASSWORD")
    assert str(excinfo.value) == f"JIRA_PASSWORD_FILE points to '{target}', which is empty."


@pytest.mark.unit
def test_resolve_credentials_env_beats_config_and_warns_without_values(
    monkeypatch: pytest.MonkeyPatch,
):
    fake_logger = MagicMock()
    monkeypatch.setattr(credentials, "logger", fake_logger)
    monkeypatch.setenv("JIRA_PASSWORD", "env-secret")
    config = {"auth_type": "basic", "username": "u", "password": "config-secret"}

    resolved = credentials.resolve_credentials(
        JiraDefectClientConfig, config, config_label="config.toml"
    )

    assert resolved["password"] == "env-secret"
    assert config["password"] == "config-secret"  # input not mutated
    fake_logger.warning.assert_called_once_with(
        "Jira credential 'password' is stored in config.toml; move it to .env (JIRA_PASSWORD) "
        "or use JIRA_PASSWORD_FILE. The configured value is ignored: JIRA_PASSWORD overrides it."
    )
    assert "secret" not in fake_logger.warning.call_args.args[0]


@pytest.mark.unit
def test_resolve_credentials_warns_for_config_value_without_override(
    monkeypatch: pytest.MonkeyPatch,
):
    fake_logger = MagicMock()
    monkeypatch.setattr(credentials, "logger", fake_logger)
    resolved = credentials.resolve_credentials(
        JiraDefectClientConfig, {"token": "config-secret"}, config_label="jira_config.toml"
    )
    assert resolved["token"] == "config-secret"
    fake_logger.warning.assert_called_once_with(
        "Jira credential 'token' is stored in jira_config.toml; move it to .env "
        "(JIRA_BEARER_TOKEN) or use JIRA_BEARER_TOKEN_FILE."
    )


@pytest.mark.unit
def test_resolve_credentials_file_source_is_named_in_override_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fake_logger = MagicMock()
    monkeypatch.setattr(credentials, "logger", fake_logger)
    (tmp_path / "pw").write_text("file-secret\n")
    monkeypatch.setenv("JIRA_PASSWORD_FILE", str(tmp_path / "pw"))
    resolved = credentials.resolve_credentials(
        JiraDefectClientConfig, {"password": "config-secret"}, config_label="config.toml"
    )
    assert resolved["password"] == "file-secret"
    assert fake_logger.warning.call_args.args[0].endswith("JIRA_PASSWORD_FILE overrides it.")


@pytest.mark.unit
def test_resolve_credentials_is_a_no_op_for_models_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
):
    class Plain(BaseModel):
        path: str = "x"

    fake_logger = MagicMock()
    monkeypatch.setattr(credentials, "logger", fake_logger)
    monkeypatch.setenv("JIRA_PASSWORD", "env-secret")
    assert credentials.resolve_credentials(Plain, {"path": "y"}, config_label="c") == {"path": "y"}
    fake_logger.warning.assert_not_called()


@pytest.mark.unit
def test_resolve_credentials_propagates_source_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("JIRA_PASSWORD_FILE", str(tmp_path / "missing"))
    with pytest.raises(credentials.CredentialSourceError):
        credentials.resolve_credentials(JiraDefectClientConfig, {}, config_label="c")


@pytest.mark.unit
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file permissions")
def test_ensure_private_file_creates_and_restricts_to_owner(tmp_path: Path):
    target = tmp_path / ".env"
    credentials.ensure_private_file(target)
    assert target.exists()
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    target.chmod(0o644)
    credentials.ensure_private_file(target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.unit
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file permissions")
def test_ensure_private_file_warns_when_permissions_cannot_be_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fake_logger = MagicMock()
    monkeypatch.setattr(credentials, "logger", fake_logger)
    target = tmp_path / ".env"
    target.write_text("")

    def _refuse(self: Path, mode: int) -> None:
        raise OSError(1, "nope")

    monkeypatch.setattr(Path, "chmod", _refuse)
    credentials.ensure_private_file(target)
    fake_logger.warning.assert_called_once_with(
        f"Could not restrict '{target}' to the owner (chmod 600 failed); "
        "set the file permissions manually."
    )


@pytest.mark.unit
def test_ensure_private_file_is_a_no_op_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(credentials.os, "name", "nt")
    credentials.ensure_private_file(tmp_path / ".env")
    assert not (tmp_path / ".env").exists()


@pytest.mark.unit
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file permissions")
def test_open_private_file_creates_owner_only_binary_file(tmp_path: Path):
    target = tmp_path / "cache.tmp"
    with credentials.open_private_file(target) as fh:
        fh.write(b"data")
    assert target.read_bytes() == b"data"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.unit
def test_open_private_file_writes_bytes_and_truncates(tmp_path: Path):
    target = tmp_path / "cache.tmp"
    with credentials.open_private_file(target) as fh:
        fh.write(b"first")
    with credentials.open_private_file(target) as fh:
        fh.write(b"x")
    assert target.read_bytes() == b"x"

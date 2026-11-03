"""Tests for Jira credential sources (environment, _FILE) in utils/credentials.py."""

from pathlib import Path

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

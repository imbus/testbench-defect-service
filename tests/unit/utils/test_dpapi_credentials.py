"""Tests for DPAPI-encrypted Jira credentials: ``<VAR>_DPAPI``, the wizard and the CLI."""

import base64
import os
import sys
from pathlib import Path
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner
from dotenv import get_key

from testbench_defect_service import cli as cli_module
from testbench_defect_service.clients.jira.config import JiraDefectClientConfig
from testbench_defect_service.utils import config_wizard, credentials, dpapi

JIRA_CLIENT_CLASS = "testbench_defect_service.clients.JiraDefectClient"
CREDENTIAL_ENV_VARS = [
    "JIRA_PASSWORD",
    "JIRA_BEARER_TOKEN",
    "JIRA_OAUTH2_CLIENT_SECRET",
    "JIRA_OAUTH1_ACCESS_TOKEN",
    "JIRA_OAUTH1_ACCESS_TOKEN_SECRET",
    "JIRA_OAUTH1_KEY_CERT",
]
RETRY_HINT = (
    "Set the credential again with 'testbench-defect-service set-client-credential JIRA_PASSWORD'."
)

pytestmark = pytest.mark.unit

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI exists on Windows only")


@pytest.fixture(autouse=True)
def _clean_jira_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in [*CREDENTIAL_ENV_VARS, "JIRA_USERNAME"]:
        for name in (var, f"{var}_FILE", f"{var}_DPAPI"):
            # setenv first so monkeypatch records the original state and restores it on teardown
            monkeypatch.setenv(name, "")
            monkeypatch.delenv(name)


@pytest.fixture
def fake_dpapi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace DPAPI by a reversible fake that works on every platform."""

    def _protect(data: bytes, *, machine_scope: bool = False) -> bytes:
        return (b"M:" if machine_scope else b"U:") + data[::-1]

    def _unprotect(data: bytes) -> bytes:
        if data[:2] not in (b"M:", b"U:"):
            raise dpapi.DpapiError(13, "The data is invalid")
        return data[2:][::-1]

    monkeypatch.setattr(dpapi, "is_available", lambda: True)
    monkeypatch.setattr(dpapi, "protect", _protect)
    monkeypatch.setattr(dpapi, "unprotect", _unprotect)


def _blob(value: str, prefix: bytes = b"U:") -> str:
    return base64.b64encode(prefix + value.encode("utf-8")[::-1]).decode("ascii")


@pytest.fixture
def jira_config_path(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[testbench-defect-service]\nclient_class = "{JIRA_CLIENT_CLASS}"\n',
        encoding="utf-8",
    )
    return config_path


@pytest.fixture
def password_answers():
    """Queue answers for the masked prompts of ``set_client_credential``."""
    with patch.object(config_wizard.questionary, "password") as password:

        def _queue(*answers: str | None) -> None:
            password.return_value.ask.side_effect = list(answers)

        yield _queue


# --- utils/dpapi.py ---------------------------------------------------------------------


@windows_only
@pytest.mark.parametrize("machine_scope", [False, True])
def test_dpapi_round_trip(machine_scope: bool):
    secret = "pä$${x} \n".encode()
    blob = dpapi.protect(secret, machine_scope=machine_scope)
    assert secret not in blob
    assert dpapi.unprotect(blob) == secret


@windows_only
def test_dpapi_refuses_a_blob_it_did_not_create():
    with pytest.raises(dpapi.DpapiError):
        dpapi.unprotect(b"not a DPAPI blob")


def test_dpapi_is_unavailable_off_windows(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(dpapi.sys, "platform", "linux")
    assert dpapi.is_available() is False
    with pytest.raises(dpapi.DpapiError, match="only available on Windows"):
        dpapi.protect(b"x")
    with pytest.raises(dpapi.DpapiError, match="only available on Windows"):
        dpapi.unprotect(b"x")


# --- utils/credentials.py ---------------------------------------------------------------


@windows_only
def test_encrypted_credential_is_read_back_with_real_dpapi(monkeypatch: pytest.MonkeyPatch):
    encoded = credentials.encrypt_credential_with_dpapi("pä${HOME}ss")
    assert "HOME" not in encoded
    monkeypatch.setenv("JIRA_PASSWORD_DPAPI", encoded)
    assert credentials.read_credential_from_env("JIRA_PASSWORD") == (
        "pä${HOME}ss",
        "JIRA_PASSWORD_DPAPI",
    )


@pytest.mark.usefixtures("fake_dpapi")
def test_encrypt_credential_returns_base64_of_the_blob():
    assert credentials.encrypt_credential_with_dpapi("abc") == _blob("abc")
    assert credentials.encrypt_credential_with_dpapi("abc", machine_scope=True) == _blob(
        "abc", b"M:"
    )


@pytest.mark.usefixtures("fake_dpapi")
def test_read_credential_decrypts_the_dpapi_variable(monkeypatch: pytest.MonkeyPatch):
    # Unlike a _FILE, the decrypted value is used as is, trailing newline included.
    monkeypatch.setenv("JIRA_PASSWORD_DPAPI", _blob("s3cret\n"))
    assert credentials.read_credential_from_env("JIRA_PASSWORD") == (
        "s3cret\n",
        "JIRA_PASSWORD_DPAPI",
    )


@pytest.mark.usefixtures("fake_dpapi")
@pytest.mark.parametrize(
    ("variables", "message"),
    [
        (
            ("JIRA_PASSWORD", "JIRA_PASSWORD_DPAPI"),
            "Both JIRA_PASSWORD and JIRA_PASSWORD_DPAPI are set; unset one of them.",
        ),
        (
            ("JIRA_PASSWORD_FILE", "JIRA_PASSWORD_DPAPI"),
            "Both JIRA_PASSWORD_FILE and JIRA_PASSWORD_DPAPI are set; unset one of them.",
        ),
        (
            ("JIRA_PASSWORD", "JIRA_PASSWORD_FILE", "JIRA_PASSWORD_DPAPI"),
            (
                "JIRA_PASSWORD, JIRA_PASSWORD_FILE and JIRA_PASSWORD_DPAPI are all set; "
                "keep only one of them."
            ),
        ),
    ],
)
def test_more_than_one_source_is_refused(
    monkeypatch: pytest.MonkeyPatch, variables: tuple[str, ...], message: str
):
    for name in variables:
        monkeypatch.setenv(name, _blob("s3cret"))
    with pytest.raises(credentials.CredentialSourceError) as excinfo:
        credentials.read_credential_from_env("JIRA_PASSWORD")
    assert str(excinfo.value) == message


def test_dpapi_variable_is_refused_off_windows(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(dpapi, "is_available", lambda: False)
    monkeypatch.setenv("JIRA_PASSWORD_DPAPI", _blob("s3cret"))
    with pytest.raises(credentials.CredentialSourceError) as excinfo:
        credentials.read_credential_from_env("JIRA_PASSWORD")
    assert str(excinfo.value) == (
        "JIRA_PASSWORD_DPAPI is set, but DPAPI-encrypted credentials are only supported on "
        "Windows; use JIRA_PASSWORD or JIRA_PASSWORD_FILE instead."
    )


@pytest.mark.usefixtures("fake_dpapi")
def test_dpapi_variable_that_is_not_base64_is_refused(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JIRA_PASSWORD_DPAPI", "not base64!")
    with pytest.raises(credentials.CredentialSourceError) as excinfo:
        credentials.read_credential_from_env("JIRA_PASSWORD")
    assert str(excinfo.value) == f"JIRA_PASSWORD_DPAPI is not valid base64. {RETRY_HINT}"


@pytest.mark.usefixtures("fake_dpapi")
def test_blob_from_another_account_is_refused_with_a_retry_hint(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("JIRA_PASSWORD_DPAPI", base64.b64encode(b"foreign blob").decode())
    with pytest.raises(credentials.CredentialSourceError) as excinfo:
        credentials.read_credential_from_env("JIRA_PASSWORD")
    assert str(excinfo.value) == (
        "JIRA_PASSWORD_DPAPI cannot be decrypted by this Windows account; it was encrypted by "
        f"another user or on another machine, or the value is damaged. {RETRY_HINT}"
    )


@pytest.mark.usefixtures("fake_dpapi")
def test_blob_decrypting_to_nothing_is_refused(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JIRA_PASSWORD_DPAPI", _blob(""))
    with pytest.raises(credentials.CredentialSourceError) as excinfo:
        credentials.read_credential_from_env("JIRA_PASSWORD")
    assert str(excinfo.value) == f"JIRA_PASSWORD_DPAPI decrypts to an empty value. {RETRY_HINT}"


def test_placeholders_cover_dpapi_sourced_credentials_without_decrypting(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("JIRA_PASSWORD_DPAPI", "never-decrypted")
    monkeypatch.setenv("JIRA_BEARER_TOKEN", "plain-value")
    monkeypatch.setenv("JIRA_BEARER_TOKEN_DPAPI", "never-decrypted")

    result = credentials.with_file_sourced_placeholders(
        JiraDefectClientConfig, {"auth_type": "basic"}
    )

    assert result == {"auth_type": "basic", "password": "<from JIRA_PASSWORD_DPAPI>"}


@pytest.mark.usefixtures("fake_dpapi")
def test_resolve_credentials_names_the_dpapi_variable_in_the_override_warning(
    monkeypatch: pytest.MonkeyPatch,
):
    warnings: list[str] = []
    monkeypatch.setattr(credentials.logger, "warning", warnings.append)
    monkeypatch.setenv("JIRA_PASSWORD_DPAPI", _blob("s3cret"))

    resolved = credentials.resolve_credentials(
        JiraDefectClientConfig, {"password": "config-secret"}, config_label="config.toml"
    )

    assert resolved["password"] == "s3cret"
    assert warnings[0].endswith("JIRA_PASSWORD_DPAPI overrides it.")


# --- utils/config_wizard.py: storing from the wizard ------------------------------------


@pytest.mark.usefixtures("fake_dpapi")
def test_store_credentials_encrypts_and_drops_the_plain_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("JIRA_PASSWORD=old-plain\nOTHER=1\n")
    monkeypatch.setenv("JIRA_PASSWORD", "old-plain")
    config = {"auth_type": "basic", "password": "s3cret"}

    stored = config_wizard.store_credentials_in_env(
        config, JiraDefectClientConfig, dotenv_path, storage=config_wizard.STORAGE_DPAPI_USER
    )

    assert stored == ["JIRA_PASSWORD"]
    assert config == {"auth_type": "basic"}
    assert get_key(str(dotenv_path), "JIRA_PASSWORD_DPAPI") == _blob("s3cret")
    assert get_key(str(dotenv_path), "JIRA_PASSWORD") is None
    assert get_key(str(dotenv_path), "OTHER") == "1"
    assert os.environ["JIRA_PASSWORD_DPAPI"] == _blob("s3cret")
    assert "JIRA_PASSWORD" not in os.environ
    out = capsys.readouterr().out
    assert f"✓ Stored JIRA_PASSWORD_DPAPI in {dotenv_path} (encrypted for this Windows user)" in out
    assert "s3cret" not in out
    assert "s3cret" not in dotenv_path.read_text()


@pytest.mark.usefixtures("fake_dpapi")
def test_store_credentials_for_the_machine_skips_the_interpolation_warning(tmp_path: Path, capsys):
    dotenv_path = tmp_path / ".env"
    config_wizard.store_credentials_in_env(
        {"password": "pa${HOME}ss"},
        JiraDefectClientConfig,
        dotenv_path,
        storage=config_wizard.STORAGE_DPAPI_MACHINE,
    )
    out = capsys.readouterr().out
    assert get_key(str(dotenv_path), "JIRA_PASSWORD_DPAPI") == _blob("pa${HOME}ss", b"M:")
    assert "(encrypted for this machine)" in out
    assert "interpolate" not in out


def test_store_credentials_as_plain_text_drops_a_stale_encrypted_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("JIRA_PASSWORD_DPAPI=stale\n")
    monkeypatch.setenv("JIRA_PASSWORD_DPAPI", "stale")

    config_wizard.store_credentials_in_env(
        {"password": "s3cret"},
        JiraDefectClientConfig,
        dotenv_path,
        storage=config_wizard.STORAGE_PLAIN,
    )

    assert get_key(str(dotenv_path), "JIRA_PASSWORD") == "s3cret"
    assert get_key(str(dotenv_path), "JIRA_PASSWORD_DPAPI") is None
    assert "JIRA_PASSWORD_DPAPI" not in os.environ


@pytest.mark.usefixtures("fake_dpapi")
def test_store_credentials_asks_for_the_storage_and_uses_the_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        config_wizard, "choose_credential_storage", lambda: config_wizard.STORAGE_DPAPI_MACHINE
    )
    dotenv_path = tmp_path / ".env"

    config_wizard.store_credentials_in_env({"token": "pat"}, JiraDefectClientConfig, dotenv_path)

    assert get_key(str(dotenv_path), "JIRA_BEARER_TOKEN_DPAPI") == _blob("pat", b"M:")


def test_store_credentials_aborts_without_writing_when_the_storage_prompt_is_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(config_wizard, "choose_credential_storage", lambda: None)
    config = {"password": "s3cret"}

    with pytest.raises(click.exceptions.Abort):
        config_wizard.store_credentials_in_env(config, JiraDefectClientConfig, tmp_path / ".env")

    assert config == {"password": "s3cret"}
    assert not (tmp_path / ".env").exists()


def test_store_credentials_does_not_ask_when_there_is_nothing_to_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def _fail() -> str:
        raise AssertionError("the storage must not be asked for")

    monkeypatch.setattr(config_wizard, "choose_credential_storage", _fail)
    assert (
        config_wizard.store_credentials_in_env(
            {"auth_type": "basic"}, JiraDefectClientConfig, tmp_path / ".env"
        )
        == []
    )


def test_storage_is_plain_text_without_asking_off_windows(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(dpapi, "is_available", lambda: False)
    with patch.object(config_wizard.questionary, "select") as select:
        assert config_wizard.choose_credential_storage() == config_wizard.STORAGE_PLAIN
    select.assert_not_called()


@pytest.mark.usefixtures("fake_dpapi")
def test_storage_prompt_offers_user_machine_and_plain():
    with patch.object(config_wizard.questionary, "select") as select:
        select.return_value.ask.return_value = config_wizard.STORAGE_DPAPI_USER
        assert config_wizard.choose_credential_storage() == config_wizard.STORAGE_DPAPI_USER
    choices = select.call_args.kwargs["choices"]
    assert [choice.value for choice in choices] == [
        config_wizard.STORAGE_DPAPI_USER,
        config_wizard.STORAGE_DPAPI_MACHINE,
        config_wizard.STORAGE_PLAIN,
    ]


def test_merge_with_defaults_succeeds_with_dpapi_sourced_credential(
    monkeypatch: pytest.MonkeyPatch,
):
    # Not a valid blob: it must never be decrypted here.
    monkeypatch.setenv("JIRA_PASSWORD_DPAPI", "not-a-blob")
    result = config_wizard.merge_with_defaults(
        {"server_url": "https://jira.example.com", "auth_type": "basic", "username": "jira-user"},
        JiraDefectClientConfig,
    )
    assert result["username"] == "jira-user"
    assert "password" not in result


def test_dc_code_exchange_reads_the_client_secret_from_a_secret_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / "secret").write_text("file-secret\n")
    monkeypatch.setenv("JIRA_OAUTH2_CLIENT_SECRET_FILE", str(tmp_path / "secret"))
    client_config = {"server_url": "https://jira.example.com", "oauth2_client_id": "id"}
    with (
        patch.object(config_wizard.questionary, "text") as text,
        patch.object(
            config_wizard, "exchange_authorization_code_sync", return_value="refresh"
        ) as exchange,
    ):
        text.return_value.ask.return_value = "answer"
        assert config_wizard._run_jira_dc_code_exchange(client_config) == "refresh"

    assert exchange.call_args.kwargs["client_secret"] == "file-secret"


# --- utils/config_wizard.py: set_client_credential --------------------------------------


@pytest.mark.usefixtures("fake_dpapi")
def test_set_client_credential_replaces_a_plain_value_with_an_encrypted_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, jira_config_path, password_answers
):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("JIRA_PASSWORD=old\n")
    monkeypatch.setenv("JIRA_PASSWORD", "old")
    password_answers("new-secret", "new-secret")

    config_wizard.set_client_credential(
        jira_config_path, "jira_password", config_wizard.STORAGE_DPAPI_USER, dotenv_path
    )

    assert get_key(str(dotenv_path), "JIRA_PASSWORD_DPAPI") == _blob("new-secret")
    assert get_key(str(dotenv_path), "JIRA_PASSWORD") is None
    out = capsys.readouterr().out
    assert f"✓ Stored JIRA_PASSWORD_DPAPI in {dotenv_path} (encrypted for this Windows user)" in out
    assert "Restart the service to use the new value." in out
    assert "new-secret" not in out
    assert "is also set in the environment" not in out


def test_set_client_credential_asks_again_until_both_entries_match(
    tmp_path: Path, capsys, jira_config_path, password_answers
):
    dotenv_path = tmp_path / ".env"
    password_answers("one", "two", "three", "three")

    config_wizard.set_client_credential(
        jira_config_path, "JIRA_BEARER_TOKEN", config_wizard.STORAGE_PLAIN, dotenv_path
    )

    assert get_key(str(dotenv_path), "JIRA_BEARER_TOKEN") == "three"
    assert "The values do not match" in capsys.readouterr().out


def test_set_client_credential_asks_which_credential_and_how_to_store_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, jira_config_path, password_answers
):
    dotenv_path = tmp_path / ".env"
    monkeypatch.setattr(
        config_wizard, "choose_credential_storage", lambda: config_wizard.STORAGE_PLAIN
    )
    password_answers("pat", "pat")
    with patch.object(config_wizard.questionary, "select") as select:
        select.return_value.ask.return_value = "JIRA_BEARER_TOKEN"
        config_wizard.set_client_credential(jira_config_path, dotenv_path=dotenv_path)

    assert select.call_args.kwargs["choices"] == CREDENTIAL_ENV_VARS
    assert get_key(str(dotenv_path), "JIRA_BEARER_TOKEN") == "pat"


@pytest.mark.parametrize("answers", [(None,), ("",), ("value", None)])
def test_set_client_credential_changes_nothing_when_cancelled(
    tmp_path: Path, capsys, jira_config_path, password_answers, answers: tuple
):
    dotenv_path = tmp_path / ".env"
    password_answers(*answers)

    config_wizard.set_client_credential(
        jira_config_path, "JIRA_PASSWORD", config_wizard.STORAGE_PLAIN, dotenv_path
    )

    assert not dotenv_path.exists()
    assert "Nothing was changed" in capsys.readouterr().out


def test_set_client_credential_rejects_an_unknown_variable(tmp_path: Path, jira_config_path):
    with pytest.raises(click.ClickException) as excinfo:
        config_wizard.set_client_credential(
            jira_config_path, "JIRA_USERNAME", config_wizard.STORAGE_PLAIN, tmp_path / ".env"
        )
    assert excinfo.value.message == (
        f"Unknown credential 'JIRA_USERNAME'. Choose one of: {', '.join(CREDENTIAL_ENV_VARS)}."
    )


def test_set_client_credential_requires_an_existing_configuration(tmp_path: Path):
    with pytest.raises(click.ClickException, match="Configuration file not found"):
        config_wizard.set_client_credential(tmp_path / "missing.toml", "JIRA_PASSWORD")


def test_set_client_credential_warns_about_a_source_set_outside_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, jira_config_path, password_answers
):
    dotenv_path = tmp_path / ".env"
    monkeypatch.setenv("JIRA_PASSWORD_FILE", str(tmp_path / "pw"))
    password_answers("new", "new")

    config_wizard.set_client_credential(
        jira_config_path, "JIRA_PASSWORD", config_wizard.STORAGE_PLAIN, dotenv_path
    )

    assert (
        f"⚠️  JIRA_PASSWORD_FILE is also set in the environment outside {dotenv_path}"
        in capsys.readouterr().out
    )


def test_set_client_credential_refuses_dpapi_off_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, jira_config_path
):
    monkeypatch.setattr(dpapi, "is_available", lambda: False)
    with pytest.raises(click.ClickException, match="only available on Windows"):
        config_wizard.set_client_credential(
            jira_config_path, "JIRA_PASSWORD", config_wizard.STORAGE_DPAPI_USER, tmp_path / ".env"
        )


# --- cli.py -----------------------------------------------------------------------------


def test_set_client_credential_is_registered_on_the_cli(tmp_path: Path):
    with patch.object(cli_module, "set_client_credential") as set_credential:
        result = CliRunner().invoke(
            cli_module.cli,
            [
                "set-client-credential",
                "JIRA_PASSWORD",
                "--path",
                str(tmp_path / "config.toml"),
                "--storage",
                "dpapi-machine",
            ],
        )
    assert result.exit_code == 0, result.output
    set_credential.assert_called_once_with(
        tmp_path / "config.toml", "JIRA_PASSWORD", "dpapi-machine"
    )


def test_set_client_credential_cli_rejects_an_unknown_storage():
    result = CliRunner().invoke(
        cli_module.cli, ["set-client-credential", "JIRA_PASSWORD", "--storage", "rot13"]
    )
    assert result.exit_code != 0
    assert "rot13" in result.output

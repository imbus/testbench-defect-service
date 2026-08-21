from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest
import tomllib

from testbench_defect_service.clients.jira.config import JiraDefectClientConfig
from testbench_defect_service.utils.conf_converter import (
    EXCEL_CLIENT_CLASS,
    JIRA_CLIENT_CLASS,
    ConfConversionError,
    auth_field_names,
    conf_defaults,
    convert_legacy_config,
    generate_excel_base_toml,
    generate_jira_base_toml,
    prompt_jira_auth_config,
)

_WIZARD = "testbench_defect_service.utils.wizard"
_CONFIG_WIZARD = "testbench_defect_service.utils.config_wizard"
_CONVERTER = "testbench_defect_service.utils.conf_converter"

# Passed wherever a test is not about the service credentials, so the generators write these
# instead of asking for a login.
_CREDENTIALS = ("password-hash", "password-salt")

_SERVER_URL = "https://jira.example.com"
_CONF_DATA: dict[str, Any] = {
    "wrapper.name": "JiraWrapper",
    "jira.baseUri": _SERVER_URL,
    "jira.baseQuery": "project = 'TB'",
}


def _questionary_mock(
    select: Any = None,
    texts: list[Any] | None = None,
    passwords: list[Any] | None = None,
) -> MagicMock:
    """Build a questionary stub answering select/text/password prompts in order."""
    questionary = MagicMock()
    questionary.select.return_value.ask.return_value = select
    questionary.text.return_value.ask.side_effect = texts or []
    questionary.password.return_value.ask.side_effect = passwords or []
    questionary.path.return_value.ask.side_effect = texts or []
    return questionary


@pytest.mark.unit
def test_prompted_fields_cover_every_required_model_field() -> None:
    """A required field that is never prompted for cannot be filled in, so
    ``prompt_model_fields`` fails validation and re-runs the wizard forever."""
    required = {
        name for name, field in JiraDefectClientConfig.model_fields.items() if field.is_required()
    }

    assert required <= auth_field_names()


@pytest.mark.unit
def test_auth_field_names_covers_auth_type_and_its_dependents() -> None:
    names = auth_field_names()

    assert {"auth_type", "username", "password", "token", "oauth2_client_id"} <= names
    # Connection settings are configured from the .conf, not by the auth prompts.
    assert not names & {"verify_ssl", "timeout", "defect_jql", "projects"}


@pytest.mark.unit
def test_conf_defaults_translate_legacy_keys_to_field_names() -> None:
    assert conf_defaults({**_CONF_DATA, "jira.user": "legacy-user"}) == {
        "server_url": _SERVER_URL,
        "username": "legacy-user",
    }


@pytest.mark.unit
def test_prompt_asks_for_basic_credentials() -> None:
    questionary = _questionary_mock(
        select="basic", texts=[_SERVER_URL, "jira-user"], passwords=["s3cret"]
    )

    with patch(f"{_WIZARD}.questionary", questionary):
        auth_config = prompt_jira_auth_config(_CONF_DATA)

    assert auth_config == {
        "server_url": _SERVER_URL,
        "auth_type": "basic",
        "username": "jira-user",
        "password": "s3cret",
    }


@pytest.mark.unit
def test_prompt_asks_only_for_the_token_on_token_auth() -> None:
    questionary = _questionary_mock(select="token", texts=[_SERVER_URL], passwords=["pat-123"])

    with patch(f"{_WIZARD}.questionary", questionary):
        auth_config = prompt_jira_auth_config(_CONF_DATA)

    assert auth_config == {
        "server_url": _SERVER_URL,
        "auth_type": "token",
        "token": "pat-123",
    }


@pytest.mark.unit
def test_prompt_prefills_the_legacy_username_and_server_url() -> None:
    questionary = _questionary_mock(
        select="basic", texts=[_SERVER_URL, "legacy-user"], passwords=["s3cret"]
    )
    conf_data = {**_CONF_DATA, "jira.user": "legacy-user"}

    with patch(f"{_WIZARD}.questionary", questionary):
        prompt_jira_auth_config(conf_data)

    defaults = [call.kwargs["default"] for call in questionary.text.call_args_list]
    assert defaults == [_SERVER_URL, "legacy-user"]


@pytest.mark.unit
def test_prompt_skips_credentials_taken_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JIRA_BEARER_TOKEN", "env-token")
    questionary = _questionary_mock(select="token", texts=[_SERVER_URL])

    with patch(f"{_WIZARD}.questionary", questionary):
        auth_config = prompt_jira_auth_config(_CONF_DATA)

    assert auth_config == {"server_url": _SERVER_URL, "auth_type": "token"}
    questionary.password.assert_not_called()


@pytest.mark.unit
def test_prompt_returns_none_when_a_required_prompt_is_aborted() -> None:
    questionary = _questionary_mock(select="token", texts=[None])

    with patch(f"{_WIZARD}.questionary", questionary):
        assert prompt_jira_auth_config(_CONF_DATA) is None


@pytest.mark.unit
def test_prompt_returns_none_when_the_jira_extra_is_missing() -> None:
    with patch(
        f"{_CONVERTER}.check_client_dependencies", side_effect=ImportError("install jira")
    ) as check:
        assert prompt_jira_auth_config(_CONF_DATA) is None

    check.assert_called_once_with("jira", raise_on_missing=True)


@pytest.mark.unit
def test_prompt_moves_the_oauth2_client_secret_out_of_the_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Recorded so monkeypatch restores it after store_client_secret_in_env exports it.
    monkeypatch.setenv("JIRA_OAUTH2_CLIENT_SECRET", "")
    questionary = _questionary_mock(
        select="oauth2 2LO (service account)",
        texts=[_SERVER_URL, "client-id"],
        passwords=["client-secret"],
    )

    with (
        patch(f"{_WIZARD}.questionary", questionary),
        patch("testbench_defect_service.utils.config_wizard.set_key") as set_key,
    ):
        auth_config = prompt_jira_auth_config(_CONF_DATA)

    assert auth_config is not None
    assert "oauth2_client_secret" not in auth_config
    assert auth_config["oauth2_client_id"] == "client-id"
    assert set_key.call_args.args[1:] == ("JIRA_OAUTH2_CLIENT_SECRET", "client-secret")


@pytest.mark.unit
def test_prompt_seeds_the_oauth2_refresh_token_instead_of_writing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JIRA_OAUTH2_CLIENT_SECRET", "env-secret")
    questionary = _questionary_mock(
        select="oauth2 3LO (user account)",
        texts=[_SERVER_URL, "client-id"],
        passwords=["refresh-123"],
    )

    with (
        patch(f"{_WIZARD}.questionary", questionary),
        patch(f"{_CONVERTER}.seed_oauth2_refresh_token") as seed,
        patch(f"{_CONVERTER}.run_jira_oauth_wizard") as oauth_wizard,
    ):
        auth_config = prompt_jira_auth_config(_CONF_DATA)

    assert auth_config is not None
    assert "oauth2_refresh_token" not in auth_config
    seed.assert_called_once_with("refresh-123")
    oauth_wizard.assert_not_called()


@pytest.mark.unit
def test_prompt_falls_back_to_the_oauth_wizard_without_a_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JIRA_OAUTH2_CLIENT_SECRET", "env-secret")
    monkeypatch.setenv("JIRA_OAUTH2_REFRESH_TOKEN", "env-refresh")
    questionary = _questionary_mock(
        select="oauth2 3LO (user account)", texts=[_SERVER_URL, "client-id"]
    )

    with (
        patch(f"{_WIZARD}.questionary", questionary),
        patch(f"{_CONVERTER}.has_cached_refresh_token", return_value=False),
        patch(f"{_CONVERTER}.run_jira_oauth_wizard", return_value="wizard-refresh") as oauth_wizard,
        patch(f"{_CONVERTER}.seed_oauth2_refresh_token") as seed,
    ):
        auth_config = prompt_jira_auth_config(_CONF_DATA)

    oauth_wizard.assert_called_once_with(auth_config)
    seed.assert_called_once_with("wizard-refresh")


@pytest.mark.unit
def test_generate_writes_the_collected_auth_fields() -> None:
    questionary = _questionary_mock(
        select="basic", texts=[_SERVER_URL, "jira-user"], passwords=["s3cret"]
    )

    with patch(f"{_WIZARD}.questionary", questionary):
        toml_text = generate_jira_base_toml(_CONF_DATA, credentials=_CREDENTIALS)

    client_config = tomllib.loads(toml_text)["testbench-defect-service"]["client_config"]
    assert client_config["auth_type"] == "basic"
    assert client_config["username"] == "jira-user"
    assert client_config["password"] == "s3cret"
    assert client_config["server_url"] == _SERVER_URL


@pytest.mark.unit
def test_generate_does_not_prompt_when_auth_config_is_passed() -> None:
    with patch(f"{_CONVERTER}.prompt_jira_auth_config") as prompt:
        toml_text = generate_jira_base_toml(
            _CONF_DATA, {"auth_type": "token", "token": "pat-123"}, _CREDENTIALS
        )

    prompt.assert_not_called()
    client_config = tomllib.loads(toml_text)["testbench-defect-service"]["client_config"]
    assert client_config["auth_type"] == "token"
    assert client_config["token"] == "pat-123"
    assert client_config["server_url"] == _SERVER_URL


_EXCEL_PROPERTIES: dict[str, str] = {
    "systemName": "Excel",
    "excelFilePath": r"C:\defects",
    "worksheetName": "defect",
    "fileType": ".xls",
    "simpleDateFormat": "dd.MM.yyyy",
    "defects.header.line": "2",
    "defects.data.startingLine": "12",
    "separator": ",",
    "controlFields": "status,class",
    "status.columnNo": "4",
    "status.value": "New,InProgress,Done",
    "class.columnNo": "6",
    "class.value": "Crash,Other",
    "New.transition.number": "1",
    "New.transition1": "New-InProgress",
    "defect.id.columnNo": "1",
    "defect.title.columnNo": "2",
    "defect.references.columnNo": "9",
    "defect.discoverer.columnNo": "3",
    "defect.lastedited.columnNo": "7",
    "defect.description.columnNo": "8",
    "defect.references.separator": ";",
    "defect.id.prefix": "Bug ",
    "defect.id.startingValue": "0001",
    "defect.id.digitNumber": "3",
    "udf.attr.number": "1",
    "udf.attr1.name": "isOpen",
    "udf.attr1.column": "11",
    "udf.attr1.type": "2",
    "udf.attr1.trueValue": "1-yes",
    "udf.attr1.falseValue": "2-no",
}


def _excel_client_config(**overrides: Any) -> dict[str, Any]:
    properties = {**_EXCEL_PROPERTIES, **overrides}
    toml_text = generate_excel_base_toml(properties, _CREDENTIALS)
    return dict(tomllib.loads(toml_text)["testbench-defect-service"]["client_config"])


@pytest.mark.unit
class TestGenerateExcelBaseToml:
    """The generated config must be what `ExcelDefectClientConfig` itself would accept.

    Everything here goes through the model, so the legacy `.properties` keys are read by the
    aliases and the `mode="before"` normalization rather than by a second mapping in the
    converter, and the values arrive with the model's types instead of as property strings.
    """

    def test_legacy_scalars_arrive_with_their_model_types(self) -> None:
        client_config = _excel_client_config()

        assert client_config["system_name"] == "Excel"
        assert client_config["excel_file_path"] == r"C:\defects"
        assert client_config["defects_data_header_line"] == 2
        assert client_config["defects_data_starting_line"] == 12
        assert client_config["references_column_no"] == 9
        assert client_config["lastedit_column_no"] == 7
        assert client_config["defect_id_digit_numbers"] == 3
        assert client_config["defect_id_starting_value"] == "0001"

    def test_a_relative_file_path_is_written_as_absolute(self, tmp_path, monkeypatch) -> None:
        """A legacy wrapper's relative path resolves against whatever directory `migrate` ran
        in, so carrying it over verbatim breaks the service as soon as it starts somewhere
        else - which is the normal case for the Windows service."""
        monkeypatch.chdir(tmp_path)

        client_config = _excel_client_config(excelFilePath="defects")

        assert Path(client_config["excel_file_path"]) == (tmp_path / "defects").resolve()

    def test_an_absolute_file_path_is_left_alone(self) -> None:
        client_config = _excel_client_config()

        assert client_config["excel_file_path"] == r"C:\defects"

    def test_control_fields_carry_their_state_keyed_transitions(self) -> None:
        client_config = _excel_client_config()

        by_name = {field["name"]: field for field in client_config["control_fields"]}
        assert by_name["status"]["values"] == ["New", "InProgress", "Done"]
        assert by_name["status"]["transitions"] == [{"from_state": "New", "to_state": "InProgress"}]
        assert by_name["classification"]["column_number"] == 6

    def test_user_defined_attributes_keep_their_value_type(self) -> None:
        client_config = _excel_client_config()

        assert client_config["udfs"] == [
            {
                "name": "isOpen",
                "column": 11,
                "type": "BOOLEAN",
                "required": False,
                "trueValue": "1-yes",
                "falseValue": "2-no",
            }
        ]

    def test_unset_options_fall_back_to_the_model_defaults(self) -> None:
        client_config = _excel_client_config()

        assert client_config["attributes"] == ["title", "status", "isOpen"]
        assert client_config["buffer_max_age_minutes"] == 1440.0
        assert client_config["buffer_cleanup_interval_minutes"] == 1.0

    def test_a_conversion_defaults_to_readonly(self) -> None:
        """A legacy file that never says otherwise must not become a writing client."""
        assert _excel_client_config()["readonly"] is True

    def test_an_explicit_legacy_readonly_flag_wins(self) -> None:
        assert _excel_client_config(readonly="false")["readonly"] is False

    def test_the_service_section_comes_from_the_service_model(self) -> None:
        toml_text = generate_excel_base_toml(_EXCEL_PROPERTIES, _CREDENTIALS)

        service_config = tomllib.loads(toml_text)["testbench-defect-service"]
        assert (
            service_config["client_class"] == "testbench_defect_service.clients.ExcelDefectClient"
        )
        assert service_config["logging"]["console"]["log_level"] == "INFO"
        assert service_config["server"]["single_process"] is True

    def test_an_unconvertible_file_names_the_offending_field(self) -> None:
        properties = {
            key: value for key, value in _EXCEL_PROPERTIES.items() if key != "excelFilePath"
        }

        with pytest.raises(ConfConversionError, match="excel_file_path"):
            generate_excel_base_toml(properties)


@pytest.mark.unit
class TestGenerateJiraBaseTomlUsesTheModel:
    _AUTH: ClassVar[dict[str, Any]] = {"auth_type": "token", "token": "pat-123"}

    def _client_config(self, **conf_overrides: Any) -> dict[str, Any]:
        toml_text = generate_jira_base_toml(
            {**_CONF_DATA, **conf_overrides}, dict(self._AUTH), _CREDENTIALS
        )
        return dict(tomllib.loads(toml_text)["testbench-defect-service"]["client_config"])

    def test_legacy_conf_entries_land_on_their_model_fields(self) -> None:
        client_config = self._client_config(
            **{"wrapper.readonly": "false", "wrapper.timeout_seconds": "45"}
        )

        assert client_config["name"] == "JiraWrapper"
        assert client_config["defect_jql"] == "project = 'TB'"
        assert client_config["readonly"] is False
        assert client_config["timeout"] == 45

    def test_unset_options_fall_back_to_the_model_defaults(self) -> None:
        client_config = self._client_config()

        assert client_config["verify_ssl"] is True
        assert client_config["max_retries"] == 3
        assert client_config["attributes"] == ["title", "status"]
        assert client_config["supports_changes_timestamps"] is True

    def test_a_conversion_defaults_to_readonly(self) -> None:
        assert self._client_config()["readonly"] is True


@pytest.mark.unit
class TestServiceCredentials:
    """The service login is asked for during a conversion, not carried over from the .conf.

    The legacy files hold no service credentials, so a generated config would otherwise ship a
    hash and salt nobody knows the password for.
    """

    def test_the_generated_config_uses_the_entered_login(self) -> None:
        questionary = _questionary_mock(texts=["svc-admin"], passwords=["s3cret", "s3cret"])

        with (
            patch(f"{_CONFIG_WIZARD}.questionary", questionary),
            patch(f"{_CONVERTER}.create_credentials", return_value=("hash-1", "salt-1")) as create,
        ):
            toml_text = generate_excel_base_toml(_EXCEL_PROPERTIES)

        create.assert_called_once_with("svc-admin", "s3cret")
        service_config = tomllib.loads(toml_text)["testbench-defect-service"]
        assert service_config["password_hash"] == "hash-1"
        assert service_config["salt"] == "salt-1"

    def test_the_hash_and_salt_are_renewed_per_conversion(self) -> None:
        """Two conversions of the same file must not share a salt."""
        first = self._converted_service_config()
        second = self._converted_service_config()

        assert first["salt"] != second["salt"]
        assert first["password_hash"] != second["password_hash"]

    def test_a_jira_conversion_asks_for_the_service_login_too(self) -> None:
        questionary = _questionary_mock(texts=["svc-admin"], passwords=["s3cret", "s3cret"])

        with (
            patch(f"{_CONFIG_WIZARD}.questionary", questionary),
            patch(f"{_CONVERTER}.create_credentials", return_value=("hash-1", "salt-1")),
        ):
            toml_text = generate_jira_base_toml(_CONF_DATA, {"auth_type": "token", "token": "pat"})

        service_config = tomllib.loads(toml_text)["testbench-defect-service"]
        assert service_config["password_hash"] == "hash-1"
        assert service_config["salt"] == "salt-1"

    def test_nothing_is_asked_when_the_credentials_are_passed(self) -> None:
        with patch(f"{_CONVERTER}.prompt_service_credentials") as prompt:
            generate_excel_base_toml(_EXCEL_PROPERTIES, _CREDENTIALS)

        prompt.assert_not_called()

    def test_a_cancelled_login_raises_a_conversion_error(self) -> None:
        questionary = _questionary_mock(texts=[None])

        with (
            patch(f"{_CONFIG_WIZARD}.questionary", questionary),
            pytest.raises(ConfConversionError, match="credentials"),
        ):
            generate_excel_base_toml(_EXCEL_PROPERTIES)

    @staticmethod
    def _converted_service_config() -> dict[str, Any]:
        questionary = _questionary_mock(texts=["svc-admin"], passwords=["s3cret", "s3cret"])

        with patch(f"{_CONFIG_WIZARD}.questionary", questionary):
            toml_text = generate_excel_base_toml(_EXCEL_PROPERTIES)

        return dict(tomllib.loads(toml_text)["testbench-defect-service"])


_LEGACY_CONF_TEXT = """# legacy Jira wrapper configuration
wrapper.name: JiraWrapper
jira.baseUri: https://jira.example.com
jira.baseQuery: project = 'TB'
"""

_LEGACY_PROPERTIES_TEXT = "\n".join(f"{key}={value}" for key, value in _EXCEL_PROPERTIES.items())


def _write_legacy_conf(tmp_path, name: str = "jira.conf"):
    legacy_path = tmp_path / name
    legacy_path.write_text(_LEGACY_CONF_TEXT, encoding="utf-8")
    return legacy_path


@pytest.mark.unit
class TestConvertLegacyConfig:
    """The dispatch from a legacy file on disk to the client it describes."""

    def test_a_conf_file_converts_as_jira(self, tmp_path) -> None:
        """``.conf`` is the legacy Jira wrapper format."""
        legacy_path = _write_legacy_conf(tmp_path)

        with (
            patch(f"{_CONVERTER}.prompt_service_credentials", return_value=_CREDENTIALS),
            patch(f"{_CONVERTER}.prompt_jira_auth_config", return_value=self._AUTH),
        ):
            toml_text = convert_legacy_config(legacy_path)

        service_config = tomllib.loads(toml_text)["testbench-defect-service"]
        assert service_config["client_class"] == JIRA_CLIENT_CLASS
        assert service_config["client_config"]["server_url"] == _SERVER_URL

    def test_a_properties_file_converts_as_excel(self, tmp_path) -> None:
        """``.properties`` is the legacy Excel wrapper format."""
        legacy_path = tmp_path / "genericexcel.properties"
        legacy_path.write_text(_LEGACY_PROPERTIES_TEXT, encoding="utf-8")

        with patch(f"{_CONVERTER}.prompt_service_credentials", return_value=_CREDENTIALS):
            toml_text = convert_legacy_config(legacy_path)

        service_config = tomllib.loads(toml_text)["testbench-defect-service"]
        assert service_config["client_class"] == EXCEL_CLIENT_CLASS

    def test_an_explicit_source_type_wins_over_the_extension(self, tmp_path) -> None:
        """A renamed wrapper file still converts once the format is named."""
        legacy_path = _write_legacy_conf(tmp_path, name="wrapper.txt")

        with (
            patch(f"{_CONVERTER}.prompt_service_credentials", return_value=_CREDENTIALS),
            patch(f"{_CONVERTER}.prompt_jira_auth_config", return_value=self._AUTH),
        ):
            toml_text = convert_legacy_config(legacy_path, source_type="jira")

        assert tomllib.loads(toml_text)["testbench-defect-service"]["client_class"] == (
            JIRA_CLIENT_CLASS
        )

    def test_an_undetectable_extension_asks_for_the_source_type(self, tmp_path) -> None:
        """Guessing the format would silently produce the wrong client."""
        legacy_path = _write_legacy_conf(tmp_path, name="wrapper.txt")

        with pytest.raises(ConfConversionError, match="source type"):
            convert_legacy_config(legacy_path)

    _AUTH: ClassVar[dict[str, Any]] = {"auth_type": "token", "token": "pat-123"}


@pytest.mark.unit
class TestUnusableLegacyFilesAreRejected:
    """A file the converter cannot read has to say where and why.

    The old message was pydantic-free but useless: `not enough values to unpack
    (expected 2, got 1)` named neither the file, the line nor the format mix-up that
    usually causes it.
    """

    def test_a_malformed_conf_line_names_the_file_and_the_line(self, tmp_path) -> None:
        legacy_path = tmp_path / "jira.conf"
        legacy_path.write_text(
            "wrapper.name: JiraWrapper\nthis line has no separator\n", encoding="utf-8"
        )

        with pytest.raises(ConfConversionError) as error:
            convert_legacy_config(legacy_path)

        assert "jira.conf line 2" in str(error.value)
        assert "this line has no separator" in str(error.value)

    def test_a_properties_file_read_as_jira_points_at_the_excel_type(self, tmp_path) -> None:
        """The `=` on the offending line is the giveaway, so say so."""
        legacy_path = tmp_path / "wrapper.txt"
        legacy_path.write_text(_LEGACY_PROPERTIES_TEXT, encoding="utf-8")

        with pytest.raises(ConfConversionError, match="--type excel"):
            convert_legacy_config(legacy_path, source_type="jira")

    def test_a_conf_file_read_as_excel_points_at_the_jira_type(self, tmp_path) -> None:
        legacy_path = _write_legacy_conf(tmp_path, name="wrapper.txt")

        with pytest.raises(ConfConversionError, match="--type jira"):
            convert_legacy_config(legacy_path, source_type="excel")

    def test_a_key_set_twice_to_different_values_is_rejected(self, tmp_path) -> None:
        """Silently keeping the last one migrates a setting the user never chose."""
        legacy_path = tmp_path / "jira.conf"
        legacy_path.write_text(
            "jira.baseUri: https://one.example.com\njira.baseUri: https://two.example.com\n",
            encoding="utf-8",
        )

        with pytest.raises(ConfConversionError) as error:
            convert_legacy_config(legacy_path)

        message = str(error.value)
        assert "jira.baseUri" in message
        assert "https://one.example.com" in message
        assert "https://two.example.com" in message

    def test_a_key_repeated_with_the_same_value_converts(self, tmp_path) -> None:
        """A duplicate that says the same thing twice is not a conflict."""
        legacy_path = tmp_path / "jira.conf"
        legacy_path.write_text(
            f"{_LEGACY_CONF_TEXT}jira.baseUri: {_SERVER_URL}\n", encoding="utf-8"
        )

        with (
            patch(f"{_CONVERTER}.prompt_service_credentials", return_value=_CREDENTIALS),
            patch(f"{_CONVERTER}.prompt_jira_auth_config", return_value=self._AUTH),
        ):
            toml_text = convert_legacy_config(legacy_path)

        client_config = tomllib.loads(toml_text)["testbench-defect-service"]["client_config"]
        assert client_config["server_url"] == _SERVER_URL

    _AUTH: ClassVar[dict[str, Any]] = {"auth_type": "token", "token": "pat-123"}


@pytest.mark.unit
class TestUnsupportedLegacyEntriesAreReported:
    """Both client models ignore what they do not know, so a legacy setting with no
    equivalent disappears into a migration that reports success. The keys that were left
    behind have to be named, or the user cannot tell a full migration from a partial one.
    """

    def test_legacy_conf_entries_with_no_equivalent_are_named(self, capsys) -> None:
        conf_data = {**_CONF_DATA, "jira.password": "secret", "wrapper.class": "com.example.Old"}

        generate_jira_base_toml(conf_data, dict(self._AUTH), _CREDENTIALS)

        output = capsys.readouterr().out
        assert "jira.password" in output
        assert "wrapper.class" in output

    def test_an_unsupported_entry_does_not_stop_the_conversion(self, capsys) -> None:
        properties = {**_EXCEL_PROPERTIES, "wrapper.someRetiredFlag": "true"}

        toml_text = generate_excel_base_toml(properties, _CREDENTIALS)

        assert "wrapper.someRetiredFlag" in capsys.readouterr().out
        client_config = tomllib.loads(toml_text)["testbench-defect-service"]["client_config"]
        assert client_config["excel_file_path"] == r"C:\defects"

    def test_a_fully_supported_legacy_file_reports_nothing(self, capsys) -> None:
        """The composite `.properties` keys are read by the model's own normalization
        rather than by an alias, so a naive alias comparison would report every one of
        them as lost."""
        generate_excel_base_toml(_EXCEL_PROPERTIES, _CREDENTIALS)

        assert "not carried over" not in capsys.readouterr().out

    def test_the_conf_keys_that_only_pre_fill_a_prompt_are_not_reported(self, capsys) -> None:
        """`jira.username` becomes the default of the username prompt, so it is carried
        over even though no model field reads it directly."""
        generate_jira_base_toml(
            {**_CONF_DATA, "jira.username": "someone"}, dict(self._AUTH), _CREDENTIALS
        )

        assert "jira.username" not in capsys.readouterr().out

    _AUTH: ClassVar[dict[str, Any]] = {"auth_type": "token", "token": "pat-123"}


@pytest.mark.unit
class TestTheUnsupportedReportIsVisible:
    """A dropped setting the user scrolls past is as good as one that was never reported."""

    def test_each_unsupported_key_is_listed_on_its_own_line(self, capsys) -> None:
        """A comma-separated run of keys is what makes a long list unreadable."""
        properties = {
            **_EXCEL_PROPERTIES,
            "wrapper.someRetiredFlag": "true",
            "wrapper.anotherRetiredFlag": "false",
        }

        generate_excel_base_toml(properties, _CREDENTIALS)

        lines = capsys.readouterr().out.splitlines()
        assert [line for line in lines if "wrapper.someRetiredFlag" in line] == [
            "  • wrapper.someRetiredFlag"
        ]
        assert [line for line in lines if "wrapper.anotherRetiredFlag" in line] == [
            "  • wrapper.anotherRetiredFlag"
        ]

    def test_the_report_is_framed_so_it_stands_out(self, capsys) -> None:
        generate_excel_base_toml({**_EXCEL_PROPERTIES, "wrapper.retired": "true"}, _CREDENTIALS)

        assert "═" * 60 in capsys.readouterr().out

    def test_a_cancelled_login_reports_nothing(self, capsys) -> None:
        """The report describes a configuration that is about to be written, so it must
        come after the last prompt that can still abort the migration - otherwise it
        scrolls off behind the login and describes a file that never appears."""
        questionary = _questionary_mock(texts=[None])

        with (
            patch(f"{_CONFIG_WIZARD}.questionary", questionary),
            pytest.raises(ConfConversionError, match="credentials"),
        ):
            generate_excel_base_toml({**_EXCEL_PROPERTIES, "wrapper.retired": "true"})

        assert "carried over" not in capsys.readouterr().out


@pytest.mark.unit
class TestConfKeysAreJudgedByTheKeyMapsNotTheModel:
    """A .conf entry never reaches the model - `fields_from_conf` picks the mapped keys and
    the rest is dropped - so what the model happens to call its own fields says nothing
    about whether a legacy key was carried over."""

    def test_a_conf_key_that_shares_a_model_field_name_is_still_reported(self, capsys) -> None:
        """`JiraDefectClientConfig` has a `readonly` field, but the .conf spelling that is
        read is `wrapper.readonly`, so a bare `readonly` entry is dropped."""
        generate_jira_base_toml({**_CONF_DATA, "readonly": "false"}, dict(self._AUTH), _CREDENTIALS)

        assert "readonly" in capsys.readouterr().out

    def test_the_mapped_spelling_is_not_reported(self, capsys) -> None:
        generate_jira_base_toml(
            {**_CONF_DATA, "wrapper.readonly": "false"}, dict(self._AUTH), _CREDENTIALS
        )

        assert "carried over" not in capsys.readouterr().out

    _AUTH: ClassVar[dict[str, Any]] = {"auth_type": "token", "token": "pat-123"}

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sanic.exceptions import InvalidUsage, NotFound, ServerError

from testbench_defect_service.clients.jsonl.client import JsonlDefectClient
from testbench_defect_service.clients.jsonl.config import (
    JsonlDefectClientConfig,
    PhaseCommands,
    ProjectConfig,
    SyncCommandConfig,
)
from testbench_defect_service.models.defects import (
    Defect,
    DefectID,
    DefectWithAttributes,
    DefectWithID,
    DefectWithLocalPk,
    ExtendedAttributes,
    KnownDefect,
    LocalSyncActions,
    Login,
    Protocol,
    ProtocolCode,
    ProtocolledString,
    RemoteSyncActions,
    Results,
    SyncContext,
    UserDefinedFieldProperties,
    ValueType,
)

PATCH_BASE = "testbench_defect_service.clients.jsonl.client"


@pytest.fixture
def defects_path(tmp_path: Path) -> Path:
    path = tmp_path / "defects"
    path.mkdir()
    return path


@pytest.fixture
def config(defects_path: Path) -> JsonlDefectClientConfig:
    return JsonlDefectClientConfig(
        defects_path=defects_path,
        control_fields={"status": ["Open", "Closed"], "priority": ["High", "Low"]},
    )


@pytest.fixture
def client(config: JsonlDefectClientConfig) -> JsonlDefectClient:
    return JsonlDefectClient(config)


@pytest.fixture
def sample_defect() -> Defect:
    return Defect(
        title="Sample",
        description="desc",
        status="Open",
        classification="Bug",
        priority="High",
        lastEdited=datetime(2024, 1, 1, tzinfo=timezone.utc),
        principal=Login(username="user", password="pass"),
    )


@pytest.fixture
def sample_defect_with_id(sample_defect: Defect) -> DefectWithID:
    return DefectWithID(**sample_defect.model_dump(), id=DefectID(root="DEF-001"))


@pytest.fixture
def sync_context() -> SyncContext:
    return SyncContext(iTBProject=None)


@pytest.fixture
def sync_type() -> str:
    return "scheduled"


def _make_defect_with_id(defect_id: str = "D-1") -> DefectWithID:
    return DefectWithID(
        id=DefectID(root=defect_id),
        title="T",
        status="Open",
        classification="Bug",
        priority="High",
        lastEdited=datetime(2024, 1, 1, tzinfo=timezone.utc),
        principal=Login(username="u", password="p"),
    )


def _make_known_defect(defect_id: str = "D-1") -> KnownDefect:
    return KnownDefect(
        id=DefectID(root=defect_id),
        localPk="lpk",
        title="T",
        status="Open",
        classification="Bug",
        priority="High",
        lastEdited=datetime(2024, 1, 1, tzinfo=timezone.utc),
        principal=Login(username="u", password="p"),
    )


@pytest.mark.unit
class TestCheckLogin:
    def test_project_dir_exists_returns_true(self, client: JsonlDefectClient, defects_path: Path):
        (defects_path / "myproj").mkdir()
        assert client.check_login("myproj") is True

    def test_project_dir_missing_returns_false(self, client: JsonlDefectClient):
        assert client.check_login("nonexistent") is False

    def test_no_project_defects_path_exists_returns_true(self, client: JsonlDefectClient):
        assert client.check_login(None) is True

    def test_no_project_defects_path_missing_returns_false(
        self, client: JsonlDefectClient, defects_path: Path
    ):
        defects_path.rmdir()
        assert client.check_login(None) is False


@pytest.mark.unit
class TestGetSettings:
    def test_returns_default_name_and_not_readonly(self, client: JsonlDefectClient):
        settings = client.get_settings()
        assert settings.name == "JSONL"
        assert settings.readonly is False

    def test_readonly_config_reflected_in_settings(self, defects_path: Path):
        config = JsonlDefectClientConfig(
            defects_path=defects_path, control_fields={}, readonly=True
        )
        assert JsonlDefectClient(config).get_settings().readonly is True

    def test_custom_name_and_description(self, defects_path: Path):
        config = JsonlDefectClientConfig(
            defects_path=defects_path,
            control_fields={},
            name="CustomName",
            description="Custom desc",
        )
        settings = JsonlDefectClient(config).get_settings()
        assert settings.name == "CustomName"
        assert settings.description == "Custom desc"


@pytest.mark.unit
class TestGetProjects:
    def test_returns_subdirectory_names(self, client: JsonlDefectClient, defects_path: Path):
        (defects_path / "projA").mkdir()
        (defects_path / "projB").mkdir()
        assert sorted(client.get_projects()) == ["projA", "projB"]

    def test_ignores_plain_files(self, client: JsonlDefectClient, defects_path: Path):
        (defects_path / "projA").mkdir()
        (defects_path / "readme.txt").write_text("x", encoding="utf-8")
        assert client.get_projects() == ["projA"]

    def test_empty_defects_path_returns_empty_list(self, client: JsonlDefectClient):
        assert client.get_projects() == []

    def test_defects_path_missing_returns_empty_list(
        self, client: JsonlDefectClient, defects_path: Path
    ):
        defects_path.rmdir()
        assert client.get_projects() == []


@pytest.mark.unit
class TestGetControlFields:
    def test_returns_global_control_fields(self, client: JsonlDefectClient):
        result = client.get_control_fields(None)
        assert result == {"status": ["Open", "Closed"], "priority": ["High", "Low"]}

    def test_returns_project_specific_fields(
        self, client: JsonlDefectClient, config: JsonlDefectClientConfig
    ):
        config.projects["proj"] = ProjectConfig(control_fields={"severity": ["Low", "High"]})
        assert client.get_control_fields("proj") == {"severity": ["Low", "High"]}

    def test_none_control_fields_returns_empty_dict(self, client: JsonlDefectClient):
        with patch.object(client, "_get_config_value", return_value=None):
            assert client.get_control_fields("proj") == {}

    def test_non_dict_raises_invalid_usage(self, client: JsonlDefectClient):
        with patch.object(client, "_get_config_value", return_value="not_a_dict"):  # noqa: SIM117
            with pytest.raises(InvalidUsage, match="must be a dictionary"):
                client.get_control_fields("proj")

    def test_field_values_not_list_raises_invalid_usage(self, client: JsonlDefectClient):
        with patch.object(client, "_get_config_value", return_value={"status": "Open"}):  # noqa: SIM117
            with pytest.raises(InvalidUsage, match="must have a list"):
                client.get_control_fields("proj")

    def test_numeric_values_normalized_to_strings(self, client: JsonlDefectClient):
        with patch.object(client, "_get_config_value", return_value={"priority": [1, 2, 3]}):
            result = client.get_control_fields("proj")
        assert result == {"priority": ["1", "2", "3"]}


@pytest.mark.unit
class TestGetDefects:
    def test_success_returns_defects(
        self,
        client: JsonlDefectClient,
        sample_defect_with_id: DefectWithID,
        sync_context: SyncContext,
    ):
        mock_files = [Path("/fake/defects.jsonl")]
        mock_defects = [sample_defect_with_id]
        with (
            patch(f"{PATCH_BASE}.find_defects_files", return_value=mock_files),
            patch(f"{PATCH_BASE}.parse_defects_from_file", return_value=mock_defects),
        ):
            result = client.get_defects("proj", sync_context)
        assert result.value == mock_defects

    def test_file_not_found_adds_project_not_found_error(
        self, client: JsonlDefectClient, sync_context: SyncContext
    ):
        with patch(f"{PATCH_BASE}.find_defects_files", side_effect=FileNotFoundError):
            result = client.get_defects("proj", sync_context)
        assert result.protocol.generalErrors
        assert result.protocol.generalErrors[0].code == ProtocolCode.PROJECT_NOT_FOUND

    def test_empty_file_list_adds_no_defect_found_error(
        self, client: JsonlDefectClient, sync_context: SyncContext
    ):
        with patch(f"{PATCH_BASE}.find_defects_files", return_value=[]):
            result = client.get_defects("proj", sync_context)
        assert result.protocol.generalErrors
        assert result.protocol.generalErrors[0].code == ProtocolCode.NO_DEFECT_FOUND


@pytest.mark.unit
class TestGetDefectsBatch:
    def test_success_returns_requested_defects(
        self,
        client: JsonlDefectClient,
        sample_defect_with_id: DefectWithID,
        sync_context: SyncContext,
    ):
        ids = [DefectID(root="DEF-001")]
        mock_files = [Path("/fake/defects.jsonl")]
        mock_defects = [sample_defect_with_id]
        with (
            patch(f"{PATCH_BASE}.find_defects_files", return_value=mock_files),
            patch(f"{PATCH_BASE}.parse_requested_defects", return_value=mock_defects),
            patch(f"{PATCH_BASE}.add_missing_defect_warnings"),
        ):
            result = client.get_defects_batch("proj", ids, sync_context)
        assert result.value == mock_defects

    def test_file_not_found_adds_project_not_found_error(
        self, client: JsonlDefectClient, sync_context: SyncContext
    ):
        with patch(f"{PATCH_BASE}.find_defects_files", side_effect=FileNotFoundError):
            result = client.get_defects_batch("proj", [DefectID(root="DEF-001")], sync_context)
        assert result.protocol.generalErrors is not None
        assert result.protocol.generalErrors[0].code == ProtocolCode.PROJECT_NOT_FOUND

    def test_empty_id_root_filtered_from_request_set(
        self, client: JsonlDefectClient, sync_context: SyncContext
    ):
        mock_files = [Path("/fake/defects.jsonl")]
        with (
            patch(f"{PATCH_BASE}.find_defects_files", return_value=mock_files),
            patch(f"{PATCH_BASE}.parse_requested_defects", return_value=[]) as mock_parse,
            patch(f"{PATCH_BASE}.add_missing_defect_warnings"),
        ):
            client.get_defects_batch("proj", [DefectID(root="")], sync_context)
        called_ids = mock_parse.call_args[0][1]
        assert called_ids == set()

    def test_missing_defects_trigger_warnings(
        self, client: JsonlDefectClient, sync_context: SyncContext
    ):
        ids = [DefectID(root="DEF-MISSING")]
        mock_files = [Path("/fake/defects.jsonl")]
        with (
            patch(f"{PATCH_BASE}.find_defects_files", return_value=mock_files),
            patch(f"{PATCH_BASE}.parse_requested_defects", return_value=[]),
            patch(f"{PATCH_BASE}.add_missing_defect_warnings") as mock_warn,
        ):
            client.get_defects_batch("proj", ids, sync_context)
        mock_warn.assert_called_once()


@pytest.mark.unit
class TestCreateDefect:
    def test_success_returns_protocolled_string(
        self,
        client: JsonlDefectClient,
        sample_defect: Defect,
        sync_context: SyncContext,
    ):
        mock_files = [Path("/fake/defects.jsonl")]
        mock_result = ProtocolledString(value="DEF-001", protocol=Protocol())
        with (
            patch.object(client, "_get_defect_files_or_raise", return_value=mock_files),
            patch(f"{PATCH_BASE}.append_defect_to_jsonl", return_value=mock_result),
        ):
            result = client.create_defect("proj", sample_defect, sync_context)
        assert result == mock_result

    def test_readonly_raises_invalid_usage(
        self, defects_path: Path, sample_defect: Defect, sync_context: SyncContext
    ):
        config = JsonlDefectClientConfig(
            defects_path=defects_path, control_fields={}, readonly=True
        )
        with pytest.raises(InvalidUsage):
            JsonlDefectClient(config).create_defect("proj", sample_defect, sync_context)

    def test_not_found_propagates(
        self, client: JsonlDefectClient, sample_defect: Defect, sync_context: SyncContext
    ):
        with (
            patch.object(client, "_get_defect_files_or_raise", side_effect=NotFound("not found")),
            pytest.raises(NotFound),
        ):
            client.create_defect("proj", sample_defect, sync_context)

    def test_os_error_raises_server_error(
        self, client: JsonlDefectClient, sample_defect: Defect, sync_context: SyncContext
    ):
        mock_files = [Path("/fake/defects.jsonl")]
        with (  # noqa: SIM117
            patch.object(client, "_get_defect_files_or_raise", return_value=mock_files),
            patch(f"{PATCH_BASE}.append_defect_to_jsonl", side_effect=OSError("disk full")),
        ):
            with pytest.raises(ServerError, match="Unable to write defect file"):
                client.create_defect("proj", sample_defect, sync_context)


@pytest.mark.unit
class TestUpdateDefect:
    def test_success_adds_success_entry(
        self, client: JsonlDefectClient, sample_defect: Defect, sync_context: SyncContext
    ):
        mock_files = [Path("/fake/defects.jsonl")]
        with (
            patch.object(client, "_get_defect_files_or_raise", return_value=mock_files),
            patch(f"{PATCH_BASE}.update_defect_in_list", return_value=([], True)),
            patch(f"{PATCH_BASE}.write_defects_to_file"),
        ):
            protocol = client.update_defect("proj", "DEF-001", sample_defect, sync_context)
        assert protocol.successes

    def test_readonly_raises_invalid_usage(
        self, defects_path: Path, sample_defect: Defect, sync_context: SyncContext
    ):
        config = JsonlDefectClientConfig(
            defects_path=defects_path, control_fields={}, readonly=True
        )
        with pytest.raises(InvalidUsage):
            JsonlDefectClient(config).update_defect("proj", "DEF-001", sample_defect, sync_context)

    def test_empty_defect_id_adds_warning(
        self, client: JsonlDefectClient, sample_defect: Defect, sync_context: SyncContext
    ):
        protocol = client.update_defect("proj", "", sample_defect, sync_context)
        assert protocol.warnings

    def test_writes_updated_defects_to_file(
        self, client: JsonlDefectClient, sample_defect: Defect, sync_context: SyncContext
    ):
        mock_files = [Path("/fake/defects.jsonl")]
        updated: list[DefectWithID] = []
        with (
            patch.object(client, "_get_defect_files_or_raise", return_value=mock_files),
            patch(f"{PATCH_BASE}.update_defect_in_list", return_value=(updated, True)),
            patch(f"{PATCH_BASE}.write_defects_to_file") as mock_write,
        ):
            client.update_defect("proj", "DEF-001", sample_defect, sync_context)
        mock_write.assert_called_once_with(mock_files[0], updated, "proj")


@pytest.mark.unit
class TestDeleteDefect:
    def test_success_adds_success_entry(
        self,
        client: JsonlDefectClient,
        sample_defect: Defect,
        sample_defect_with_id: DefectWithID,
        sync_context: SyncContext,
    ):
        mock_files = [Path("/fake/defects.jsonl")]
        with (
            patch.object(client, "_get_defect_files_or_raise", return_value=mock_files),
            patch(
                f"{PATCH_BASE}.remove_defect_from_list",
                return_value=([], sample_defect_with_id),
            ),
            patch(f"{PATCH_BASE}.write_defects_to_file"),
        ):
            protocol = client.delete_defect("proj", "DEF-001", sample_defect, sync_context)
        assert protocol.successes

    def test_readonly_raises_invalid_usage(
        self, defects_path: Path, sample_defect: Defect, sync_context: SyncContext
    ):
        config = JsonlDefectClientConfig(
            defects_path=defects_path, control_fields={}, readonly=True
        )
        with pytest.raises(InvalidUsage):
            JsonlDefectClient(config).delete_defect("proj", "DEF-001", sample_defect, sync_context)

    def test_empty_defect_id_adds_general_error(
        self, client: JsonlDefectClient, sample_defect: Defect, sync_context: SyncContext
    ):
        protocol = client.delete_defect("proj", "", sample_defect, sync_context)
        assert protocol.generalErrors

    def test_defect_not_found_adds_general_error(
        self, client: JsonlDefectClient, sample_defect: Defect, sync_context: SyncContext
    ):
        mock_files = [Path("/fake/defects.jsonl")]
        with (
            patch.object(client, "_get_defect_files_or_raise", return_value=mock_files),
            patch(f"{PATCH_BASE}.remove_defect_from_list", return_value=([], None)),
        ):
            protocol = client.delete_defect("proj", "DEF-001", sample_defect, sync_context)
        assert protocol.generalErrors

    def test_writes_remaining_defects_to_file(
        self,
        client: JsonlDefectClient,
        sample_defect: Defect,
        sample_defect_with_id: DefectWithID,
        sync_context: SyncContext,
    ):
        mock_files = [Path("/fake/defects.jsonl")]
        remaining: list[DefectWithID] = []
        with (
            patch.object(client, "_get_defect_files_or_raise", return_value=mock_files),
            patch(
                f"{PATCH_BASE}.remove_defect_from_list",
                return_value=(remaining, sample_defect_with_id),
            ),
            patch(f"{PATCH_BASE}.write_defects_to_file") as mock_write,
        ):
            client.delete_defect("proj", "DEF-001", sample_defect, sync_context)
        mock_write.assert_called_once_with(mock_files[0], remaining, "proj")


@pytest.mark.unit
class TestGetDefectExtended:
    def test_success_delegates_to_build_defect_with_attributes(
        self,
        client: JsonlDefectClient,
        sample_defect_with_id: DefectWithID,
        sync_context: SyncContext,
    ):
        mock_files = [Path("/fake/defects.jsonl")]
        expected = DefectWithAttributes(
            **sample_defect_with_id.model_dump(), attributes=ExtendedAttributes()
        )
        with (
            patch.object(client, "_get_defect_files_or_raise", return_value=mock_files),
            patch(f"{PATCH_BASE}.find_defect_by_id", return_value=sample_defect_with_id),
            patch.object(client, "_build_defect_with_attributes", return_value=expected),
        ):
            result = client.get_defect_extended("proj", "DEF-001", sync_context)
        assert result == expected

    def test_build_called_with_correct_args(
        self,
        client: JsonlDefectClient,
        sample_defect_with_id: DefectWithID,
        sync_context: SyncContext,
    ):
        mock_files = [Path("/fake/defects.jsonl")]
        mock_result = DefectWithAttributes(
            **sample_defect_with_id.model_dump(), attributes=ExtendedAttributes()
        )
        with (
            patch.object(client, "_get_defect_files_or_raise", return_value=mock_files),
            patch(f"{PATCH_BASE}.find_defect_by_id", return_value=sample_defect_with_id),
            patch.object(
                client, "_build_defect_with_attributes", return_value=mock_result
            ) as mock_build,
        ):
            client.get_defect_extended("proj", "DEF-001", sync_context)
        mock_build.assert_called_once_with(defect=sample_defect_with_id, project="proj")


@pytest.mark.unit
class TestGetUserDefinedAttributes:
    def test_missing_udf_file_returns_empty_list(
        self, client: JsonlDefectClient, defects_path: Path
    ):
        assert client.get_user_defined_attributes("proj") == []

    def test_reads_udfs_from_project_directory(self, client: JsonlDefectClient, defects_path: Path):
        proj_dir = defects_path / "proj"
        proj_dir.mkdir()
        udf_data = [{"name": "MyField", "valueType": "STRING"}]
        (proj_dir / "UserDefinedAttributes.json").write_text(json.dumps(udf_data), encoding="utf-8")
        with patch(f"{PATCH_BASE}.validate_udf_structure"):
            result = client.get_user_defined_attributes("proj")
        assert len(result) == 1
        assert result[0].name == "MyField"
        assert result[0].valueType == ValueType.STRING

    def test_reads_udfs_from_root_when_no_project(
        self, client: JsonlDefectClient, defects_path: Path
    ):
        udf_data = [{"name": "GlobalField", "valueType": "BOOLEAN"}]
        (defects_path / "UserDefinedAttributes.json").write_text(
            json.dumps(udf_data), encoding="utf-8"
        )
        with patch(f"{PATCH_BASE}.validate_udf_structure"):
            result = client.get_user_defined_attributes(None)
        assert result[0].name == "GlobalField"
        assert result[0].valueType == ValueType.BOOLEAN

    def test_no_project_and_missing_root_udf_returns_empty(self, client: JsonlDefectClient):
        assert client.get_user_defined_attributes(None) == []

    def test_optional_fields_populated_from_file(
        self, client: JsonlDefectClient, defects_path: Path
    ):
        proj_dir = defects_path / "proj"
        proj_dir.mkdir()
        udf_data = [
            {
                "name": "Flag",
                "valueType": "BOOLEAN",
                "mustField": True,
                "booleanValue": False,
            }
        ]
        (proj_dir / "UserDefinedAttributes.json").write_text(json.dumps(udf_data), encoding="utf-8")
        with patch(f"{PATCH_BASE}.validate_udf_structure"):
            result = client.get_user_defined_attributes("proj")
        assert result[0].mustField is True
        assert result[0].booleanValue is False


@pytest.mark.unit
class TestSyncHooks:
    def test_post_projects_sync_before_delegates_to_execute_hook(
        self, client: JsonlDefectClient, sync_context: SyncContext, sync_type: str
    ):
        expected = Protocol()
        with patch.object(client, "_execute_sync_hook", return_value=expected) as mock_hook:
            result = client.before_sync("proj", sync_type, sync_context)
        mock_hook.assert_called_once_with("proj", sync_type, "presync")
        assert result is expected

    def test_post_projects_sync_after_delegates_to_execute_hook(
        self, client: JsonlDefectClient, sync_context: SyncContext, sync_type: str
    ):
        expected = Protocol()
        with patch.object(client, "_execute_sync_hook", return_value=expected) as mock_hook:
            result = client.after_sync("proj", sync_type, sync_context)
        mock_hook.assert_called_once_with("proj", sync_type, "postsync")
        assert result is expected


@pytest.mark.unit
class TestSupportsChangesTimestamps:
    def test_returns_true_by_default(self, client: JsonlDefectClient):
        assert client.supports_changes_timestamps() is True

    def test_returns_false_when_configured(self, defects_path: Path):
        config = JsonlDefectClientConfig(
            defects_path=defects_path,
            control_fields={},
            supports_changes_timestamps=False,
        )
        assert JsonlDefectClient(config).supports_changes_timestamps() is False


@pytest.mark.unit
class TestCorrectSyncResults:
    def test_valid_create_actions_kept(self, client: JsonlDefectClient):
        defect = _make_defect_with_id("D-1")
        body = Results(local=LocalSyncActions(create=[defect]))
        with patch(f"{PATCH_BASE}.validate_defect", return_value=True):
            result = client.correct_sync_results("proj", body)
        assert result.local is not None
        assert result.local.create is not None
        assert len(result.local.create) == 1

    def test_invalid_create_actions_filtered(self, client: JsonlDefectClient):
        defect = _make_defect_with_id("D-1")
        body = Results(local=LocalSyncActions(create=[defect]))
        with patch(f"{PATCH_BASE}.validate_defect", return_value=False):
            result = client.correct_sync_results("proj", body)
        assert result.local is not None
        assert result.local.create == []

    def test_none_local_and_remote_skipped(self, client: JsonlDefectClient):
        body = Results(local=None, remote=None)
        result = client.correct_sync_results("proj", body)
        assert result.local is None
        assert result.remote is None

    def test_original_body_not_mutated(self, client: JsonlDefectClient):
        defect = _make_defect_with_id("D-1")
        body = Results(local=LocalSyncActions(create=[defect]))
        with patch(f"{PATCH_BASE}.validate_defect", return_value=False):
            client.correct_sync_results("proj", body)
        assert body.local is not None
        assert body.local.create is not None
        assert len(body.local.create) == 1

    def test_remote_actions_also_corrected(self, client: JsonlDefectClient):
        defect = DefectWithLocalPk(
            localPk="lpk",
            title="T",
            status="Open",
            classification="Bug",
            priority="High",
            lastEdited=datetime(2024, 1, 1, tzinfo=timezone.utc),
            principal=Login(username="u", password="p"),
        )
        body = Results(remote=RemoteSyncActions(create=[defect]))
        with patch(f"{PATCH_BASE}.validate_defect", return_value=False):
            result = client.correct_sync_results("proj", body)
        assert result.remote is not None
        assert result.remote.create == []


@pytest.mark.unit
class TestEnsureWritable:
    def test_readonly_raises_invalid_usage(self, defects_path: Path):
        config = JsonlDefectClientConfig(
            defects_path=defects_path, control_fields={}, readonly=True
        )
        with pytest.raises(InvalidUsage, match="read-only mode"):
            JsonlDefectClient(config)._ensure_writable()

    def test_writable_does_not_raise(self, client: JsonlDefectClient):
        client._ensure_writable()


@pytest.mark.unit
class TestGetDefectFilesOrRaise:
    def test_returns_files_on_success(self, client: JsonlDefectClient):
        mock_files = [Path("/fake/defects.jsonl")]
        with patch(f"{PATCH_BASE}.find_defects_files", return_value=mock_files):
            assert client._get_defect_files_or_raise("proj") == mock_files

    def test_file_not_found_raises_not_found(self, client: JsonlDefectClient):
        with patch(f"{PATCH_BASE}.find_defects_files", side_effect=FileNotFoundError):  # noqa: SIM117
            with pytest.raises(NotFound, match="No defect files found"):
                client._get_defect_files_or_raise("proj")


@pytest.mark.unit
class TestBuildDefectWithAttributes:
    def test_direct_attributes_extracted(
        self, client: JsonlDefectClient, sample_defect_with_id: DefectWithID
    ):
        # Default attributes are ["title", "status"]
        result = client._build_defect_with_attributes(sample_defect_with_id, "proj")
        attrs = result.attributes.model_dump(exclude_none=True)
        assert attrs.get("title") == "Sample"
        assert attrs.get("status") == "Open"

    def test_udf_attribute_extracted(
        self, client: JsonlDefectClient, sample_defect_with_id: DefectWithID
    ):
        sample_defect_with_id.userDefinedFields = [
            UserDefinedFieldProperties(name="myUDF", value="UDFvalue")
        ]
        with patch.object(client, "_get_config_value", return_value=["myUDF"]):
            result = client._build_defect_with_attributes(sample_defect_with_id, "proj")
        assert result.attributes.model_dump(exclude_none=True).get("myUDF") == "UDFvalue"

    def test_missing_attribute_not_included(
        self, client: JsonlDefectClient, sample_defect_with_id: DefectWithID
    ):
        with patch.object(client, "_get_config_value", return_value=["nonexistent_field"]):
            result = client._build_defect_with_attributes(sample_defect_with_id, "proj")
        assert "nonexistent_field" not in result.attributes.model_dump(exclude_none=True)

    def test_returns_defect_with_attributes_type(
        self, client: JsonlDefectClient, sample_defect_with_id: DefectWithID
    ):
        result = client._build_defect_with_attributes(sample_defect_with_id, "proj")
        assert isinstance(result, DefectWithAttributes)


@pytest.mark.unit
class TestExecuteSyncHook:
    def test_no_command_configured_returns_success_protocol(
        self, client: JsonlDefectClient, sync_type: str
    ):
        protocol = client._execute_sync_hook("proj", sync_type, "presync")
        assert protocol.successes

    def test_unsupported_file_extension_returns_empty_protocol(
        self, defects_path: Path, sync_type: str
    ):
        script = defects_path / "hook.py"
        script.write_text("pass", encoding="utf-8")
        config = JsonlDefectClientConfig(
            defects_path=defects_path,
            control_fields={},
            commands=PhaseCommands(presync=SyncCommandConfig(scheduled=str(script))),
        )
        protocol = JsonlDefectClient(config)._execute_sync_hook("proj", sync_type, "presync")
        assert not protocol.successes
        assert not protocol.generalErrors

    def test_command_file_missing_returns_empty_protocol(self, defects_path: Path, sync_type: str):
        nonexistent = defects_path / "missing.sh"
        config = JsonlDefectClientConfig(
            defects_path=defects_path,
            control_fields={},
            commands=PhaseCommands(presync=SyncCommandConfig(scheduled=str(nonexistent))),
        )
        protocol = JsonlDefectClient(config)._execute_sync_hook("proj", sync_type, "presync")
        assert not protocol.successes
        assert not protocol.generalErrors

    def test_successful_execution_adds_success(self, defects_path: Path, sync_type: str):
        script = defects_path / "hook.sh"
        script.write_text("#!/bin/sh", encoding="utf-8")
        config = JsonlDefectClientConfig(
            defects_path=defects_path,
            control_fields={},
            commands=PhaseCommands(presync=SyncCommandConfig(scheduled=str(script))),
        )
        with patch(f"{PATCH_BASE}.subprocess.run"):
            protocol = JsonlDefectClient(config)._execute_sync_hook("proj", sync_type, "presync")
        assert protocol.successes

    def test_called_process_error_adds_general_error(self, defects_path: Path, sync_type: str):
        script = defects_path / "hook.sh"
        script.write_text("#!/bin/sh", encoding="utf-8")
        config = JsonlDefectClientConfig(
            defects_path=defects_path,
            control_fields={},
            commands=PhaseCommands(presync=SyncCommandConfig(scheduled=str(script))),
        )
        with patch(
            f"{PATCH_BASE}.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "cmd"),
        ):
            protocol = JsonlDefectClient(config)._execute_sync_hook("proj", sync_type, "presync")
        assert protocol.generalErrors

    def test_os_error_adds_general_error(self, defects_path: Path, sync_type: str):
        script = defects_path / "hook.sh"
        script.write_text("#!/bin/sh", encoding="utf-8")
        config = JsonlDefectClientConfig(
            defects_path=defects_path,
            control_fields={},
            commands=PhaseCommands(presync=SyncCommandConfig(scheduled=str(script))),
        )
        with patch(f"{PATCH_BASE}.subprocess.run", side_effect=OSError("permission denied")):
            protocol = JsonlDefectClient(config)._execute_sync_hook("proj", sync_type, "presync")
        assert protocol.generalErrors

    def test_postsync_hook_type_uses_postsync_commands(self, defects_path: Path, sync_type: str):
        script = defects_path / "hook.sh"
        script.write_text("#!/bin/sh", encoding="utf-8")
        config = JsonlDefectClientConfig(
            defects_path=defects_path,
            control_fields={},
            commands=PhaseCommands(postsync=SyncCommandConfig(scheduled=str(script))),
        )
        with patch(f"{PATCH_BASE}.subprocess.run"):
            protocol = JsonlDefectClient(config)._execute_sync_hook("proj", sync_type, "postsync")
        assert protocol.successes


@pytest.mark.unit
class TestValidateAndFilterActions:
    def test_valid_create_actions_kept(self, client: JsonlDefectClient):
        defect = _make_defect_with_id("D-1")
        actions = LocalSyncActions(create=[defect])
        with patch(f"{PATCH_BASE}.validate_defect", return_value=True):
            client._validate_and_filter_actions(actions, "proj")
        assert actions.create is not None
        assert len(actions.create) == 1

    def test_invalid_create_actions_filtered(self, client: JsonlDefectClient):
        defect = _make_defect_with_id("D-1")
        actions = LocalSyncActions(create=[defect])
        with patch(f"{PATCH_BASE}.validate_defect", return_value=False):
            client._validate_and_filter_actions(actions, "proj")
        assert actions.create == []

    def test_valid_update_actions_kept(self, client: JsonlDefectClient):
        defect = _make_known_defect("D-1")
        actions = LocalSyncActions(update=[defect])
        with patch(f"{PATCH_BASE}.validate_defect", return_value=True):
            client._validate_and_filter_actions(actions, "proj")
        assert actions.update is not None
        assert len(actions.update) == 1

    def test_delete_actions_copied_regardless_of_validity(self, client: JsonlDefectClient):
        defect = _make_known_defect("D-1")
        actions = LocalSyncActions(delete=[defect])
        with patch(f"{PATCH_BASE}.validate_defect", return_value=False):
            client._validate_and_filter_actions(actions, "proj")
        assert actions.delete == [defect]

    def test_empty_actions_unchanged(self, client: JsonlDefectClient):
        actions = LocalSyncActions()
        client._validate_and_filter_actions(actions, "proj")
        assert actions.create == []
        assert actions.delete is None


@pytest.mark.unit
class TestGetConfigValue:
    def test_project_specific_value_returned_when_set(
        self, client: JsonlDefectClient, config: JsonlDefectClientConfig
    ):
        config.projects["proj"] = ProjectConfig(control_fields={"severity": ["Low", "High"]})
        result = client._get_config_value("control_fields", project="proj")
        assert result == {"severity": ["Low", "High"]}

    def test_global_fallback_when_project_attr_is_none(
        self, client: JsonlDefectClient, config: JsonlDefectClientConfig
    ):
        config.projects["proj"] = ProjectConfig(control_fields=None)
        result = client._get_config_value("control_fields", project="proj")
        assert result == {"status": ["Open", "Closed"], "priority": ["High", "Low"]}

    def test_global_value_returned_when_no_project(self, client: JsonlDefectClient):
        result = client._get_config_value("control_fields")
        assert result == {"status": ["Open", "Closed"], "priority": ["High", "Low"]}

    def test_unknown_project_falls_back_to_global(self, client: JsonlDefectClient):
        result = client._get_config_value("control_fields", project="unknown")
        assert result == {"status": ["Open", "Closed"], "priority": ["High", "Low"]}

    def test_readonly_from_project_config(
        self, client: JsonlDefectClient, config: JsonlDefectClientConfig
    ):
        config.projects["proj"] = ProjectConfig(readonly=True)
        assert client._get_config_value("readonly", project="proj") is True

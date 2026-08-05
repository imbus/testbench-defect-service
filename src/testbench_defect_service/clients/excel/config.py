import re
from contextlib import suppress
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.fields import FieldInfo

from testbench_defect_service.log import logger
from testbench_defect_service.models.defects import ValueType


def _split_csv(raw_value: Any) -> list[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    return [part.strip() for part in str(raw_value).split(",") if part.strip()]


def _normalize_file_type(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    if not normalized.startswith("."):
        normalized = f".{normalized}"
    return normalized


def _normalize_control_field_name(name: str) -> str:
    normalized_name = name.strip()
    if normalized_name == "class":
        return "classification"
    return normalized_name


def _parse_legacy_control_fields(data: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw_name in _split_csv(data.get("controlFields")):
        column_number = data.get(f"{raw_name}.columnNo")
        if column_number in (None, ""):
            continue
        result.append(
            {
                "name": _normalize_control_field_name(raw_name),
                "column_number": column_number,
                "values": _split_csv(data.get(f"{raw_name}.value")),
            }
        )
    return result


def _parse_legacy_transitions(data: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for key in sorted(data):
        if key.endswith(".transition.number"):
            continue
        match = re.fullmatch(r"(.+)\.transition\d+", key)
        if not match:
            continue
        raw_transition = str(data[key]).strip()
        if "-" not in raw_transition:
            continue
        from_state, to_state = raw_transition.split("-", 1)
        field_name = _normalize_control_field_name(match.group(1))
        result.setdefault(field_name, []).append(
            {"from_state": from_state.strip(), "to_state": to_state.strip()}
        )
    return result


def _attach_legacy_transitions(
    normalized: dict[str, Any], legacy_transitions: dict[str, list[dict[str, str]]]
) -> None:
    control_fields = normalized.get("control_fields") or []
    by_name = {
        field["name"]: field
        for field in control_fields
        if isinstance(field, dict) and "name" in field
    }
    for field_name, transitions in legacy_transitions.items():
        target = by_name.get(field_name)
        if target is None:
            logger.warning(
                "Ignoring legacy transitions for '%s': not configured as a control field.",
                field_name,
            )
            continue
        if not target.get("transitions"):
            target["transitions"] = transitions


def _parse_legacy_udfs(data: dict[str, Any]) -> list[dict[str, Any]]:
    indices: set[int] = set()
    udf_count = data.get("udf.attr.number")
    if udf_count not in (None, ""):
        with suppress(ValueError):
            indices.update(range(1, int(str(udf_count)) + 1))

    for key in data:
        match = re.fullmatch(r"udf\.attr(\d+)\..+", key)
        if match:
            indices.add(int(match.group(1)))

    result: list[dict[str, Any]] = []
    for idx in sorted(indices):
        prefix = f"udf.attr{idx}"
        name = data.get(f"{prefix}.name")
        column = data.get(f"{prefix}.column")
        if name in (None, "") or column in (None, ""):
            continue
        result.append(
            {
                "name": name,
                "column": column,
                "type": data.get(f"{prefix}.type", ValueType.STRING),
                "required": data.get(f"{prefix}.required", False),
                "value": data.get(f"{prefix}.value"),
                "trueValue": data.get(f"{prefix}.trueValue"),
                "falseValue": data.get(f"{prefix}.falseValue") or data.get(f"{prefix}.falsevalue"),
            }
        )
    return result


def _normalize_legacy_excel_config(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)

    legacy_scalar_fields = {
        "systemName": "system_name",
        "excelFilePath": "excel_file_path",
        "worksheetName": "worksheet_name",
        "fileType": "file_type",
        "simpleDateFormat": "simple_date_format",
        "defects.header.line": "defects_data_header_line",
        "defects.data.startingLine": "defects_data_starting_line",
        "separator": "separator",
        "defect.id.columnNo": "id_column_no",
        "defect.title.columnNo": "title_column_no",
        "defect.references.columnNo": "references_column_no",
        "defect.discoverer.columnNo": "discoverer_column_no",
        "defect.lastedited.columnNo": "lastedit_column_no",
        "defect.description.columnNo": "description_column_no",
        "defect.references.separator": "references_separator",
        "defect.id.prefix": "id_prefix",
        "defect.id.startingValue": "defect_id_starting_value",
        "defect.id.digitNumber": "defect_id_digit_numbers",
        "bufferCleanupIntervalMinutes": "buffer_cleanup_interval_minutes",
        "bufferMaxAgeMinutes": "buffer_max_age_minutes",
        "bufferMaxSizeMiB": "buffer_max_size_mib",
    }
    for source_key, target_key in legacy_scalar_fields.items():
        if target_key not in normalized and source_key in data:
            normalized[target_key] = data[source_key]

    if "control_fields" not in normalized:
        control_fields = _parse_legacy_control_fields(data)
        if control_fields:
            normalized["control_fields"] = control_fields

    legacy_transitions = _parse_legacy_transitions(data)
    if legacy_transitions:
        _attach_legacy_transitions(normalized, legacy_transitions)

    if "udfs" not in normalized:
        udfs = _parse_legacy_udfs(data)
        if udfs:
            normalized["udfs"] = udfs

    return normalized


class Transition(BaseModel):
    from_state: str
    to_state: str


class ControlFields(BaseModel):
    name: str
    column_number: int
    values: list[str] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: Any) -> str:
        return _normalize_control_field_name(str(value))

    @model_validator(mode="after")
    def check_transitions_against_values(self) -> "ControlFields":
        if not self.values:
            return self
        for transition in self.transitions:
            for role, state in (
                ("from_state", transition.from_state),
                ("to_state", transition.to_state),
            ):
                if state not in self.values:
                    raise ValueError(
                        f"control field '{self.name}': transition {role} '{state}' is not "
                        f"one of its values ({', '.join(self.values)})"
                    )
        return self


class UserDefiendAttributes(BaseModel):
    name: str
    column: int
    type: ValueType
    required: bool = False
    value: str | None = None
    trueValue: str | None = None
    falseValue: str | None = Field(
        default=None,
        validation_alias=AliasChoices("falseValue", "falsevalue"),
    )

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value: Any) -> ValueType | Any:
        if value in (ValueType.STRING, "STRING", "string", 0, "0"):
            return ValueType.STRING
        if value in (ValueType.BOOLEAN, "BOOLEAN", "boolean", 2, "2"):
            return ValueType.BOOLEAN
        return value


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    readonly: bool | None = None
    worksheet_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("worksheet_name", "worksheetName"),
        description="Name of the worksheet in the Excel file that contains the defects data.",
    )
    file_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("file_type", "fileType"),
        description="Type of the Excel file (e.g., '.xlsx', '.xls', '.csv', '.txt').",
    )
    simple_date_format: str | None = Field(
        default=None,
        validation_alias=AliasChoices("simple_date_format", "simpleDateFormat"),
        description="Date format used in the Excel file (e.g., 'yyyy-MM-dd').",
    )

    @field_validator("file_type", mode="before")
    @classmethod
    def normalize_file_type(cls, value: Any) -> str | None:
        return _normalize_file_type(value)

    defects_data_header_line: int | None = Field(
        default=None,
        validation_alias=AliasChoices("defects_data_header_line", "defects.header.line"),
        description="Line number in the Excel file where the table header is located.",
    )
    defects_data_starting_line: int | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "defects_data_starting_line",
            "defects.data.startingLine",
        ),
        description="Line number in the Excel file where the defects data starts.",
    )

    separator: str | None = Field(
        default=None,
        validation_alias=AliasChoices("separator", "separator"),
        description="Character used to separate values in the file (e.g., ',', ';', '\\t').",
    )
    control_fields: list[ControlFields] | None = Field(
        default=None, description="List of control fields for this project."
    )

    id_column_no: int | None = Field(
        default=None,
        validation_alias=AliasChoices("id_column_no", "defect.id.columnNo"),
        description="Column number in the Excel file that contains the defect ID.",
    )
    title_column_no: int | None = Field(
        default=None,
        validation_alias=AliasChoices("title_column_no", "defect.title.columnNo"),
        description="Column number in the Excel file that contains the defect title.",
    )
    references_column_no: int | None = Field(
        default=None,
        validation_alias=AliasChoices("references_column_no", "defect.references.columnNo"),
        description="Column number in the Excel file that contains the defect references.",
    )
    discoverer_column_no: int | None = Field(
        default=None,
        validation_alias=AliasChoices("discoverer_column_no", "defect.discoverer.columnNo"),
        description="Column number in the Excel file that contains the defect discoverer.",
    )
    lastedit_column_no: int | None = Field(
        default=None,
        validation_alias=AliasChoices("lastedit_column_no", "defect.lastedit.columnNo"),
        description="Column number in the Excel file that contains the defect last edit.",
    )
    description_column_no: int | None = Field(
        default=None,
        validation_alias=AliasChoices("description_column_no", "defect.description.columnNo"),
        description="Column number in the Excel file that contains the defect description.",
    )

    references_separator: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "references_separator",
            "defect.references.separator",
        ),
        description="Character used to separate multiple references in the references column.",
    )
    attributes: list[str] | None = Field(None, description="Attributes for this project")
    id_prefix: str | None = Field(
        default=None,
        validation_alias=AliasChoices("id_prefix", "defect.id.prefix"),
        description="Prefix used for defect IDs in this project.",
    )
    defect_id_starting_value: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "defect_id_starting_value",
            "defect.id.startingValue",
        ),
        description="Starting value for defect IDs in this project.",
    )
    defect_id_digit_numbers: int | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "defect_id_digit_numbers",
            "defect.id.digitNumber",
        ),
        description="Number of digits for defect IDs in this project.",
    )

    transitions: list[Transition] | None = Field(
        default=None, description="List of state transitions for defects in this project."
    )
    udfs: list[UserDefiendAttributes] | None = Field(
        default=None,
        description="List of user-defined attributes for defects in this project.",
    )

    buffer_cleanup_interval_minutes: float | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "buffer_cleanup_interval_minutes",
            "bufferCleanupIntervalMinutes",
        ),
        description="Interval in minutes for cleaning up the buffer for this project.",
    )
    buffer_max_age_minutes: float | None = Field(
        default=None,
        validation_alias=AliasChoices("buffer_max_age_minutes", "bufferMaxAgeMinutes"),
        description="Maximum age in minutes for the buffer for this project.",
    )
    buffer_max_size_mib: float | None = Field(
        default=None,
        validation_alias=AliasChoices("buffer_max_size_mib", "bufferMaxSizeMiB"),
        description="Maximum size in MiB for the buffer for this project.",
    )

    @property
    def column_settings(self) -> dict[str, FieldInfo]:
        return {
            field_name: field_info
            for field_name, field_info in self.__class__.model_fields.items()
            if field_name.endswith("_column_no")
        }


class ExcelDefectClientConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    system_name: str = Field(
        default="DefectService",
        validation_alias=AliasChoices("system_name", "systemName"),
        description="Name of the defect management system.",
    )
    readonly: bool = Field(
        default=False,
        validation_alias=AliasChoices("readonly", "readOnly"),
        description="Indicates if the Excel file is read-only.",
    )
    excel_file_path: Path = Field(
        validation_alias=AliasChoices("excel_file_path", "excelFilePath"),
        description="Path to the Excel file containing defect data.",
    )
    worksheet_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("worksheet_name", "worksheetName"),
        description="Name of the worksheet in the Excel file.",
    )

    file_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("file_type", "fileType"),
        description="Type of the Excel file (e.g., '.xlsx', '.xls', '.csv', '.txt').",
    )
    simple_date_format: str | None = Field(
        default=None,
        validation_alias=AliasChoices("simple_date_format", "simpleDateFormat"),
        description="Date format used in the Excel file (e.g., 'yyyy-MM-dd').",
    )

    @field_validator("file_type", mode="before")
    @classmethod
    def normalize_file_type(cls, value: Any) -> str | None:
        return _normalize_file_type(value)

    defects_data_header_line: int = Field(
        default=1,
        validation_alias=AliasChoices("defects_data_header_line", "defects.header.line"),
        description="Line number in the Excel file where the table header is located.",
    )
    defects_data_starting_line: int = Field(
        default=2,
        validation_alias=AliasChoices(
            "defects_data_starting_line",
            "defects.data.startingLine",
        ),
        description="Line number in the Excel file where the defect data starts.",
    )

    separator: str | None = Field(
        default=None,
        validation_alias=AliasChoices("separator", "separator"),
        description="Separator used in the file.",
    )
    control_fields: list[ControlFields] = Field(
        default_factory=list, description="List of control fields."
    )

    id_column_no: int = Field(
        default=1,
        validation_alias=AliasChoices("id_column_no", "defect.id.columnNo"),
        description="Column number in the Excel file that contains the defect ID.",
    )
    title_column_no: int = Field(
        default=2,
        validation_alias=AliasChoices("title_column_no", "defect.title.columnNo"),
        description="Column number in the Excel file that contains the defect title.",
    )
    references_column_no: int = Field(
        default=3,
        validation_alias=AliasChoices("references_column_no", "defect.references.columnNo"),
        description="Column number in the Excel file that contains the defect references.",
    )
    discoverer_column_no: int = Field(
        default=4,
        validation_alias=AliasChoices("discoverer_column_no", "defect.discoverer.columnNo"),
        description="Column number in the Excel file that contains the defect discoverer.",
    )
    lastedit_column_no: int = Field(
        default=5,
        validation_alias=AliasChoices("lastedit_column_no", "defect.lastedit.columnNo"),
        description="Column number in the Excel file that contains the defect last edit.",
    )
    description_column_no: int = Field(
        default=6,
        validation_alias=AliasChoices("description_column_no", "defect.description.columnNo"),
        description="Column number in the Excel file that contains the defect description.",
    )

    references_separator: str = Field(
        default=",",
        validation_alias=AliasChoices(
            "references_separator",
            "defect.references.separator",
        ),
        description="Character used to separate multiple references in the references column.",
    )
    id_prefix: str = Field(
        default="BUG",
        validation_alias=AliasChoices("id_prefix", "defect.id.prefix"),
        description="Prefix used for defect IDs in this project.",
    )
    defect_id_starting_value: str = Field(
        default="1",
        validation_alias=AliasChoices("defect_id_starting_value", "defect.id.startingValue"),
        description="Starting value for defect IDs in this project.",
    )
    defect_id_digit_numbers: int = Field(
        default=4,
        validation_alias=AliasChoices("defect_id_digit_numbers", "defect.id.digitNumber"),
        description="Number of digits for defect IDs in this project.",
    )

    attributes: list[str] = Field(
        default_factory=lambda: ["title", "status", "isOpen"],
        description="Fields from Excel to display in the extended defect view.",
    )

    transitions: list[Transition] = Field(
        default_factory=list,
        description="List of state transitions for defects.",
    )
    udfs: list[UserDefiendAttributes] = Field(
        default_factory=list, description="List of user-defined attributes for defects."
    )
    projects: dict[str, ProjectConfig] = Field(
        default_factory=dict,
        description="Dictionary of project configurations, keyed by project name.",
    )

    buffer_cleanup_interval_minutes: float = Field(
        default=1.0,
        validation_alias=AliasChoices(
            "buffer_cleanup_interval_minutes",
            "bufferCleanupIntervalMinutes",
        ),
    )
    buffer_max_age_minutes: float = Field(
        default=1440.0,
        validation_alias=AliasChoices("buffer_max_age_minutes", "bufferMaxAgeMinutes"),
    )
    buffer_max_size_mib: float = Field(
        default=1024.0,
        validation_alias=AliasChoices("buffer_max_size_mib", "bufferMaxSizeMiB"),
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_properties(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        return _normalize_legacy_excel_config(data)

    @property
    def column_settings(self) -> dict[str, FieldInfo]:
        return {
            field_name: field_info
            for field_name, field_info in self.__class__.model_fields.items()
            if field_name.endswith("_column_no")
        }

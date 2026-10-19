import re
from contextlib import suppress
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from testbench_defect_service.log import logger
from testbench_defect_service.models.config import PhaseCommands
from testbench_defect_service.models.defects import ValueType

#: The legacy `.properties` keys that `_normalize_legacy_excel_config` below reads, as
#: opposed to the scalar keys a field's own `validation_alias` reads. Whoever wants to know
#: which legacy keys this model understands - the `migrate` command, reporting the ones it
#: could not carry over - cannot see these on the model, so they are named here instead.
LEGACY_COMPOSITE_KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"controlFields"),
    re.compile(r".+\.columnNo"),
    re.compile(r".+\.value"),
    re.compile(r".+\.transition\d+"),
    re.compile(r".+\.transition\.number"),
    re.compile(r"udf\.attr\.number"),
    re.compile(r"udf\.attr\d+\..+"),
)


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


def _control_field_owning_state(control_fields: list[dict[str, Any]], state: str) -> int | None:
    """Return the index of the first control field that lists *state* among its values."""
    for index, field in enumerate(control_fields):
        if any(str(value) == state for value in field.get("values") or []):
            return index
    return None


def _attach_legacy_transitions(
    normalized: dict[str, Any], legacy_transitions: dict[str, list[dict[str, str]]]
) -> None:
    """Attach each legacy transition group to the control field it belongs to.

    A group's key prefix is either the control field itself (`status.transition1`, the
    spelling `docs/clients/excel-client.md` documents) or the state the transitions lead
    away from (`New.transition1=New-InProgress`, the spelling the DMProxy connector
    ships). State-keyed groups therefore all land on the same control field and have to
    accumulate; a field that already declares `transitions` explicitly keeps them.
    """
    control_fields = [
        field for field in normalized.get("control_fields") or [] if isinstance(field, dict)
    ]
    index_by_name = {
        _normalize_control_field_name(str(field["name"])): index
        for index, field in enumerate(control_fields)
        if "name" in field
    }

    collected: dict[int, list[dict[str, str]]] = {}
    for prefix, transitions in legacy_transitions.items():
        index = index_by_name.get(prefix)
        if index is None:
            index = _control_field_owning_state(control_fields, prefix)
        if index is None:
            logger.warning(
                "Ignoring legacy transitions for '%s': neither a control field nor a value of one.",
                prefix,
            )
            continue
        if control_fields[index].get("transitions"):
            continue
        collected.setdefault(index, []).extend(transitions)

    for index, transitions in collected.items():
        control_fields[index]["transitions"] = transitions


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
    """Fold legacy `.properties` *structures* into their modern shape.

    Only the composite keys need work here - the ones where several flat properties become one
    nested model (control fields, transitions, UDFs). Legacy *scalar* keys are handled by the
    `validation_alias=AliasChoices(<modern>, <legacy>)` declared on each field, on both
    `ExcelDefectClientConfig` and `ProjectConfig`, so they need no remapping. `TestLegacyScalarKeys`
    pins every documented scalar key against those aliases.
    """
    normalized = dict(data)

    if "control_fields" not in normalized:
        control_fields = _parse_legacy_control_fields(data)
        if control_fields:
            normalized["control_fields"] = control_fields

    legacy_transitions = _parse_legacy_transitions(data)
    if legacy_transitions:
        if "transitions" in normalized:
            logger.warning(
                "Ignoring legacy transitions for %s: a top-level 'transitions' list is present.",
                ", ".join(sorted(legacy_transitions)),
            )
        else:
            _attach_legacy_transitions(normalized, legacy_transitions)

    if "udfs" not in normalized:
        udfs = _parse_legacy_udfs(data)
        if udfs:
            normalized["udfs"] = udfs

    return normalized


class LegacyExcelConfigMixin:
    """Fold the legacy composite `.properties` keys before either model validates.

    Both the global config and a project block can arrive in the old flat spelling - a project
    reads its own `<Project>.properties` file, which is precisely where that spelling survives.
    Leaving this off `ProjectConfig` meant `extra="ignore"` swallowed `controlFields`,
    `*.transitionN` and `udf.attrN.*`, and the project silently kept the global values.
    """

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_properties(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        return _normalize_legacy_excel_config(data)


class Transition(BaseModel):
    from_state: str
    to_state: str


class ControlFields(BaseModel):
    name: str = Field(description="Control field name (e.g. 'status', 'severity')")
    column_number: int = Field(description="Column number in the Excel file for this field")
    values: list[str] = Field(
        default_factory=list, description="Allowed values for this control field (comma-separated)"
    )
    transitions: list[Transition] = Field(
        default_factory=list,
        description="Allowed state transitions for this control field",
        json_schema_extra={
            "item_label": "State Transition",
            "add_prompt": "Would you like to add a state transition for this control field?",
            "add_another_prompt": "Add another state transition for this control field?",
        },
    )

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
    name: str = Field(description="Name of the user-defined attribute")
    column: int = Field(description="Column number in the Excel file for this attribute")
    type: ValueType = Field(description="Value type of this attribute")
    required: bool = Field(default=False, description="Whether this attribute is mandatory")
    value: str | None = Field(default=None, description="Fixed default value for this attribute")
    trueValue: str | None = Field(
        default=None,
        description="Cell content that represents 'true'",
        json_schema_extra={"depends_on": {"type": ValueType.BOOLEAN.value}},
    )
    falseValue: str | None = Field(
        default=None,
        validation_alias=AliasChoices("falseValue", "falsevalue"),
        description="Cell content that represents 'false'",
        json_schema_extra={"depends_on": {"type": ValueType.BOOLEAN.value}},
    )

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value: Any) -> ValueType | Any:
        if value in (ValueType.STRING, "STRING", "string", 0, "0"):
            return ValueType.STRING
        if value in (ValueType.BOOLEAN, "BOOLEAN", "boolean", 2, "2"):
            return ValueType.BOOLEAN
        return value


class ProjectConfig(BaseModel, LegacyExcelConfigMixin):
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
        default=None,
        description="List of control fields for this project.",
        json_schema_extra={"item_label": "Control Field"},
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
        validation_alias=AliasChoices(
            "lastedit_column_no",
            "defect.lastedit.columnNo",
            # Spelling shipped in the DMProxy connector's own `.properties` files.
            "defect.lastedited.columnNo",
        ),
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
    attributes: list[str] | None = Field(default=None, description="Attributes for this project")
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
        default=None,
        description=(
            "Deprecated project-level state transitions, kept for legacy configurations. "
            "Configure transitions on the 'status' control field instead."
        ),
        json_schema_extra={"skip_if_wizard": True},
    )
    udfs: list[UserDefiendAttributes] | None = Field(
        default=None,
        description="List of user-defined attributes for defects in this project.",
        json_schema_extra={"item_label": "User-Defined Attribute"},
    )

    commands: PhaseCommands | None = Field(
        default=None, description="Sync hook scripts for this project"
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


class ExcelDefectClientConfig(BaseModel, LegacyExcelConfigMixin):
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
        json_schema_extra={"path_type": "file"},
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
        default_factory=list,
        description="List of control fields.",
        json_schema_extra={"item_label": "Control Field"},
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
        validation_alias=AliasChoices(
            "lastedit_column_no",
            "defect.lastedit.columnNo",
            # Spelling shipped in the DMProxy connector's own `.properties` files.
            "defect.lastedited.columnNo",
        ),
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
        description=(
            "Deprecated top-level state transitions, kept for legacy configurations. "
            "Configure transitions on the 'status' control field instead."
        ),
        json_schema_extra={"skip_if_wizard": True},
    )
    udfs: list[UserDefiendAttributes] = Field(
        default_factory=list,
        description="List of user-defined attributes for defects.",
        json_schema_extra={"item_label": "User-Defined Attribute"},
    )
    commands: PhaseCommands | None = Field(
        default=None, description="Sync hook scripts (run before and after a sync)"
    )
    projects: dict[str, ProjectConfig] = Field(
        default_factory=dict,
        description="Dictionary of project configurations, keyed by project name.",
        json_schema_extra={"item_label": "Project", "key_label": "Project name"},
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

import json
from pathlib import Path

from sanic.exceptions import InvalidUsage, NotFound, ServerError

from testbench_defect_service.log import logger
from testbench_defect_service.models.defects import (
    Defect,
    DefectID,
    DefectWithID,
    Protocol,
    ProtocolCode,
    ProtocolledDefectSet,
    ProtocolledString,
)


def find_defects_files(defects_path: Path, project: str) -> list[Path]:
    folder = Path(defects_path) / project
    jsonl_files = [p for p in folder.glob("*.jsonl") if p.is_file()]

    if not jsonl_files:
        raise FileNotFoundError(f"No .jsonl files found in {folder}")

    return jsonl_files


def generate_defect_id(jsonl_file: Path, prefix: str) -> str:
    ids: list[int] = []
    with jsonl_file.open("r", encoding="utf-8") as f:
        for line_number, raw_line in enumerate(f, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                json_line = json.loads(stripped)
            except json.JSONDecodeError:
                logger.warning(
                    f"Skipping malformed line {line_number} in '{jsonl_file.name}' "
                    f"during ID generation."
                )
                continue
            raw_id = str(json_line.get("id", ""))
            numeric_part = raw_id.removeprefix(prefix)
            try:
                ids.append(int(numeric_part))
            except ValueError:
                logger.warning(
                    f"Skipping non-numeric defect ID '{raw_id}' at line {line_number} "
                    f"in '{jsonl_file.name}'."
                )
    next_id = 1 if not ids else max(ids) + 1
    return f"{prefix}{next_id}"


def append_defect_to_jsonl(project: str, jsonl_file: Path, defect: Defect) -> ProtocolledString:
    prefix = "BUG-"
    defect_id = generate_defect_id(jsonl_file=jsonl_file, prefix=prefix)
    payload = DefectWithID(id=DefectID(root=defect_id), **defect.model_dump(mode="json"))
    with jsonl_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload.model_dump(mode="json")) + "\n")

    protocol = Protocol()
    protocol.add_success(
        key=str(project),
        message=(
            f"Defect '{defect_id}' created successfully in project {project} "
            f"and appended to '{jsonl_file.name}'."
        ),
        protocol_code=ProtocolCode.INSERT_SUCCESS,
    )
    return ProtocolledString(value=defect_id, protocol=protocol)


def validate_defect(defect: Defect | DefectWithID, control_field) -> bool:
    """
    Validate a defect object used in create/update sync operations.

    Performs two levels of validation:
    1. **Mandatory Field Check**: Ensures all required fields are present and not empty
    2. **Control Field Constraint Check**: Verifies field values match configured allowed values

    Required Fields (always checked):
        - status: Must be non-empty and in control_fields['status']
        - classification: Must be non-empty and in control_fields['classification']
        - priority: Must be non-empty and in control_fields['priority']
        - lastEdited: Must be a valid timestamp (non-empty)
        - principal: Must contain valid authentication info (non-empty)

    Control Field Constraints:
        The control_field dict defines allowed values for each field. Example:
        {
            'status': ['Open', 'In Progress', 'Closed'],
            'priority': ['High', 'Medium', 'Low'],
            'classification': ['Bug', 'Task', 'Feature']
        }

        If a defect has a field value not in its allowed values, validation fails.

    Args:
        defect: Defect or DefectWithID object to validate
        control_field: Dict mapping field names to lists of allowed values

    Returns:
        True  → defect is valid and can be synced
        False → defect is invalid and should be rejected

    Examples:
        Valid defect:
        >>> control = {'status': ['Open', 'Closed'], 'priority': ['High', 'Low']}
        >>> defect = Defect(status='Open', priority='High', ...)
        >>> validate_defect(defect, control)
        True

        Invalid - status not in allowed values:
        >>> defect = Defect(status='InProgress', priority='High', ...)
        >>> validate_defect(defect, control)
        False
    """

    # Required according to OpenAPI spec:
    required_fields = ["status", "classification", "priority", "lastEdited", "principal"]

    # Check missing mandatory fields
    for field in required_fields:
        if getattr(defect, field, None) in (None, ""):
            return False

    # Check control_field constraints (e.g., status must be in allowed values)
    if not control_field:
        return True
    for field, allowed_values in control_field.items():
        actual_value = getattr(defect, field, None)
        if actual_value not in allowed_values:
            logger.debug(
                f"Validation failed: field '{field}' has value '{actual_value}', "
                f"expected one of {allowed_values}"
            )
            return False

    return True


def build_protocol_result(defects: list[DefectWithID], protocol: Protocol) -> ProtocolledDefectSet:
    """Build a ProtocolledDefectSet from defects and protocol entries."""
    return ProtocolledDefectSet(value=defects, protocol=protocol)


def parse_defect_line(
    line: str, line_number: int, filename: str, protocol: Protocol
) -> DefectWithID | None:
    """Parse a single line from JSONL file into a DefectWithID."""
    try:
        return DefectWithID(**json.loads(line))
    except json.JSONDecodeError:
        logger.warning(f"Malformed defect entry in JSONL file '{filename}' at line {line_number}.")
        protocol.add_general_warning(
            protocol_code=ProtocolCode.IMPORT_WARNING,
            message=(f"Malformed defect entry in JSONL file '{filename}' at line {line_number}."),
        )
        return None


def add_missing_defect_warnings(
    requested_ids: set[str],
    found_defects: list[DefectWithID],
    project: str,
    protocol: Protocol,
):
    """Add warnings for defects that were requested but not found."""
    found_ids = {defect.id.root for defect in found_defects}
    missing_ids = requested_ids - found_ids

    for missing_id in sorted(missing_ids):
        logger.warning(f"Requested defect id '{missing_id}' not found in project {project}.")
        protocol.add_warning(
            key=str(missing_id),
            protocol_code=ProtocolCode.DEFECT_NOT_FOUND,
            message=f"Requested defect id '{missing_id}' not found in project {project}.",
        )


def update_defect_in_list(
    defect_file: Path, updated_defect: DefectWithID, protocol: Protocol
) -> tuple[list[DefectWithID], bool]:
    """Read defects and replace the matching one with the updated version.

    Returns:
        A tuple of (defects list, found flag). The found flag is True if the
        target defect was found and replaced, False otherwise.
    """
    defects: list[DefectWithID] = []
    found = False

    try:
        with defect_file.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                try:
                    defect = DefectWithID(**json.loads(line))
                    if defect.id.root == updated_defect.id.root:
                        defects.append(updated_defect)
                        found = True
                    else:
                        defects.append(defect)
                except json.JSONDecodeError:
                    logger.warning(
                        f"Malformed defect entry in JSONL file '{defect_file.name}' "
                        f"at line {line_number}; entry skipped."
                    )
                    protocol.add_general_warning(
                        protocol_code=ProtocolCode.IMPORT_WARNING,
                        message=(
                            f"Malformed defect entry in JSONL file '{defect_file.name}' "
                            f"at line {line_number}; entry skipped."
                        ),
                    )
    except OSError as exc:
        raise ServerError("Unable to read defect file.") from exc

    return defects, found


def remove_defect_from_list(
    defect_file: Path, defect_id: str, protocol: Protocol
) -> tuple[list[DefectWithID], DefectWithID | None]:
    """Read defects and remove the matching one."""
    remaining_defects: list[DefectWithID] = []
    deleted_defect: DefectWithID | None = None

    try:
        with defect_file.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                try:
                    defect = DefectWithID(**json.loads(line))
                    if defect.id.root == defect_id:
                        deleted_defect = defect
                    else:
                        remaining_defects.append(defect)
                except json.JSONDecodeError:
                    logger.warning(
                        f"Malformed defect entry in JSONL file '{defect_file.name}'"
                        f" at line {line_number}; entry skipped."
                    )
                    protocol.add_general_warning(
                        protocol_code=ProtocolCode.IMPORT_WARNING,
                        message=(
                            f"Malformed defect entry in JSONL file '{defect_file.name}'"
                            f" at line {line_number}; entry skipped."
                        ),
                    )
    except OSError as exc:
        raise ServerError("Unable to read defect file.") from exc

    return remaining_defects, deleted_defect


def write_defects_to_file(defect_file: Path, defects: list[DefectWithID], project: str):
    """Write defects to a JSONL file."""
    try:
        with defect_file.open("w", encoding="utf-8") as file:
            for defect in defects:
                file.write(json.dumps(defect.model_dump(mode="json")) + "\n")
    except OSError as exc:
        raise ServerError(f"Unable to write defect file for project {project}.") from exc


def find_defect_by_id(defect_file: Path, defect_id: str, project: str) -> DefectWithID:
    """Find a defect by ID in the JSONL file."""
    try:
        with defect_file.open("r", encoding="utf-8") as file:
            for line in file:
                try:
                    defect = DefectWithID(**json.loads(line))
                    if defect.id.root == defect_id:
                        return defect
                except json.JSONDecodeError as exc:
                    raise InvalidUsage("Malformed defect entry in JSONL file.") from exc
    except OSError as exc:
        raise ServerError(f"Unable to read defect file for project {project}.") from exc

    raise NotFound(f"Defect with id {defect_id} not found in project {project}.")


def validate_udf_structure(udf_definitions):
    """Validate the structure of user-defined field definitions."""
    if not isinstance(udf_definitions, list):
        raise ValueError("UserDefinedAttributes.json must contain a list of definitions.")

    for udf in udf_definitions:
        if not isinstance(udf, dict):
            raise ValueError("UserDefinedAttributes.json must contain a list of dictionaries.")
        if "name" not in udf or "valueType" not in udf:
            raise ValueError(
                "UserDefinedAttributes.json must contain a list of definitions "
                "with 'name' and 'valueType' keys."
            )


def parse_defects_from_file(
    defect_file: Path, project: str, protocol: Protocol
) -> list[DefectWithID]:
    """Parse all defects from a JSONL file."""
    defects: list[DefectWithID] = []

    try:
        with defect_file.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                defect = parse_defect_line(line, line_number, defect_file.name, protocol)
                if defect:
                    defects.append(defect)
                    protocol.add_success(
                        key=str(defect.id.root),
                        protocol_code=ProtocolCode.IMPORT_SUCCESS,
                        message=f"Retrieved {len(defects)} defects for project: {project}",
                    )
    except OSError:
        logger.error(f"Unable to read defect file for project {project}.")
        protocol.add_general_error(
            protocol_code=ProtocolCode.READ_ACCESS_ERROR,
            message=f"Unable to read defect file for project {project}.",
        )

    return defects


def parse_requested_defects(
    defect_file: Path, requested_ids: set[str], project: str, protocol: Protocol
) -> list[DefectWithID]:
    """Parse only requested defects from a JSONL file."""
    defects: list[DefectWithID] = []

    try:
        with defect_file.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                defect = parse_defect_line(line, line_number, defect_file.name, protocol)
                if defect and defect.id.root in requested_ids:
                    defects.append(defect)
                    logger.info(
                        f"Defect '{defect.id.root}' loaded successfully from '{defect_file.name}'."
                    )
                    protocol.add_success(
                        key=defect.id.root,
                        protocol_code=ProtocolCode.IMPORT_SUCCESS,
                        message=(
                            f"Defect '{defect.id.root}' loaded successfully "
                            f"from '{defect_file.name}'."
                        ),
                    )
    except OSError:
        logger.error(f"Unable to read defect file for project {project}.")
        protocol.add_general_error(
            protocol_code=ProtocolCode.READ_ACCESS_ERROR,
            message=f"Unable to read defect file for project {project}.",
        )

    return defects

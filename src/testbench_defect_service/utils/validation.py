from typing import TypedDict

from pydantic import ValidationError


class ValidationErrorDetail(TypedDict):
    field: str | None
    message: str


def format_validation_error_details(e: ValidationError) -> list[ValidationErrorDetail]:
    """Convert a pydantic ValidationError to a list of structured error dicts.

    Each dict contains:
    - `field`: dot-joined location path (e.g. "syncContext.lastSync"), or None for root errors
    - `message`: human-readable description of the problem

    Example output:

    ```
    [{"field": "lastSync", "message": "Missing required field 'lastSync'"},
    {"field": "startDate", "message": "Invalid value for 'startDate': not a valid datetime"}]
    ```
    """
    errors: list[ValidationErrorDetail] = []
    for error in e.errors():
        loc = [str(part) for part in error["loc"]]
        field = ".".join(loc) if loc else None
        error_type = error.get("type", "")
        msg = error.get("msg", "")

        if error_type == "missing":
            message = f"Missing required field '{field}'" if field else "Missing required field"
        elif field and msg:
            message = f"Invalid value for '{field}': {msg}"
        elif field:
            message = f"Invalid value for '{field}'"
        else:
            message = msg or "Validation error"

        errors.append({"field": field, "message": message})
    return errors

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypedDict, get_args, get_origin

import click
import questionary
from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined
from questionary import Choice

_MISSING = object()

# Constants for json_schema_extra keys
SCHEMA_KEYS = {
    "ENV_VAR": "env_var",
    "DEPENDS_ON": "depends_on",
    "SENSITIVE": "sensitive",
    "SKIP_IF_WIZARD": "skip_if_wizard",
    "ITEM_LABEL": "item_label",
    "KEY_LABEL": "key_label",
    "LABEL": "label",
    "REQUIRED": "required",
    "PATH_TYPE": "path_type",  # "file" or "directory" (default: "directory")
}


class FieldPromptOptions(TypedDict, total=False):
    label: str
    default: Any
    skip: bool
    validate: Callable[[Any], tuple[bool, str | None]]
    required: bool


def get_field_extra(field_info: FieldInfo) -> dict[str, Any]:
    """Extract json_schema_extra dict from field info."""
    extra = field_info.json_schema_extra
    return extra if isinstance(extra, dict) else {}


def is_basemodel_subclass(cls: Any) -> bool:
    """Check if a type is a Pydantic BaseModel subclass."""
    try:
        return isinstance(cls, type) and issubclass(cls, BaseModel)
    except TypeError:
        return False


def normalize_to_dict(item: dict | BaseModel) -> dict:
    """Convert a Pydantic model or dict to a plain dict.

    Args:
        item: Either a dictionary or Pydantic BaseModel instance

    Returns:
        Plain dictionary representation
    """
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def normalize_answer(answer: Any) -> Any:
    """Convert blank string answers to None for optional fields."""
    if isinstance(answer, str) and not answer.strip():
        return None
    return answer


def dependency_matches(
    field_info: FieldInfo,
    provided_values: dict[str, Any] | None,
    fallback_values: dict[str, Any] | None = None,
) -> bool:
    """Check if a field's dependency condition is met based on provided values.

    depends_on format: {"field_name": expected_value, ...}
    Example: {"auth_type": "basic"} or {"type": "BOOLEAN"}
    """
    extra = get_field_extra(field_info)
    dependency = extra.get(SCHEMA_KEYS["DEPENDS_ON"])
    if not dependency or not isinstance(dependency, dict):
        return True

    for field, expected in dependency.items():
        provided = provided_values or {}
        actual = provided.get(field, _MISSING)
        if actual is _MISSING and fallback_values is not None:
            actual = fallback_values.get(field, _MISSING)
        if actual is _MISSING:
            actual = None
        if isinstance(expected, (list, tuple, set)):
            if actual not in expected:
                return False
        elif actual != expected:
            return False

    return True


def parse_value_from_input(value_str: str, field_type: type) -> Any:  # noqa: C901, PLR0911, PLR0912
    """Parse user input string to the appropriate Python type."""
    if not value_str:
        return None

    origin = get_origin(field_type)

    if field_type is Path:
        return Path(value_str)

    if origin is list:
        value_str = value_str.strip()
        if value_str.startswith("[") and value_str.endswith("]"):
            value_str = value_str[1:-1].strip()

        args = get_args(field_type)
        if args and args[0] is str:
            # Comma-separated string list
            return [item.strip() for item in value_str.split(",") if item.strip()]
        if args and args[0] is int:
            # Comma-separated int list
            try:
                return [int(item.strip()) for item in value_str.split(",") if item.strip()]
            except ValueError as e:
                raise ValueError(f"List must contain only integers, got: {value_str}") from e
        if args and args[0] is float:
            # Comma-separated float list
            try:
                return [float(item.strip()) for item in value_str.split(",") if item.strip()]
            except ValueError as e:
                raise ValueError(f"List must contain only numbers, got: {value_str}") from e

    if field_type is bool:
        return value_str.lower() in ("true", "yes", "1", "y")

    if field_type is int:
        try:
            return int(value_str)
        except ValueError as e:
            raise ValueError(f"Expected an integer, got: '{value_str}'") from e

    if field_type is float:
        try:
            return float(value_str)
        except ValueError as e:
            raise ValueError(f"Expected a number, got: '{value_str}'") from e

    return value_str


def get_field_type(field_info: FieldInfo) -> type:
    """Extract the actual field type from Optional/Union types."""
    field_type = field_info.annotation
    if field_type is None:
        return type(None)

    args = get_args(field_type)
    if args and type(None) in args:
        # Extract the non-None type
        non_none_types = [arg for arg in args if arg is not type(None)]
        if non_none_types:
            return non_none_types[0]  # type: ignore[no-any-return]
    return field_type


def prompt_with_validation(
    prompt_text: str,
    default: str,
    field_type: type,
    is_required: bool,
    max_retries: int = 3,
) -> Any:
    """Prompt for input with validation and retry logic, returning the parsed value or None."""

    for attempt in range(max_retries):
        answer = questionary.text(prompt_text, default=default).ask()

        if answer is None:
            return None

        if not answer and not is_required:
            return answer

        if not answer and is_required:
            click.echo("❌ This field is required")
            continue

        try:
            return parse_value_from_input(answer, field_type)
        except (ValueError, TypeError) as e:
            remaining = max_retries - attempt - 1
            if remaining > 0:
                click.echo(f"❌ Invalid value: {e}. {remaining} attempt(s) remaining.")
            else:
                click.echo(f"❌ Invalid value: {e}. Maximum retries reached.")

    return None


def is_sensitive_field(field_name: str, field_info: FieldInfo) -> bool:
    """Check if a field contains sensitive data like passwords or tokens."""
    sensitive_keywords = {"password", "token", "secret", "api_token"}
    if any(keyword in field_name.lower() for keyword in sensitive_keywords):
        return True
    schema_extra = get_field_extra(field_info)
    return bool(schema_extra.get(SCHEMA_KEYS["SENSITIVE"], False))


def get_field_default(field_info: FieldInfo) -> Any:
    """Get the schema-defined default value for a field."""
    if field_info.default is not None and field_info.default is not PydanticUndefined:
        return field_info.default
    if field_info.default_factory is not None and callable(field_info.default_factory):
        factory_result = field_info.default_factory()  # type: ignore[call-arg]
        if isinstance(factory_result, (list, dict)) and not factory_result:
            return None
        return factory_result
    return None


def should_skip_field(  # noqa: PLR0913
    field_name: str,
    field_info: FieldInfo,
    config_dict: dict[str, Any],
    existing: dict[str, Any],
    allowed_fields: set[str] | None,
    skip_fields: set[str],
    field_overrides: dict[str, FieldPromptOptions],
) -> bool:
    """Check if a field should be skipped in the wizard."""
    if field_info.annotation is None:
        return True
    if allowed_fields and field_name not in allowed_fields:
        return True
    if field_name in skip_fields:
        return True

    overrides = field_overrides.get(field_name, {})
    schema_extra = get_field_extra(field_info)

    if overrides.get("skip") or schema_extra.get(SCHEMA_KEYS["SKIP_IF_WIZARD"]):
        return True

    return not dependency_matches(field_info, config_dict, existing)


def get_field_description(
    field_name: str, field_info: FieldInfo, field_overrides: dict[str, FieldPromptOptions]
) -> str:
    """Get the display description for a field."""
    overrides = field_overrides.get(field_name, {})
    schema_extra = get_field_extra(field_info)

    return (
        overrides.get("label")
        or schema_extra.get(SCHEMA_KEYS["LABEL"])
        or field_info.description
        or field_name.replace("_", " ").title()
    )


def get_field_value(field_name: str, field_info: FieldInfo, existing: dict[str, Any]) -> Any:
    """Get existing value for a field, checking both field name and alias."""
    field_value = existing.get(field_name)
    if field_value is None and field_info.alias:
        field_value = existing.get(field_info.alias)
    return field_value


def get_env_value(field_info: FieldInfo) -> tuple[str | None, Any]:
    """Get environment variable name and value if configured."""
    schema_extra = get_field_extra(field_info)
    env_var = schema_extra.get(SCHEMA_KEYS["ENV_VAR"])
    if env_var:
        env_value = os.getenv(env_var) or None
        return env_var, env_value
    return None, None


def get_env_sourced_field_names(config_class: type[BaseModel]) -> set[str]:
    """Return field names whose values come from environment variables that are currently set."""
    env_sourced: set[str] = set()
    for field_name, field_info in config_class.model_fields.items():
        _, env_value = get_env_value(field_info)
        if env_value is not None:
            env_sourced.add(field_name)
    return env_sourced


def resolve_field_default(
    field_name: str,
    field_info: FieldInfo,
    field_value: Any,
    env_value: Any,
    field_overrides: dict[str, FieldPromptOptions],
) -> Any:
    """Resolve a field's default value using precedence rules.

    Priority (highest to lowest):
    1. Existing field value
    2. Environment variable value
    3. Field override default
    4. Schema-defined default
    """
    if field_value is not None:
        return field_value
    if env_value is not None:
        return env_value
    override = field_overrides.get(field_name)
    if override and "default" in override:
        return override["default"]
    return get_field_default(field_info)


def format_default_value(default_value: Any) -> str:
    """Format default value for display in prompts."""
    if default_value is None or default_value is PydanticUndefined:
        return ""
    if isinstance(default_value, Path):
        return str(default_value)
    if isinstance(default_value, list):
        return ",".join(str(x) for x in default_value)
    if isinstance(default_value, bool):
        return str(default_value).lower()
    return str(default_value)


def is_field_required(
    field_name: str, field_info: FieldInfo, field_overrides: dict[str, FieldPromptOptions]
) -> bool:
    overrides = field_overrides.get(field_name, {})
    schema_extra = get_field_extra(field_info)

    if "required" in overrides:
        return bool(overrides["required"])
    if SCHEMA_KEYS["REQUIRED"] in schema_extra:
        return bool(schema_extra[SCHEMA_KEYS["REQUIRED"]])
    return field_info.is_required()


def prompt_for_existing_items_action(item_label: str) -> str | None:
    """Prompt user for action on existing items.

    Args:
        item_label: Display label for items

    Returns:
        Action string ('keep_all', 'edit', 'remove', 'remove_all') or None if cancelled
    """
    return questionary.select(  # type: ignore[no-any-return]
        f"What would you like to do with existing {item_label}s?",
        choices=[
            Choice("✓ Keep all as-is", "keep_all"),
            Choice("✏️  Edit specific items", "edit"),
            Choice("🗑️  Remove specific items", "remove"),
            Choice("🗑️  Remove all and start fresh", "remove_all"),
        ],
    ).ask()


def select_items_for_action(
    items_info: list[tuple[Any, str]],
    action: str,
    item_label: str,
) -> list[Any] | None:
    """Display checkbox to select items for editing or removing.

    Args:
        items_info: List of (index/key, display_name) tuples
        action: 'edit' or 'remove'
        item_label: Display label for items

    Returns:
        List of selected indices/keys, or None if cancelled
    """
    verb = "edit" if action == "edit" else "remove"

    choices = [
        Choice(title=display_name, value=identifier) for identifier, display_name in items_info
    ]

    click.echo(f"\n📌 Instructions: Select items you want to {verb}, then press Enter")
    click.echo("   Items not selected will be kept as-is\n")

    selected: list[Any] | None = questionary.checkbox(
        f"Select {item_label}(s) to {verb}:",
        choices=choices,
    ).ask()

    if selected is None:
        return None

    if not selected:
        click.echo(f"\nℹ️  No items selected. All {item_label}s will be kept as-is.")  # noqa: RUF001

    return selected


def handle_existing_list_of_models(
    existing: list[dict | BaseModel], item_class: type[BaseModel], item_label: str
) -> list[dict] | None:
    """Handle existing list of models for editing/removal.

    Returns:
        List of configured items, or None if user cancelled
    """

    result: list[dict] = []

    existing_dicts = [normalize_to_dict(item) for item in existing]

    click.echo(f"\n📋 Found {len(existing_dicts)} existing {item_label}(s)\n")
    for i, existing_item in enumerate(existing_dicts, 1):
        item_name = existing_item.get("name", f"{item_label} {i}")
        click.echo(f"  {i}. {item_name}")

    click.echo()
    action = prompt_for_existing_items_action(item_label)
    if action is None:
        return None

    if action == "remove_all":
        return result

    if action == "keep_all":
        return existing_dicts.copy()

    items_info = [
        (i - 1, f"{i}. {existing_item.get('name', f'{item_label} {i}')}")
        for i, existing_item in enumerate(existing_dicts, 1)
    ]
    selected_indices = select_items_for_action(items_info, action, item_label)
    if selected_indices is None:
        return None

    for i, existing_item in enumerate(existing_dicts):
        if i not in selected_indices:
            result.append(existing_item)
            continue
        if action == "remove":
            continue

        item_name = existing_item.get("name", f"{item_label} {i + 1}")
        click.echo(f"\n--- Editing: {item_name} ---")
        edited_item = prompt_model_fields(
            item_class, existing_config=existing_item, section_label=None
        )
        if edited_item is None:
            click.echo("\n⚠️  Edit cancelled. Keeping original item.")
            result.append(existing_item)
        else:
            result.append(edited_item)

    return result


def prompt_list_of_models(
    item_class: type[BaseModel],
    item_label: str,
    existing: list[dict | BaseModel] | None = None,
    schema_extra: dict[str, Any] | None = None,
) -> list[dict] | None:
    """Prompt user to configure a list of BaseModel items interactively.

    Args:
        item_class: BaseModel class for list items
        item_label: Display label for items (e.g., "User Defined Attribute")
        existing: Existing list of items from config
        schema_extra: json_schema_extra metadata for custom prompts

    Returns:
        List of dictionaries representing configured items, or None if cancelled
    """
    schema_extra = schema_extra or {}
    add_prompt = schema_extra.get("add_prompt", f"Would you like to add a {item_label}?")
    add_another_prompt = schema_extra.get("add_another_prompt", f"Add another {item_label}?")

    result: list[dict] = []

    if existing:
        existing_result = handle_existing_list_of_models(existing, item_class, item_label)
        if existing_result is None:
            return None
        result = existing_result

    prompt_text = add_prompt if not result else add_another_prompt

    while True:
        click.echo()
        should_add = questionary.confirm(prompt_text, default=False).ask()
        if should_add is None:
            return None
        if not should_add:
            break

        click.echo(f"\n--- New {item_label} {len(result) + 1} ---")
        item_config = prompt_model_fields(item_class, existing_config=None, section_label=None)
        if item_config is None:
            return None

        result.append(item_config)
        prompt_text = add_another_prompt

    return result


def handle_existing_dict_of_models(
    existing: dict[str, dict | BaseModel], item_class: type[BaseModel], item_label: str
) -> dict[str, dict] | None:
    """Handle existing dict of models for editing/removal.

    Returns:
        Dictionary of configured items, or None if user cancelled
    """

    result: dict[str, dict] = {}

    existing_dicts = {key: normalize_to_dict(value) for key, value in existing.items()}

    click.echo(f"\n📋 Found {len(existing_dicts)} existing {item_label}(s)\n")
    for key in existing_dicts:
        click.echo(f"  {key}")

    click.echo()
    action = prompt_for_existing_items_action(item_label)
    if action is None:
        return None

    if action == "remove_all":
        return result

    if action == "keep_all":
        return existing_dicts.copy()

    items_info = [(key, key) for key in existing_dicts]

    selected_keys = select_items_for_action(items_info, action, item_label)
    if selected_keys is None:
        return None

    for key, value in existing_dicts.items():
        if key not in selected_keys:
            result[key] = value
            continue
        if action == "remove":
            continue

        click.echo(f"\n--- Editing: {key} ---")
        edited_value = prompt_model_fields(item_class, existing_config=value)
        if edited_value is None:
            click.echo("\n⚠️  Edit cancelled. Keeping original item.")
            result[key] = value
        else:
            result[key] = edited_value

    return result


def prompt_for_new_unique_key(key_label: str, existing: dict[str, Any]) -> str | None:
    """Prompt user for a unique key for the new item."""

    key = None

    while key is None:
        key_input = questionary.text(f"{key_label}:").ask()
        if key_input is None:
            return None

        key_stripped = (key_input or "").strip()
        if not key_stripped:
            click.echo("❌ Key cannot be empty, please try again")
            continue

        if key_stripped in existing:
            click.echo(f"❌ Key '{key_stripped}' already exists, please enter a different key")
            continue

        key = key_stripped

    return key


def prompt_dict_of_models(
    item_class: type[BaseModel],
    item_label: str,
    key_label: str = "Key",
    existing: dict[str, dict | BaseModel] | None = None,
    schema_extra: dict[str, Any] | None = None,
) -> dict[str, dict] | None:
    """Prompt user to configure a dictionary of BaseModel items interactively.

    Args:
        item_class: BaseModel class for dict values
        item_label: Display label for items (e.g., "Project Configuration")
        key_label: Display label for keys (e.g., "Project Key")
        existing: Existing dictionary from config
        schema_extra: json_schema_extra metadata for custom prompts

    Returns:
        Dictionary mapping keys to configured items, or None if cancelled
    """
    schema_extra = schema_extra or {}
    add_prompt = schema_extra.get("add_prompt", f"Would you like to add a {item_label}?")
    add_another_prompt = schema_extra.get("add_another_prompt", f"Add another {item_label}?")

    result: dict[str, dict] = {}

    if existing:
        existing_result = handle_existing_dict_of_models(existing, item_class, item_label)
        if existing_result is None:
            return None
        result = existing_result

    prompt_text = add_prompt if not result else add_another_prompt

    while True:
        click.echo()
        should_add = questionary.confirm(prompt_text, default=False).ask()
        if should_add is None:
            return None
        if not should_add:
            break

        key = prompt_for_new_unique_key(key_label, result)
        if key is None:
            return None

        click.echo(f"--- Configure {item_label} for '{key}' ---")
        item_config = prompt_model_fields(item_class)
        if item_config is None:
            return None

        result[key] = item_config
        prompt_text = add_another_prompt

    return result


def prompt_plain_dict_value(
    key: str,
    value_type: type,
    value_hint: str,
    existing_value: Any,
) -> Any | None:
    """Prompt for the value of a single key in a plain dict field, retrying on empty/invalid input.

    Returns:
        The parsed value, or None if the user cancelled (Ctrl+C)
    """
    default = format_default_value(existing_value) if existing_value is not None else ""
    while True:
        raw = questionary.text(f"Value for '{key}' ({value_hint}):", default=default).ask()
        if raw is None:
            return None
        if not raw and existing_value is not None:
            return existing_value
        if not raw:
            click.echo("\u274c Value cannot be empty")
            continue
        try:
            return parse_value_from_input(raw, value_type)
        except (ValueError, TypeError) as e:
            click.echo(f"\u274c Invalid value: {e}")


def handle_existing_plain_dict(
    existing: dict[str, Any],
    value_type: type,
    value_hint: str,
    item_label: str,
) -> dict[str, Any] | None:
    """Handle existing plain dict entries for editing/removal.

    Returns:
        Updated dict, or None if user cancelled
    """
    result: dict[str, Any] = {}

    entry_word = "entry" if len(existing) == 1 else "entries"
    click.echo(f"\n\U0001f4cb Found {len(existing)} existing {item_label} {entry_word}\n")
    for key, value in existing.items():
        click.echo(f"  {key}: {value}")

    click.echo()
    action = prompt_for_existing_items_action(item_label)
    if action is None:
        return None

    if action == "remove_all":
        return result

    if action == "keep_all":
        return dict(existing)

    items_info = [(key, f"{key}: {value}") for key, value in existing.items()]
    selected_keys = select_items_for_action(items_info, action, item_label)
    if selected_keys is None:
        return None

    for key, value in existing.items():
        if key not in selected_keys:
            result[key] = value
            continue
        if action == "remove":
            continue

        click.echo(f"\n--- Editing: {key} ---")
        new_value = prompt_plain_dict_value(key, value_type, value_hint, value)
        if new_value is None:
            click.echo("\n\u26a0\ufe0f  Edit cancelled. Keeping original value.")
            result[key] = value
        else:
            result[key] = new_value

    return result


def prompt_key_value_dict(
    value_type: type,
    item_label: str,
    key_label: str = "Key",
    existing: dict[str, Any] | None = None,
    schema_extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Prompt user to configure a dict[str, X] field interactively.

    Args:
        value_type: The type of each dict value (e.g., list[str], str, int)
        item_label: Display label for the dict entries (e.g., "Control Field")
        key_label: Display label for keys (e.g., "Field Name")
        existing: Existing dict from config
        schema_extra: json_schema_extra metadata for custom prompts

    Returns:
        Dictionary of configured entries, or None if cancelled
    """
    schema_extra = schema_extra or {}
    value_origin = get_origin(value_type)
    value_args = get_args(value_type)

    if value_origin is list and value_args:
        inner_name = getattr(value_args[0], "__name__", str(value_args[0]))
        value_hint = f"comma-separated {inner_name}s"
    else:
        value_hint = getattr(value_type, "__name__", str(value_type))

    result: dict[str, Any] = {}

    if existing:
        existing_result = handle_existing_plain_dict(existing, value_type, value_hint, item_label)
        if existing_result is None:
            return None
        result = existing_result

    add_prompt = schema_extra.get("add_prompt", f"Would you like to add a {item_label} entry?")
    add_another_prompt = schema_extra.get("add_another_prompt", f"Add another {item_label} entry?")
    prompt_text = add_prompt if not result else add_another_prompt

    while True:
        click.echo()
        should_add = questionary.confirm(prompt_text, default=False).ask()
        if should_add is None:
            return None
        if not should_add:
            break

        key = prompt_for_new_unique_key(key_label, result)
        if key is None:
            return None

        value = prompt_plain_dict_value(key, value_type, value_hint, None)
        if value is None:
            return None

        result[key] = value
        prompt_text = add_another_prompt

    return result


def is_list_of_models(field_info: FieldInfo) -> bool:
    """Check if field is a list[BaseModel] (auto-detected by type)."""
    field_type = get_field_type(field_info)
    if get_origin(field_type) is not list:
        return False
    args = get_args(field_type)
    return len(args) > 0 and is_basemodel_subclass(args[0])


def is_dict_of_models(field_info: FieldInfo) -> bool:
    """Check if field is a dict[str, BaseModel] (auto-detected by type)."""
    field_type = get_field_type(field_info)
    if get_origin(field_type) is not dict:
        return False
    args = get_args(field_type)
    # Dict requires exactly 2 type arguments: dict[key_type, value_type]
    return len(args) == 2 and args[0] is str and is_basemodel_subclass(args[1])  # noqa: PLR2004


def is_nested_model(field_info: FieldInfo) -> bool:
    """Check if field is a direct BaseModel subclass (not wrapped in list or dict)."""
    field_type = get_field_type(field_info)
    if get_origin(field_type) is not None:
        return False  # It's a generic (list, dict, Union, etc.)
    return is_basemodel_subclass(field_type)


def handle_list_of_models(
    field_info: FieldInfo,
    field_value: Any,
) -> list[dict] | None:
    """Handle list[BaseModel] fields (auto-detected by type).

    Returns:
        The configured list, or None if cancelled
    """
    schema_extra = get_field_extra(field_info)
    field_type = get_field_type(field_info)
    args = get_args(field_type)
    item_class = args[0]
    item_label = schema_extra.get(SCHEMA_KEYS["ITEM_LABEL"], item_class.__name__)
    return prompt_list_of_models(item_class, item_label, field_value, schema_extra)


def handle_dict_of_models(
    field_info: FieldInfo,
    field_value: Any,
) -> dict[str, dict] | None:
    """Handle dict[str, BaseModel] fields (auto-detected by type).

    Returns:
        The configured dict, or None if cancelled
    """
    schema_extra = get_field_extra(field_info)
    field_type = get_field_type(field_info)
    args = get_args(field_type)
    value_class = args[1]
    item_label = schema_extra.get(SCHEMA_KEYS["ITEM_LABEL"], value_class.__name__)
    key_label = schema_extra.get(SCHEMA_KEYS["KEY_LABEL"], "Key")
    return prompt_dict_of_models(value_class, item_label, key_label, field_value, schema_extra)


def handle_nested_model(
    field_name: str,
    field_info: FieldInfo,
    field_value: Any,
) -> dict[str, Any] | None:
    """Handle a direct BaseModel field by recursing into prompt_model_fields.

    For optional fields, asks the user whether to configure the nested section.
    Returns the configured dict, an empty sentinel (skip), or None if cancelled.
    """
    field_type = get_field_type(field_info)
    is_optional = not field_info.is_required()
    description = field_info.description or field_name.replace("_", " ").title()

    if is_optional:
        click.echo()
        configure_it = questionary.confirm(
            f"Configure '{description}'? (optional — press N to skip)", default=False
        ).ask()
        if configure_it is None:
            return None
        if not configure_it:
            return {}  # sentinel: field will not be added to config_dict

    click.echo(f"\n--- {description} ---")
    return prompt_model_fields(field_type, existing_config=field_value or {})


def is_plain_dict(field_info: FieldInfo) -> bool:
    """Check if field is a dict[str, X] where X is not a BaseModel subclass."""
    field_type = get_field_type(field_info)
    if get_origin(field_type) is not dict:
        return False
    args = get_args(field_type)
    if len(args) != 2 or args[0] is not str:  # noqa: PLR2004
        return False
    return not is_basemodel_subclass(args[1])


def handle_plain_dict(
    field_info: FieldInfo,
    field_value: Any,
) -> dict[str, Any] | None:
    """Handle dict[str, X] fields interactively where X is not a BaseModel.

    Returns:
        The configured dict, or None if cancelled
    """
    field_type = get_field_type(field_info)
    args = get_args(field_type)
    value_type = args[1]
    schema_extra = get_field_extra(field_info)
    item_label = schema_extra.get(SCHEMA_KEYS["ITEM_LABEL"]) or field_info.description or "Entry"
    key_label = schema_extra.get(SCHEMA_KEYS["KEY_LABEL"], "Key")
    return prompt_key_value_dict(value_type, item_label, key_label, field_value, schema_extra)


def prompt_literal_field(field_type: type, description: str, default: Any) -> Any:
    choices = list(get_args(field_type))
    default_val = default if default in choices else choices[0]
    return questionary.select(f"{description}:", choices=choices, default=default_val).ask()


def prompt_bool_field(description: str, default: Any) -> Any:
    default_bool = bool(default) if default is not None else False
    return questionary.confirm(f"{description}:", default=default_bool).ask()


def prompt_path_field(description: str, default: Any, only_directories: bool = True) -> Any:
    return questionary.path(
        f"{description}:", default=default, only_directories=only_directories
    ).ask()


def prompt_password_field(description: str, default: Any) -> Any:
    return questionary.password(f"{description}:", default=default if default else "").ask()


def prompt_single_field(  # noqa: C901, PLR0912, PLR0913
    field_name: str,
    field_info: FieldInfo,
    field_value: Any,
    field_overrides: dict[str, FieldPromptOptions],
    config_class: type[BaseModel],
    config_dict: dict[str, Any],
) -> Any | None:
    """Prompt for a single field value with validation.

    Returns:
        The validated field value (str, int, bool, Path, list, etc.) or None if:
        - User cancelled the prompt
        - Field is optional and user provided no value
        - An error occurred during processing
    """

    field_type = get_field_type(field_info)
    origin = get_origin(field_type)
    description = get_field_description(field_name, field_info, field_overrides)
    default_value = resolve_field_default(
        field_name, field_info, field_value, None, field_overrides=field_overrides
    )
    default_display = format_default_value(default_value)
    is_required = is_field_required(field_name, field_info, field_overrides)
    custom_validator = field_overrides.get(field_name, {}).get("validate")

    while True:
        try:
            raw_answer: Any = None

            if origin is Literal:
                raw_answer = prompt_literal_field(field_type, description, default_value)
            elif field_type is bool:
                raw_answer = prompt_bool_field(description, default_value)
            elif field_type is Path:
                schema_extra = get_field_extra(field_info)
                only_dirs = schema_extra.get(SCHEMA_KEYS["PATH_TYPE"], "directory") != "file"
                raw_answer = prompt_path_field(description, default_display, only_dirs)
            elif is_sensitive_field(field_name, field_info):
                raw_answer = prompt_password_field(description, default_display)
            else:
                prompt_text = f"{description}:"
                if not is_required:
                    prompt_text += " (optional)"
                raw_answer = prompt_with_validation(
                    prompt_text, default_display, field_type, is_required
                )

            if raw_answer is None:
                return None

            answer = normalize_answer(raw_answer)

            if answer is None:
                if is_required:
                    click.echo("❌ This field is required")
                    continue
                return None

            if custom_validator:
                is_valid, error_message = custom_validator(answer)
                if not is_valid:
                    click.echo(f"❌ {error_message}" if error_message else "❌ Invalid value")
                    continue

            is_valid, error_message = validate_field_value(
                config_class, field_name, answer, config_dict
            )
            if not is_valid:
                click.echo(f"❌ {error_message}" if error_message else "❌ Invalid value")
                continue

            return answer

        except (ValueError, TypeError) as e:
            if is_sensitive_field(field_name, field_info):
                click.echo(
                    f"❌ Error processing sensitive field '{field_name}': Invalid value provided"
                )
            else:
                click.echo(f"❌ Error processing field '{field_name}': {e}")
            return None


def validate_field_value(
    config_class: type[BaseModel],
    field_name: str,
    field_value: Any,
    partial_config: dict[str, Any],
) -> tuple[bool, str | None]:
    """Validate a single field value using Pydantic's field validators.

    Args:
        config_class: The Pydantic model class
        field_name: Name of the field to validate
        field_value: Value to validate
        partial_config: Dictionary of previously validated fields (using field names, not aliases)

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        config_class.model_validate({**partial_config, field_name: field_value})
        return True, None
    except ValidationError as e:
        for error in e.errors():
            error_loc = error.get("loc", ())
            error_msg = error.get("msg", "Invalid value")
            if error_loc and error_loc[0] == field_name:
                return False, error_msg
        return True, None


def prompt_model_fields(  # noqa: C901, PLR0911, PLR0912, PLR0913, PLR0915
    config_class: type[BaseModel],
    *,
    existing_config: dict[str, Any] | None = None,
    section_label: str | None = None,
    skip_fields: set[str] | None = None,
    field_overrides: dict[str, FieldPromptOptions] | None = None,
    allowed_fields: set[str] | None = None,
) -> dict[str, Any] | None:
    """Interactively collect configuration values based on a Pydantic model."""

    existing = existing_config or {}
    skip_fields = skip_fields or set()
    field_overrides = field_overrides or {}

    if section_label:
        click.echo(f"📋 {section_label}")
        click.echo(f"Configure fields for {config_class.__name__}\n")

    config_dict: dict[str, Any] = {}

    while True:
        try:
            for field_name, field_info in config_class.model_fields.items():
                if should_skip_field(
                    field_name,
                    field_info,
                    config_dict,
                    existing,
                    allowed_fields,
                    skip_fields,
                    field_overrides,
                ):
                    continue

                field_value = get_field_value(field_name, field_info, existing)
                env_var, env_value = get_env_value(field_info)
                if env_value is not None:
                    click.echo(f"✓ Using {env_var} from environment for {field_name}")
                    continue

                if is_list_of_models(field_info):
                    result = handle_list_of_models(field_info, field_value)
                    if result is None:
                        return None
                    config_dict[field_name] = result
                    continue

                if is_dict_of_models(field_info):
                    dict_result: dict[str, dict] | None = handle_dict_of_models(
                        field_info, field_value
                    )
                    if dict_result is None:
                        return None
                    config_dict[field_name] = dict_result
                    continue

                if is_plain_dict(field_info):
                    plain_dict_result: dict[str, Any] | None = handle_plain_dict(
                        field_info, field_value
                    )
                    if plain_dict_result is None:
                        return None
                    config_dict[field_name] = plain_dict_result
                    continue

                if is_nested_model(field_info):
                    nested_result = handle_nested_model(field_name, field_info, field_value)
                    if nested_result is None:
                        return None
                    if nested_result:  # empty dict {} means user skipped optional field
                        config_dict[field_name] = nested_result
                    continue

                answer = prompt_single_field(
                    field_name,
                    field_info,
                    field_value,
                    field_overrides,
                    config_class,
                    config_dict,
                )
                if answer is not None:
                    config_dict[field_name] = answer
                elif is_field_required(field_name, field_info, field_overrides):
                    field_description = get_field_description(
                        field_name, field_info, field_overrides
                    )
                    click.echo(
                        f"\n⚠️  Required field '{field_description}' was not provided. "
                        "Configuration cancelled."
                    )
                    return None

            try:
                config_class.model_validate(config_dict)
                return config_dict
            except ValidationError as e:
                click.echo("\n❌ Configuration validation failed:")
                for error in e.errors():
                    error_loc = error.get("loc", ())
                    error_msg = error.get("msg", "Invalid value")
                    if error_loc:
                        click.echo(f"  • {error_loc[0]}: {error_msg}")
                    else:
                        click.echo(f"  • {error_msg}")
                click.echo("\n🔄 Re-running configuration wizard...\n")
                existing = {**existing, **config_dict}
                config_dict = {}

        except KeyboardInterrupt:
            return None

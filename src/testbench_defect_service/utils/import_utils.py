import importlib.util
import inspect
import types
from pathlib import Path


def _discover_subclass_in_module(
    module: types.ModuleType, base_class: type, source: str | Path
) -> type:
    """Return the single subclass of *base_class* defined in *module*.

    Only classes whose ``__module__`` matches the loaded module are considered,
    so names that were merely imported into the file are excluded.

    Args:
        module: The imported module to scan.
        base_class: The base class to search for subclasses of.
        source: File path or module string — used only in error messages.

    Raises:
        ImportError: If zero or more than one matching subclass is found.
    """
    candidates = list(
        {
            obj
            for obj in vars(module).values()
            if inspect.isclass(obj)
            and obj is not base_class
            and obj.__module__ == module.__name__
            and issubclass(obj, base_class)
        }
    )

    if len(candidates) == 1:
        return candidates[0]

    if len(candidates) > 1:
        names = ", ".join(sorted(c.__name__ for c in candidates))
        raise ImportError(
            f"Multiple subclasses of '{base_class.__name__}' found in "
            f"'{source}' ({names}). Pass class_name explicitly."
        )

    raise ImportError(f"No subclass of '{base_class.__name__}' found in '{source}'.")


def import_module_from_file_path(file_path: Path) -> types.ModuleType:
    """Imports a module dynamically from a file path."""
    file_path = Path(file_path).resolve()
    module_name = file_path.stem

    if not file_path.exists() or file_path.suffix != ".py":
        raise FileNotFoundError(f"File '{file_path}' not found or not a .py file.")

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from '{file_path}'.")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return module
    except Exception as e:
        raise ImportError(f"Failed to import module from '{file_path}': {e}") from e


def import_class_from_file_path(
    file_path: Path, class_name: str | None = None, subclass_of: type | None = None
) -> type:
    """Import a class dynamically from a Python source file.

    Resolution order when *class_name* is ``None``:
    1. Derive a candidate name by converting the file stem from snake_case to
       PascalCase (e.g. ``custom_client.py`` → ``CustomClient``) and look that
       name up in the module.
    2. If no matching class is found and *subclass_of* is given, scan the module
       for exactly one subclass (direct or indirect) of *subclass_of* that is
       **defined** in the file — classes that are merely imported into the module
       namespace are excluded.

    Args:
        file_path (Path): Path to the Python source file to import from.
        class_name (str | None): Name of the class to import. When omitted the resolution
            order above is used.
        subclass_of (type | None): When provided the resolved class is validated as a subclass
            (direct or indirect) of this type. Also drives the fallback
            discovery mechanism when *class_name* is ``None``.

    Returns:
        type: The resolved class object.

    Raises:
        ImportError: If the module cannot be loaded, no matching class is found,
            the resolved attribute is not a class, or it fails the
            *subclass_of* constraint.
    """
    try:
        module = import_module_from_file_path(file_path)

        if class_name is None:
            stem = Path(file_path).stem
            pascal_name = "".join(word.capitalize() for word in stem.split("_"))

            candidate = getattr(module, pascal_name, None)
            if inspect.isclass(candidate):
                class_name = pascal_name
            elif subclass_of is not None:
                return _discover_subclass_in_module(module, subclass_of, file_path)
            else:
                raise ImportError(
                    f"No class named '{pascal_name}' found in '{file_path}'. "
                    "Pass class_name explicitly or provide subclass_of for automatic discovery."
                )

        if not hasattr(module, class_name):
            raise ImportError(f"Class '{class_name}' not found in '{file_path}'.")

        imported_class = getattr(module, class_name)
        if not inspect.isclass(imported_class):
            raise ImportError(f"'{class_name}' in '{file_path}' is not a valid class.")

        if subclass_of is not None and not issubclass(imported_class, subclass_of):
            raise ImportError(
                f"Class '{class_name}' in '{file_path}' is not a subclass "
                f"of '{subclass_of.__name__}'."
            )

        return imported_class

    except ImportError:
        raise
    except Exception as e:
        raise ImportError(f"Failed to import class from '{file_path}': {e}") from e


def import_class_from_module_str(
    module_str: str, class_name: str | None = None, subclass_of: type | None = None
) -> type:
    """Import a class dynamically from a module string.

    Args:
        module_str (str): The module import string (e.g., ``"my_package.my_module"``).
            May also include the class name as the last segment
            (e.g., ``"my_package.my_module.MyClass"``).
        class_name (str | None): Name of the class to import. When omitted, the last
            segment of *module_str* is used as the class name. If that name is not
            found in the module and *subclass_of* is provided, the module is scanned
            for exactly one subclass of *subclass_of* that is **defined** in it.
        subclass_of (type | None): When provided the resolved class is validated as a
            subclass (direct or indirect) of this type. Also drives the fallback
            discovery mechanism when *class_name* is ``None``.

    Returns:
        type: The resolved class object.

    Raises:
        ImportError: If the module cannot be loaded, the class is not found,
            the attribute is not a class, or it fails the *subclass_of* constraint.
    """
    infer_class = class_name is None

    try:
        try:
            # Try importing module assuming class name is not included in module_str
            module = importlib.import_module(module_str)
            if class_name is None:
                parts = module_str.rsplit(".", 1)
                if len(parts) < 2:  # noqa: PLR2004
                    raise ImportError(
                        f"Cannot infer class name from module string '{module_str}': no dots found."
                    )
                class_name = parts[1]
        except ModuleNotFoundError:
            # Fallback: the last segment must be the explicit class name embedded in the string.
            resolved_module_str, class_name = module_str.rsplit(".", 1)
            module = importlib.import_module(resolved_module_str)
            infer_class = False

        if not hasattr(module, class_name):
            if infer_class and subclass_of is not None:
                return _discover_subclass_in_module(module, subclass_of, module_str)
            raise ImportError(f"Class '{class_name}' not found in module '{module.__name__}'.")

        imported_class = getattr(module, class_name)
        if not inspect.isclass(imported_class):
            raise ImportError(f"'{class_name}' in module '{module.__name__}' is not a class.")

        if subclass_of is not None and not issubclass(imported_class, subclass_of):
            raise ImportError(
                f"Class '{class_name}' in module '{module.__name__}' is not a subclass "
                f"of '{subclass_of.__name__}'."
            )

        return imported_class

    except ImportError:
        raise
    except Exception as e:
        raise ImportError(f"Failed to import class from '{module_str}': {e}") from e


def get_project_root() -> Path:
    current_path = Path.cwd()
    if (current_path / "pyproject.toml").exists():
        return current_path
    for parent in current_path.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return current_path

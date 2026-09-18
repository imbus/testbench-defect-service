import importlib.metadata
import importlib.util

EXCEL_PACKAGES: list[str] = []
JIRA_PACKAGES: list[str] = ["jira", "beautifulsoup4"]


def _missing_packages(packages: list[str]) -> list[str]:
    """Return a list of packages that are not importable in the current environment.

    This function is robust to the common mismatch between the pip distribution
    name and the importable top-level module name. For example, the package
    installed via "pip install beautifulsoup4" provides the importable
    module "bs4". `importlib.util.find_spec('beautifulsoup4')` will therefore
    return None even though the distribution is installed. To handle this we:

    - first try to find an importable module with the given name,
    - if that fails, fall back to checking whether a distribution with that
      name is installed using importlib.metadata.

    If neither check finds the package it is considered missing.
    """
    missing = []

    for pkg in packages:
        # Quick check: is there an importable module with that name?
        if importlib.util.find_spec(pkg) is not None:
            continue

        # If import failed, check whether a distribution with that name is
        # installed (handles cases like 'beautifulsoup4' -> import 'bs4').
        try:
            importlib.metadata.distribution(pkg)
            continue
        except Exception:
            pass

        missing.append(pkg)

    return missing


def check_excel_dependencies(raise_on_missing: bool = True) -> list[str]:
    """
    Check for Excel-related optional dependencies.

    Args:
        raise_on_missing: if True, raise ImportError when missing packages are found.
                          if False, return the list of missing packages.

    Returns:
        List of missing package names (empty if all present).

    Raises:
        ImportError: when raise_on_missing is True and missing packages exist.
    """
    missing = _missing_packages(EXCEL_PACKAGES)
    if missing and raise_on_missing:
        raise ImportError(
            "Excel functionality is required but missing.\n"
            "To enable Excel support, install the required dependencies with:\n\n"
            "    pip install testbench-defect-service[excel]\n\n"
            f"Missing dependencies: {', '.join(missing)}"
        )
    return missing


def check_jira_dependencies(raise_on_missing: bool = True) -> list[str]:
    """
    Check for JIRA-related optional dependencies.

    Args:
        raise_on_missing: if True, raise ImportError when missing packages are found.
                          if False, return the list of missing packages.

    Returns:
        List of missing package names (empty if all present).

    Raises:
        ImportError: when raise_on_missing is True and missing packages exist.
    """
    missing = _missing_packages(JIRA_PACKAGES)
    if missing and raise_on_missing:
        raise ImportError(
            "JIRA functionality is required but missing.\n"
            "To enable JIRA support, install the required dependencies with:\n\n"
            "    pip install testbench-defect-service[jira]\n\n"
            f"Missing dependencies: {', '.join(missing)}"
        )
    return missing


def is_excel_available() -> bool:
    """Convenience: True when all excel packages are available."""
    return not _missing_packages(EXCEL_PACKAGES)


def is_jira_available() -> bool:
    """Convenience: True when all jira packages are available."""
    return not _missing_packages(JIRA_PACKAGES)


def check_client_dependencies(client_type: str, raise_on_missing: bool = True) -> list[str]:
    """Check dependencies for a specific client type.

    Args:
        client_type: Type of client ('excel', 'jira', 'jsonl', etc.)
        raise_on_missing: if True, raise ImportError when missing packages are found.
                          if False, return the list of missing packages.

    Returns:
        List of missing package names (empty if all present or no checks needed).

    Raises:
        ImportError: when raise_on_missing is True and missing packages exist.
    """
    if client_type == "excel":
        return check_excel_dependencies(raise_on_missing=raise_on_missing)
    if client_type == "jira":
        return check_jira_dependencies(raise_on_missing=raise_on_missing)
    return []

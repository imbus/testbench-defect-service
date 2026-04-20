#!/usr/bin/env python3
# ruff: noqa: T201
"""
Build a self-contained executable for testbench-defect-service using PyInstaller.

The output is a onedir bundle:
    dist/testbench-defect-service/
        testbench-defect-service[.exe]   <- launch this
        ...                                   <- support files

Usage:
    python build_binary.py [options]

Options:
    --spec PATH     Path to the .spec file  [default: testbench-defect-service.spec]
    --no-clean      Keep previous artefacts (faster incremental rebuild)
"""

from __future__ import annotations

import argparse
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.resolve()
INIT_FILE = REPO_ROOT / "src" / "testbench_defect_service" / "__init__.py"
DEFAULT_SPEC = REPO_ROOT / "testbench-defect-service.spec"
DIST_DIR = REPO_ROOT / "dist"
BUILD_DIR = REPO_ROOT / "build"

MIN_PYTHON = (3, 10)


def _check_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        sys.exit(
            f"ERROR: Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required (running {sys.version})."
        )


def _read_version() -> str:
    text = INIT_FILE.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', text, re.MULTILINE)
    if not match:
        sys.exit(f"ERROR: Could not read __version__ from {INIT_FILE}.")
    return match.group(1)


def _binary_name() -> str:
    """Return the platform-specific executable name, e.g. 'testbench-defect-service.exe'."""
    suffix = ".exe" if platform.system() == "Windows" else ""
    return f"testbench-defect-service{suffix}"


def _platform_tag() -> str:
    """Return a compact platform tag, e.g. 'win_amd64' or 'linux_x86_64'."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        return "win_amd64" if machine in ("amd64", "x86_64") else f"win_{machine}"
    if system == "linux":
        arch = "x86_64" if machine in ("amd64", "x86_64") else machine
        return f"linux_{arch}"
    if system == "darwin":
        return f"macos_{machine}"
    return f"{system}_{machine}"


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print(f"\n>>> {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=cwd, check=False)
    if result.returncode != 0:
        sys.exit(f"ERROR: Command failed with exit code {result.returncode}.")


def _ensure_pyinstaller() -> None:
    """Install PyInstaller into the current environment if it is not present."""
    try:
        import PyInstaller  # noqa: PLC0415, F401
    except ImportError:
        print("PyInstaller not found — installing …")
        _run([sys.executable, "-m", "pip", "install", "pyinstaller"])


def _install_package_editable() -> None:
    """
    Install the package in editable mode with the reader extras so that
    PyInstaller's collect_data_files() can locate the package data files
    (openapi.yaml, static/, readers/jsonl/schemas/, …).
    """
    print("Installing package in editable mode with reader extras …")
    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "-e",
            ".[jira]",
        ],
        cwd=REPO_ROOT,
    )


def _clean_artefacts() -> None:
    for directory in (BUILD_DIR, DIST_DIR):
        if directory.exists():
            print(f"Removing {directory} …")
            shutil.rmtree(directory)


def _build(spec: Path) -> None:
    _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(spec),
            "--noconfirm",
        ],
        cwd=REPO_ROOT,
    )


def _zip_output(version: str, platform_tag: str) -> Path:
    """Zip the onedir output folder and return the archive path."""
    bundle_dir = DIST_DIR / "testbench-defect-service"
    if not bundle_dir.exists():
        sys.exit(f"ERROR: Expected output folder not found: {bundle_dir}")

    archive_name = f"testbench-defect-service-{version}-{platform_tag}.zip"
    archive_path = DIST_DIR / archive_name

    print(f"\nCreating archive: {archive_path} …")
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(bundle_dir.rglob("*")):
            if file.is_file():
                zf.write(file, file.relative_to(DIST_DIR))

    return archive_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a self-contained executable using PyInstaller.",
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=DEFAULT_SPEC,
        metavar="PATH",
        help=f"Path to the .spec file  [default: {DEFAULT_SPEC.name}]",
    )
    parser.add_argument(
        "--no-clean",
        dest="clean",
        action="store_false",
        default=True,
        help="Keep previous artefacts (faster incremental rebuild)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    _check_python_version()
    _ensure_pyinstaller()
    _install_package_editable()

    version = _read_version()
    platform_tag = _platform_tag()
    spec: Path = args.spec.resolve()

    if not spec.exists():
        sys.exit(f"ERROR: Spec file not found: {spec}")

    print(f"\nBuilding testbench-defect-service v{version} for {platform_tag} …")

    if args.clean:
        _clean_artefacts()

    _build(spec)

    bundle_dir = DIST_DIR / "testbench-defect-service"
    print(f"\nBuild complete: {bundle_dir}")

    archive = _zip_output(version, platform_tag)
    print(f"Archive:        {archive}")

    binary_path = bundle_dir / _binary_name()
    print(f"\nTo test the executable, run:\n  {binary_path} --version\n")


if __name__ == "__main__":
    main()

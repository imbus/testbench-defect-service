#!/usr/bin/env python3
# ruff: noqa: T201
"""
Download all wheels for every dependency declared in pyproject.toml.

Usage:
    python download_dependencies.py [options]

Options:
    --extras           Comma-separated optional dependency groups (default: excel,jira,sql,dev)
    --platform         Target pip platform tag (default: win_amd64)
    --python-versions  Comma-separated Python versions in compact form (default: 310,311,312,313)
    --dest             Destination root folder for downloads (default: downloads)
    --zip              Also zip each per-version folder as <name>-<version>-<platform>-py<pyver>.zip
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

# tomllib is stdlib from 3.11; use tomli backport on 3.10
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]
    except ImportError as exc:
        print(
            "Missing 'tomli' package. Install via: python -m pip install tomli",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

try:
    from packaging.requirements import Requirement
    from packaging.specifiers import SpecifierSet
    from packaging.utils import canonicalize_name, parse_wheel_filename
    from packaging.version import Version
except ImportError as exc:
    print(
        "Missing 'packaging' module. Install via: python -m pip install packaging",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


def merge_spec(a: SpecifierSet | None, b: SpecifierSet | None) -> SpecifierSet | None:
    """Merge two specifier sets into one combined constraint."""
    if not a:
        return b
    if not b:
        return a
    merged = ",".join(s for s in [str(a), str(b)] if s)
    return SpecifierSet(merged)


def target_env(pyver: str, platform: str) -> dict[str, str]:
    """Build a PEP 508 marker environment dict for the given Python version and platform.

    Args:
        pyver: Python version in compact form, e.g. '310', '311'
        platform: Platform tag, e.g. 'win_amd64', 'manylinux_2_17_x86_64'

    Raises:
        ValueError: If pyver format is invalid
    """
    if not pyver or len(pyver) < 2 or not pyver.isdigit():  # noqa: PLR2004
        raise ValueError(
            f"Invalid Python version format: '{pyver}' (expected compact form like '310', '311')"
        )
    major = int(pyver[0])
    minor = int(pyver[1:])
    ver = f"{major}.{minor}"
    full = f"{ver}.0"
    if platform.startswith("win"):
        sys_platform = "win32"
        platform_system = "Windows"
        platform_machine = "AMD64" if "amd64" in platform else "x86"
        os_name = "nt"
    elif platform.startswith(("manylinux", "linux")):
        sys_platform = "linux"
        platform_system = "Linux"
        platform_machine = "x86_64" if "x86_64" in platform or "amd64" in platform else "aarch64"
        os_name = "posix"
    elif platform.startswith("macosx"):
        sys_platform = "darwin"
        platform_system = "Darwin"
        platform_machine = "arm64" if "arm64" in platform else "x86_64"
        os_name = "posix"
    else:
        sys_platform = "linux"
        platform_system = "Linux"
        platform_machine = "x86_64"
        os_name = "posix"

    return {
        "python_version": ver,
        "python_full_version": full,
        "sys_platform": sys_platform,
        "platform_system": platform_system,
        "platform_machine": platform_machine,
        "platform_python_implementation": "CPython",
        "implementation_name": "cpython",
        "implementation_version": full,
        "os_name": os_name,
    }


def parse_requires_dist(metadata_text: str) -> list[str]:
    """Extract Requires-Dist entries from wheel METADATA content."""
    requires: list[str] = []
    current: str | None = None
    for line in metadata_text.splitlines():
        if line.startswith("Requires-Dist:"):
            if current:
                requires.append(current)
            current = line[len("Requires-Dist:") :].strip()
        elif current and line.startswith(" "):
            current += " " + line.strip()
        elif current:
            requires.append(current)
            current = None
    if current:
        requires.append(current)
    return requires


def find_wheel(dest: Path, name: str) -> Path | None:
    """Return the highest-versioned wheel in *dest* matching the canonical package *name*."""
    candidates: list[tuple[Version, Path]] = []
    for wheel in dest.glob("*.whl"):
        try:
            dist, ver, _build, _tags = parse_wheel_filename(wheel.name)
        except Exception:
            continue
        if canonicalize_name(dist) == name:
            candidates.append((ver, wheel))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def download_with_deps(pyver: str, dest: Path, reqs: list[str], platform: str) -> None:  # noqa: C901
    """Download wheels for *reqs* and all their transitive dependencies."""
    env = target_env(pyver, platform)
    dest.mkdir(parents=True, exist_ok=True)

    specs: dict[str, SpecifierSet | None] = {}
    queue: list[str] = []
    queued: set[str] = set()
    processed: set[str] = set()

    def enqueue(req_str: str) -> None:
        try:
            req = Requirement(req_str)
        except Exception as exc:
            print(
                f"  [!] Failed to parse requirement '{req_str}': {exc} -- skipping.",
                file=sys.stderr,
            )
            return
        try:
            if req.marker and not req.marker.evaluate(env):
                return
        except Exception as exc:
            print(
                f"  [!] Failed to evaluate marker for '{req_str}': {exc} -- including.",
                file=sys.stderr,
            )
        name = canonicalize_name(req.name)
        spec = req.specifier
        merged = merge_spec(specs.get(name), spec)
        if name not in specs or str(specs[name]) != str(merged):
            specs[name] = merged
            if name not in queued and name not in processed:
                queue.append(name)
                queued.add(name)

    for line in reqs:
        enqueue(line)

    while queue:
        name = queue.pop(0)
        queued.discard(name)
        spec = specs.get(name)
        req_str = f"{name}{spec}" if spec else name

        cmd = [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--dest",
            str(dest),
            "--platform",
            platform,
            "--python-version",
            pyver,
            "--implementation",
            "cp",
            "--abi",
            f"cp{pyver}",
            "--only-binary=:all:",
            "--no-deps",
            req_str,
        ]
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            print(
                f"  [!] pip download failed for '{req_str}' (py{pyver}, {platform}) -- skipping.",
                file=sys.stderr,
            )
            processed.add(name)
            continue

        wheel = find_wheel(dest, name)
        if not wheel:
            print(
                f"  [!] Wheel for '{req_str}' not found in {dest} after download -- skipping.",
                file=sys.stderr,
            )
            processed.add(name)
            continue

        with zipfile.ZipFile(wheel) as zf:
            meta_name = next(
                (n for n in zf.namelist() if n.endswith(".dist-info/METADATA")),
                None,
            )
            if not meta_name:
                processed.add(name)
                continue
            metadata = zf.read(meta_name).decode("utf-8", "replace")

        for dep in parse_requires_dist(metadata):
            enqueue(dep)

        processed.add(name)


def zip_folder(folder: Path, zip_path: Path) -> None:
    """Create (or overwrite) a zip archive of *folder*."""
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in folder.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(folder))


def _read_pyproject(root: Path) -> dict:
    """Parse pyproject.toml and return the full data dict.

    Raises:
        SystemExit: If the file is missing, unreadable, or contains invalid TOML
    """
    path = root / "pyproject.toml"
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        print(
            f"Configuration Error: pyproject.toml not found at '{path.resolve()}'.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    except tomllib.TOMLDecodeError as exc:
        print(
            f"Configuration Error: pyproject.toml contains invalid TOML.\n  Detail: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    except OSError as exc:
        print(
            f"Configuration Error: Could not read pyproject.toml: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


def get_project_metadata(root: Path) -> tuple[str, str]:
    """Return (normalized_name, version) derived from pyproject.toml.

    When version is declared dynamic (flit convention), it is read from the
    package's ``__init__.py`` via a ``__version__ = "..."`` assignment.

    Raises:
        SystemExit: If pyproject.toml is missing required fields
    """
    try:
        data = _read_pyproject(root)
        project = data["project"]
    except KeyError as exc:
        print(
            f"Configuration Error: Invalid pyproject.toml structure (missing {exc}).",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    name: str | None = project.get("name")
    if not name:
        print(
            "Configuration Error: pyproject.toml missing [project] name field.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    normalized = name.replace("-", "_")

    if "version" in project.get("dynamic", []):
        # flit reads __version__ from the module; honour [tool.flit.module] if set
        module_name: str = data.get("tool", {}).get("flit", {}).get("module", normalized)
        for candidate in [
            root / "src" / module_name / "__init__.py",
            root / module_name / "__init__.py",
        ]:
            if candidate.exists():
                content = candidate.read_text(encoding="utf-8")
                m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
                if m:
                    return normalized, m.group(1)
        print(
            f"Configuration Warning: Could not find __version__ in {module_name}/__init__.py -- using 'unknown'.",  # noqa: E501
            file=sys.stderr,
        )
        return normalized, "unknown"

    return normalized, project.get("version", "unknown")


def load_requirements(root: Path, extras_csv: str) -> list[str]:
    """Read all dependency strings (core + requested extras) from pyproject.toml.

    Raises:
        SystemExit: If pyproject.toml is missing required fields
    """
    try:
        data = _read_pyproject(root)
        project = data["project"]
    except KeyError as exc:
        print(
            f"Configuration Error: Invalid pyproject.toml structure (missing {exc}).",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    reqs = list(project.get("dependencies", []))
    opt = project.get("optional-dependencies", {})
    extras = [e.strip() for e in extras_csv.split(",") if e.strip()]
    for e in extras:
        if e not in opt:
            print(f"  [!] Extra '{e}' not found in pyproject.toml -- skipping.", file=sys.stderr)
            continue
        reqs.extend(opt[e])
    return reqs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download all dependency wheels declared in pyproject.toml."
    )
    parser.add_argument(
        "--extras",
        default="excel,jira,sql,dev",
        help="Comma-separated optional dependency groups to include (default: excel,jira,sql,dev).",
    )
    parser.add_argument(
        "--platform",
        default="win_amd64",
        help=(
            "Target platform tag for wheel downloads. "
            "Examples: win_amd64, win32, manylinux_2_17_x86_64, macosx_11_0_arm64."
        ),
    )
    parser.add_argument(
        "--python-versions",
        default="310,311,312,313,314",
        help="Comma-separated Python versions in compact form (default: 310,311,312,313,314).",
    )
    parser.add_argument(
        "--dest",
        default="downloads",
        help="Destination root for downloads (default: downloads).",
    )
    parser.add_argument(
        "--zip",
        action="store_true",
        help="Zip each per-version folder as <name>-<version>-<platform>-py<pyver>.zip into --dest.",  # noqa: E501
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    reqs = load_requirements(root, args.extras)
    pkg_name, pkg_version = get_project_metadata(root)

    dest_root = root / args.dest / pkg_version / args.platform
    for pyver in [v.strip() for v in args.python_versions.split(",") if v.strip()]:
        try:
            print(f"\n--- {pkg_name}-{pkg_version} / {args.platform} / py{pyver} ---")
            dest = dest_root / f"py{pyver}"
            download_with_deps(pyver, dest, reqs, args.platform)
        except ValueError as exc:
            print(f"  [!] Skipping py{pyver}: {exc}", file=sys.stderr)
            continue
        if args.zip:
            zip_root = root / args.dest
            zip_root.mkdir(parents=True, exist_ok=True)
            zip_path = zip_root / f"{pkg_name}-{pkg_version}-{args.platform}-py{pyver}.zip"
            print(f"  Zipping -> {zip_path}")
            zip_folder(dest, zip_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# ruff: noqa: T201
"""
Generate README.dist.md for PyPI by replacing relative docs/ links
with their published equivalents on the documentation site.

Usage:
    python build_readme.py

Output:
    README.dist.md  (used by flit as the PyPI long description)
"""

import re
from pathlib import Path

DOCS_BASE_URL = "https://testbench-ecosystem-documentation.surge.sh/"
SOURCE = Path("README.md")
OUTPUT = Path("README.dist.md")


def docs_link_to_url(match: re.Match) -> str:
    """Convert a relative docs/ link to an absolute documentation URL."""
    path = match.group(1)  # e.g. "getting-started/installation"
    return f"]({DOCS_BASE_URL}/{path})"


def build() -> None:
    content = SOURCE.read_text(encoding="utf-8")

    # Replace ](docs/path/to/file.md) → ](https://.../path/to/file)
    content = re.sub(
        r"\]\(docs/([^)]+?)\.md\)",
        docs_link_to_url,
        content,
    )

    OUTPUT.write_text(content, encoding="utf-8")
    print(f"Written {OUTPUT}  ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    build()

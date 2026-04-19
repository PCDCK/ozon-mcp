"""Guards that the version string is in sync across pyproject, package, and CHANGELOG."""

from __future__ import annotations

import tomllib
from pathlib import Path

import ozon_mcp

ROOT = Path(__file__).resolve().parent.parent.parent


def test_version_matches_pyproject() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert ozon_mcp.__version__ == pyproject["project"]["version"]


def test_version_in_changelog() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    marker = f"## [{ozon_mcp.__version__}]"
    assert marker in changelog, f"Version {ozon_mcp.__version__} not found in CHANGELOG.md"

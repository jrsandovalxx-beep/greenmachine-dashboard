"""Smoke tests for the GM-001 package scaffolding.

These assert only that the package is installed, importable, and that its version
is exposed from a single source of truth. No behaviour is tested, because none
exists yet.
"""

from __future__ import annotations

import importlib
import tomllib
from importlib.metadata import version as distribution_version
from pathlib import Path

import pytest

import greenmachine

PYPROJECT_PATH = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_package_imports() -> None:
    """The installed package can be imported by name."""
    module = importlib.import_module("greenmachine")

    assert module.__name__ == "greenmachine"


def test_version_is_exposed() -> None:
    """``greenmachine.__version__`` is a non-empty string."""
    assert isinstance(greenmachine.__version__, str)
    assert greenmachine.__version__


def test_version_matches_pyproject() -> None:
    """The exposed version agrees with pyproject.toml and distribution metadata.

    The version is declared only in pyproject.toml, so this guards against a stale
    installed distribution rather than against duplicated literals in source.
    """
    if not PYPROJECT_PATH.exists():
        pytest.skip("pyproject.toml is unavailable outside a source checkout")

    with PYPROJECT_PATH.open("rb") as handle:
        pyproject = tomllib.load(handle)

    declared_version = pyproject["project"]["version"]

    assert distribution_version("greenmachine") == declared_version
    assert greenmachine.__version__ == declared_version


def test_version_resolves_without_installed_distribution_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The uninstalled source-tree deployment path (Streamlit Community Cloud
    installs only requirements.txt) must resolve the version from the adjacent
    pyproject.toml instead of crashing at import.

    Regression for the 2026-07-25 Community Cloud outage: the previous
    ``__init__`` raised ``RuntimeError`` whenever distribution metadata was
    absent, and the local requirements-only smoke had been masked by a stray
    ``src/greenmachine.egg-info`` build artifact that never ships.
    """
    import importlib.metadata

    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)
    reloaded = importlib.reload(greenmachine)
    try:
        with PYPROJECT_PATH.open("rb") as handle:
            declared_version = tomllib.load(handle)["project"]["version"]
        assert reloaded.__version__ == declared_version
    finally:
        monkeypatch.undo()
        importlib.reload(greenmachine)

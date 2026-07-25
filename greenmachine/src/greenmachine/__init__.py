"""GreenMachine: a deterministic MLB home-run grading and research platform.

The package version is declared once, in ``pyproject.toml``, and never
duplicated in source. It is resolved from the installed distribution metadata
when the project is installed; when the package runs **uninstalled from the
source tree** (the supported Streamlit Community Cloud deployment: the root
``requirements.txt`` alone, with ``src/`` placed on ``sys.path`` by the
composition root), the same ``pyproject.toml`` is read directly — so the two
still cannot drift, and requirements installation alone is sufficient to run.
"""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _version_from_source_tree() -> str:
    """The single declared version, read from the adjacent ``pyproject.toml``.

    Only reachable when the distribution is not installed, which is exactly
    the uninstalled source-tree layout: ``<root>/pyproject.toml`` beside
    ``<root>/src/greenmachine/__init__.py``.
    """
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        raw = pyproject.read_text(encoding="utf-8")
    except OSError as exc:
        message = (
            "The greenmachine distribution is not installed and no adjacent "
            "pyproject.toml exists, so its version cannot be resolved. Install "
            "the project (pip install -e .) or run it from a complete source tree."
        )
        raise RuntimeError(message) from exc
    declared = tomllib.loads(raw)["project"]["version"]
    if not isinstance(declared, str):  # pragma: no cover - pyproject is validated in CI
        raise RuntimeError("pyproject.toml declares a non-string project version")
    return declared


try:
    __version__ = version("greenmachine")
except PackageNotFoundError:
    __version__ = _version_from_source_tree()

__all__ = ["__version__"]

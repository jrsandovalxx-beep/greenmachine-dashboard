"""GreenMachine: a deterministic MLB home-run grading and research platform.

The package version is declared once, in ``pyproject.toml``. It is read here from
the installed distribution metadata rather than duplicated in source, so the two
can never drift apart.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("greenmachine")
except PackageNotFoundError as exc:  # pragma: no cover - only reachable when not installed
    message = (
        "The greenmachine distribution is not installed, so its version cannot be "
        "resolved. Install the project in editable mode first: make install"
    )
    raise RuntimeError(message) from exc

__all__ = ["__version__"]

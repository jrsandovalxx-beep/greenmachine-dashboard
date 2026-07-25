"""Centralized launcher for guarded Python test subprocesses (GM-008).

Every Python child the test suite spawns goes through
:func:`guarded_python_command` (or the :func:`run_guarded_python`
convenience), which routes the invocation through ``child_bootstrap.py`` so
the GreenMachine network guard is installed before the child payload runs —
portably, regardless of any competing ``sitecustomize``. An architecture guard
enforces that ``sys.executable`` appears in no other test file, so an
unguarded direct child invocation cannot slip in.

Supported forms mirror the interpreter's own::

    guarded_python_command("-c", PROGRAM, *args)
    guarded_python_command("-m", MODULE, *args)
    guarded_python_command(str(SCRIPT), *args)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

GUARD_DIR = Path(__file__).resolve().parent
CHILD_BOOTSTRAP = GUARD_DIR / "child_bootstrap.py"


def guarded_python_command(*arguments: str) -> list[str]:
    """The argv for a guarded Python child running the given invocation form."""
    return [sys.executable, str(CHILD_BOOTSTRAP), *arguments]


def run_guarded_python(
    *arguments: str,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 240,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a guarded Python child, capturing text output."""
    return subprocess.run(
        guarded_python_command(*arguments),
        capture_output=True,
        text=True,
        cwd=None if cwd is None else str(cwd),
        env=env,
        timeout=timeout,
        check=check,
    )

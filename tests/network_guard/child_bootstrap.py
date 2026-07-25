"""Explicit guarded entry point for every Python child the test suite spawns.

Test-only support code (GM-008): the **primary** child network-guard
mechanism. The suite never launches ``python -c/-m/script`` directly; it
launches::

    python child_bootstrap.py -c PROGRAM [ARG ...]
    python child_bootstrap.py -m MODULE  [ARG ...]
    python child_bootstrap.py SCRIPT.py  [ARG ...]

mirroring the interpreter's own invocation forms. The bootstrap imports
``greenmachine_network_guard`` from its own directory — resolved from this
file's location, independent of ``PYTHONPATH`` and of any competing
``sitecustomize`` anywhere on ``sys.path`` — and calls ``install()``
**before** the supplied program, module, or script executes. There is no
fallback path that runs the payload unguarded: a failure to install the guard
fails the child loudly.

``sys.argv`` is rewritten to what the payload would see under the mirrored
plain invocation, and ``SystemExit`` from the payload propagates unchanged so
exit codes are preserved. Not production code; never imported by the package.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

_GUARD_DIR = Path(__file__).resolve().parent

_USAGE = "usage: child_bootstrap.py (-c PROGRAM | -m MODULE | SCRIPT) [ARG ...]"


def _install_guard() -> None:
    """Import the installer from this file's own directory and apply it."""
    entry = str(_GUARD_DIR)
    if entry not in sys.path:
        sys.path.insert(0, entry)
    import greenmachine_network_guard

    greenmachine_network_guard.install()


def main() -> int:
    _install_guard()

    arguments = sys.argv[1:]
    if not arguments:
        print(_USAGE, file=sys.stderr)
        return 2

    form = arguments[0]
    if form == "-c":
        if len(arguments) < 2:
            print(_USAGE, file=sys.stderr)
            return 2
        program = arguments[1]
        sys.argv = ["-c", *arguments[2:]]
        exec(compile(program, "<guarded child -c>", "exec"), {"__name__": "__main__"})
        return 0

    if form == "-m":
        if len(arguments) < 2:
            print(_USAGE, file=sys.stderr)
            return 2
        module = arguments[1]
        sys.argv = [module, *arguments[2:]]
        runpy.run_module(module, run_name="__main__", alter_sys=True)
        return 0

    script = arguments[0]
    sys.argv = [script, *arguments[1:]]
    # Mirror `python SCRIPT`: the script's directory leads sys.path.
    sys.path.insert(0, str(Path(script).resolve().parent))
    runpy.run_path(script, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())

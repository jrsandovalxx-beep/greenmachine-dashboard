"""Shared pytest configuration for the GreenMachine test suite.

Three suite-wide concerns live here:

**Import paths.** The GM-006 synthetic record builders under
``tests/fixtures/evaluations`` are shared by several suites and are placed on
``sys.path``. The repository root is also inserted so the GM-008 golden harness
has one canonical import name everywhere: ``tests.golden.runner`` and
``tests.golden.stub_scorer``.

**Hypothesis profiles (GM-008).** The deterministic profiles are *registered*
here — registration must happen before the Hypothesis pytest plugin's
``pytest_configure`` resolves the ``--hypothesis-profile`` and
``--hypothesis-seed`` options, and only this root conftest is imported that
early. The **fixed seed 20260724** is supplied through Hypothesis's supported
pytest mechanism via ``addopts`` in ``pyproject.toml``; the CI profile
deliberately sets ``derandomize=False`` so that explicit seed — not a
derandomized derivation — genuinely drives example generation. Which profile
is *loaded* is decided in ``tests/property/conftest.py``, beside the property
suite it governs.

**Network blocking (GM-008).** An autouse session fixture makes every network
operation fail immediately: TCP/stream connections (``connect``,
``connect_ex``, ``create_connection``), datagram sends (``sendto``, and
``sendmsg`` where the platform provides it), and name resolution
(``getaddrinfo``, ``gethostbyname``, ``gethostbyname_ex``, ``gethostbyaddr``)
— IPv4 and IPv6 alike. Every guard raises before any system call, so no DNS
lookup and no packet ever occurs. There is no opt-out flag and no environment
variable that disables it. Local filesystem and subprocess use remain
untouched.

Child Python processes spawned by the suite carry an equivalent guard through
two mechanisms. **Primary:** every test-spawned Python child is launched
through the explicit bootstrap (``tests/network_guard/child_bootstrap.py``,
via ``tests.network_guard.guarded_child``), which installs the guard before
the child payload executes — portably, regardless of any competing
``sitecustomize`` anywhere on ``sys.path``; an architecture guard confines
``sys.executable`` to the launcher so no unguarded child invocation exists.
**Secondary defense:** this fixture also prepends ``tests/network_guard`` to
the child ``PYTHONPATH`` so the ``site`` module imports that directory's
test-only ``sitecustomize`` where the environment permits it. The only
environment key this conftest ever touches is ``PYTHONPATH``, for exactly this
purpose — asserted by the architecture guards.

Pytest configuration itself lives in ``pyproject.toml`` under
``[tool.pytest.ini_options]``, not here.
"""

from __future__ import annotations

import os
import socket
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from hypothesis import settings

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EVALUATION_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "evaluations"
_NETWORK_GUARD_DIR = _REPO_ROOT / "tests" / "network_guard"

for _entry in (str(_REPO_ROOT), str(_EVALUATION_FIXTURES)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)


# --------------------------------------------------------------------------
# Hypothesis profile registration (loaded/documented in tests/property/conftest.py)
# --------------------------------------------------------------------------

# Deterministic CI profile. The seed is the explicit fixed value 20260724,
# delivered via --hypothesis-seed in pyproject addopts; derandomize stays False
# because Hypothesis prefers derandomization over a forced seed, and the fixed
# seed is the configured mechanism. In-memory examples only (no persistent
# database), no wall-clock deadline, an explicit example budget, and no health
# check suppressed. Registration is idempotent.
settings.register_profile(
    "greenmachine-ci",
    derandomize=False,
    database=None,
    deadline=None,
    max_examples=50,
    print_blob=False,
)

# Deliberate local override for exploratory bug-hunting: a larger budget, and
# typically combined with --hypothesis-seed=random to leave the fixed seed
# behind. Never the default; select it explicitly with
# ``pytest --hypothesis-profile=greenmachine-exploratory``.
settings.register_profile(
    "greenmachine-exploratory",
    derandomize=False,
    database=None,
    deadline=None,
    max_examples=200,
)


# --------------------------------------------------------------------------
# Suite-wide network blocking
# --------------------------------------------------------------------------


class NetworkAccessBlockedError(RuntimeError):
    """Raised when a test attempts any network operation."""


def _blocked(entry_point: str) -> NetworkAccessBlockedError:
    return NetworkAccessBlockedError(
        f"network access is prohibited in tests: the GreenMachine suite is fully local and "
        f"deterministic, and {entry_point} attempted a network operation (GM-008 network policy)"
    )


# Every socket entry point the guard closes: connection paths, datagram paths,
# and resolver paths. ``sendmsg`` is patched only where the platform provides
# it. One registry drives patching *and* restoration, so nothing can be
# patched without being restored.
_SOCKET_METHOD_NAMES = ("connect", "connect_ex", "sendto", "sendmsg")
_MODULE_FUNCTION_NAMES = (
    "create_connection",
    "getaddrinfo",
    "gethostbyname",
    "gethostbyname_ex",
    "gethostbyaddr",
)


def _guard_targets() -> list[tuple[object, str, str]]:
    targets: list[tuple[object, str, str]] = [
        (socket.socket, name, f"socket.socket.{name}")
        for name in _SOCKET_METHOD_NAMES
        if hasattr(socket.socket, name)
    ]
    targets.extend(
        (socket, name, f"socket.{name}") for name in _MODULE_FUNCTION_NAMES if hasattr(socket, name)
    )
    return targets


def _make_blocked(entry_point: str) -> object:
    def blocked(*args: object, **kwargs: object) -> object:
        raise _blocked(entry_point)

    return blocked


@pytest.fixture(autouse=True, scope="session")
def blocked_network() -> Iterator[None]:
    """Fail every network operation immediately, for the whole session.

    Also arranges the *secondary* child-process defense: ``tests/network_guard``
    is prepended to ``PYTHONPATH`` so a Python subprocess imports the test-only
    ``sitecustomize`` there where the environment permits. The primary child
    mechanism is the explicit ``child_bootstrap.py`` launcher, which does not
    depend on this. Every patched attribute and the previous ``PYTHONPATH`` are
    restored on teardown.
    """
    targets = _guard_targets()
    originals = [(owner, name, getattr(owner, name)) for owner, name, _ in targets]
    for owner, name, entry_point in targets:
        setattr(owner, name, _make_blocked(entry_point))

    previous_pythonpath = os.environ.get("PYTHONPATH")
    guard_entry = str(_NETWORK_GUARD_DIR)
    os.environ["PYTHONPATH"] = (
        guard_entry
        if previous_pythonpath is None
        else guard_entry + os.pathsep + previous_pythonpath
    )
    try:
        yield
    finally:
        for owner, name, original in originals:
            setattr(owner, name, original)
        if previous_pythonpath is None:
            del os.environ["PYTHONPATH"]
        else:
            os.environ["PYTHONPATH"] = previous_pythonpath

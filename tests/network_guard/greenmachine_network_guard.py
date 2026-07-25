"""The GreenMachine child-process socket guard: one installer, imported explicitly.

Test-only support code (GM-008). :func:`install` patches every socket entry
point the suite prohibits — connection paths (``connect``, ``connect_ex``,
``create_connection``), datagram paths (``sendto``, and ``sendmsg`` where the
platform provides it), and resolver paths (``getaddrinfo``, ``gethostbyname``,
``gethostbyname_ex``, ``gethostbyaddr``) — so every blocked operation raises
before any system call: no DNS lookup and no packet ever leaves the process.

Two callers, by design:

* ``child_bootstrap.py`` — the **primary** mechanism. Every Python subprocess
  the test suite spawns runs through that explicit bootstrap, which imports
  this module and calls :func:`install` before the child payload executes. It
  works regardless of any competing ``sitecustomize`` anywhere on ``sys.path``.
* ``sitecustomize.py`` (this directory) — **secondary defense only**, active
  when the ``site`` module happens to import it via ``PYTHONPATH``. It is never
  relied upon: another environment-provided ``sitecustomize`` earlier on
  ``sys.path`` can silently displace it, which is exactly why the bootstrap
  exists.

Installation is idempotent and is never undone: the policy holds for the
child's lifetime.
"""

from __future__ import annotations

import socket

_SOCKET_METHOD_NAMES = ("connect", "connect_ex", "sendto", "sendmsg")
_MODULE_FUNCTION_NAMES = (
    "create_connection",
    "getaddrinfo",
    "gethostbyname",
    "gethostbyname_ex",
    "gethostbyaddr",
)


class NetworkAccessBlockedError(RuntimeError):
    """Raised when a child test process attempts any network operation."""


def _make_blocked(entry_point: str) -> object:
    def blocked(*args: object, **kwargs: object) -> object:
        raise NetworkAccessBlockedError(
            f"network access is prohibited in tests: the GreenMachine suite is fully local "
            f"and deterministic, and {entry_point} attempted a network operation "
            f"(GM-008 network policy, child-process guard)"
        )

    return blocked


def install() -> None:
    """Install the no-network policy on this interpreter. Idempotent."""
    for name in _SOCKET_METHOD_NAMES:
        if hasattr(socket.socket, name):
            setattr(socket.socket, name, _make_blocked(f"socket.socket.{name}"))
    for name in _MODULE_FUNCTION_NAMES:
        if hasattr(socket, name):
            setattr(socket, name, _make_blocked(f"socket.{name}"))

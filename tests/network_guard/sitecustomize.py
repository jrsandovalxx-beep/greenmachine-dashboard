"""SECONDARY-DEFENSE child network guard for the GreenMachine suite (GM-008).

This module is **not** the enforcement mechanism, and the suite never relies
on it: Python imports at most one module named ``sitecustomize``, so an
environment that ships its own — or injects one ahead of ``PYTHONPATH`` —
silently displaces this file. The **primary** mechanism is the explicit
``child_bootstrap.py`` in this directory, through which every Python
subprocess the tests spawn is launched; it installs the same guard
unconditionally, before the child payload executes.

This shim exists only as defense in depth for the case where the ``site``
module does import it (the root ``tests/conftest.py`` prepends this directory
to ``PYTHONPATH`` for the session): then even a Python child spawned outside
the approved launcher would start with the guard installed. Not production
code; never imported by the package.
"""

from __future__ import annotations

import greenmachine_network_guard

greenmachine_network_guard.install()

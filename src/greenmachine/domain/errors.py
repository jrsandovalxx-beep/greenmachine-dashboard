"""Typed errors for domain-object construction.

These sit under the project taxonomy defined in ADR-0007, so a caller may catch
``GreenMachineError`` and be certain nothing the project raises deliberately
escapes.

**This module is the one approved exception to the domain's import isolation.**
It imports :mod:`greenmachine.common.errors` and nothing else — that module
holds only exception classes and an immutable context, reads no clock, no
environment, and no filesystem, and itself imports nothing from GreenMachine. No
other domain module may import ``common``, and an architecture test enforces
exactly that boundary: this file may reach ``common.errors``, and nothing may
reach ``common.numeric``, ``common.clock``, ``common.serialization``,
``common.ids``, or ``common.logging``.

:class:`DomainValidationError` also subclasses :class:`ValueError`, because a
rejected constructor argument is by Python convention a value error — callers
already catching ``ValueError`` keep working.
"""

from __future__ import annotations

from greenmachine.common.errors import DomainInvariantError

__all__ = ["DomainError", "DomainValidationError"]


class DomainError(DomainInvariantError):
    """Base class for every error raised by :mod:`greenmachine.domain`.

    A subclass of :class:`~greenmachine.common.errors.DomainInvariantError`, and
    therefore of ``GreenMachineError``: a domain failure always means an object
    was asked to exist in a state the model forbids.
    """


class DomainValidationError(DomainError, ValueError):
    """A domain object was constructed with values that violate an invariant.

    Raised for missing or empty required fields, disordered windows, naive
    datetimes, non-finite ``Decimal`` values, negative counts, and similar
    construction-time rule violations. It never encodes a *baseball* rule — only
    the structural invariants that make an object well-formed.

    Like every :class:`~greenmachine.common.errors.GreenMachineError` it accepts
    an optional :class:`~greenmachine.common.errors.ErrorContext`; existing raise
    sites pass a message alone and keep working unchanged.
    """

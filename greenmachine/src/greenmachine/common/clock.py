"""Clock port: time is injected, never read from inside the core.

ENGINEERING_GUIDELINES D2 — ``datetime.now()`` appears only at the composition
root. :class:`SystemClock` is the one implementation permitted to read real time,
and a static architecture test enforces that by rejecting a clock read anywhere
else in ``src/``.

Nothing here is instantiated at import time, and no module-level timestamp
exists: importing this module reads no clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from .errors import DataInputError

__all__ = ["Clock", "ClockError", "FixedClock", "SystemClock"]

_UTC_OFFSET = timedelta(0)


class ClockError(DataInputError, ValueError):
    """A clock was given a time it cannot represent.

    Reparented under :class:`~greenmachine.common.errors.DataInputError` by
    GM-009; ``ValueError`` is retained for callers already catching it.
    """


@runtime_checkable
class Clock(Protocol):
    """Supplies the current instant as a timezone-aware UTC datetime.

    A Protocol rather than a base class, so an implementation is anything with a
    conforming ``now()`` — no inheritance required (ENGINEERING_GUIDELINES 7).
    """

    def now(self) -> datetime:
        """Return the current instant, timezone-aware and in UTC."""
        ...


class SystemClock:
    """Reads real wall-clock time. **The only permitted real-time reader.**

    Instantiate it at the composition root and inject it; never reach for it from
    inside the grading core, which must be a pure function of its inputs.

    The read happens when :meth:`now` is called, never at import or construction,
    so merely importing this module has no dependence on the current time.
    """

    __slots__ = ()

    def now(self) -> datetime:
        """Return the current instant as a timezone-aware UTC datetime."""
        return datetime.now(UTC)

    def __repr__(self) -> str:
        return "SystemClock()"


@dataclass(frozen=True, slots=True)
class FixedClock:
    """Returns one explicitly supplied instant, forever. For tests and replay.

    Frozen, so the time cannot drift mid-test, and the instant must be supplied
    by the caller: there is no default and nothing is generated. Determinism tests
    for the evaluation envelope depend on this being fully controlled
    (ENGINEERING_GUIDELINES D7).

    Raises:
        ClockError: if the instant is naive or is not at UTC offset ``00:00``.
    """

    moment: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.moment, datetime):
            raise ClockError(
                f"FixedClock.moment must be a datetime, got {type(self.moment).__name__}"
            )
        if self.moment.tzinfo is None or self.moment.utcoffset() is None:
            raise ClockError("FixedClock.moment must be timezone-aware, got a naive datetime")
        if self.moment.utcoffset() != _UTC_OFFSET:
            raise ClockError(
                f"FixedClock.moment must be in UTC (offset 00:00), got offset "
                f"{self.moment.utcoffset()}"
            )

    def now(self) -> datetime:
        """Return the fixed instant. Always the same value."""
        return self.moment

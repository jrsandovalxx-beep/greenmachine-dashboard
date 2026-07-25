"""Clock port: injected time, with exactly one permitted real-time reader."""

from __future__ import annotations

import ast
import dataclasses
import importlib
import subprocess
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from greenmachine.common import Clock, ClockError, FixedClock, SystemClock

EASTERN = timezone(timedelta(hours=-4))
MOMENT = datetime(2026, 7, 15, 16, 30, tzinfo=UTC)

CLOCK_SOURCE = Path(__file__).resolve().parents[3] / "src" / "greenmachine" / "common" / "clock.py"


# --------------------------------------------------------------------------
# FixedClock
# --------------------------------------------------------------------------


def test_fixed_clock_returns_its_supplied_instant() -> None:
    clock = FixedClock(MOMENT)

    assert clock.now() == MOMENT


def test_fixed_clock_fully_controls_time() -> None:
    """Repeated reads never advance: a dependent component sees one instant."""
    clock = FixedClock(MOMENT)

    assert {clock.now() for _ in range(100)} == {MOMENT}


def test_fixed_clock_controls_a_dependent_component() -> None:
    def stamp(clock: Clock) -> datetime:
        return clock.now()

    assert stamp(FixedClock(MOMENT)) == MOMENT


def test_fixed_clock_requires_an_explicit_instant() -> None:
    """No default and nothing generated: the caller supplies the time."""
    with pytest.raises(TypeError):
        FixedClock()  # type: ignore[call-arg]


def test_fixed_clock_rejects_a_naive_datetime() -> None:
    with pytest.raises(ClockError, match=r"timezone-aware"):
        FixedClock(datetime(2026, 7, 15, 16, 30))


def test_fixed_clock_rejects_a_non_utc_datetime() -> None:
    with pytest.raises(ClockError, match=r"must be in UTC"):
        FixedClock(datetime(2026, 7, 15, 12, 30, tzinfo=EASTERN))


def test_fixed_clock_rejects_a_non_datetime() -> None:
    with pytest.raises(ClockError, match=r"must be a datetime"):
        FixedClock("2026-07-15T16:30:00Z")  # type: ignore[arg-type]


def test_fixed_clock_accepts_a_zero_offset_zone_that_is_not_the_utc_singleton() -> None:
    equivalent = timezone(timedelta(0))

    assert FixedClock(datetime(2026, 7, 15, 16, 30, tzinfo=equivalent)).now() == MOMENT


def test_fixed_clock_is_frozen() -> None:
    clock = FixedClock(MOMENT)

    with pytest.raises(dataclasses.FrozenInstanceError):
        clock.moment = datetime(2027, 1, 1, tzinfo=UTC)


def test_fixed_clocks_with_the_same_instant_are_equal() -> None:
    assert FixedClock(MOMENT) == FixedClock(MOMENT)
    assert hash(FixedClock(MOMENT)) == hash(FixedClock(MOMENT))


# --------------------------------------------------------------------------
# SystemClock
# --------------------------------------------------------------------------


def test_system_clock_returns_an_aware_utc_datetime() -> None:
    moment = SystemClock().now()

    assert moment.tzinfo is not None
    assert moment.utcoffset() == timedelta(0)


def test_system_clock_reads_time_when_called_not_when_constructed() -> None:
    clock = SystemClock()
    first = clock.now()
    second = clock.now()

    assert second >= first


def test_system_clock_holds_no_state() -> None:
    assert not hasattr(SystemClock(), "__dict__")


def test_system_clock_repr_is_stable() -> None:
    """Stateless, so its repr carries no address or timestamp."""
    assert repr(SystemClock()) == "SystemClock()"
    assert repr(SystemClock()) == repr(SystemClock())


# --------------------------------------------------------------------------
# Protocol conformance
# --------------------------------------------------------------------------


@pytest.mark.parametrize("clock", [SystemClock(), FixedClock(MOMENT)])
def test_both_clocks_satisfy_the_protocol(clock: Clock) -> None:
    assert isinstance(clock, Clock)


def test_an_arbitrary_conforming_object_satisfies_the_protocol() -> None:
    """A Protocol, not a base class: no inheritance required."""

    class StubClock:
        def now(self) -> datetime:
            return MOMENT

    assert isinstance(StubClock(), Clock)


# --------------------------------------------------------------------------
# No import-time clock read
# --------------------------------------------------------------------------


def test_importing_the_module_reads_no_clock() -> None:
    """A fresh import must not capture a timestamp at module scope.

    Checked in a subprocess rather than with ``importlib.reload``. Reloading
    re-executes the module and rebinds its classes, so ``clock.ClockError``
    would become a *different* class object from the one ``common.__init__``
    already holds — after which ``pytest.raises(ClockError)`` silently stops
    matching in unrelated tests. A subprocess proves the same property with no
    effect on this interpreter's module registry.
    """
    probe = (
        "from datetime import datetime\n"
        "import greenmachine.common.clock as clock\n"
        "stamps = [n for n, v in vars(clock).items()"
        " if isinstance(v, datetime) and not n.startswith('__')]\n"
        "print(stamps)\n"
    )
    from tests.network_guard.guarded_child import guarded_python_command

    completed = subprocess.run(
        guarded_python_command("-c", probe), capture_output=True, text=True, check=True
    )

    assert completed.stdout.strip() == "[]"


def test_importing_the_module_does_not_rebind_its_error_class() -> None:
    """The class the package exports is the one the module raises.

    Guards the identity that ``pytest.raises(ClockError)`` depends on across the
    whole suite.
    """
    import greenmachine.common as common_package
    import greenmachine.common.clock as clock_module

    assert clock_module.ClockError is common_package.ClockError


def test_no_clock_is_instantiated_at_module_scope() -> None:
    module = importlib.import_module("greenmachine.common.clock")

    instances = [
        name for name, value in vars(module).items() if isinstance(value, SystemClock | FixedClock)
    ]

    assert instances == []


def test_the_clock_read_lives_only_inside_system_clock_now() -> None:
    """Structural: the single datetime.now call is inside SystemClock.now."""
    tree = ast.parse(CLOCK_SOURCE.read_text(encoding="utf-8"))
    locations: list[str] = []

    for klass in ast.walk(tree):
        if not isinstance(klass, ast.ClassDef):
            continue
        for func in klass.body:
            if not isinstance(func, ast.FunctionDef):
                continue
            for node in ast.walk(func):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "now"
                ):
                    locations.append(f"{klass.name}.{func.name}")

    assert locations == ["SystemClock.now"]

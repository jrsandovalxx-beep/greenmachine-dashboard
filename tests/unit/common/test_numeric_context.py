"""The project-local Decimal context: isolated in both directions.

ADR-0002 requires precision 28 and ROUND_HALF_EVEN, applied through a context that
is never the global one. Two failure modes matter equally: another library
changing the global context must not change our answers, and our arithmetic must
not change theirs.
"""

from __future__ import annotations

import decimal
from collections.abc import Iterator
from decimal import ROUND_HALF_EVEN, ROUND_UP, Decimal

import pytest

from greenmachine.common import (
    PRECISION,
    ROUNDING,
    add,
    divide,
    multiply,
    numeric_context,
    percentage,
    project_context,
    subtract,
)


@pytest.fixture(autouse=True)
def restore_global_context() -> Iterator[None]:
    """Snapshot and restore the global context around every test in this module."""
    saved = decimal.getcontext().copy()
    try:
        yield
    finally:
        decimal.setcontext(saved)


# --------------------------------------------------------------------------
# Declared settings
# --------------------------------------------------------------------------


def test_declared_precision_and_rounding() -> None:
    assert PRECISION == 28
    assert ROUNDING == ROUND_HALF_EVEN


def test_context_carries_the_declared_settings() -> None:
    ctx = numeric_context()

    assert ctx.prec == 28
    assert ctx.rounding == ROUND_HALF_EVEN


def test_numeric_context_returns_a_copy_each_time() -> None:
    """Callers get their own context; there is no shared mutable singleton."""
    first = numeric_context()
    second = numeric_context()

    assert first is not second

    first.prec = 5

    assert numeric_context().prec == 28
    assert second.prec == 28


def test_mutating_a_returned_context_does_not_affect_operations() -> None:
    borrowed = numeric_context()
    borrowed.prec = 2

    assert divide(Decimal(1), Decimal(3)) == Decimal("0.3333333333333333333333333333")


# --------------------------------------------------------------------------
# Isolation from the global context
# --------------------------------------------------------------------------


def test_operations_do_not_mutate_the_global_context() -> None:
    before_prec = decimal.getcontext().prec
    before_rounding = decimal.getcontext().rounding

    divide(Decimal(1), Decimal(3))
    add(Decimal("0.75"), Decimal("1.5"))
    with project_context():
        pass

    assert decimal.getcontext().prec == before_prec
    assert decimal.getcontext().rounding == before_rounding


def test_a_hostile_global_context_does_not_change_our_answers() -> None:
    """Another library setting prec=3/ROUND_UP must not reach our arithmetic."""
    decimal.getcontext().prec = 3
    decimal.getcontext().rounding = ROUND_UP

    assert divide(Decimal(1), Decimal(3)) == Decimal("0.3333333333333333333333333333")

    # And the hostile settings are still in force for the caller afterwards.
    assert decimal.getcontext().prec == 3


def test_the_global_context_is_restored_even_when_a_block_raises() -> None:
    decimal.getcontext().prec = 9

    with pytest.raises(RuntimeError), project_context():
        raise RuntimeError("boom")

    assert decimal.getcontext().prec == 9


def test_project_context_yields_the_declared_settings() -> None:
    decimal.getcontext().prec = 3

    with project_context() as ctx:
        assert ctx.prec == 28
        assert ctx.rounding == ROUND_HALF_EVEN


# --------------------------------------------------------------------------
# ROUND_HALF_EVEN behaviour
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.5", "0"),
        ("1.5", "2"),
        ("2.5", "2"),
        ("3.5", "4"),
        ("-0.5", "-0"),
        ("-1.5", "-2"),
        ("-2.5", "-2"),
        ("-3.5", "-4"),
    ],
)
def test_half_even_at_midpoints_including_negatives(value: str, expected: str) -> None:
    """Ties go to the even neighbour, symmetrically about zero."""
    with project_context():
        assert Decimal(value).quantize(Decimal("1")) == Decimal(expected)


def test_division_rounds_at_the_declared_precision() -> None:
    result = divide(Decimal(1), Decimal(3))

    assert len(result.as_tuple().digits) == 28


# --------------------------------------------------------------------------
# Exact fractional arithmetic (ADR-0002's motivating cases)
# --------------------------------------------------------------------------


def test_fractional_allocations_sum_exactly() -> None:
    """0.75 + 0.75 + 1.5 is exactly 3 — no epsilon, no tolerance."""
    total = add(Decimal("0.75"), Decimal("0.75"), Decimal("1.5"))

    assert total == Decimal("3")


def test_strong_category_comparison_is_exact_at_the_boundary() -> None:
    """A 3-point category is strong at exactly 2.25 (MODEL_SPEC 16)."""
    threshold = multiply(Decimal("3"), Decimal("0.75"))

    assert threshold == Decimal("2.25")
    assert Decimal("2.25") >= threshold


def test_strong_category_comparison_holds_for_a_summed_left_side() -> None:
    """The hazard ADR-0002 names: the left side is a sum, not a literal."""
    category = add(Decimal("0.75"), Decimal("0.75"), Decimal("0.75"))
    threshold = multiply(Decimal("3"), Decimal("0.75"))

    assert category >= threshold


def test_two_point_category_is_strong_at_one_and_a_half() -> None:
    threshold = multiply(Decimal("2"), Decimal("0.75"))

    assert threshold == Decimal("1.50")
    assert Decimal("1.5") >= threshold


def test_subtract_and_multiply_run_under_the_context() -> None:
    assert subtract(Decimal("3"), Decimal("0.75")) == Decimal("2.25")
    assert multiply(Decimal("1.5"), Decimal("2")) == Decimal("3")


def test_derived_ratios_are_not_quantized() -> None:
    """MODEL_SPEC 4: derived values keep full precision until they are compared."""
    ratio = divide(Decimal(2), Decimal(3))

    assert ratio != Decimal("0.67")
    assert str(ratio).startswith("0.6666666666")


def test_percentage_is_generic_arithmetic() -> None:
    assert percentage(Decimal(1), Decimal(4)) == Decimal(25)
    assert percentage(Decimal(1), Decimal(3)) > Decimal("33.3")


def test_division_by_zero_is_refused_rather_than_trapped_late() -> None:
    from greenmachine.common import NumericPolicyError

    with pytest.raises(NumericPolicyError, match=r"divide by zero"):
        divide(Decimal(1), Decimal(0))
    with pytest.raises(NumericPolicyError, match=r"zero denominator"):
        percentage(Decimal(1), Decimal(0))

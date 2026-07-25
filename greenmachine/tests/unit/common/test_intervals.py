"""Two interval conventions, kept deliberately apart.

Scoring intervals are half-open ``[lower, upper)``; ranges defined by an outside
source are inclusive at both ends. ADR-0002 accepts the duplication between the
two helpers because unifying them would silently corrupt one convention.

The boundaries used here (0, 4, 6, 8, 10, 12) are the documented grade cutoffs,
supplied *by the test* to prove generic behaviour. The production helpers know no
thresholds — a static test asserts they contain no such table.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from greenmachine.common import (
    NumericPolicyError,
    in_inclusive_range,
    in_scoring_interval,
    resolve_scoring_interval,
)

# The documented grade domain, supplied by the test, never by the source.
GRADE_BOUNDARIES = [Decimal(b) for b in ("0", "4", "6", "8", "10", "12")]
GRADE_NAMES = ["D", "C", "B", "A", "S"]

TINY = Decimal("0.0000000000000000000000001")


# --------------------------------------------------------------------------
# Half-open scoring interval
# --------------------------------------------------------------------------


def test_exact_lower_boundary_is_included() -> None:
    assert in_scoring_interval(Decimal("10"), Decimal("10"), Decimal("20")) is True


def test_exact_upper_boundary_is_excluded() -> None:
    """The defining rule: a value equal to the upper bound belongs to the next."""
    assert in_scoring_interval(Decimal("20"), Decimal("10"), Decimal("20")) is False


def test_the_shared_boundary_belongs_to_the_next_interval() -> None:
    value = Decimal("20")

    assert in_scoring_interval(value, Decimal("10"), Decimal("20")) is False
    assert in_scoring_interval(value, Decimal("20"), Decimal("30")) is True


def test_just_below_the_upper_boundary_is_included() -> None:
    assert in_scoring_interval(Decimal("20") - TINY, Decimal("10"), Decimal("20")) is True


def test_just_below_the_lower_boundary_is_excluded() -> None:
    assert in_scoring_interval(Decimal("10") - TINY, Decimal("10"), Decimal("20")) is False


def test_terminal_interval_is_closed_at_the_supplied_domain_maximum() -> None:
    assert in_scoring_interval(Decimal("12"), Decimal("10"), Decimal("12"), terminal=True) is True


def test_terminal_interval_still_excludes_values_beyond_the_maximum() -> None:
    assert (
        in_scoring_interval(Decimal("12") + TINY, Decimal("10"), Decimal("12"), terminal=True)
        is False
    )


@pytest.mark.parametrize(
    ("lower", "upper"),
    [(Decimal("20"), Decimal("10")), (Decimal("5"), Decimal("5"))],
)
def test_unordered_or_degenerate_bounds_are_rejected(lower: Decimal, upper: Decimal) -> None:
    with pytest.raises(NumericPolicyError, match=r"requires lower < upper"):
        in_scoring_interval(Decimal("7"), lower, upper)


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity")])
def test_non_finite_inputs_are_rejected(bad: Decimal) -> None:
    with pytest.raises(NumericPolicyError, match=r"finite"):
        in_scoring_interval(bad, Decimal("0"), Decimal("1"))


def test_float_bounds_are_rejected() -> None:
    with pytest.raises(NumericPolicyError, match=r"must be a Decimal"):
        in_scoring_interval(Decimal("1"), 0.0, 2.0)  # type: ignore[arg-type]


def test_a_non_bool_terminal_flag_is_rejected() -> None:
    """A truthy string would silently close an interval that should be half-open."""
    with pytest.raises(NumericPolicyError, match=r"terminal must be bool"):
        in_scoring_interval(
            Decimal("20"),
            Decimal("10"),
            Decimal("20"),
            terminal="yes",  # type: ignore[arg-type]
        )


# --------------------------------------------------------------------------
# Generic resolver over caller-supplied boundaries
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        ("0", "D"),
        ("3.9999", "D"),
        ("4", "C"),
        ("5.5", "C"),
        ("6", "B"),
        ("7.9999", "B"),
        ("8", "A"),
        ("9.9999", "A"),
        ("10", "S"),
        ("11.5", "S"),
        ("12", "S"),
    ],
)
def test_resolver_places_every_value_in_exactly_one_interval(score: str, expected: str) -> None:
    """Each cutoff belongs to the interval above it; 12 closes the domain."""
    index = resolve_scoring_interval(Decimal(score), GRADE_BOUNDARIES)

    assert GRADE_NAMES[index] == expected


@pytest.mark.parametrize("cutoff", ["4", "6", "8", "10"])
def test_each_cutoff_lands_in_the_upper_interval_not_the_lower(cutoff: str) -> None:
    at_cutoff = resolve_scoring_interval(Decimal(cutoff), GRADE_BOUNDARIES)
    just_below = resolve_scoring_interval(Decimal(cutoff) - TINY, GRADE_BOUNDARIES)

    assert at_cutoff == just_below + 1


def test_resolver_rejects_a_value_below_the_domain() -> None:
    with pytest.raises(NumericPolicyError, match=r"outside the declared domain"):
        resolve_scoring_interval(Decimal("-0.5"), GRADE_BOUNDARIES)


def test_resolver_rejects_a_value_above_the_domain() -> None:
    with pytest.raises(NumericPolicyError, match=r"outside the declared domain"):
        resolve_scoring_interval(Decimal("12.5"), GRADE_BOUNDARIES)


def test_resolver_rejects_unordered_boundaries() -> None:
    with pytest.raises(NumericPolicyError, match=r"strictly increase"):
        resolve_scoring_interval(Decimal("5"), [Decimal("0"), Decimal("8"), Decimal("4")])


def test_resolver_rejects_duplicate_boundaries() -> None:
    with pytest.raises(NumericPolicyError, match=r"strictly increase"):
        resolve_scoring_interval(Decimal("5"), [Decimal("0"), Decimal("4"), Decimal("4")])


def test_resolver_needs_at_least_two_boundaries() -> None:
    with pytest.raises(NumericPolicyError, match=r"at least two boundaries"):
        resolve_scoring_interval(Decimal("5"), [Decimal("0")])


def test_resolver_covers_the_domain_without_gaps() -> None:
    """Totality: every in-domain value resolves, none raises."""
    value = Decimal("0")
    step = Decimal("0.25")
    while value <= Decimal("12"):
        assert 0 <= resolve_scoring_interval(value, GRADE_BOUNDARIES) < len(GRADE_NAMES)
        value += step


# --------------------------------------------------------------------------
# Inclusive range
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["5", "5.1", "12", "19.9", "20"])
def test_inclusive_range_includes_both_endpoints_and_between(value: str) -> None:
    """The motivating case is inclusive at both 5 and 20 (MODEL_SPEC 9.2)."""
    assert in_inclusive_range(Decimal(value), Decimal("5"), Decimal("20")) is True


@pytest.mark.parametrize("value", ["4.9", "20.1"])
def test_inclusive_range_excludes_values_just_outside(value: str) -> None:
    assert in_inclusive_range(Decimal(value), Decimal("5"), Decimal("20")) is False


def test_inclusive_range_allows_a_single_point() -> None:
    assert in_inclusive_range(Decimal("5"), Decimal("5"), Decimal("5")) is True


def test_inclusive_range_rejects_unordered_bounds() -> None:
    with pytest.raises(NumericPolicyError, match=r"requires lower <= upper"):
        in_inclusive_range(Decimal("7"), Decimal("20"), Decimal("5"))


def test_inclusive_range_rejects_non_finite_values() -> None:
    with pytest.raises(NumericPolicyError, match=r"finite"):
        in_inclusive_range(Decimal("NaN"), Decimal("5"), Decimal("20"))


# --------------------------------------------------------------------------
# The two conventions must disagree
# --------------------------------------------------------------------------


def test_the_two_helpers_disagree_at_a_shared_upper_bound() -> None:
    """The whole reason they are separate implementations.

    Same value, same bounds, opposite answers — the half-open interval excludes
    its upper bound, the inclusive range includes it. If these ever agreed here,
    one convention would have swallowed the other.
    """
    value, lower, upper = Decimal("20"), Decimal("5"), Decimal("20")

    assert in_scoring_interval(value, lower, upper) is False
    assert in_inclusive_range(value, lower, upper) is True
    assert in_scoring_interval(value, lower, upper) != in_inclusive_range(value, lower, upper)


def test_the_two_helpers_agree_strictly_inside_the_range() -> None:
    """They differ only at the upper edge, which is the point of the distinction."""
    for raw in ("5", "10", "19.9999"):
        value = Decimal(raw)
        assert in_scoring_interval(value, Decimal("5"), Decimal("20")) is True
        assert in_inclusive_range(value, Decimal("5"), Decimal("20")) is True


def test_the_helpers_are_distinct_objects_not_aliases() -> None:
    assert in_scoring_interval is not in_inclusive_range
    assert in_scoring_interval.__code__ is not in_inclusive_range.__code__

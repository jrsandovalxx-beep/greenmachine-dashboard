"""Result value objects: pure containers with no scoring behaviour.

These record outcomes; they never compute them. The tests below assert the
construction invariants and, just as importantly, assert the *absence* of
calculation — a CategoryScore does not re-derive its total, and no type exposes a
scoring method.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from greenmachine.domain import (
    BucketHit,
    Category,
    CategoryScore,
    ComponentId,
    ComponentScore,
    DomainValidationError,
    MeasurementId,
    ValidationFinding,
    ValidationInputId,
)

RESULT_TYPES = (BucketHit, ComponentScore, CategoryScore, ValidationFinding)


def make_bucket_hit(**overrides: object) -> BucketHit:
    params: dict[str, object] = {
        "lower_bound": Decimal("10"),
        "upper_bound": Decimal("20"),
        "is_terminal": False,
        "points_awarded": Decimal("0.75"),
    }
    params.update(overrides)
    return BucketHit(**params)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# BucketHit
# --------------------------------------------------------------------------


def test_bucket_hit_records_bounds_and_points() -> None:
    hit = make_bucket_hit()

    assert hit.lower_bound == Decimal("10")
    assert hit.upper_bound == Decimal("20")
    assert hit.points_awarded == Decimal("0.75")
    assert hit.is_terminal is False


def test_terminal_bucket_has_no_upper_bound() -> None:
    """The terminal bucket is closed at the domain maximum (MODEL_SPEC 4.1)."""
    hit = make_bucket_hit(upper_bound=None, is_terminal=True)

    assert hit.upper_bound is None
    assert hit.is_terminal is True


def test_bucket_hit_rejects_reversed_bounds() -> None:
    with pytest.raises(DomainValidationError, match=r"must be < upper_bound"):
        make_bucket_hit(lower_bound=Decimal("20"), upper_bound=Decimal("10"))


def test_bucket_hit_rejects_negative_points() -> None:
    """MODEL_SPEC 19, invariant 1: every bucket's points are >= 0."""
    with pytest.raises(DomainValidationError, match=r"points_awarded"):
        make_bucket_hit(points_awarded=Decimal("-0.25"))


def test_bucket_hit_accepts_zero_points() -> None:
    hit = make_bucket_hit(points_awarded=Decimal("0"))

    assert hit.points_awarded == Decimal("0")


def test_bucket_hit_accepts_fractional_points() -> None:
    """MODEL_SPEC 3.1: fractional points are allowed and expected."""
    hit = make_bucket_hit(points_awarded=Decimal("0.25"))

    assert hit.points_awarded == Decimal("0.25")


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity")])
def test_bucket_hit_rejects_non_finite_numbers(bad: Decimal) -> None:
    with pytest.raises(DomainValidationError, match=r"finite"):
        make_bucket_hit(points_awarded=bad)
    with pytest.raises(DomainValidationError, match=r"finite"):
        make_bucket_hit(lower_bound=bad)


def test_bucket_hit_rejects_float_points() -> None:
    with pytest.raises(DomainValidationError, match=r"Decimal"):
        make_bucket_hit(points_awarded=0.75)


# --------------------------------------------------------------------------
# ComponentScore
# --------------------------------------------------------------------------


def test_component_score_records_points_and_measurement() -> None:
    score = ComponentScore(
        component_id=ComponentId.ATTACK_ANGLE_QUALITY,
        measurement_id=MeasurementId.IDEAL_ATTACK_ANGLE_PCT,
        points_awarded=Decimal("0.5"),
        bucket_hit=make_bucket_hit(),
    )

    assert score.component_id is ComponentId.ATTACK_ANGLE_QUALITY
    assert score.measurement_id is MeasurementId.IDEAL_ATTACK_ANGLE_PCT
    assert score.points_awarded == Decimal("0.5")


def test_component_score_allows_no_bucket_for_binary_components() -> None:
    """MODEL_SPEC 5: binary components declare a predicate, not bucket ranges."""
    score = ComponentScore(ComponentId.WEATHER, None, Decimal("1"))

    assert score.bucket_hit is None


def test_component_score_rejects_negative_points() -> None:
    with pytest.raises(DomainValidationError, match=r"points_awarded"):
        ComponentScore(ComponentId.PARK, None, Decimal("-1"))


def test_component_score_holds_at_most_one_measurement() -> None:
    measurement_fields = [
        f.name for f in dataclasses.fields(ComponentScore) if "measurement" in f.name
    ]

    assert measurement_fields == ["measurement_id"]


# --------------------------------------------------------------------------
# CategoryScore
# --------------------------------------------------------------------------


def test_category_score_holds_its_component_scores() -> None:
    components = (
        ComponentScore(ComponentId.EXIT_VELOCITY, None, Decimal("1.5")),
        ComponentScore(ComponentId.BARREL_PCT, None, Decimal("0.75")),
        ComponentScore(ComponentId.HARD_HIT_PCT, None, Decimal("0.75")),
    )
    score = CategoryScore(Category.POWER_PROFILE, Decimal("3"), components)

    assert score.category is Category.POWER_PROFILE
    assert score.points_awarded == Decimal("3")
    assert len(score.component_scores) == 3


def test_category_score_does_not_recompute_its_total() -> None:
    """Aggregation is the scoring core's job (Sprint 2), not a construction rule.

    This asserts the *absence* of behaviour: a deliberately inconsistent total is
    stored as given rather than corrected or rejected here.
    """
    score = CategoryScore(
        Category.FORM,
        Decimal("99"),
        (ComponentScore(ComponentId.BAT_SPEED, None, Decimal("0.25")),),
    )

    assert score.points_awarded == Decimal("99")


def test_category_score_defaults_to_no_components() -> None:
    score = CategoryScore(Category.ENVIRONMENT, Decimal("0"))

    assert score.component_scores == ()


def test_category_score_rejects_negative_points() -> None:
    with pytest.raises(DomainValidationError, match=r"points_awarded"):
        CategoryScore(Category.PULL_POWER, Decimal("-0.5"))


def test_fractional_component_points_sum_exactly_in_decimal() -> None:
    """ADR-0002: 0.75 + 0.75 + 1.5 is exactly 3, with no epsilon anywhere.

    The addition here is the test's own arithmetic, not domain behaviour.
    """
    components = (
        ComponentScore(ComponentId.EXIT_VELOCITY, None, Decimal("0.75")),
        ComponentScore(ComponentId.BARREL_PCT, None, Decimal("0.75")),
        ComponentScore(ComponentId.HARD_HIT_PCT, None, Decimal("1.5")),
    )
    total = sum((c.points_awarded for c in components), start=Decimal("0"))

    assert total == Decimal("3")


# --------------------------------------------------------------------------
# ValidationFinding
# --------------------------------------------------------------------------


def test_validation_finding_records_an_advisory_message() -> None:
    finding = ValidationFinding(
        input_id=ValidationInputId.SAMPLE_WARNINGS,
        message="sample below configured minimum",
        component_id=ComponentId.BAT_SPEED,
    )

    assert finding.input_id is ValidationInputId.SAMPLE_WARNINGS
    assert finding.component_id is ComponentId.BAT_SPEED


def test_validation_finding_component_is_optional() -> None:
    finding = ValidationFinding(ValidationInputId.BULLPEN_NOTES, "context only")

    assert finding.component_id is None


@pytest.mark.parametrize("bad", ["", "   "])
def test_validation_finding_requires_a_message(bad: str) -> None:
    with pytest.raises(DomainValidationError, match=r"message"):
        ValidationFinding(ValidationInputId.COVERAGE_WARNINGS, bad)


def test_validation_finding_carries_no_points() -> None:
    """MODEL_SPEC 17: the Validation Layer is advisory and awards zero points.

    There is no points field to award through.
    """
    field_names = {f.name for f in dataclasses.fields(ValidationFinding)}

    assert not any("point" in name or "score" in name for name in field_names)


# --------------------------------------------------------------------------
# Shared guarantees
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "instance",
    [
        make_bucket_hit(),
        ComponentScore(ComponentId.PARK, None, Decimal("1")),
        CategoryScore(Category.ENVIRONMENT, Decimal("2")),
        ValidationFinding(ValidationInputId.FALLBACK_STATUS, "used event derivation"),
    ],
    ids=["bucket_hit", "component_score", "category_score", "validation_finding"],
)
def test_result_objects_are_hashable_and_equal_by_value(instance: object) -> None:
    """Value semantics: a field-for-field copy equals and hashes like the original.

    Immutability is asserted in test_immutability.py, which targets a real field on
    each type. The mutation assertion that used to live here assigned
    ``points_awarded`` to all four cases, including ValidationFinding, which has no
    such field — on a frozen slotted dataclass CPython 3.13 raises TypeError rather
    than FrozenInstanceError, so it passed on one interpreter and failed on another
    while never testing immutability.
    """
    assert hash(instance)
    assert instance == dataclasses.replace(instance)  # type: ignore[type-var]


@pytest.mark.parametrize("result_type", RESULT_TYPES, ids=lambda t: t.__name__)
def test_result_objects_expose_no_scoring_behaviour(result_type: type) -> None:
    """No calculation, resolution, or aggregation methods live on these records."""
    public_methods = {
        name
        for name in dir(result_type)
        if not name.startswith("_") and callable(getattr(result_type, name, None))
    }

    assert public_methods == set()

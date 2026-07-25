"""Metric observations: full provenance, Decimal values, and typed missingness.

The rules under test come from MODEL_SPEC 8 and ENGINEERING_GUIDELINES S1-S4:
every provenance field is mandatory, values entering scoring are Decimal, an
insufficient sample is still a present scored value, and missing is a separate
type carrying a reason.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from decimal import Decimal

import pytest
from domain_builders import (
    AS_OF,
    WINDOW_END,
    WINDOW_START,
    make_missing_observation,
    make_observation,
    missing_observation_kwargs,
    observation_kwargs,
)

from greenmachine.domain import (
    ComponentId,
    DomainValidationError,
    MeasurementId,
    MetricObservation,
    MissingObservation,
    MissingReason,
    SampleStatus,
    SampleType,
    WindowProfile,
)

# --------------------------------------------------------------------------
# MetricObservation — construction and required provenance
# --------------------------------------------------------------------------


def test_observation_constructs_with_full_provenance() -> None:
    observation = make_observation()

    assert observation.component_id is ComponentId.EXIT_VELOCITY
    assert observation.window_profile is WindowProfile.RECENT_7D
    assert observation.raw_value == Decimal("12.3456")
    assert observation.sample_type is SampleType.BATTED_BALL_EVENTS
    assert observation.sample_status is SampleStatus.SUFFICIENT
    assert observation.fallback_used is None


@pytest.mark.parametrize(
    "omitted",
    [name for name in observation_kwargs() if name != "fallback_used"],
)
def test_observation_construction_fails_when_a_provenance_field_is_absent(
    omitted: str,
) -> None:
    """MODEL_SPEC 8.4: an observation missing any required provenance field
    fails construction. Only ``fallback_used`` is optional, because a fallback
    does not always occur."""
    kwargs = observation_kwargs()
    del kwargs[omitted]

    with pytest.raises(TypeError):
        MetricObservation(**kwargs)


def test_observation_carries_every_field_required_by_the_spec() -> None:
    """The §8.4 provenance list, asserted field by field."""
    field_names = {f.name for f in dataclasses.fields(MetricObservation)}

    assert field_names == {
        "component_id",
        "measurement_id",
        "window_profile",
        "window_start",
        "window_end",
        "as_of",
        "raw_value",
        "unit",
        "sample_type",
        "sample_count",
        "minimum_sample_required",
        "sample_status",
        "data_coverage",
        "provider_id",
        "acquisition_method",
        "source_as_of",
        "retrieved_at",
        "source_capture_id",
        "fallback_used",
    }


# --------------------------------------------------------------------------
# Numeric policy (ADR-0002)
# --------------------------------------------------------------------------


def test_observation_value_is_decimal_not_float() -> None:
    observation = make_observation(raw_value=Decimal("0.1"))

    assert isinstance(observation.raw_value, Decimal)
    assert not isinstance(observation.raw_value, float)


def test_observation_rejects_a_float_value() -> None:
    """ADR-0002: values entering scoring are built from strings or ints, never
    from a binary float."""
    with pytest.raises(DomainValidationError, match=r"Decimal"):
        make_observation(raw_value=12.3456)


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_observation_rejects_non_finite_values(bad: Decimal) -> None:
    """ENGINEERING_GUIDELINES D6: no NaN-carrying value crosses into the core."""
    with pytest.raises(DomainValidationError, match=r"finite"):
        make_observation(raw_value=bad)


def test_observation_preserves_decimal_precision_exactly() -> None:
    """Trailing zeros and scale survive, so serialization stays deterministic."""
    observation = make_observation(raw_value=Decimal("12.3400"))

    assert str(observation.raw_value) == "12.3400"


def test_observation_accepts_a_zero_value_as_a_real_measurement() -> None:
    """Zero is a genuine value, never a stand-in for missing (MODEL_SPEC 8.3)."""
    observation = make_observation(raw_value=Decimal("0"))

    assert observation.raw_value == Decimal("0")


# --------------------------------------------------------------------------
# Window and timestamp invariants
# --------------------------------------------------------------------------


def test_observation_rejects_a_reversed_window() -> None:
    with pytest.raises(DomainValidationError, match=r"must be <="):
        make_observation(window_start=WINDOW_END, window_end=WINDOW_START)


def test_observation_accepts_a_zero_length_window() -> None:
    observation = make_observation(window_start=WINDOW_END, window_end=WINDOW_END)

    assert observation.window_start == observation.window_end


@pytest.mark.parametrize(
    "field_name",
    ["window_start", "window_end", "as_of", "source_as_of", "retrieved_at"],
)
def test_observation_rejects_naive_datetimes(field_name: str) -> None:
    naive = datetime(2026, 7, 15, 16, 30)

    with pytest.raises(DomainValidationError, match=r"timezone-aware"):
        make_observation(**{field_name: naive})


# --------------------------------------------------------------------------
# Sample accounting
# --------------------------------------------------------------------------


def test_insufficient_sample_is_still_a_present_scored_observation() -> None:
    """MODEL_SPEC 8.2 / S3a: a valid value below its minimum is still scored,
    labelled INSUFFICIENT, and is *not* missing."""
    observation = make_observation(
        raw_value=Decimal("9.8765"),
        sample_count=2,
        minimum_sample_required=7,
        sample_status=SampleStatus.INSUFFICIENT,
    )

    assert observation.sample_status is SampleStatus.INSUFFICIENT
    assert observation.raw_value == Decimal("9.8765")
    assert not hasattr(observation, "missing_reason")


def test_minimum_sample_does_not_gate_construction() -> None:
    """Minimum-sample configuration governs the label, never whether a value
    may exist (MODEL_SPEC 8.2)."""
    observation = make_observation(sample_count=0, minimum_sample_required=99)

    assert observation.sample_count == 0


@pytest.mark.parametrize("field_name", ["sample_count", "minimum_sample_required"])
def test_observation_rejects_negative_counts(field_name: str) -> None:
    with pytest.raises(DomainValidationError, match=field_name):
        make_observation(**{field_name: -1})


@pytest.mark.parametrize("bad_unit", ["", "   "])
def test_observation_requires_a_unit(bad_unit: str) -> None:
    with pytest.raises(DomainValidationError, match=r"unit"):
        make_observation(unit=bad_unit)


def test_each_component_declares_its_own_denominator() -> None:
    """S1/S2: bat speed is always a swing sample, never a batted-ball sample."""
    bat_speed = make_observation(component_id=ComponentId.BAT_SPEED, sample_type=SampleType.SWINGS)

    assert bat_speed.sample_type is SampleType.SWINGS


# --------------------------------------------------------------------------
# Measurement slot (MODEL_SPEC 9.1)
# --------------------------------------------------------------------------


def test_observation_holds_at_most_one_measurement() -> None:
    """The single slot makes two measurements for one component unconstructable."""
    measurement_fields = [
        f.name for f in dataclasses.fields(MetricObservation) if "measurement" in f.name
    ]

    assert measurement_fields == ["measurement_id"]


@pytest.mark.parametrize(
    "measurement",
    [MeasurementId.IDEAL_ATTACK_ANGLE_PCT, MeasurementId.ATTACK_ANGLE_THRESHOLD_PROXY],
)
def test_attack_angle_quality_accepts_either_measurement(
    measurement: MeasurementId,
) -> None:
    observation = make_observation(
        component_id=ComponentId.ATTACK_ANGLE_QUALITY,
        measurement_id=measurement,
        unit="percent",
    )

    assert observation.measurement_id is measurement


def test_measurement_id_is_none_for_single_measurement_components() -> None:
    """Every component other than attack_angle_quality has one implicit
    measurement identical to itself, represented by None."""
    observation = make_observation(component_id=ComponentId.BARREL_PCT)

    assert observation.measurement_id is None


def test_measurement_id_must_be_supplied_explicitly() -> None:
    """It has no default, so 'not applicable' is always a deliberate choice."""
    kwargs = observation_kwargs()
    del kwargs["measurement_id"]

    with pytest.raises(TypeError):
        MetricObservation(**kwargs)


# --------------------------------------------------------------------------
# Immutability, equality, hashing, repr
# --------------------------------------------------------------------------


def test_observation_is_frozen() -> None:
    observation = make_observation()

    with pytest.raises(dataclasses.FrozenInstanceError):
        observation.raw_value = Decimal("99")


def test_observation_equality_and_hashing_are_by_value() -> None:
    assert make_observation() == make_observation()
    assert hash(make_observation()) == hash(make_observation())
    assert make_observation() != make_observation(raw_value=Decimal("1"))


def test_observations_differing_only_by_profile_are_distinct() -> None:
    """W3: profile is carried on every observation, never inferred."""
    recent = make_observation(window_profile=WindowProfile.RECENT_7D)
    long_term = make_observation(window_profile=WindowProfile.LONG_TERM_2Y)

    assert recent != long_term
    assert len({recent, long_term}) == 2


def test_observation_repr_names_its_type_and_component() -> None:
    text = repr(make_observation())

    assert text.startswith("MetricObservation(")
    assert "ComponentId.EXIT_VELOCITY" in text


# --------------------------------------------------------------------------
# MissingObservation — typed missingness
# --------------------------------------------------------------------------


def test_missing_observation_constructs_with_a_reason() -> None:
    missing = make_missing_observation()

    assert missing.missing_reason is MissingReason.TRACKING_UNAVAILABLE
    assert missing.component_id is ComponentId.ATTACK_ANGLE_QUALITY


def test_missing_observation_has_no_value_and_no_sample_status() -> None:
    """Missing is a distinct type, not a present value with None fields
    (MODEL_SPEC 8.3: no ambiguous None, no zero standing in for missing)."""
    missing = make_missing_observation()

    assert not hasattr(missing, "raw_value")
    assert not hasattr(missing, "sample_status")
    assert not hasattr(missing, "sample_count")


def test_missing_observation_has_no_acquisition_method() -> None:
    """MODEL_SPEC 10: unavailability is not an acquisition method."""
    field_names = {f.name for f in dataclasses.fields(MissingObservation)}

    assert "acquisition_method" not in field_names


def test_missing_observation_allows_an_unknown_provider() -> None:
    """A source that was never reached has no provider to record."""
    missing = make_missing_observation(
        provider_id=None, missing_reason=MissingReason.SOURCE_UNAVAILABLE
    )

    assert missing.provider_id is None


@pytest.mark.parametrize("omitted", list(missing_observation_kwargs()))
def test_missing_observation_requires_every_field(omitted: str) -> None:
    kwargs = missing_observation_kwargs()
    del kwargs[omitted]

    with pytest.raises(TypeError):
        MissingObservation(**kwargs)


def test_missing_observation_rejects_a_reversed_window() -> None:
    with pytest.raises(DomainValidationError, match=r"must be <="):
        make_missing_observation(window_start=WINDOW_END, window_end=WINDOW_START)


def test_missing_observation_rejects_a_naive_as_of() -> None:
    with pytest.raises(DomainValidationError, match=r"timezone-aware"):
        make_missing_observation(as_of=datetime(2026, 7, 15, 16, 30))


def test_missing_observation_is_frozen_and_hashable() -> None:
    missing = make_missing_observation()

    assert hash(missing)
    with pytest.raises(dataclasses.FrozenInstanceError):
        missing.missing_reason = MissingReason.SOURCE_UNAVAILABLE


def test_missing_and_present_observations_are_different_types() -> None:
    """Zero, insufficient, and missing are never collapsed (GLOSSARY 4)."""
    assert not isinstance(make_missing_observation(), MetricObservation)
    assert not isinstance(make_observation(), MissingObservation)


def test_a_sample_status_cannot_be_used_as_a_missing_reason() -> None:
    """INSUFFICIENT is not a MissingReason, and the types keep it that way."""
    with pytest.raises(ValueError, match=r"INSUFFICIENT"):
        MissingReason(SampleStatus.INSUFFICIENT.value)


def test_observation_as_of_is_supplied_never_generated() -> None:
    """D2: the domain reads no clock. as_of is whatever the caller froze."""
    observation = make_observation()

    assert observation.as_of == AS_OF

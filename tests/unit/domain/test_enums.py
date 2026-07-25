"""Enum correctness: exact membership, exact identifiers, and the v6.3 regressions.

These tests are deliberately literal. An enum member is a contract between
``MODEL_SPEC.md`` and the code, so each expected set is written out in full — if
somebody adds, removes, or renames a member, a test must fail rather than quietly
accept it.
"""

from __future__ import annotations

import json
from enum import Enum

import pytest

from greenmachine.domain import (
    AcquisitionMethod,
    Category,
    ComponentId,
    CoverageStatus,
    EvaluationStatus,
    Grade,
    MeasurementId,
    MissingReason,
    PitcherRole,
    ProviderId,
    SampleStatus,
    SampleType,
    Signal,
    ValidationInputId,
    WindowProfile,
)

ALL_ENUMS: tuple[type[Enum], ...] = (
    AcquisitionMethod,
    Category,
    ComponentId,
    CoverageStatus,
    EvaluationStatus,
    Grade,
    MeasurementId,
    MissingReason,
    PitcherRole,
    ProviderId,
    SampleStatus,
    SampleType,
    Signal,
    ValidationInputId,
    WindowProfile,
)


def values(enum_type: type[Enum]) -> set[str]:
    return {str(member.value) for member in enum_type}


# --------------------------------------------------------------------------
# Exact membership (MODEL_SPEC.md / GLOSSARY.md)
# --------------------------------------------------------------------------


def test_window_profile_has_exactly_two_members() -> None:
    """MODEL_SPEC.md 6.1 defines exactly two profiles."""
    assert values(WindowProfile) == {"RECENT_7D", "LONG_TERM_2Y"}


def test_window_profile_display_names() -> None:
    """Each profile carries the display name from MODEL_SPEC.md 6.1."""
    assert WindowProfile.RECENT_7D.display_name == "Recent — Last 7 Days"
    assert WindowProfile.LONG_TERM_2Y.display_name == "Long-Term — Rolling 2 Years"


def test_component_id_has_exactly_the_eleven_scored_components() -> None:
    """MODEL_SPEC.md 2: eleven scored components, no more and no fewer."""
    assert values(ComponentId) == {
        "exit_velocity",
        "barrel_pct",
        "hard_hit_pct",
        "pitch_mix_pressure",
        "put_away_pitch_exploitation",
        "sweet_spot_pct",
        "attack_angle_quality",
        "bat_speed",
        "pull_pct_air_balls",
        "park",
        "weather",
    }
    assert len(ComponentId) == 11


def test_measurement_id_holds_only_the_two_attack_angle_measurements() -> None:
    """MODEL_SPEC.md 9.1: two mutually exclusive measurements."""
    assert values(MeasurementId) == {
        "ideal_attack_angle_pct",
        "attack_angle_threshold_proxy",
    }


def test_validation_input_ids_match_the_glossary() -> None:
    """GLOSSARY.md 2: advisory inputs, enumerated separately from scored components."""
    assert values(ValidationInputId) == {
        "woba_window",
        "relief_vulnerability",
        "bullpen_notes",
        "sample_warnings",
        "coverage_warnings",
        "fallback_status",
    }


def test_sample_types_match_the_spec() -> None:
    assert values(SampleType) == {
        "batted_ball_events",
        "swings",
        "air_balls",
        "plate_appearances",
        "pitches",
        "games",
    }


def test_sample_status_is_exactly_sufficient_and_insufficient() -> None:
    assert values(SampleStatus) == {"SUFFICIENT", "INSUFFICIENT"}


def test_missing_reason_has_exactly_the_eight_members() -> None:
    """MODEL_SPEC.md 8.2 lists eight reasons."""
    assert values(MissingReason) == {
        "NO_EVENTS_IN_WINDOW",
        "SOURCE_UNAVAILABLE",
        "TRACKING_UNAVAILABLE",
        "PLAYER_NOT_COVERED",
        "INVALID_SOURCE_VALUE",
        "EXPECTED_PITCHER_UNKNOWN",
        "WEATHER_UNAVAILABLE",
        "UNSUPPORTED_HISTORICAL_PERIOD",
    }
    assert len(MissingReason) == 8


def test_acquisition_methods_match_the_priority_list() -> None:
    """MODEL_SPEC.md 9.4. Unavailability is deliberately not a member."""
    assert values(AcquisitionMethod) == {
        "direct_aggregate",
        "structured_extract",
        "rendered_scrape",
        "event_derived",
        "configured_proxy",
    }


def test_provider_id_only_contains_approved_providers() -> None:
    """Only providers named in the approved documentation exist (Q23 still open)."""
    assert values(ProviderId) == {"baseball_savant"}


def test_pitcher_roles_match_the_spec() -> None:
    """MODEL_SPEC.md 7.1: bullpen games record the role explicitly."""
    assert values(PitcherRole) == {"opener", "expected_starter", "uncertain"}


def test_evaluation_status_members() -> None:
    assert values(EvaluationStatus) == {"EVALUATED", "NOT_EVALUABLE"}


def test_grade_members() -> None:
    """MODEL_SPEC.md 14. Cutoffs live in configuration, not on the enum."""
    assert values(Grade) == {"S", "A", "B", "C", "D"}


def test_signal_members() -> None:
    assert values(Signal) == {"STRONG_BET", "LEAN", "PASS", "AVOID"}


def test_categories_match_the_spec() -> None:
    """MODEL_SPEC.md 2: five categories."""
    assert values(Category) == {
        "power_profile",
        "pitcher_matchup",
        "form",
        "pull_power",
        "environment",
    }
    assert Category.POWER_PROFILE.display_name == "Power Profile"
    assert Category.PITCHER_MATCHUP.display_name == "Pitcher Matchup"
    assert Category.FORM.display_name == "Form"
    assert Category.PULL_POWER.display_name == "Pull Power"
    assert Category.ENVIRONMENT.display_name == "Environment"


def test_coverage_status_members() -> None:
    assert values(CoverageStatus) == {"COMPLETE", "PARTIAL", "NONE"}


# --------------------------------------------------------------------------
# v6.3 regressions
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "removed",
    ["chase_rate", "zone_contact_pct", "whiff_rate", "chase_pct", "whiff_pct"],
)
def test_removed_form_metrics_are_absent_from_component_id(removed: str) -> None:
    """MODEL_SPEC.md 2: Chase Rate, Zone Contact %, and Whiff Rate were removed
    from Form and must not be reintroduced."""
    assert removed not in values(ComponentId)


def test_component_id_holds_the_component_not_the_measurement() -> None:
    """v6.3 separated the scored component from the measurement satisfying it."""
    assert "attack_angle_quality" in values(ComponentId)
    assert "ideal_attack_angle_pct" not in values(ComponentId)
    assert "attack_angle_threshold_proxy" not in values(ComponentId)


def test_measurement_ids_are_not_scored_components() -> None:
    """The two enums must not overlap in either direction."""
    assert values(MeasurementId).isdisjoint(values(ComponentId))


def test_insufficient_is_not_a_missing_reason() -> None:
    """MODEL_SPEC.md 8.2: 'INSUFFICIENT is not a MissingReason.'"""
    assert "INSUFFICIENT" not in values(MissingReason)
    assert not any("INSUFFICIENT" in str(member.value) for member in MissingReason)
    assert not any("insufficient" in member.name.lower() for member in MissingReason)


def test_sample_status_and_missing_reason_are_unrelated_types() -> None:
    """A SampleStatus is never assignable where a MissingReason is required."""
    assert not isinstance(SampleStatus.INSUFFICIENT, MissingReason)
    assert SampleStatus.INSUFFICIENT not in set(MissingReason)
    with pytest.raises(ValueError, match=r"INSUFFICIENT"):
        MissingReason("INSUFFICIENT")


def test_no_composite_provider_source_label_enum_exists() -> None:
    """v6.3 replaced AttackAngleSource with provider_id + acquisition_method.

    A composite provider-specific source label must not reappear as a stored type;
    user-facing labels are derived downstream (MODEL_SPEC.md 10).
    """
    import greenmachine.domain as domain

    exported = set(domain.__all__)
    for forbidden in ("AttackAngleSource", "SourceLabel", "AttackAngleSourceLabel"):
        assert forbidden not in exported
        assert not hasattr(domain, forbidden)


# --------------------------------------------------------------------------
# Serialization, hashing, and lookup
# --------------------------------------------------------------------------


@pytest.mark.parametrize("enum_type", ALL_ENUMS, ids=lambda e: e.__name__)
def test_enum_values_are_stable_json_serializable_strings(enum_type: type[Enum]) -> None:
    """The member ``value`` is the canonical serialized form and is a plain string."""
    for member in enum_type:
        assert isinstance(member.value, str)
        assert member.value.strip()
        assert json.loads(json.dumps(member.value)) == member.value


@pytest.mark.parametrize("enum_type", ALL_ENUMS, ids=lambda e: e.__name__)
def test_enum_round_trips_by_value(enum_type: type[Enum]) -> None:
    """Deserialization by value returns the identical member (identity, not a copy)."""
    for member in enum_type:
        assert enum_type(member.value) is member


@pytest.mark.parametrize("enum_type", ALL_ENUMS, ids=lambda e: e.__name__)
def test_enum_members_are_hashable_and_unique(enum_type: type[Enum]) -> None:
    members = list(enum_type)
    assert len(set(members)) == len(members)
    assert len({member.value for member in enum_type}) == len(members)


@pytest.mark.parametrize("enum_type", ALL_ENUMS, ids=lambda e: e.__name__)
def test_enum_members_are_not_bare_strings(enum_type: type[Enum]) -> None:
    """Members are Enum values, not str subclasses.

    This is what stops a raw string being passed where the vocabulary is required.
    """
    for member in enum_type:
        assert not isinstance(member, str)
        assert member != member.value


def test_unknown_enum_value_raises() -> None:
    with pytest.raises(ValueError, match=r"not_a_component"):
        ComponentId("not_a_component")

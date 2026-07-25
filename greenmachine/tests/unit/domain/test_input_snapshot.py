"""InputSnapshot coherence: one profile, one point in time, no leakage.

Structural rules only — content-derived identity is verified in the evaluation
layer. Each case starts from a valid frozen snapshot and breaks exactly one rule
via ``sr.rebuild_snapshot``, the test-only path through the internal construction
authority; the public paths are the factory and record decoding.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest
import synthetic_records as sr

from greenmachine.domain import (
    ComponentId,
    DomainValidationError,
    InputSnapshot,
    MissingReason,
    PitcherRole,
    SampleType,
    SnapshotId,
    WindowProfile,
)

VALID = sr.input_snapshot()


def test_a_frozen_snapshot_carries_one_profile_and_its_observations() -> None:
    assert VALID.window_profile is WindowProfile.RECENT_7D
    assert len(VALID.present_observations) == 3
    assert len(VALID.missing_observations) == 1


# --------------------------------------------------------------------------
# The construction boundary (r1 §2)
# --------------------------------------------------------------------------


def test_direct_public_construction_is_rejected() -> None:
    """Even a byte-perfect copy of a valid snapshot cannot be built directly."""
    field_values = {
        field.name: getattr(VALID, field.name) for field in dataclasses.fields(InputSnapshot)
    }

    with pytest.raises(DomainValidationError, match=r"freeze_input_snapshot"):
        InputSnapshot(**field_values)


def test_arbitrary_identity_replacement_is_unavailable() -> None:
    """dataclasses.replace re-runs __init__ without the authority, so it fails."""
    with pytest.raises(DomainValidationError, match=r"freeze_input_snapshot"):
        dataclasses.replace(VALID, snapshot_id=SnapshotId("CALLER-CHOSEN"))


def test_the_factory_path_still_works() -> None:
    assert sr.input_snapshot() == VALID


# --------------------------------------------------------------------------
# Structural coherence
# --------------------------------------------------------------------------


def test_a_list_is_rejected_where_a_tuple_is_required() -> None:
    with pytest.raises(DomainValidationError, match=r"must be a tuple"):
        sr.rebuild_snapshot(VALID, present_observations=list(VALID.present_observations))


def test_a_duplicate_observation_key_is_rejected() -> None:
    first = VALID.present_observations[0]
    with pytest.raises(DomainValidationError, match=r"duplicate"):
        sr.rebuild_snapshot(VALID, present_observations=(first, first))


def test_a_component_present_and_missing_at_once_is_rejected() -> None:
    missing_exit = sr.missing_observation(
        ComponentId.EXIT_VELOCITY, MissingReason.SOURCE_UNAVAILABLE, SampleType.BATTED_BALL_EVENTS
    )
    with pytest.raises(DomainValidationError, match=r"duplicate"):
        sr.rebuild_snapshot(VALID, missing_observations=(missing_exit,))


def test_an_observation_with_a_different_profile_is_rejected() -> None:
    wrong = dataclasses.replace(
        VALID.present_observations[0], window_profile=WindowProfile.LONG_TERM_2Y
    )
    others = VALID.present_observations[1:]
    with pytest.raises(DomainValidationError, match=r"window_profile"):
        sr.rebuild_snapshot(VALID, present_observations=(wrong, *others))


def test_an_observation_with_a_different_source_capture_is_rejected() -> None:
    other_capture = dataclasses.replace(
        VALID.present_observations[0], source_capture_id=sr.SourceCaptureId("OTHER-CAPTURE")
    )
    others = VALID.present_observations[1:]
    with pytest.raises(DomainValidationError, match=r"source_capture_id"):
        sr.rebuild_snapshot(VALID, present_observations=(other_capture, *others))


# --------------------------------------------------------------------------
# Exact window context on every observation (r1 §1)
# --------------------------------------------------------------------------


def _with_present_override(**observation_overrides: object) -> InputSnapshot:
    drifted = dataclasses.replace(VALID.present_observations[0], **observation_overrides)
    return sr.rebuild_snapshot(
        VALID, present_observations=(drifted, *VALID.present_observations[1:])
    )


def _with_missing_override(**observation_overrides: object) -> InputSnapshot:
    drifted = dataclasses.replace(VALID.missing_observations[0], **observation_overrides)
    return sr.rebuild_snapshot(VALID, missing_observations=(drifted,))


def test_a_present_observation_window_start_mismatch_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"present_observations\[0\]\.window_start"):
        _with_present_override(window_start=sr.WINDOW_START - timedelta(days=1))


def test_a_present_observation_window_end_mismatch_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"present_observations\[0\]\.window_end"):
        _with_present_override(window_end=sr.WINDOW_END - timedelta(hours=1))


def test_a_present_observation_as_of_mismatch_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"present_observations\[0\]\.as_of"):
        _with_present_override(as_of=sr.AS_OF - timedelta(minutes=5))


def test_a_missing_observation_window_start_mismatch_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"missing_observations\[0\]\.window_start"):
        _with_missing_override(window_start=sr.WINDOW_START - timedelta(days=1))


def test_a_missing_observation_window_end_mismatch_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"missing_observations\[0\]\.window_end"):
        _with_missing_override(window_end=sr.WINDOW_END - timedelta(hours=1))


def test_a_missing_observation_as_of_mismatch_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"missing_observations\[0\]\.as_of"):
        _with_missing_override(as_of=sr.AS_OF - timedelta(minutes=5))


def test_a_contained_but_different_observation_window_is_still_rejected() -> None:
    """Falling inside the snapshot window is not enough; it must be the window."""
    narrower_start = sr.WINDOW_START + timedelta(days=1)  # inside [start, end]
    with pytest.raises(DomainValidationError, match=r"window_start"):
        _with_present_override(window_start=narrower_start)


# --------------------------------------------------------------------------
# Point-in-time and weather rules
# --------------------------------------------------------------------------


def test_an_observation_sourced_after_as_of_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"source_as_of"):
        _with_present_override(source_as_of=sr.AS_OF + timedelta(hours=1))


def test_an_observation_retrieved_after_as_of_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"retrieved_at"):
        _with_present_override(retrieved_at=sr.AS_OF + timedelta(hours=1))


def test_a_window_that_closes_after_as_of_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"window_end"):
        sr.rebuild_snapshot(VALID, window_end=VALID.as_of + timedelta(hours=1))


def test_observed_weather_is_not_a_grading_input() -> None:
    # The snapshot has a present weather observation, so it must be a forecast.
    with pytest.raises(DomainValidationError, match=r"forecast"):
        sr.rebuild_snapshot(VALID, weather_is_forecast=False)


def test_a_pitcher_role_disagreeing_with_the_pitcher_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"pitcher_role"):
        sr.rebuild_snapshot(VALID, pitcher_role=PitcherRole.OPENER)


def test_a_snapshot_is_frozen_and_hashable() -> None:
    assert isinstance(hash(VALID), int)
    with pytest.raises(dataclasses.FrozenInstanceError):
        VALID.weather_is_forecast = False  # type: ignore[misc]


def test_the_abstract_input_snapshot_type_is_the_only_snapshot_type() -> None:
    assert isinstance(VALID, InputSnapshot)

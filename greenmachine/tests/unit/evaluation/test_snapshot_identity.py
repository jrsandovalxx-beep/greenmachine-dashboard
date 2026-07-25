"""Content-derived snapshot identity: deterministic, and self-verifying."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest
import synthetic_records as sr

from greenmachine.common.serialization import CanonicalizationError
from greenmachine.domain import (
    DomainValidationError,
    PitcherRole,
    Sha256Digest,
    SnapshotId,
    WindowProfile,
)
from greenmachine.evaluation import (
    EvaluationSerializationError,
    RecordIntegrityError,
    freeze_input_snapshot,
    serialize_record,
    verify_snapshot_identity,
)


def _freeze(present: tuple[object, ...]) -> object:
    return freeze_input_snapshot(
        source_capture_id=sr.CAPTURE,
        game_context=sr.game_context(),
        batter=sr.batter(),
        expected_starting_pitcher=sr.pitcher(),
        pitcher_role=PitcherRole.EXPECTED_STARTER,
        as_of=sr.AS_OF,
        window_profile=WindowProfile.RECENT_7D,
        window_start=sr.WINDOW_START,
        window_end=sr.WINDOW_END,
        present_observations=present,  # type: ignore[arg-type]
        missing_observations=(),
        validation_inputs=(),
        weather_is_forecast=False,
    )


def test_freezing_is_deterministic() -> None:
    first = sr.input_snapshot()
    second = sr.input_snapshot()

    assert first.snapshot_id == second.snapshot_id
    assert first.input_hash == second.input_hash
    assert first == second


def test_equal_payloads_produce_equal_identity() -> None:
    assert _freeze((sr.present_exit_velocity(),)) == _freeze((sr.present_exit_velocity(),))


def test_a_frozen_snapshot_passes_verification() -> None:
    verify_snapshot_identity(sr.input_snapshot())


def test_one_changed_observation_changes_the_identity() -> None:
    base = _freeze((sr.present_exit_velocity(),))
    changed_obs = dataclasses.replace(sr.present_exit_velocity(), raw_value=Decimal("99.9"))
    changed = _freeze((changed_obs,))

    assert base.snapshot_id != changed.snapshot_id  # type: ignore[attr-defined]
    assert base.input_hash != changed.input_hash  # type: ignore[attr-defined]


def test_two_profiles_from_one_capture_share_capture_but_not_identity() -> None:
    recent = sr.input_snapshot()
    long_term = sr.input_snapshot_long_term()

    assert recent.source_capture_id == long_term.source_capture_id
    assert recent.snapshot_id != long_term.snapshot_id
    assert recent.input_hash != long_term.input_hash


def test_a_tampered_input_hash_fails_verification() -> None:
    tampered = sr.rebuild_snapshot(sr.input_snapshot(), input_hash=Sha256Digest("b" * 64))
    with pytest.raises(RecordIntegrityError, match=r"input_hash"):
        verify_snapshot_identity(tampered)


def test_a_tampered_snapshot_id_fails_verification() -> None:
    tampered = sr.rebuild_snapshot(sr.input_snapshot(), snapshot_id=SnapshotId("TAMPERED"))
    with pytest.raises(RecordIntegrityError, match=r"snapshot_id"):
        verify_snapshot_identity(tampered)


# --------------------------------------------------------------------------
# r2 §3: the factory validates every input before hashing
# --------------------------------------------------------------------------


def _valid_freeze_kwargs() -> dict[str, object]:
    return {
        "source_capture_id": sr.CAPTURE,
        "game_context": sr.game_context(),
        "batter": sr.batter(),
        "expected_starting_pitcher": sr.pitcher(),
        "pitcher_role": PitcherRole.EXPECTED_STARTER,
        "as_of": sr.AS_OF,
        "window_profile": WindowProfile.RECENT_7D,
        "window_start": sr.WINDOW_START,
        "window_end": sr.WINDOW_END,
        "present_observations": (sr.present_exit_velocity(),),
        "missing_observations": (),
        "validation_inputs": (),
        "weather_is_forecast": False,
    }


def test_an_invalid_game_context_fails_before_hashing() -> None:
    kwargs = _valid_freeze_kwargs()
    kwargs["game_context"] = object()
    with pytest.raises(DomainValidationError, match=r"game_context"):
        freeze_input_snapshot(**kwargs)  # type: ignore[arg-type]


def test_an_invalid_member_in_present_observations_fails_before_hashing() -> None:
    kwargs = _valid_freeze_kwargs()
    kwargs["present_observations"] = (object(),)
    with pytest.raises(DomainValidationError, match=r"present_observations\[0\]"):
        freeze_input_snapshot(**kwargs)  # type: ignore[arg-type]


def test_an_invalid_member_in_validation_inputs_fails_before_hashing() -> None:
    kwargs = _valid_freeze_kwargs()
    kwargs["validation_inputs"] = (object(),)
    with pytest.raises(DomainValidationError, match=r"validation_inputs\[0\]"):
        freeze_input_snapshot(**kwargs)  # type: ignore[arg-type]


def test_a_list_passed_to_the_factory_fails_before_hashing() -> None:
    kwargs = _valid_freeze_kwargs()
    kwargs["present_observations"] = [sr.present_exit_velocity()]
    with pytest.raises(DomainValidationError, match=r"must be a tuple"):
        freeze_input_snapshot(**kwargs)  # type: ignore[arg-type]


def test_a_context_mismatch_through_the_factory_is_a_domain_error() -> None:
    kwargs = _valid_freeze_kwargs()
    long_term_obs = dataclasses.replace(
        sr.present_exit_velocity(), window_profile=WindowProfile.LONG_TERM_2Y
    )
    kwargs["present_observations"] = (long_term_obs,)
    with pytest.raises(DomainValidationError, match=r"window_profile"):
        freeze_input_snapshot(**kwargs)  # type: ignore[arg-type]


def test_valid_factory_output_remains_byte_and_identity_stable() -> None:
    first = sr.input_snapshot()
    second = sr.input_snapshot()

    assert first == second
    assert first.snapshot_id == second.snapshot_id
    assert serialize_record(first) == serialize_record(second)


# --------------------------------------------------------------------------
# r2 §4: verify_snapshot_identity is hardened at its public boundary
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["not a snapshot", None, object()], ids=["str", "None", "object"])
def test_verify_rejects_a_non_snapshot_argument(bad: object) -> None:
    with pytest.raises(EvaluationSerializationError, match=r"expects an InputSnapshot"):
        verify_snapshot_identity(bad)  # type: ignore[arg-type]


def test_an_uncanonicalizable_tampered_snapshot_is_a_record_integrity_error() -> None:
    """A forged field that cannot be canonically serialized is still a typed error.

    No public path can produce this state (construction validates every field);
    the slot is forged past the frozen dataclass purely to prove the translation.
    """
    snapshot = sr.input_snapshot()
    object.__setattr__(snapshot, "batter", object())

    with pytest.raises(RecordIntegrityError, match=r"could not be canonically") as caught:
        verify_snapshot_identity(snapshot)

    assert isinstance(caught.value.__cause__, CanonicalizationError)


def test_a_valid_snapshot_still_verifies() -> None:
    verify_snapshot_identity(sr.input_snapshot())

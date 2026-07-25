"""The frozen input snapshot: one window profile, enough to reproduce a grade.

ADR-0003 makes the ``InputSnapshot`` — not the code — the unit of
reproducibility. ADR-0005 makes it carry **exactly one** :class:`WindowProfile`:
one source capture freezes two independent profile-specific snapshots that share
a ``source_capture_id`` but differ in everything the window touches.

This module defines the *contract and its coherence rules only*. It computes no
rolling window (feature assembly supplies the resolved bounds later) and no
identity: ``snapshot_id`` and ``input_hash`` are content-derived at the
domain/evaluation boundary by ``greenmachine.evaluation`` — the domain never
imports ``common`` hashing, so a snapshot cannot hash itself.

Because the domain cannot recompute the identity, it refuses to construct a
snapshot for anyone who could fake one: creation requires a module-private
construction authority held only by the evaluation layer's freezing factory and
its decode-time rehydration path (which verifies the stored identity before
trusting it). Direct public construction — and identity replacement through
``dataclasses.replace`` — fails with :class:`DomainValidationError`, so a
caller-selected ``snapshot_id``/``input_hash`` pair can never come into being.

The content validation itself lives in one module-private function,
:func:`_validate_snapshot_content`, shared by ``__post_init__`` and the freezing
factory: the factory validates the raw inputs *before* canonical hashing (so an
invalid payload fails as a typed domain error, never as a canonicalization
error), and the constructor applies exactly the same rules, so the two can never
drift.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass
from datetime import datetime

from ._guards import (
    ensure_aware_datetime,
    ensure_bool,
    ensure_instance,
    ensure_no_duplicates,
    ensure_non_empty_text,
    ensure_optional_instance,
    ensure_tuple_of,
    ensure_utc,
)
from .entities import Batter, GameContext, Pitcher
from .enums import ComponentId, PitcherRole, ValidationInputId, WindowProfile
from .errors import DomainValidationError
from .observations import MetricObservation, MissingObservation
from .values import Sha256Digest, SnapshotId, SourceCaptureId

__all__ = ["InputSnapshot", "ValidationInputRecord"]

# The internal construction authority. Deliberately module-private, never in
# ``__all__``, and never re-exported by ``greenmachine.domain``: only the
# evaluation layer's snapshot-freezing factory and its decode-time rehydration
# path hold it, so a snapshot with a caller-selected identity cannot be built.
_SNAPSHOT_CONSTRUCTION_AUTHORITY: object = object()


@dataclass(frozen=True, slots=True)
class ValidationInputRecord:
    """One advisory Validation Layer *input* captured in a snapshot.

    Data only — it awards no points and carries no value that scoring could read
    (``MODEL_SPEC.md`` §17). It records which advisory input was captured, the
    component it concerns where applicable, and a normalized human-readable
    summary. The advisory *conclusion* drawn from it is a
    :class:`~greenmachine.domain.results.ValidationFinding`, which lives on the
    result, not here.
    """

    input_id: ValidationInputId
    summary: str
    component_id: ComponentId | None = None

    def __post_init__(self) -> None:
        ensure_instance(self.input_id, ValidationInputId, "ValidationInputRecord.input_id")
        ensure_non_empty_text(self.summary, "ValidationInputRecord.summary")
        ensure_optional_instance(
            self.component_id, ComponentId, "ValidationInputRecord.component_id"
        )


@dataclass(frozen=True, slots=True)
class InputSnapshot:
    """A frozen, profile-specific set of grading inputs (ADR-0003, ADR-0005).

    Holds one window profile's resolved bounds and every present and missing
    observation, plus the subject, the advisory validation inputs, and whether
    weather was a grading-time forecast. Its identity fields are validated for
    *shape* here (``input_hash`` is a :class:`Sha256Digest`), while their
    *coherence with the content* is guaranteed by the construction boundary: the
    only holders of the internal authority are the evaluation layer's
    ``freeze_input_snapshot`` (which validates the content, then derives the
    identity from it) and its decode path (which verifies the stored identity
    before returning).

    Construction enforces the point-in-time and single-profile invariants: the
    window is ordered and closes at or before ``as_of``; every observation shares
    the snapshot's exact profile, ``window_start``, ``window_end``, ``as_of``,
    and ``source_capture_id``; no ``(component_id, measurement_id)`` key appears
    twice or as both present and missing; nothing was sourced or retrieved after
    ``as_of``; and weather, if present, is explicitly a forecast — observed
    postgame weather has no representation and can never enter grading.
    """

    snapshot_id: SnapshotId
    input_hash: Sha256Digest
    source_capture_id: SourceCaptureId
    game_context: GameContext
    batter: Batter
    expected_starting_pitcher: Pitcher
    pitcher_role: PitcherRole
    as_of: datetime
    window_profile: WindowProfile
    window_start: datetime
    window_end: datetime
    present_observations: tuple[MetricObservation, ...]
    missing_observations: tuple[MissingObservation, ...]
    validation_inputs: tuple[ValidationInputRecord, ...]
    weather_is_forecast: bool
    _authority: InitVar[object | None] = None

    def __post_init__(self, _authority: object | None) -> None:
        # The construction gate comes first: without the internal authority this
        # record must not exist at all, whatever its fields contain. The gate also
        # covers dataclasses.replace, which re-runs __init__ with the default.
        if _authority is not _SNAPSHOT_CONSTRUCTION_AUTHORITY:
            raise DomainValidationError(
                "InputSnapshot cannot be constructed directly: snapshot_id and input_hash "
                "are content-derived. Create one with "
                "greenmachine.evaluation.freeze_input_snapshot, or decode a stored record."
            )
        ensure_instance(self.snapshot_id, SnapshotId, "InputSnapshot.snapshot_id")
        ensure_instance(self.input_hash, Sha256Digest, "InputSnapshot.input_hash")
        _validate_snapshot_content(
            source_capture_id=self.source_capture_id,
            game_context=self.game_context,
            batter=self.batter,
            expected_starting_pitcher=self.expected_starting_pitcher,
            pitcher_role=self.pitcher_role,
            as_of=self.as_of,
            window_profile=self.window_profile,
            window_start=self.window_start,
            window_end=self.window_end,
            present_observations=self.present_observations,
            missing_observations=self.missing_observations,
            validation_inputs=self.validation_inputs,
            weather_is_forecast=self.weather_is_forecast,
        )


def _validate_snapshot_content(
    *,
    source_capture_id: SourceCaptureId,
    game_context: GameContext,
    batter: Batter,
    expected_starting_pitcher: Pitcher,
    pitcher_role: PitcherRole,
    as_of: datetime,
    window_profile: WindowProfile,
    window_start: datetime,
    window_end: datetime,
    present_observations: tuple[MetricObservation, ...],
    missing_observations: tuple[MissingObservation, ...],
    validation_inputs: tuple[ValidationInputRecord, ...],
    weather_is_forecast: bool,
) -> None:
    """The single definition of a well-formed snapshot's content.

    Shared verbatim by ``InputSnapshot.__post_init__`` and the evaluation
    layer's freezing factory, which calls it *before* canonical hashing so that
    a malformed payload fails as a :class:`DomainValidationError` rather than a
    canonicalization error. Every check runs against the runtime value, so an
    untyped caller's garbage is named, never leaked.
    """
    capture = ensure_instance(source_capture_id, SourceCaptureId, "InputSnapshot.source_capture_id")
    ensure_instance(game_context, GameContext, "InputSnapshot.game_context")
    ensure_instance(batter, Batter, "InputSnapshot.batter")
    pitcher = ensure_instance(
        expected_starting_pitcher, Pitcher, "InputSnapshot.expected_starting_pitcher"
    )
    role = ensure_instance(pitcher_role, PitcherRole, "InputSnapshot.pitcher_role")
    as_of_instant = ensure_utc(as_of, "InputSnapshot.as_of")
    profile = ensure_instance(window_profile, WindowProfile, "InputSnapshot.window_profile")
    start = ensure_aware_datetime(window_start, "InputSnapshot.window_start")
    end = ensure_aware_datetime(window_end, "InputSnapshot.window_end")
    present = ensure_tuple_of(
        present_observations, MetricObservation, "InputSnapshot.present_observations"
    )
    missing = ensure_tuple_of(
        missing_observations, MissingObservation, "InputSnapshot.missing_observations"
    )
    ensure_tuple_of(validation_inputs, ValidationInputRecord, "InputSnapshot.validation_inputs")
    forecast = ensure_bool(weather_is_forecast, "InputSnapshot.weather_is_forecast")

    # The pitcher role is carried on the snapshot and must agree with the
    # pitcher it describes, so the two can never drift apart.
    if role is not pitcher.role:
        raise DomainValidationError(
            f"InputSnapshot.pitcher_role ('{role.value}') must equal "
            f"expected_starting_pitcher.role ('{pitcher.role.value}')"
        )

    # The window is ordered and closes at or before the point in time.
    if start > end:
        raise DomainValidationError(
            f"InputSnapshot.window_start ({start.isoformat()}) must be <= "
            f"window_end ({end.isoformat()})"
        )
    if end > as_of_instant:
        raise DomainValidationError(
            f"InputSnapshot.window_end ({end.isoformat()}) must be <= "
            f"as_of ({as_of_instant.isoformat()})"
        )

    for index, present_obs in enumerate(present):
        _check_shared_fields(
            present_obs,
            f"present_observations[{index}]",
            profile,
            capture,
            start,
            end,
            as_of_instant,
        )
        if present_obs.source_as_of > as_of_instant:
            raise DomainValidationError(
                f"InputSnapshot.present_observations[{index}].source_as_of "
                f"({present_obs.source_as_of.isoformat()}) must be <= as_of "
                f"({as_of_instant.isoformat()}); no input dated after the point in time "
                f"may enter"
            )
        if present_obs.retrieved_at > as_of_instant:
            raise DomainValidationError(
                f"InputSnapshot.present_observations[{index}].retrieved_at "
                f"({present_obs.retrieved_at.isoformat()}) must be <= as_of "
                f"({as_of_instant.isoformat()})"
            )
    for index, missing_obs in enumerate(missing):
        _check_shared_fields(
            missing_obs,
            f"missing_observations[{index}]",
            profile,
            capture,
            start,
            end,
            as_of_instant,
        )

    # A component/measurement key identifies one observation. It may not repeat
    # within present, within missing, or across the two — a component cannot be
    # both present and missing at once.
    keys = [(o.component_id, o.measurement_id) for o in present]
    keys += [(o.component_id, o.measurement_id) for o in missing]
    ensure_no_duplicates(keys, "InputSnapshot observation (component_id, measurement_id) keys")

    has_weather = any(o.component_id is ComponentId.WEATHER for o in present)
    if has_weather and not forecast:
        raise DomainValidationError(
            "InputSnapshot has a present weather observation but weather_is_forecast is "
            "False; grading-time weather must be a forecast, and observed postgame weather "
            "is never a grading input"
        )


def _check_shared_fields(
    observation: MetricObservation | MissingObservation,
    where: str,
    profile: WindowProfile,
    capture: SourceCaptureId,
    window_start: datetime,
    window_end: datetime,
    as_of: datetime,
) -> None:
    """Exact context equality: the observation carries the snapshot's window.

    Not containment — the observation must have been assembled for exactly the
    selected profile window, so every field is compared for equality and the
    failure names the observation index and the offending field.
    """
    if observation.window_profile is not profile:
        raise DomainValidationError(
            f"InputSnapshot.{where}.window_profile ('{observation.window_profile.value}') "
            f"must equal the snapshot's window_profile ('{profile.value}')"
        )
    if observation.source_capture_id != capture:
        raise DomainValidationError(
            f"InputSnapshot.{where}.source_capture_id must equal the snapshot's "
            f"source_capture_id ('{capture.value}')"
        )
    if observation.window_start != window_start:
        raise DomainValidationError(
            f"InputSnapshot.{where}.window_start "
            f"({observation.window_start.isoformat()}) must equal the snapshot's "
            f"window_start ({window_start.isoformat()})"
        )
    if observation.window_end != window_end:
        raise DomainValidationError(
            f"InputSnapshot.{where}.window_end "
            f"({observation.window_end.isoformat()}) must equal the snapshot's "
            f"window_end ({window_end.isoformat()})"
        )
    if observation.as_of != as_of:
        raise DomainValidationError(
            f"InputSnapshot.{where}.as_of ({observation.as_of.isoformat()}) "
            f"must equal the snapshot's as_of ({as_of.isoformat()})"
        )

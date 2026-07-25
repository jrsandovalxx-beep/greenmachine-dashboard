"""The evaluation envelope: one grade result plus its orchestration metadata.

ADR-0004 keeps ``GradeResult`` pure by moving everything time-, identity-, and
version-bearing onto this wrapper. The envelope carries the evaluation identity,
the ``evaluated_at`` supplied by orchestration (never read from a clock here), the
four version streams, the two content hashes as :class:`Sha256Digest` references,
the subject identity, provenance, and an optional supersession link.

It holds exactly one :class:`~greenmachine.domain.grade_result.GradeResult` and no
outcome (ADR-0006), and it never mutates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from ._guards import (
    ensure_aware_datetime,
    ensure_instance,
    ensure_measurement_matches_component,
    ensure_no_duplicates,
    ensure_non_empty_text,
    ensure_non_negative_int,
    ensure_optional_instance,
    ensure_tuple_of,
    ensure_utc,
)
from .enums import (
    AcquisitionMethod,
    ComponentId,
    MeasurementId,
    PitcherRole,
    ProviderId,
    WindowProfile,
)
from .errors import DomainValidationError
from .grade_result import EvaluatedGradeResult, GradeResult, NotEvaluableGradeResult
from .observations import MetricObservation
from .values import EvaluationId, GameId, PlayerId, Sha256Digest, SnapshotId, SourceCaptureId

__all__ = ["EvaluationEnvelope", "ProvenanceEntry"]


@dataclass(frozen=True, slots=True)
class ProvenanceEntry:
    """One normalized provenance fact for the envelope.

    Stable, normalized concepts only — the provider, the acquisition method, the
    source and retrieval instants, and the component/measurement it concerns where
    applicable. It deliberately holds no Savant column name, CSS selector, raw
    response, or parser detail: those are ingestion implementation, not identity.
    """

    provider_id: ProviderId
    acquisition_method: AcquisitionMethod
    source_as_of: datetime
    retrieved_at: datetime
    component_id: ComponentId | None = None
    measurement_id: MeasurementId | None = None

    def __post_init__(self) -> None:
        ensure_instance(self.provider_id, ProviderId, "ProvenanceEntry.provider_id")
        ensure_instance(
            self.acquisition_method, AcquisitionMethod, "ProvenanceEntry.acquisition_method"
        )
        ensure_aware_datetime(self.source_as_of, "ProvenanceEntry.source_as_of")
        ensure_aware_datetime(self.retrieved_at, "ProvenanceEntry.retrieved_at")
        if self.component_id is None:
            ensure_optional_instance(
                self.measurement_id, MeasurementId, "ProvenanceEntry.measurement_id"
            )
            if self.measurement_id is not None:
                raise DomainValidationError(
                    "ProvenanceEntry.measurement_id must be None when component_id is None"
                )
        else:
            ensure_measurement_matches_component(
                self.component_id, self.measurement_id, "ProvenanceEntry"
            )


@dataclass(frozen=True, slots=True)
class EvaluationEnvelope:
    """A stored evaluation: one :class:`GradeResult` and its metadata.

    Construction validates the metadata rather than trusting it: ``evaluated_at``
    is timezone-aware UTC and supplied (no clock is read); the schema version is a
    strict positive ``int`` (``bool`` refused); the version strings are non-blank;
    ``slate_date`` is a plain ``date``; the two hashes are :class:`Sha256Digest`;
    the envelope's profile matches the result's; a supersession cannot point at the
    envelope's own id; and every provenance entry that names a component matches an
    observation on the result.
    """

    evaluation_id: EvaluationId
    snapshot_id: SnapshotId
    source_capture_id: SourceCaptureId
    evaluated_at: datetime
    code_version: str
    model_configuration_version: str
    product_specification_version: str
    schema_version: int
    config_hash: Sha256Digest
    input_hash: Sha256Digest
    game_id: GameId
    slate_date: date
    batter_id: PlayerId
    expected_starting_pitcher_id: PlayerId
    window_profile: WindowProfile
    pitcher_role: PitcherRole
    provenance: tuple[ProvenanceEntry, ...]
    supersedes: EvaluationId | None
    grade_result: GradeResult

    def __post_init__(self) -> None:
        evaluation_id = ensure_instance(
            self.evaluation_id, EvaluationId, "EvaluationEnvelope.evaluation_id"
        )
        ensure_instance(self.snapshot_id, SnapshotId, "EvaluationEnvelope.snapshot_id")
        ensure_instance(
            self.source_capture_id, SourceCaptureId, "EvaluationEnvelope.source_capture_id"
        )
        ensure_utc(self.evaluated_at, "EvaluationEnvelope.evaluated_at")
        ensure_non_empty_text(self.code_version, "EvaluationEnvelope.code_version")
        ensure_non_empty_text(
            self.model_configuration_version, "EvaluationEnvelope.model_configuration_version"
        )
        ensure_non_empty_text(
            self.product_specification_version,
            "EvaluationEnvelope.product_specification_version",
        )
        version = ensure_non_negative_int(self.schema_version, "EvaluationEnvelope.schema_version")
        if version == 0:
            raise DomainValidationError(
                "EvaluationEnvelope.schema_version must be a positive integer, got 0"
            )
        ensure_instance(self.config_hash, Sha256Digest, "EvaluationEnvelope.config_hash")
        ensure_instance(self.input_hash, Sha256Digest, "EvaluationEnvelope.input_hash")
        ensure_instance(self.game_id, GameId, "EvaluationEnvelope.game_id")
        # ``datetime`` is a subtype of ``date``; reject it so the slate stays a date.
        if isinstance(self.slate_date, datetime):
            raise DomainValidationError(
                "EvaluationEnvelope.slate_date must be a datetime.date, not a datetime"
            )
        ensure_instance(self.slate_date, date, "EvaluationEnvelope.slate_date")
        ensure_instance(self.batter_id, PlayerId, "EvaluationEnvelope.batter_id")
        ensure_instance(
            self.expected_starting_pitcher_id,
            PlayerId,
            "EvaluationEnvelope.expected_starting_pitcher_id",
        )
        profile = ensure_instance(
            self.window_profile, WindowProfile, "EvaluationEnvelope.window_profile"
        )
        ensure_instance(self.pitcher_role, PitcherRole, "EvaluationEnvelope.pitcher_role")
        provenance = ensure_tuple_of(
            self.provenance, ProvenanceEntry, "EvaluationEnvelope.provenance"
        )
        supersedes = ensure_optional_instance(
            self.supersedes, EvaluationId, "EvaluationEnvelope.supersedes"
        )
        result = ensure_instance(self.grade_result, GradeResult, "EvaluationEnvelope.grade_result")

        # Only the two approved variants may be enveloped. An arbitrary third
        # subclass of GradeResult — even one that passes the base validation —
        # is not a contract this system stores.
        if type(result) is not EvaluatedGradeResult and type(result) is not NotEvaluableGradeResult:
            raise DomainValidationError(
                f"EvaluationEnvelope.grade_result must be exactly an EvaluatedGradeResult or "
                f"a NotEvaluableGradeResult, got {type(result).__name__}"
            )

        if profile is not result.window_profile:
            raise DomainValidationError(
                f"EvaluationEnvelope.window_profile ('{profile.value}') must equal "
                f"grade_result.window_profile ('{result.window_profile.value}')"
            )
        if supersedes is not None and supersedes == evaluation_id:
            raise DomainValidationError(
                f"EvaluationEnvelope.supersedes must not equal evaluation_id "
                f"('{evaluation_id.value}'); an evaluation cannot supersede itself"
            )
        evaluated_at = self.evaluated_at
        self._check_result_observations(result, self.source_capture_id, evaluated_at)
        self._check_provenance_consistency(provenance, result, evaluated_at)

    @staticmethod
    def _check_result_observations(
        result: GradeResult, capture: SourceCaptureId, evaluated_at: datetime
    ) -> None:
        """The result's observations belong to this capture and precede this time.

        Every observation must carry the envelope's ``source_capture_id`` — an
        envelope may not label a result with another capture, and a result mixing
        captures cannot be enveloped at all. Nothing the evaluation consumed may
        be dated, sourced, or retrieved after ``evaluated_at``.
        """
        for index, present in enumerate(result.present_observations):
            where = f"grade_result.present_observations[{index}]"
            if present.source_capture_id != capture:
                raise DomainValidationError(
                    f"EvaluationEnvelope.{where}.source_capture_id "
                    f"('{present.source_capture_id.value}') must equal the envelope's "
                    f"source_capture_id ('{capture.value}')"
                )
            if present.source_as_of > evaluated_at:
                raise DomainValidationError(
                    f"EvaluationEnvelope.{where}.source_as_of "
                    f"({present.source_as_of.isoformat()}) must be <= evaluated_at "
                    f"({evaluated_at.isoformat()})"
                )
            if present.retrieved_at > evaluated_at:
                raise DomainValidationError(
                    f"EvaluationEnvelope.{where}.retrieved_at "
                    f"({present.retrieved_at.isoformat()}) must be <= evaluated_at "
                    f"({evaluated_at.isoformat()})"
                )
            if present.as_of > evaluated_at:
                raise DomainValidationError(
                    f"EvaluationEnvelope.{where}.as_of ({present.as_of.isoformat()}) must "
                    f"be <= evaluated_at ({evaluated_at.isoformat()})"
                )
        for index, missing in enumerate(result.missing_observations):
            where = f"grade_result.missing_observations[{index}]"
            if missing.source_capture_id != capture:
                raise DomainValidationError(
                    f"EvaluationEnvelope.{where}.source_capture_id "
                    f"('{missing.source_capture_id.value}') must equal the envelope's "
                    f"source_capture_id ('{capture.value}')"
                )
            if missing.as_of > evaluated_at:
                raise DomainValidationError(
                    f"EvaluationEnvelope.{where}.as_of ({missing.as_of.isoformat()}) must "
                    f"be <= evaluated_at ({evaluated_at.isoformat()})"
                )

    @staticmethod
    def _check_provenance_consistency(
        provenance: tuple[ProvenanceEntry, ...], result: GradeResult, evaluated_at: datetime
    ) -> None:
        """Component-scoped provenance must match a present observation exactly.

        A matching component key alone is not enough: the provider, acquisition
        method, ``source_as_of``, and ``retrieved_at`` must all equal the present
        observation's. A missing-only component has no *selected* acquisition
        method (its failed attempts are ``MethodIneligibility`` records), so a
        component-scoped entry may never point at one. Generic entries with
        ``component_id=None`` remain permitted, duplicates are refused, and no
        provenance instant may follow ``evaluated_at``.
        """
        ensure_no_duplicates(provenance, "EvaluationEnvelope.provenance")
        present_by_key: dict[tuple[ComponentId, MeasurementId | None], MetricObservation] = {
            (observation.component_id, observation.measurement_id): observation
            for observation in result.present_observations
        }
        for index, entry in enumerate(provenance):
            where = f"provenance[{index}]"
            if entry.source_as_of > evaluated_at:
                raise DomainValidationError(
                    f"EvaluationEnvelope.{where}.source_as_of "
                    f"({entry.source_as_of.isoformat()}) must be <= evaluated_at "
                    f"({evaluated_at.isoformat()})"
                )
            if entry.retrieved_at > evaluated_at:
                raise DomainValidationError(
                    f"EvaluationEnvelope.{where}.retrieved_at "
                    f"({entry.retrieved_at.isoformat()}) must be <= evaluated_at "
                    f"({evaluated_at.isoformat()})"
                )
            if entry.component_id is None:
                continue
            key = (entry.component_id, entry.measurement_id)
            observation = present_by_key.get(key)
            if observation is None:
                raise DomainValidationError(
                    f"EvaluationEnvelope.{where} names component "
                    f"'{entry.component_id.value}', which has no matching present observation "
                    f"on the grade result; a missing-only component has no selected "
                    f"acquisition method"
                )
            if entry.provider_id is not observation.provider_id:
                raise DomainValidationError(
                    f"EvaluationEnvelope.{where}.provider_id ('{entry.provider_id.value}') "
                    f"must equal the matching observation's provider_id "
                    f"('{observation.provider_id.value}')"
                )
            if entry.acquisition_method is not observation.acquisition_method:
                raise DomainValidationError(
                    f"EvaluationEnvelope.{where}.acquisition_method "
                    f"('{entry.acquisition_method.value}') must equal the matching "
                    f"observation's acquisition_method "
                    f"('{observation.acquisition_method.value}')"
                )
            if entry.source_as_of != observation.source_as_of:
                raise DomainValidationError(
                    f"EvaluationEnvelope.{where}.source_as_of "
                    f"({entry.source_as_of.isoformat()}) must equal the matching "
                    f"observation's source_as_of ({observation.source_as_of.isoformat()})"
                )
            if entry.retrieved_at != observation.retrieved_at:
                raise DomainValidationError(
                    f"EvaluationEnvelope.{where}.retrieved_at "
                    f"({entry.retrieved_at.isoformat()}) must equal the matching "
                    f"observation's retrieved_at ({observation.retrieved_at.isoformat()})"
                )

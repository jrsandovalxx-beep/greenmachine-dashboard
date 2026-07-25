"""Domain vocabulary: frozen value objects, enums, and observation records.

This package depends on nothing else in GreenMachine and on no third-party
library. It performs no I/O, reads no clock, and holds no rules: every threshold,
allocation, bucket, and sample minimum is configuration (``MODEL_SPEC.md`` §3,
§19), and every calculation belongs to the scoring core.

What lives here is the shared, typed vocabulary named in ``GLOSSARY.md`` — the
names the Product Owner and the code agree on. All types are frozen, hashable,
and validate their structural invariants at construction, raising
:class:`DomainValidationError`.

Delivered by GM-002; the composite records that sit on top of this vocabulary —
:class:`InputSnapshot`, the :class:`GradeResult` variants,
:class:`EvaluationEnvelope`, and :class:`OutcomeRecord` — are added by GM-006.
Content-derived identity and canonical serialization for those records live in
``greenmachine.evaluation``, which keeps the hashing out of the pure domain.
"""

from __future__ import annotations

from .entities import Batter, GameContext, Pitcher, Venue
from .enums import (
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
from .envelope import EvaluationEnvelope, ProvenanceEntry
from .errors import DomainError, DomainValidationError
from .grade_result import (
    AuditEntry,
    EvaluatedGradeResult,
    GradeResult,
    NotEvaluableGradeResult,
    UnavailableRequiredInput,
)
from .observations import MetricObservation, MissingObservation
from .outcome import OutcomeRecord
from .results import BucketHit, CategoryScore, ComponentScore, ValidationFinding
from .snapshot import InputSnapshot, ValidationInputRecord
from .values import (
    CoverageWindow,
    DataCoverage,
    EvaluationId,
    FallbackRecord,
    GameId,
    MethodIneligibility,
    PlayerId,
    Sha256Digest,
    SnapshotId,
    SourceCaptureId,
    VenueId,
)

__all__ = [
    "AcquisitionMethod",
    "AuditEntry",
    "Batter",
    "BucketHit",
    "Category",
    "CategoryScore",
    "ComponentId",
    "ComponentScore",
    "CoverageStatus",
    "CoverageWindow",
    "DataCoverage",
    "DomainError",
    "DomainValidationError",
    "EvaluatedGradeResult",
    "EvaluationEnvelope",
    "EvaluationId",
    "EvaluationStatus",
    "FallbackRecord",
    "GameContext",
    "GameId",
    "Grade",
    "GradeResult",
    "InputSnapshot",
    "MeasurementId",
    "MethodIneligibility",
    "MetricObservation",
    "MissingObservation",
    "MissingReason",
    "NotEvaluableGradeResult",
    "OutcomeRecord",
    "Pitcher",
    "PitcherRole",
    "PlayerId",
    "ProvenanceEntry",
    "ProviderId",
    "SampleStatus",
    "SampleType",
    "Sha256Digest",
    "Signal",
    "SnapshotId",
    "SourceCaptureId",
    "UnavailableRequiredInput",
    "ValidationFinding",
    "ValidationInputId",
    "ValidationInputRecord",
    "Venue",
    "VenueId",
    "WindowProfile",
]

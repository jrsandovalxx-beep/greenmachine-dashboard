"""Immutable value objects: identifiers, provenance, and coverage.

All types are frozen and hashable and validate their invariants at construction —
both the runtime *type* of every field and the coherence rules that relate them.
Identifiers are *distinct* wrapper types rather than bare strings, so a
:class:`GameId` cannot be passed where a :class:`PlayerId` is expected. None of
them generate a value — construction only (``MODEL_SPEC.md`` §7.2: the official
provider identifier is used canonically, and no replacement id is minted here).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ._guards import (
    ensure_bool,
    ensure_instance,
    ensure_no_duplicates,
    ensure_non_empty_text,
    ensure_non_negative_int,
    ensure_optional_instance,
    ensure_ordered,
    ensure_sha256_hex,
    ensure_tuple_of,
)
from .enums import AcquisitionMethod, CoverageStatus
from .errors import DomainValidationError

__all__ = [
    "CoverageWindow",
    "DataCoverage",
    "EvaluationId",
    "FallbackRecord",
    "GameId",
    "MethodIneligibility",
    "PlayerId",
    "Sha256Digest",
    "SnapshotId",
    "SourceCaptureId",
    "VenueId",
]


@dataclass(frozen=True, slots=True)
class Sha256Digest:
    """A stored SHA-256 digest reference: one lowercase 64-character hex string.

    Frozen, hashable, and validated at construction — it rejects uppercase, the
    wrong length, whitespace, non-hex characters, and non-string values, raising
    :class:`DomainValidationError`. It **validates only; it never computes a
    digest** (hashing stays in ``greenmachine.common``).

    This one generic type carries both a ``config_hash`` and an ``input_hash``.
    Their semantic distinction is not erased, because the *fields* that hold them
    — ``EvaluationEnvelope.config_hash`` and ``EvaluationEnvelope.input_hash`` —
    stay distinct and separately named. Keeping the reference type in the domain
    is what lets a stored record cite a hash without the domain depending on
    ``greenmachine.config`` (which owns :class:`~greenmachine.config.ConfigHash`
    and is never imported here).
    """

    value: str

    def __post_init__(self) -> None:
        ensure_sha256_hex(self.value, "Sha256Digest.value")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class GameId:
    """The official provider's canonical game identifier (``MODEL_SPEC.md`` §7.2).

    Doubleheader games have separate ids; a suspended-and-resumed game keeps its
    id. No internal replacement id is ever generated — the provider string is the
    identity, preserved verbatim.
    """

    value: str

    def __post_init__(self) -> None:
        ensure_non_empty_text(self.value, "GameId.value")


@dataclass(frozen=True, slots=True)
class PlayerId:
    """A provider's player identifier, used for both batters and pitchers."""

    value: str

    def __post_init__(self) -> None:
        ensure_non_empty_text(self.value, "PlayerId.value")


@dataclass(frozen=True, slots=True)
class VenueId:
    """A provider's venue identifier."""

    value: str

    def __post_init__(self) -> None:
        ensure_non_empty_text(self.value, "VenueId.value")


@dataclass(frozen=True, slots=True)
class SnapshotId:
    """Identifier of one frozen, profile-specific input snapshot.

    Content derivation is GM-005/GM-006 work; this is a construction-only wrapper
    so the vocabulary that references a snapshot exists now. Distinct per profile
    (``GLOSSARY.md`` §3).
    """

    value: str

    def __post_init__(self) -> None:
        ensure_non_empty_text(self.value, "SnapshotId.value")


@dataclass(frozen=True, slots=True)
class SourceCaptureId:
    """Identifier shared by snapshots produced from the same source capture.

    It *links* the two profile-specific snapshots of one collection operation; it
    does not make them identical (``MODEL_SPEC.md`` §6.2).
    """

    value: str

    def __post_init__(self) -> None:
        ensure_non_empty_text(self.value, "SourceCaptureId.value")


@dataclass(frozen=True, slots=True)
class EvaluationId:
    """Identifier of one stored evaluation. Construction-only wrapper."""

    value: str

    def __post_init__(self) -> None:
        ensure_non_empty_text(self.value, "EvaluationId.value")


@dataclass(frozen=True, slots=True)
class CoverageWindow:
    """A period bound, used for requested and actual coverage."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        ensure_ordered(self.start, self.end, "CoverageWindow.start", "CoverageWindow.end")


@dataclass(frozen=True, slots=True)
class DataCoverage:
    """Point-in-time coverage record for one observation (``MODEL_SPEC.md`` §11.1).

    Preserves the requested period, the period actually covered (``None`` when no
    data was available), a coverage status, source availability, and the observed
    sample count.

    The coherence rules exist so partial coverage can never be dressed up as
    complete: ``COMPLETE`` and ``PARTIAL`` both require a real covered period from
    an available source, ``NONE`` requires no covered period and no samples, and an
    unavailable source can only be ``NONE``. A covered period must also fall inside
    the period that was requested.
    """

    requested: CoverageWindow
    actual: CoverageWindow | None
    status: CoverageStatus
    source_available: bool
    sample_count: int

    def __post_init__(self) -> None:
        requested = ensure_instance(self.requested, CoverageWindow, "DataCoverage.requested")
        actual = ensure_optional_instance(self.actual, CoverageWindow, "DataCoverage.actual")
        status = ensure_instance(self.status, CoverageStatus, "DataCoverage.status")
        ensure_bool(self.source_available, "DataCoverage.source_available")
        ensure_non_negative_int(self.sample_count, "DataCoverage.sample_count")

        # An unavailable source is the stronger precondition, so it is checked
        # first: nothing was retrieved, so nothing may be claimed.
        if not self.source_available:
            if status is not CoverageStatus.NONE:
                raise DomainValidationError(
                    f"DataCoverage.status must be 'NONE' when source_available is False, "
                    f"got '{status.value}'"
                )
            if actual is not None:
                raise DomainValidationError(
                    "DataCoverage.actual must be None when source_available is False"
                )
            if self.sample_count != 0:
                raise DomainValidationError(
                    f"DataCoverage.sample_count must be 0 when source_available is False, "
                    f"got {self.sample_count}"
                )

        if status in (CoverageStatus.COMPLETE, CoverageStatus.PARTIAL):
            if actual is None:
                raise DomainValidationError(
                    f"DataCoverage.actual must be a CoverageWindow when status is "
                    f"'{status.value}', got None"
                )
        else:
            if actual is not None:
                raise DomainValidationError(
                    "DataCoverage.actual must be None when status is 'NONE'"
                )
            if self.sample_count != 0:
                raise DomainValidationError(
                    f"DataCoverage.sample_count must be 0 when status is 'NONE', "
                    f"got {self.sample_count}"
                )

        if actual is not None:
            if actual.start < requested.start:
                raise DomainValidationError(
                    f"DataCoverage.actual.start ({actual.start.isoformat()}) must fall "
                    f"within requested coverage starting {requested.start.isoformat()}"
                )
            if actual.end > requested.end:
                raise DomainValidationError(
                    f"DataCoverage.actual.end ({actual.end.isoformat()}) must fall "
                    f"within requested coverage ending {requested.end.isoformat()}"
                )


@dataclass(frozen=True, slots=True)
class MethodIneligibility:
    """Why one higher-priority acquisition method could not be used.

    Feature assembly records one of these per method it skipped, so a backtest can
    explain why a lower-priority method was chosen (``MODEL_SPEC.md`` §11.2).
    """

    method: AcquisitionMethod
    reason: str

    def __post_init__(self) -> None:
        ensure_instance(self.method, AcquisitionMethod, "MethodIneligibility.method")
        ensure_non_empty_text(self.reason, "MethodIneligibility.reason")


@dataclass(frozen=True, slots=True)
class FallbackRecord:
    """Records that a lower-priority acquisition method was selected.

    Carries the method actually used and, for each higher-priority method that was
    passed over, why it was ineligible (``MODEL_SPEC.md`` §8.4, §11.2).

    A fallback that skipped nothing is not a fallback, so at least one
    ineligibility is required; the selected method cannot also appear as one it
    was passed over for; and a method cannot be skipped twice. These are record
    consistency rules — the *priority ordering* itself is resolved in ``features``,
    not here.
    """

    selected_method: AcquisitionMethod
    higher_priority_ineligible: tuple[MethodIneligibility, ...]

    def __post_init__(self) -> None:
        selected = ensure_instance(
            self.selected_method, AcquisitionMethod, "FallbackRecord.selected_method"
        )
        skipped = ensure_tuple_of(
            self.higher_priority_ineligible,
            MethodIneligibility,
            "FallbackRecord.higher_priority_ineligible",
        )

        if not skipped:
            raise DomainValidationError(
                "FallbackRecord.higher_priority_ineligible must record at least one "
                "ineligible higher-priority method; a fallback that skipped nothing "
                "is not a fallback"
            )

        methods = [entry.method for entry in skipped]
        ensure_no_duplicates(methods, "FallbackRecord.higher_priority_ineligible")

        if selected in methods:
            raise DomainValidationError(
                f"FallbackRecord.selected_method '{selected.value}' must not also appear "
                f"in higher_priority_ineligible"
            )

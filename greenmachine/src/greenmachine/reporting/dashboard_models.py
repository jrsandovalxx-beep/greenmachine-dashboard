"""Immutable view models for the GM-030 manual-review dashboard.

Provider-neutral by construction: nothing here carries a provider wire-column
name, a float, a performance threshold, or any scoring logic. A view model
describes **data state** (present/sufficient, present/insufficient, missing,
audit-only), never favorability.

The excluded pitch-outcome rate (see the loader's frozen exclusion filter)
has no field in any view model: the loader drops matching archived audit
fields before a view model can exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from greenmachine.domain import WindowProfile

__all__ = [
    "AuditSection",
    "CaptureEntrySummary",
    "ComparisonRow",
    "DashboardData",
    "DataStatus",
    "IntegrityStatus",
    "MetricCard",
    "MetricProvenance",
    "MissingComponentNote",
    "OverviewHeader",
    "PitcherContext",
    "ProfileMetrics",
]


class DataStatus(Enum):
    """Data state — never a performance judgment."""

    PRESENT_SUFFICIENT = "present_sufficient"
    PRESENT_INSUFFICIENT = "present_insufficient"
    MISSING = "missing"
    AUDIT_CONTEXT = "audit_context"


@dataclass(frozen=True, slots=True)
class MetricProvenance:
    """The tucked-away provenance trail for one card (tooltip/expander)."""

    measurement_label: str
    acquisition_label: str
    provider_label: str
    source_as_of: datetime | None
    retrieved_at: datetime | None
    derivation_note: str
    fallback_summary: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MetricCard:
    """One metric for one profile. Exactly one profile per card."""

    key: str
    label: str
    profile: WindowProfile
    value_display: str | None
    value_exact: str | None
    unit: str
    sample_count: int
    sample_unit: str
    minimum_required: int | None
    status: DataStatus
    explanation: str
    provenance: MetricProvenance
    audit_only: bool = False


@dataclass(frozen=True, slots=True)
class ProfileMetrics:
    """All cards for one window profile, grouped by research category."""

    profile: WindowProfile
    snapshot_id: str
    input_hash: str
    window_start: date
    window_end_exclusive: date
    power_profile: tuple[MetricCard, ...]
    form: tuple[MetricCard, ...]
    pull_power: tuple[MetricCard, ...]

    @property
    def all_cards(self) -> tuple[MetricCard, ...]:
        return self.power_profile + self.form + self.pull_power


@dataclass(frozen=True, slots=True)
class ComparisonRow:
    """One metric across both profiles; difference only when meaningful."""

    label: str
    recent_display: str | None
    recent_sample: int
    long_term_display: str | None
    long_term_sample: int
    difference_display: str | None
    difference_note: str
    status_note: str
    audit_only: bool


@dataclass(frozen=True, slots=True)
class OverviewHeader:
    batter_name: str
    batter_id: str
    team_note: str
    opponent_note: str
    game_id: str
    slate_date: date
    venue_name: str
    venue_timezone: str
    scheduled_start_utc: datetime
    venue_local_start: datetime
    pitcher_name: str
    pitcher_id: str
    pitcher_role_label: str
    capture_mode_label: str
    capture_completed_at: datetime
    as_of: datetime
    source_capture_id: str
    manifest_id: str


@dataclass(frozen=True, slots=True)
class IntegrityStatus:
    """What was verified, stated precisely.

    Raw captures, the manifest, the archived policy, and both snapshots are
    **replay-verified** (they participate in the archived identities); the
    dashboard's audit/context reports are additionally **schema-validated
    for display** — they are not part of ``SourceCaptureId``.
    """

    archived_run_verified: bool
    replay_byte_identical: bool
    prospective_verified: bool
    prospective_note: str
    verification_scope_note: str


@dataclass(frozen=True, slots=True)
class PitcherContext:
    """Game-context identity only: pitcher-specific metrics are deferred by
    Product Owner ruling, so no pitcher performance statistic has a field
    here — the loader never even parses the archived ingredient report for
    the UI."""

    pitcher_name: str
    pitcher_id: str
    role_label: str
    handedness_note: str
    deferred_note: str


@dataclass(frozen=True, slots=True)
class MissingComponentNote:
    component_label: str
    profile: WindowProfile
    reason_label: str
    explanation: str


@dataclass(frozen=True, slots=True)
class CaptureEntrySummary:
    """Audit view of one raw capture: label + digest + instants only.

    Provider request parameters are deliberately not surfaced — they carry
    provider wire vocabulary that stays out of the dashboard.
    """

    label: str
    sha256: str
    retrieval_started_at: datetime
    retrieval_completed_at: datetime
    participates_in_snapshot: bool


@dataclass(frozen=True, slots=True)
class AuditSection:
    missing_components: tuple[MissingComponentNote, ...]
    insufficient_cards: tuple[str, ...]
    fallback_notes: tuple[str, ...]
    normalization_lines: tuple[str, ...]
    capture_entries: tuple[CaptureEntrySummary, ...]
    manifest_id: str
    prospective_evidence_lines: tuple[str, ...]
    replay_lines: tuple[str, ...]
    sample_policy_disclaimer: str


@dataclass(frozen=True, slots=True)
class DashboardData:
    """Everything the dashboard renders for one approved archived run."""

    run_name: str
    header: OverviewHeader
    integrity: IntegrityStatus
    recent: ProfileMetrics
    long_term: ProfileMetrics
    comparison: tuple[ComparisonRow, ...]
    pitcher_context: PitcherContext
    audit: AuditSection

    def __post_init__(self) -> None:
        if self.recent.profile is self.long_term.profile:
            raise ValueError("the two profile views must be distinct profiles")
        if self.recent.snapshot_id == self.long_term.snapshot_id:
            raise ValueError("profile snapshots must remain distinct")

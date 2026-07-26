"""Read-only loading of approved archived GM-020 runs for the dashboard.

Everything flows through the existing GM-020 integrity path: an archived run
is opened with the confined ``bundle_reader``, verified end-to-end by the
read-only ``replay_run`` (strict manifest contract, per-entry and overall
identities, raw digests, archived digest-pinned sample policy, prospective
timing from recorded instants, byte-identical snapshot regeneration), and
only then translated into provider-neutral view models. The loader performs
**no network request and no write of any kind**.

The audit/context reports the dashboard additionally reads are **not** part
of ``SourceCaptureId``; they are parsed here through strict display adapters
(duplicate JSON keys rejected, runtime types and structures validated, only
canonical Decimal strings accepted, negative counts rejected, nothing
silently skipped or coerced). Every report-shaped failure — Unicode, JSON,
duplicate keys, Decimal, ``KeyError``, ``IndexError``, ``TypeError``,
``ValueError`` — surfaces as a :class:`DashboardLoadError` carrying the run
name, the report label, and a concise deterministic explanation, so the
application renders a focused error instead of a traceback.

Pitcher-specific metrics are **deferred by Product Owner ruling**: the
archived ingredient report is never parsed for UI purposes, and the pitcher
context view model carries game-context identity only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TypeVar

from greenmachine.common.errors import ErrorContext, GreenMachineError
from greenmachine.domain import (
    AcquisitionMethod,
    ComponentId,
    InputSnapshot,
    MetricObservation,
    MissingObservation,
    MissingReason,
    PitcherRole,
    SampleStatus,
    WindowProfile,
)
from greenmachine.evaluation import deserialize_snapshot
from greenmachine.ingestion.archive import bundle_reader
from greenmachine.ingestion.models import CaptureMode
from greenmachine.ingestion.orchestration import (
    MANIFEST_PATH,
    SAMPLE_POLICY_PATH,
    SNAPSHOT_PATHS,
    ReplayResult,
    replay_run,
)
from greenmachine.ingestion.policy import load_sample_policy
from greenmachine.ingestion.strict_json import strict_json_loads

from .dashboard_formatting import format_display_value
from .dashboard_models import (
    AuditSection,
    CaptureEntrySummary,
    ComparisonRow,
    DashboardData,
    DataStatus,
    IntegrityStatus,
    MetricCard,
    MetricProvenance,
    MissingComponentNote,
    OverviewHeader,
    PitcherContext,
    ProfileMetrics,
)

__all__ = [
    "DashboardLoadError",
    "RunHandle",
    "VerifiedRun",
    "discover_runs",
    "load_dashboard",
    "load_verified_run",
]

VERIFICATION_SCOPE_NOTE = (
    "raw captures, the manifest, the archived sample policy, and both snapshots "
    "were replay-verified (they participate in the archived identities); the "
    "dashboard's audit/context reports were schema-validated for display and are "
    "not part of SourceCaptureId"
)

PITCHER_ANALYSIS_DEFERRED_NOTE = (
    "Advanced pitcher analysis is deferred to a later ticket. This screen shows "
    "game-context identity only: the expected pitcher and role come from the "
    "verified archived game feed."
)


class DashboardLoadError(GreenMachineError):
    """A focused, user-facing dashboard loading failure."""


@dataclass(frozen=True, slots=True)
class RunHandle:
    """One discovered approved archived run."""

    name: str
    directory: Path


def discover_runs(evidence_root: Path) -> tuple[RunHandle, ...]:
    """Discover archived runs beneath the approved evidence root.

    Deterministic (sorted by directory name, never by enumeration order),
    path-confined (a symlinked directory resolving outside the root is
    rejected), and free of working-directory assumptions (the caller passes
    an absolute root). A directory qualifies by carrying a ``manifest.json``;
    adding another approved run requires no dashboard-code change.
    """
    root = evidence_root.resolve()
    if not root.is_dir():
        return ()
    handles: list[RunHandle] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if not child.is_dir():
            continue
        resolved = child.resolve()
        if not resolved.is_relative_to(root):
            continue  # a symlink escaping the evidence root is never offered
        if not (resolved / "manifest.json").is_file():
            continue
        handles.append(RunHandle(name=child.name, directory=resolved))
    return tuple(handles)


# --------------------------------------------------------------------------
# Strict display adapters for the audit/context reports
# --------------------------------------------------------------------------

_T = TypeVar("_T")


def _report_error(run_name: str, report_label: str, detail: str) -> DashboardLoadError:
    return DashboardLoadError(
        f"archived report '{report_label}' in run '{run_name}' cannot be displayed: {detail}",
        ErrorContext(subject=run_name),
    )


def _translated(run_name: str, report_label: str, build: Callable[[], _T]) -> _T:
    """Run a display builder; any incidental failure becomes a focused error."""
    try:
        return build()
    except DashboardLoadError:
        raise
    except (
        UnicodeDecodeError,
        InvalidOperation,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
    ) as failure:
        raise _report_error(
            run_name, report_label, f"malformed content ({type(failure).__name__})"
        ) from failure


def _load_report(
    reader: Callable[[str], bytes], run_name: str, relative_path: str
) -> dict[str, object]:
    def on_error(detail: str) -> DashboardLoadError:
        return _report_error(run_name, relative_path, detail)

    document = strict_json_loads(reader(relative_path), describe="the report", on_error=on_error)
    if not isinstance(document, dict):
        raise _report_error(run_name, relative_path, "the report root must be a JSON object")
    return document


def _report_int(document: dict[str, object], key: str, run_name: str, report_label: str) -> int:
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _report_error(run_name, report_label, f"field '{key}' must be an integer")
    if value < 0:
        raise _report_error(run_name, report_label, f"field '{key}' must not be negative")
    return value


def _report_pairs(
    document: dict[str, object], key: str, run_name: str, report_label: str
) -> tuple[tuple[str, int], ...]:
    """A list of exact ``[name, non-negative count]`` pairs, or a focused error."""
    raw = document.get(key)
    if not isinstance(raw, list):
        raise _report_error(run_name, report_label, f"field '{key}' must be an array")
    pairs: list[tuple[str, int]] = []
    for member in raw:
        if not isinstance(member, list) or len(member) != 2:
            raise _report_error(run_name, report_label, f"field '{key}' has a malformed pair")
        name, count = member
        if not isinstance(name, str):
            raise _report_error(run_name, report_label, f"field '{key}' pair names must be strings")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise _report_error(
                run_name,
                report_label,
                f"field '{key}' pair counts must be non-negative integers",
            )
        pairs.append((name, count))
    return tuple(pairs)


def _canonical_decimal_or_none(
    value: object, run_name: str, report_label: str, field_name: str
) -> str | None:
    """``None`` stays ``None``; otherwise only a parseable Decimal string passes."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise _report_error(
            run_name, report_label, f"field '{field_name}' must be a Decimal string or null"
        )
    try:
        Decimal(value)
    except InvalidOperation as failure:
        raise _report_error(
            run_name, report_label, f"field '{field_name}' is not a valid Decimal string"
        ) from failure
    return value


@dataclass(frozen=True, slots=True)
class _OverallPull:
    value_exact: str | None
    sample_count: int


def _overall_pull_of(document: dict[str, object], run_name: str, report_label: str) -> _OverallPull:
    overall = document.get("overall_pull_report_only")
    if not isinstance(overall, dict):
        raise _report_error(
            run_name, report_label, "field 'overall_pull_report_only' must be an object"
        )
    value = _canonical_decimal_or_none(overall.get("value"), run_name, report_label, "value")
    sample_count = _report_int(overall, "sample_count", run_name, report_label)
    if (value is None) != (sample_count == 0):
        raise _report_error(
            run_name,
            report_label,
            "overall pull value/sample coherence is violated (a value requires a "
            "nonzero sample and vice versa)",
        )
    return _OverallPull(value_exact=value, sample_count=sample_count)


def _pull_exclusions_of(
    document: dict[str, object], run_name: str, report_label: str
) -> tuple[tuple[str, int], ...]:
    chosen = document.get("chosen_pull_air")
    if not isinstance(chosen, dict):
        raise _report_error(run_name, report_label, "field 'chosen_pull_air' must be an object")
    return _report_pairs(chosen, "exclusions", run_name, report_label)


def _normalization_lines(
    profile_label: str,
    document: dict[str, object],
    run_name: str,
    report_label: str,
) -> tuple[str, ...]:
    profile_value = document.get("profile")
    if profile_value != profile_label:
        raise _report_error(
            run_name,
            report_label,
            f"the report records profile {profile_value!r}, not the expected {profile_label!r}",
        )
    received = _report_int(document, "rows_received", run_name, report_label)
    duplicates = _report_int(document, "duplicates_collapsed", run_name, report_label)
    eligible = _report_int(document, "rows_eligible", run_name, report_label)
    missing_type = _report_int(document, "excluded_missing_game_type", run_name, report_label)
    outside = _report_int(document, "excluded_outside_window", run_name, report_label)
    selected = _report_int(document, "excluded_selected_game", run_name, report_label)
    by_type_pairs = _report_pairs(document, "excluded_by_game_type", run_name, report_label)
    by_type = (
        ", ".join(f"{name}: {count}" for name, count in by_type_pairs) if by_type_pairs else "none"
    )
    return (
        f"{profile_label}: {received} rows received, {duplicates} duplicates collapsed, "
        f"{eligible} eligible",
        f"{profile_label}: excluded by game type — {by_type}; missing game type "
        f"{missing_type}; outside window {outside}; selected game {selected}",
    )


# --------------------------------------------------------------------------
# Metric cards
# --------------------------------------------------------------------------

_METRIC_LABELS: dict[ComponentId, tuple[str, str]] = {
    ComponentId.EXIT_VELOCITY: ("Average Exit Velocity", "mph"),
    ComponentId.BARREL_PCT: ("Barrel%", "%"),
    ComponentId.HARD_HIT_PCT: ("Hard-Hit%", "%"),
    ComponentId.BAT_SPEED: ("Bat Speed", "mph"),
    ComponentId.SWEET_SPOT_PCT: ("Sweet Spot%", "%"),
    ComponentId.ATTACK_ANGLE_QUALITY: ("Ideal Attack Angle%", "%"),
    ComponentId.PULL_PCT_AIR_BALLS: ("Pull Air%", "%"),
}

_POWER_CARDS = (
    ComponentId.EXIT_VELOCITY,
    ComponentId.BARREL_PCT,
    ComponentId.HARD_HIT_PCT,
    ComponentId.BAT_SPEED,
)
_FORM_CARDS = (ComponentId.SWEET_SPOT_PCT, ComponentId.ATTACK_ANGLE_QUALITY)
_PULL_CARDS = (ComponentId.PULL_PCT_AIR_BALLS,)

_COMPONENT_DISPLAY: dict[ComponentId, str] = {
    ComponentId.PITCH_MIX_PRESSURE: "Pitch Mix Pressure",
    ComponentId.PUT_AWAY_PITCH_EXPLOITATION: "Put-Away Pitch Exploitation",
    ComponentId.PARK: "Park",
    ComponentId.WEATHER: "Weather",
}

_MISSING_EXPLANATIONS: dict[ComponentId, str] = {
    ComponentId.PITCH_MIX_PRESSURE: (
        "provider data was captured and the audit ingredients are archived; no "
        "approved component formula exists (Q15/Q16 are open), so no value was "
        "manufactured"
    ),
    ComponentId.PUT_AWAY_PITCH_EXPLOITATION: (
        "provider data was captured and the audit ingredients are archived; no "
        "approved component formula exists (Q15/Q16 are open), so no value was "
        "manufactured"
    ),
    ComponentId.PARK: "no park-factor source is selected in this vertical slice",
    ComponentId.WEATHER: (
        "no weather source exists in this vertical slice; nothing here is a forecast"
    ),
}

_REASON_LABELS: dict[MissingReason, str] = {
    reason: reason.value.replace("_", " ") for reason in MissingReason
}

_ROLE_LABELS: dict[PitcherRole, str] = {
    PitcherRole.EXPECTED_STARTER: "expected starter",
    PitcherRole.OPENER: "announced opener",
    PitcherRole.UNCERTAIN: "named but uncertain",
}


def _acquisition_label(method: AcquisitionMethod) -> str:
    if method is AcquisitionMethod.EVENT_DERIVED:
        return "event-derived (GreenMachine-derived from archived pitch-level events)"
    return str(method.value).replace("_", " ")


def _provenance_of(observation: MetricObservation) -> MetricProvenance:
    fallback = observation.fallback_used
    fallback_summary: tuple[str, ...] = ()
    if fallback is not None:
        fallback_summary = tuple(
            f"{record.method.value.replace('_', ' ')} ineligible: {record.reason}"
            for record in fallback.higher_priority_ineligible
        )
    measurement = observation.measurement_id
    return MetricProvenance(
        measurement_label=(measurement.value if measurement is not None else "—"),
        acquisition_label=_acquisition_label(observation.acquisition_method),
        provider_label=str(observation.provider_id.value).replace("_", " "),
        source_as_of=observation.source_as_of,
        retrieved_at=observation.retrieved_at,
        derivation_note=(
            "not the provider's published aggregate"
            if observation.acquisition_method is AcquisitionMethod.EVENT_DERIVED
            else ""
        ),
        fallback_summary=fallback_summary,
    )


def _present_card(observation: MetricObservation) -> MetricCard:
    label, unit = _METRIC_LABELS[observation.component_id]
    exact = format(observation.raw_value, "f")
    sufficient = observation.sample_status is SampleStatus.SUFFICIENT
    return MetricCard(
        key=observation.component_id.value,
        label=label,
        profile=observation.window_profile,
        value_display=format_display_value(exact, unit),
        value_exact=exact,
        unit=unit,
        sample_count=observation.sample_count,
        sample_unit=observation.sample_type.value.replace("_", " "),
        minimum_required=observation.minimum_sample_required,
        status=(DataStatus.PRESENT_SUFFICIENT if sufficient else DataStatus.PRESENT_INSUFFICIENT),
        explanation=(
            ""
            if sufficient
            else (
                f"sample of {observation.sample_count} is below the archived "
                f"validation-only minimum of {observation.minimum_sample_required}"
            )
        ),
        provenance=_provenance_of(observation),
    )


def _missing_card(observation: MissingObservation, label: str, unit: str) -> MetricCard:
    return MetricCard(
        key=observation.component_id.value,
        label=label,
        profile=observation.window_profile,
        value_display=None,
        value_exact=None,
        unit=unit,
        sample_count=0,
        sample_unit=observation.sample_type.value.replace("_", " "),
        minimum_required=None,
        status=DataStatus.MISSING,
        explanation=(
            f"{_REASON_LABELS[observation.missing_reason]} — "
            + _MISSING_EXPLANATIONS.get(
                observation.component_id, "no eligible value exists in this window"
            )
        ),
        provenance=MetricProvenance(
            measurement_label="—",
            acquisition_label="—",
            provider_label=(
                str(observation.provider_id.value).replace("_", " ")
                if observation.provider_id is not None
                else "—"
            ),
            source_as_of=None,
            retrieved_at=None,
            derivation_note="",
            fallback_summary=(),
        ),
    )


def _overall_pull_card(profile: WindowProfile, overall: _OverallPull) -> MetricCard:
    exact = overall.value_exact
    return MetricCard(
        key="overall_pull_context",
        label="Overall Pull%",
        profile=profile,
        value_display=(format_display_value(exact, "%") if exact is not None else None),
        value_exact=exact,
        unit="%",
        sample_count=overall.sample_count,
        sample_unit="batted ball events",
        minimum_required=None,
        status=DataStatus.AUDIT_CONTEXT,
        explanation=(
            "audit/context only: all batted balls, not the approved Pull Air% "
            "denominator; never a scoring input"
        ),
        provenance=MetricProvenance(
            measurement_label="—",
            acquisition_label="event-derived (GreenMachine-derived, report-only)",
            provider_label="baseball savant",
            source_as_of=None,
            retrieved_at=None,
            derivation_note="report-only by Product Owner ruling",
            fallback_summary=(),
        ),
        audit_only=True,
    )


def _profile_metrics(snapshot: InputSnapshot, overall: _OverallPull) -> ProfileMetrics:
    present = {
        observation.component_id: observation for observation in snapshot.present_observations
    }
    missing = {
        observation.component_id: observation for observation in snapshot.missing_observations
    }

    def card_for(component: ComponentId) -> MetricCard:
        if component in present:
            return _present_card(present[component])
        label, unit = _METRIC_LABELS[component]
        return _missing_card(missing[component], label, unit)

    return ProfileMetrics(
        profile=snapshot.window_profile,
        snapshot_id=snapshot.snapshot_id.value,
        input_hash=snapshot.input_hash.value,
        window_start=snapshot.window_start.date(),
        window_end_exclusive=snapshot.window_end.date(),
        power_profile=tuple(card_for(component) for component in _POWER_CARDS),
        form=tuple(card_for(component) for component in _FORM_CARDS),
        pull_power=(
            *(card_for(component) for component in _PULL_CARDS),
            _overall_pull_card(snapshot.window_profile, overall),
        ),
    )


def _comparison_rows(
    recent: ProfileMetrics, long_term: ProfileMetrics
) -> tuple[ComparisonRow, ...]:
    long_by_key = {card.key: card for card in long_term.all_cards}
    rows: list[ComparisonRow] = []
    for recent_card in recent.all_cards:
        long_card = long_by_key[recent_card.key]
        difference_display: str | None = None
        difference_note = ""
        if recent_card.value_exact is not None and long_card.value_exact is not None:
            difference = Decimal(recent_card.value_exact) - Decimal(long_card.value_exact)
            unit_suffix = " pp" if recent_card.unit == "%" else f" {recent_card.unit}"
            magnitude = format_display_value(format(abs(difference), "f"), "")
            sign = "+" if difference >= 0 else "-"
            difference_display = f"{sign}{magnitude}{unit_suffix}"
            difference_note = "recent minus long-term; same event-derived method"
        else:
            difference_note = "not computed: at least one side is missing"
        status_bits: list[str] = []
        for side, card in (("recent", recent_card), ("long-term", long_card)):
            if card.status is DataStatus.PRESENT_INSUFFICIENT:
                status_bits.append(f"{side} sample below validation-only minimum")
            if card.status is DataStatus.MISSING:
                status_bits.append(f"{side} missing")
        if recent_card.audit_only:
            status_bits.append("audit-only context, not a scoring input")
        rows.append(
            ComparisonRow(
                label=recent_card.label,
                recent_display=recent_card.value_display,
                recent_sample=recent_card.sample_count,
                long_term_display=long_card.value_display,
                long_term_sample=long_card.sample_count,
                difference_display=difference_display,
                difference_note=difference_note,
                status_note="; ".join(status_bits),
                audit_only=recent_card.audit_only,
            )
        )
    return tuple(rows)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerifiedRun:
    """One replay-verified run: its view models plus both frozen snapshots.

    The snapshots are named fields, not a mapping, so the profile a caller gets
    is fixed by the attribute it reads rather than by a lookup that could miss.
    ``__post_init__`` proves each field really holds its declared profile, that
    the two are genuinely distinct records, and that they agree with the
    dashboard view built from them — a mismatch here would mean the loader had
    crossed two runs, which must fail loudly rather than score the wrong game.

    This record deliberately carries **no scoring behaviour**. It is the
    hand-off point: ``reporting`` produces verified domain records, and the
    composition root decides what to do with them.
    """

    dashboard: DashboardData
    recent_snapshot: InputSnapshot
    long_term_snapshot: InputSnapshot

    def __post_init__(self) -> None:
        if self.recent_snapshot.window_profile is not WindowProfile.RECENT_7D:
            raise DashboardLoadError(
                f"VerifiedRun.recent_snapshot must carry RECENT_7D, got "
                f"'{self.recent_snapshot.window_profile.value}'",
                ErrorContext(subject=self.dashboard.run_name),
            )
        if self.long_term_snapshot.window_profile is not WindowProfile.LONG_TERM_2Y:
            raise DashboardLoadError(
                f"VerifiedRun.long_term_snapshot must carry LONG_TERM_2Y, got "
                f"'{self.long_term_snapshot.window_profile.value}'",
                ErrorContext(subject=self.dashboard.run_name),
            )
        if self.recent_snapshot.snapshot_id == self.long_term_snapshot.snapshot_id:
            raise DashboardLoadError(
                "the two profile snapshots share a snapshot_id; one run produces "
                "two independently frozen snapshots, never one reused",
                ErrorContext(subject=self.dashboard.run_name),
            )
        if self.recent_snapshot.input_hash == self.long_term_snapshot.input_hash:
            raise DashboardLoadError(
                "the two profile snapshots share an input_hash; their observations "
                "must differ because their windows differ",
                ErrorContext(subject=self.dashboard.run_name),
            )
        self._require_coherent_identity()

    def _require_coherent_identity(self) -> None:
        """Both snapshots describe the same subject as the dashboard header."""
        header = self.dashboard.header
        for label, snapshot in (
            ("recent_snapshot", self.recent_snapshot),
            ("long_term_snapshot", self.long_term_snapshot),
        ):
            if snapshot.batter.player_id.value != header.batter_id:
                raise DashboardLoadError(
                    f"{label} describes batter '{snapshot.batter.player_id.value}' but "
                    f"the dashboard header describes '{header.batter_id}'",
                    ErrorContext(subject=self.dashboard.run_name),
                )
            if snapshot.game_context.game_id.value != header.game_id:
                raise DashboardLoadError(
                    f"{label} describes game '{snapshot.game_context.game_id.value}' but "
                    f"the dashboard header describes '{header.game_id}'",
                    ErrorContext(subject=self.dashboard.run_name),
                )
        if self.recent_snapshot.source_capture_id != self.long_term_snapshot.source_capture_id:
            raise DashboardLoadError(
                "the two profile snapshots come from different source captures; "
                "one run is exactly one capture",
                ErrorContext(subject=self.dashboard.run_name),
            )


def load_verified_run(handle: RunHandle) -> VerifiedRun:
    """Verify one approved archived run read-only, then build its view models.

    Performs **exactly one** replay-verification path and deserializes each
    frozen snapshot **exactly once**, then returns both the view models and the
    snapshots themselves. The snapshots are the immutable GM-006 domain records
    the composition root needs to run the pure grading engine; handing them back
    here is what lets ``streamlit_app.py`` score a run without ``reporting`` ever
    importing ``greenmachine.scoring`` (or ``greenmachine.config``).

    Nothing is written, and no snapshot is copied or rebuilt.
    """
    reader = bundle_reader(handle.directory)
    result: ReplayResult = replay_run(reader)
    if not result.byte_identical:
        raise DashboardLoadError(
            f"archived snapshots for run '{handle.name}' did not regenerate "
            f"byte-identically; the run cannot be trusted for review",
            ErrorContext(subject=handle.name),
        )

    recent_snapshot = deserialize_snapshot(reader(SNAPSHOT_PATHS[WindowProfile.RECENT_7D]))
    long_snapshot = deserialize_snapshot(reader(SNAPSHOT_PATHS[WindowProfile.LONG_TERM_2Y]))

    run = handle.name
    manifest_doc = _load_report(reader, run, MANIFEST_PATH)
    pull_recent = _load_report(reader, run, "reports/pull_audit_recent_7d.json")
    pull_long = _load_report(reader, run, "reports/pull_audit_long_term_2y.json")
    normalization_recent = _load_report(reader, run, "reports/normalization_recent_7d.json")
    normalization_long = _load_report(reader, run, "reports/normalization_long_term_2y.json")
    policy = _translated(
        run, SAMPLE_POLICY_PATH, lambda: load_sample_policy(reader(SAMPLE_POLICY_PATH))
    )

    overall_recent = _overall_pull_of(pull_recent, run, "reports/pull_audit_recent_7d.json")
    overall_long = _overall_pull_of(pull_long, run, "reports/pull_audit_long_term_2y.json")

    recent = _profile_metrics(recent_snapshot, overall_recent)
    long_term = _profile_metrics(long_snapshot, overall_long)

    def build_header() -> OverviewHeader:
        context = recent_snapshot.game_context
        capture_mode = CaptureMode(str(manifest_doc["capture_mode"]))
        run_completed_at = datetime.fromisoformat(str(manifest_doc["run_completed_at"]))
        return OverviewHeader(
            batter_name=recent_snapshot.batter.full_name,
            batter_id=recent_snapshot.batter.player_id.value,
            team_note="not recorded in the provider-neutral archive",
            opponent_note="not recorded in the provider-neutral archive",
            game_id=context.game_id.value,
            slate_date=context.slate_date,
            venue_name=context.venue.name,
            venue_timezone=context.venue.timezone,
            scheduled_start_utc=context.scheduled_start_utc,
            venue_local_start=context.venue_local_scheduled_time,
            pitcher_name=recent_snapshot.expected_starting_pitcher.full_name,
            pitcher_id=recent_snapshot.expected_starting_pitcher.player_id.value,
            pitcher_role_label=_ROLE_LABELS[recent_snapshot.pitcher_role],
            capture_mode_label=(
                "prospective live capture"
                if capture_mode is CaptureMode.PROSPECTIVE
                else "retrospective reconstruction (not prospective evidence)"
            ),
            capture_completed_at=run_completed_at,
            as_of=recent_snapshot.as_of,
            source_capture_id=result.source_capture_id.value,
            manifest_id=str(manifest_doc["manifest_id"]),
        )

    header = _translated(run, MANIFEST_PATH, build_header)

    prospective = header.capture_mode_label.startswith("prospective")
    integrity = IntegrityStatus(
        archived_run_verified=True,
        replay_byte_identical=result.byte_identical,
        prospective_verified=prospective,
        prospective_note=(
            "recorded completions precede the scheduled first pitch; re-proven from "
            "manifest instants on every replay"
            if prospective
            else "retrospective reconstruction: not evidence of prospective capture"
        ),
        verification_scope_note=VERIFICATION_SCOPE_NOTE,
    )

    pitcher_context = PitcherContext(
        pitcher_name=header.pitcher_name,
        pitcher_id=header.pitcher_id,
        role_label=header.pitcher_role_label,
        handedness_note="pitcher handedness is not captured in the archived slice",
        deferred_note=PITCHER_ANALYSIS_DEFERRED_NOTE,
    )

    missing_notes: list[MissingComponentNote] = []
    for snapshot in (recent_snapshot, long_snapshot):
        for observation in snapshot.missing_observations:
            missing_notes.append(
                MissingComponentNote(
                    component_label=_COMPONENT_DISPLAY.get(
                        observation.component_id,
                        _METRIC_LABELS.get(observation.component_id, ("?", ""))[0],
                    ),
                    profile=observation.window_profile,
                    reason_label=_REASON_LABELS[observation.missing_reason],
                    explanation=_MISSING_EXPLANATIONS.get(
                        observation.component_id, "no eligible value exists in this window"
                    ),
                )
            )

    insufficient = tuple(
        f"{card.label} ({card.profile.value}): {card.explanation}"
        for metrics in (recent, long_term)
        for card in metrics.all_cards
        if card.status is DataStatus.PRESENT_INSUFFICIENT
    )
    fallback_notes = tuple(
        f"{card.label} ({card.profile.value}): event derivation selected; "
        + "; ".join(card.provenance.fallback_summary)
        for metrics in (recent, long_term)
        for card in metrics.all_cards
        if card.provenance.fallback_summary
    )

    def build_capture_entries() -> tuple[CaptureEntrySummary, ...]:
        entries_raw = manifest_doc["entries"]
        if not isinstance(entries_raw, list):
            raise _report_error(run, MANIFEST_PATH, "'entries' must be an array")
        summaries: list[CaptureEntrySummary] = []
        for entry in entries_raw:
            if not isinstance(entry, dict):
                raise _report_error(run, MANIFEST_PATH, "entries must be objects")
            participates = entry["participates_in_snapshot"]
            if not isinstance(participates, bool):
                raise _report_error(
                    run, MANIFEST_PATH, "'participates_in_snapshot' must be a boolean"
                )
            summaries.append(
                CaptureEntrySummary(
                    label=str(entry["label"]),
                    sha256=str(entry["sha256"]),
                    retrieval_started_at=datetime.fromisoformat(str(entry["retrieval_started_at"])),
                    retrieval_completed_at=datetime.fromisoformat(
                        str(entry["retrieval_completed_at"])
                    ),
                    participates_in_snapshot=participates,
                )
            )
        return tuple(summaries)

    capture_entries = _translated(run, MANIFEST_PATH, build_capture_entries)

    latest_participating = max(
        entry.retrieval_completed_at for entry in capture_entries if entry.participates_in_snapshot
    )
    prospective_lines = (
        f"scheduled first pitch (UTC): {header.scheduled_start_utc.isoformat()}",
        f"latest participating capture completion: {latest_participating.isoformat()}",
        f"run completed: {header.capture_completed_at.isoformat()}",
        (
            "prospective timing is proven from recorded manifest instants on every "
            "replay; the current date never participates"
        ),
    )
    replay_lines = tuple(
        f"{key}: {value}"
        for key, value in sorted(result.report_document.items())
        if isinstance(value, (str, bool))
    )

    def build_normalization_lines() -> tuple[str, ...]:
        return (
            *_normalization_lines(
                "RECENT_7D", normalization_recent, run, "reports/normalization_recent_7d.json"
            ),
            *_normalization_lines(
                "LONG_TERM_2Y",
                normalization_long,
                run,
                "reports/normalization_long_term_2y.json",
            ),
        )

    def build_pull_exclusion_lines() -> tuple[str, ...]:
        lines: list[str] = []
        for profile_label, document, label in (
            ("RECENT_7D", pull_recent, "reports/pull_audit_recent_7d.json"),
            ("LONG_TERM_2Y", pull_long, "reports/pull_audit_long_term_2y.json"),
        ):
            pairs = _pull_exclusions_of(document, run, label)
            rendered = ", ".join(f"{name}: {count}" for name, count in pairs) if pairs else "none"
            lines.append(f"{profile_label}: pull-denominator exclusions — {rendered}")
        return tuple(lines)

    audit = AuditSection(
        missing_components=tuple(missing_notes),
        insufficient_cards=insufficient,
        fallback_notes=fallback_notes,
        normalization_lines=(
            *_translated(run, "normalization reports", build_normalization_lines),
            *_translated(run, "pull audit reports", build_pull_exclusion_lines),
        ),
        capture_entries=capture_entries,
        manifest_id=header.manifest_id,
        prospective_evidence_lines=prospective_lines,
        replay_lines=replay_lines,
        sample_policy_disclaimer=(
            "VALIDATION-ONLY sample policy (non-production; not a production model "
            "configuration): " + policy.disclaimer
        ),
    )

    dashboard = DashboardData(
        run_name=handle.name,
        header=header,
        integrity=integrity,
        recent=recent,
        long_term=long_term,
        comparison=_comparison_rows(recent, long_term),
        pitcher_context=pitcher_context,
        audit=audit,
    )
    return VerifiedRun(
        dashboard=dashboard,
        recent_snapshot=recent_snapshot,
        long_term_snapshot=long_snapshot,
    )


def load_dashboard(handle: RunHandle) -> DashboardData:
    """The view models alone, for callers that do not need the snapshots.

    Backward-compatible with every pre-GM-041.5 caller; it is exactly the
    ``dashboard`` field of :func:`load_verified_run`.
    """
    return load_verified_run(handle).dashboard

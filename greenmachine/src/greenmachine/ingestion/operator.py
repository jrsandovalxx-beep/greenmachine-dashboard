"""GM-040 operator workflow: composition over the frozen GM-020 pipeline.

Nothing here captures, archives, verifies, normalizes, maps, or replays —
those behaviors live unchanged in the GM-020 modules. This module adds only
the missing operator-facing extension points:

* an explicit **operator selection** record, including the projected/confirmed
  lineup status. No compatible frozen surface exists for lineup status (it is
  not part of any manifest-v1 identity, snapshot, or report), so per ruling it
  is recorded in the generated **operator report** only — bundle identities
  are untouched;
* honest **prospective vs. retrospective-development classification** from
  recorded instants (never the current clock): a capture completed after the
  scheduled start is never represented as a locked pregame prediction, and an
  explicitly retrospective run is clearly distinguished even when its
  timestamps happen to precede first pitch;
* an optional **expected-pitcher cross-check**: manifest v1 requires the
  pitcher capture to match the *feed-resolved* pitcher exactly, so an
  operator-supplied MLBAM id can only verify that resolution — it can never
  override it. A mismatch fails closed before publication;
* **idempotent publication**: repeating a run whose planned bytes match an
  existing bundle verifies instead of writing; any true content conflict
  fails explicitly; nothing is ever destructively overwritten.

Multi-player operation stays exactly what manifest v1 supports: independent
one-hitter bundles, one per selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path

from greenmachine.common.clock import Clock
from greenmachine.common.errors import ErrorContext
from greenmachine.common.serialization import canonical_bytes

from .archive import REPLAY_REPORT_RELATIVE_PATH, publish_bundle
from .capture import HttpTransport, RetryPolicy, Sleeper
from .errors import CapturePublicationError, IngestionEligibilityError, IngestionModelError
from .models import CaptureMode
from .orchestration import (
    CaptureFailure,
    PublishedRun,
    VerticalSliceRequest,
    coordinated_as_of,
    run_capture,
)

__all__ = [
    "OPERATOR_REPORT_JSON_PATH",
    "OPERATOR_REPORT_MARKDOWN_PATH",
    "CaptureClassification",
    "LineupStatus",
    "OperatorRun",
    "OperatorSelection",
    "classify_capture",
    "execute_real_slice",
    "publish_or_verify",
]

OPERATOR_REPORT_JSON_PATH = "reports/operator_report.json"
OPERATOR_REPORT_MARKDOWN_PATH = "OPERATOR_REPORT.md"
_FAILED_OPERATOR_REPORT_JSON_PATH = "failed_run/operator_report.json"

OPERATOR_REPORT_VERSION = 1

_LINEUP_STATUS_NOTE = (
    "lineup status is operator-supplied metadata recorded in this report only; "
    "it participates in no manifest-v1 identity, snapshot, or archived report"
)
_NO_SCORING_NOTE = (
    "no score, tier, recommendation, ranking, or betting claim is produced by this run"
)


class LineupStatus(Enum):
    """The operator's statement about the selected hitter's lineup standing."""

    PROJECTED = "projected"
    CONFIRMED = "confirmed"


@dataclass(frozen=True, slots=True)
class OperatorSelection:
    """One explicit real-data selection. Nothing is guessed or inferred."""

    slate_date: date
    game_pk: int
    batter_id: int
    lineup_status: LineupStatus
    capture_mode: CaptureMode
    expected_pitcher_id: int | None = None
    operator_note: str = ""

    def __post_init__(self) -> None:
        if self.game_pk <= 0:
            raise IngestionModelError("OperatorSelection.game_pk must be positive")
        if self.batter_id <= 0:
            raise IngestionModelError("OperatorSelection.batter_id must be positive")
        if self.expected_pitcher_id is not None and self.expected_pitcher_id <= 0:
            raise IngestionModelError(
                "OperatorSelection.expected_pitcher_id must be positive when supplied"
            )
        if not isinstance(self.lineup_status, LineupStatus):
            raise IngestionModelError("OperatorSelection.lineup_status must be a LineupStatus")
        if not isinstance(self.operator_note, str):
            raise IngestionModelError("OperatorSelection.operator_note must be a string")


@dataclass(frozen=True, slots=True)
class CaptureClassification:
    """The honest timing verdict, derived from recorded instants only."""

    label: str
    scheduled_start_utc: datetime
    latest_participating_completion: datetime
    run_completed_at: datetime
    captured_before_scheduled_start: bool
    statement: str


def classify_capture(run: PublishedRun) -> CaptureClassification:
    """Classify a published run from its own recorded instants.

    The current clock never participates: the same bundle classifies the same
    way on any later day. A prospective-mode run is only publishable when the
    frozen GM-020 timing contract already held, so its classification restates
    proven facts; an explicitly retrospective run is labeled
    ``retrospective-development`` even when its recorded completion happens to
    precede the scheduled start — it is never a locked pregame prediction.
    """
    scheduled_start = run.recent.snapshot.game_context.scheduled_start_utc
    manifest = run.manifest
    latest_participating = coordinated_as_of(manifest)
    captured_before = (
        manifest.run_completed_at < scheduled_start and latest_participating < scheduled_start
    )
    if manifest.capture_mode is CaptureMode.PROSPECTIVE:
        return CaptureClassification(
            label="prospective",
            scheduled_start_utc=scheduled_start,
            latest_participating_completion=latest_participating,
            run_completed_at=manifest.run_completed_at,
            captured_before_scheduled_start=captured_before,
            statement=(
                "prospective capture: every participating retrieval and the run "
                "completion precede the scheduled first pitch, proven from recorded "
                "manifest instants and re-proven on every replay"
            ),
        )
    timing_note = (
        "the recorded completion precedes the scheduled start, but the operator "
        "explicitly marked this run retrospective-development"
        if captured_before
        else "the recorded completion does not precede the scheduled start"
    )
    return CaptureClassification(
        label="retrospective-development",
        scheduled_start_utc=scheduled_start,
        latest_participating_completion=latest_participating,
        run_completed_at=manifest.run_completed_at,
        captured_before_scheduled_start=captured_before,
        statement=(
            f"retrospective-development capture (explicit operator permission): "
            f"{timing_note}; this run is never represented as a locked pregame "
            f"prediction"
        ),
    )


# --------------------------------------------------------------------------
# Operator reports (the sanctioned surface for operator metadata)
# --------------------------------------------------------------------------


def _selection_document(selection: OperatorSelection) -> dict[str, object]:
    return {
        "slate_date": selection.slate_date.isoformat(),
        "game_pk": selection.game_pk,
        "batter_id": selection.batter_id,
        "lineup_status": selection.lineup_status.value,
        "capture_mode": selection.capture_mode.value,
        "expected_pitcher_id_crosscheck": selection.expected_pitcher_id,
        "operator_note": selection.operator_note,
    }


def _published_report_document(
    selection: OperatorSelection, run: PublishedRun, classification: CaptureClassification
) -> dict[str, object]:
    recent = run.recent.snapshot
    long_term = run.long_term.snapshot
    return {
        "operator_report_version": OPERATOR_REPORT_VERSION,
        "selection": _selection_document(selection),
        "resolved": {
            "batter_name": recent.batter.full_name,
            "expected_pitcher_id": recent.expected_starting_pitcher.player_id.value,
            "expected_pitcher_name": recent.expected_starting_pitcher.full_name,
            "expected_pitcher_role": recent.pitcher_role.value,
            "venue": recent.game_context.venue.name,
        },
        "identities": {
            "manifest_id": run.manifest_id,
            "source_capture_id": run.source_capture_id.value,
            "recent_snapshot_id": recent.snapshot_id.value,
            "long_term_snapshot_id": long_term.snapshot_id.value,
            "recent_input_hash": recent.input_hash.value,
            "long_term_input_hash": long_term.input_hash.value,
        },
        "classification": {
            "label": classification.label,
            "scheduled_start_utc": classification.scheduled_start_utc.isoformat(),
            "latest_participating_completion": (
                classification.latest_participating_completion.isoformat()
            ),
            "run_completed_at": classification.run_completed_at.isoformat(),
            "captured_before_scheduled_start": (classification.captured_before_scheduled_start),
            "statement": classification.statement,
        },
        "notes": (_LINEUP_STATUS_NOTE, _NO_SCORING_NOTE),
    }


def _published_report_markdown(
    selection: OperatorSelection, run: PublishedRun, classification: CaptureClassification
) -> str:
    recent = run.recent.snapshot
    lines = [
        "# GM-040 operator report",
        "",
        f"**Classification:** {classification.label}",
        "",
        classification.statement,
        "",
        "## Selection",
        f"- slate date: {selection.slate_date.isoformat()}",
        f"- game: `{selection.game_pk}` at {recent.game_context.venue.name}",
        f"- hitter: {recent.batter.full_name} (MLBAM `{selection.batter_id}`)",
        f"- lineup status (operator-supplied): **{selection.lineup_status.value}**",
        f"- capture mode: {selection.capture_mode.value}",
        (
            f"- expected-pitcher cross-check: `{selection.expected_pitcher_id}` (matched)"
            if selection.expected_pitcher_id is not None
            else "- expected-pitcher cross-check: not supplied (feed resolution accepted)"
        ),
    ]
    if selection.operator_note:
        lines.append(f"- operator note: {selection.operator_note}")
    lines.extend(
        [
            "",
            "## Resolved expected pitcher",
            (
                f"- {recent.expected_starting_pitcher.full_name} "
                f"(MLBAM `{recent.expected_starting_pitcher.player_id.value}`), "
                f"{recent.pitcher_role.value}"
            ),
            "",
            "## Timing (recorded instants only)",
            f"- scheduled first pitch (UTC): {classification.scheduled_start_utc.isoformat()}",
            (
                f"- latest participating capture completion: "
                f"{classification.latest_participating_completion.isoformat()}"
            ),
            f"- run completed: {classification.run_completed_at.isoformat()}",
            (
                f"- captured before scheduled start: "
                f"{str(classification.captured_before_scheduled_start).lower()}"
            ),
            "",
            "## Identities",
            f"- manifest_id: `{run.manifest_id}`",
            f"- source_capture_id: `{run.source_capture_id.value}`",
            f"- RECENT_7D snapshot: `{recent.snapshot_id.value}`",
            f"- LONG_TERM_2Y snapshot: `{run.long_term.snapshot.snapshot_id.value}`",
            "",
            "## Notes",
            f"- {_LINEUP_STATUS_NOTE}",
            f"- {_NO_SCORING_NOTE}",
            "",
            "Replay offline with:",
            "```",
            "python scripts/run_gm040_real_slice.py replay --run-dir <this run directory>",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _failure_report_files(selection: OperatorSelection) -> tuple[tuple[str, bytes], ...]:
    document = {
        "operator_report_version": OPERATOR_REPORT_VERSION,
        "selection": _selection_document(selection),
        "outcome": "not published",
        "statement": (
            "the coordinated capture did not publish; the blockers and attempt "
            "evidence are recorded beside this report under failed_run/"
        ),
        "notes": (_LINEUP_STATUS_NOTE, _NO_SCORING_NOTE),
    }
    return ((_FAILED_OPERATOR_REPORT_JSON_PATH, canonical_bytes(document)),)


# --------------------------------------------------------------------------
# Execution and idempotent publication
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OperatorRun:
    """One executed GM-040 selection: the pipeline outcome plus the complete
    publishable file plan (operator reports included) and the classification
    (``None`` when the capture did not publish)."""

    outcome: PublishedRun | CaptureFailure
    files: tuple[tuple[str, bytes], ...]
    classification: CaptureClassification | None

    @property
    def published(self) -> bool:
        return self.outcome.published


def execute_real_slice(
    selection: OperatorSelection,
    *,
    transport: HttpTransport,
    clock: Clock,
    sleeper: Sleeper,
    retry_policy: RetryPolicy,
    sample_policy_bytes: bytes,
) -> OperatorRun:
    """Run one real-data selection through the unchanged GM-020 pipeline.

    The only additions are operator-level: the pitcher cross-check (fail
    closed before anything is published) and the operator report appended to
    the file plan ahead of atomic publication.
    """
    outcome = run_capture(
        VerticalSliceRequest(
            slate_date=selection.slate_date,
            game_pk=selection.game_pk,
            batter_id=selection.batter_id,
            capture_mode=selection.capture_mode,
        ),
        transport=transport,
        clock=clock,
        sleeper=sleeper,
        retry_policy=retry_policy,
        sample_policy_bytes=sample_policy_bytes,
    )
    if isinstance(outcome, CaptureFailure):
        return OperatorRun(
            outcome=outcome,
            files=outcome.files + _failure_report_files(selection),
            classification=None,
        )

    resolved_pitcher = int(outcome.recent.snapshot.expected_starting_pitcher.player_id.value)
    if selection.expected_pitcher_id is not None and (
        selection.expected_pitcher_id != resolved_pitcher
    ):
        raise IngestionEligibilityError(
            f"expected-pitcher cross-check failed: the operator supplied MLBAM "
            f"{selection.expected_pitcher_id}, but the verified game feed resolves "
            f"MLBAM {resolved_pitcher}; nothing was published — manifest v1 always "
            f"records the feed-resolved pitcher, so re-run without the cross-check "
            f"only if the feed resolution is actually correct",
            ErrorContext(subject=str(selection.game_pk)),
        )

    classification = classify_capture(outcome)
    report_files = (
        (
            OPERATOR_REPORT_JSON_PATH,
            canonical_bytes(_published_report_document(selection, outcome, classification)),
        ),
        (
            OPERATOR_REPORT_MARKDOWN_PATH,
            _published_report_markdown(selection, outcome, classification).encode("utf-8"),
        ),
    )
    return OperatorRun(
        outcome=outcome,
        files=outcome.files + report_files,
        classification=classification,
    )


def publish_or_verify(directory: Path, files: tuple[tuple[str, bytes], ...]) -> str:
    """Publish atomically, or verify an existing identical bundle.

    Returns ``"published"`` or ``"verified-existing"``. An existing directory
    is compared byte-for-byte against the plan (the once-only replay report is
    the sole permitted extra); any difference is an explicit conflict and
    nothing is ever overwritten.
    """
    if not directory.exists():
        publish_bundle(directory, files)
        return "published"

    planned = dict(files)
    existing = {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }
    extras = sorted(set(existing) - set(planned) - {REPLAY_REPORT_RELATIVE_PATH})
    missing = sorted(set(planned) - set(existing))
    different = sorted(
        relative_path
        for relative_path, data in planned.items()
        if relative_path in existing and existing[relative_path] != data
    )
    if not extras and not missing and not different:
        return "verified-existing"
    raise CapturePublicationError(
        f"run directory '{directory.name}' already exists with conflicting content "
        f"(missing: {missing or 'none'}; different: {different or 'none'}; "
        f"unexpected: {extras or 'none'}); existing runs are never overwritten — "
        f"publish to a new directory or investigate the conflict"
    )

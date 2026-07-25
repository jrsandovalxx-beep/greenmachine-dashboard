"""Coordinated capture, atomic publication, and deterministic offline replay.

One coordinated run retrieves five raw responses — MLB schedule, MLB game
feed, batter events for each profile window, and the expected pitcher's
season events (audit-only) — through the injected transport, then parses,
validates identities, normalizes, maps, and freezes the two profile
snapshots. **Everything is assembled in memory**: a run publishes atomically
only when every required capture succeeded and validated, and a failed or
ineligible run yields a failure bundle preserving raw attempt evidence
without ever publishing a coordinated capture, a ``SourceCaptureId``,
normalized production records, or an ``InputSnapshot``.

Replay reverses the path from exact archived bytes: the manifest is parsed
under a **strict, fail-closed document contract** (exact field sets, no
unknown fields, no coercion, per-entry recorded ``capture_id`` verified
against its recomputed identity before any raw parsing), every raw artifact's
digest verified (one flipped byte fails), the archived sample-minimum policy
reloaded and digest-verified from inside the bundle itself, and the snapshots
regenerated offline — no network, no clock, no dependence on the current
date, working directory, timezone setting, or filesystem enumeration order.
A published bundle is therefore **self-contained**: a copied run directory
alone is sufficient for replay.

Prospective integrity is proven from **recorded instants**, never from the
current time: publication (and replay) of a prospective run requires pregame
status in both sources, agreeing scheduled starts, and every participating
capture — and the run itself — completed strictly before the scheduled first
pitch, all read from the manifest.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from typing import TypeVar

from greenmachine.common.clock import Clock
from greenmachine.common.errors import ErrorContext
from greenmachine.common.serialization import canonical_bytes
from greenmachine.domain import SourceCaptureId, WindowProfile
from greenmachine.evaluation import serialize_record

from .capture import FetchResult, HttpTransport, RetryPolicy, Sleeper, fetch_with_retry
from .errors import (
    IdentityMismatchError,
    IngestionEligibilityError,
    ProviderResponseError,
    SamplePolicyError,
    SchemaDriftError,
)
from .events import (
    EligibleBatterEvents,
    EligiblePitcherEvents,
    normalize_batter_events,
    normalize_pitcher_events,
)
from .manifest import (
    capture_entry_identity,
    manifest_document,
    manifest_identity,
    source_capture_identity,
    verify_raw_bytes,
)
from .mapping import ProfileMappingResult, map_profile_snapshot
from .mlb.client import live_feed_request, schedule_request
from .mlb.client import request_url as mlb_request_url
from .mlb.parser import (
    FEED_CONTRACT_VERSION,
    SCHEDULE_CONTRACT_VERSION,
    GameFeedRecord,
    feed_fingerprint_of,
    parse_game_feed,
    parse_schedule,
    resolve_expected_pitcher,
    schedule_fingerprint_of,
)
from .models import (
    RETROSPECTIVE_DISCLAIMER,
    AttemptOutcome,
    AttemptRecord,
    CaptureManifest,
    CaptureMode,
    CaptureProvider,
    EventWindowReport,
    ExpectedPitcherRecord,
    GameRecord,
    IngestionEligibilityResult,
    ProviderRequest,
    RawCaptureEntry,
    SampleMinimumPolicy,
)
from .policy import load_sample_policy
from .savant.client import batter_events_request, pitcher_events_request
from .savant.client import request_url as savant_request_url
from .savant.metrics import MetricComputation, PullAudit, pitcher_ingredient_rows
from .savant.parser import (
    BATTER_EVENTS_CONTRACT_VERSION,
    PITCHER_EVENTS_CONTRACT_VERSION,
    header_fingerprint_of,
    parse_batter_events,
    parse_pitcher_events,
)
from .strict_json import strict_json_loads

__all__ = [
    "LONG_TERM_WINDOW_DAYS",
    "RECENT_WINDOW_DAYS",
    "CaptureFailure",
    "PublishedRun",
    "ReplayResult",
    "VerticalSliceRequest",
    "coordinated_as_of",
    "prospective_blockers",
    "replay_run",
    "run_capture",
]

RECENT_WINDOW_DAYS = 7
LONG_TERM_WINDOW_DAYS = 730

_LABEL_SCHEDULE = "mlb_schedule"
_LABEL_FEED = "mlb_game_feed"
_LABEL_BATTER_RECENT = "batter_events_recent_7d"
_LABEL_BATTER_LONG = "batter_events_long_term_2y"
_LABEL_PITCHER = "pitcher_events_season"

MANIFEST_PATH = "manifest.json"
SNAPSHOT_PATHS = {
    WindowProfile.RECENT_7D: "snapshots/input_snapshot_recent_7d.json",
    WindowProfile.LONG_TERM_2Y: "snapshots/input_snapshot_long_term_2y.json",
}
REPLAY_REPORT_PATH = "reports/replay.json"
SAMPLE_POLICY_PATH = "inputs/sample_minimum_policy.json"
REPLAY_INPUTS_PATH = "inputs/replay_inputs.json"
REPLAY_INPUTS_SCHEMA_VERSION = 1

# The exact replay-input metadata for schema version 1. These are contract
# values, not decoration: the reader requires byte-exact equality, so a
# bundle cannot masquerade as production or quietly drop its disclaimer.
REPLAY_INPUTS_CLASSIFICATION = "non_production_validation_only"
REPLAY_INPUTS_DISCLAIMER = (
    "GM-020 validation-only sample-minimum policy; the production minimums "
    "are open under Q14 and this file is replaced when Q14 resolves"
)
REPLAY_INPUTS_STATEMENT = (
    "this is NOT a production model configuration; replay loads exactly these "
    "archived policy bytes, verifies this digest, and refuses any substitute"
)

_PREGAME_ABSTRACT_STATE = "Preview"


# --------------------------------------------------------------------------
# Run shapes
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerticalSliceRequest:
    """The explicit selection for one vertical-slice run. Nothing is inferred."""

    slate_date: date
    game_pk: int
    batter_id: int
    capture_mode: CaptureMode


@dataclass(frozen=True, slots=True)
class PublishedRun:
    """A successfully published coordinated capture, entirely in memory."""

    manifest: CaptureManifest
    manifest_id: str
    source_capture_id: SourceCaptureId
    recent: ProfileMappingResult
    long_term: ProfileMappingResult
    files: tuple[tuple[str, bytes], ...]

    @property
    def published(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class CaptureFailure:
    """A run that must not publish: raw attempt evidence only, under failed_run/."""

    eligibility: IngestionEligibilityResult
    files: tuple[tuple[str, bytes], ...]

    @property
    def published(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """The outcome of one offline replay against archived bytes."""

    manifest_id: str
    source_capture_id: SourceCaptureId
    recent_identical: bool
    long_term_identical: bool
    report_document: dict[str, object]

    @property
    def byte_identical(self) -> bool:
        return self.recent_identical and self.long_term_identical


@dataclass(frozen=True, slots=True)
class _Windows:
    recent_start: date
    long_term_start: date
    end_exclusive: date
    pitcher_season_start: date


def _windows_for(slate_date: date) -> _Windows:
    return _Windows(
        recent_start=slate_date - timedelta(days=RECENT_WINDOW_DAYS),
        long_term_start=slate_date - timedelta(days=LONG_TERM_WINDOW_DAYS),
        end_exclusive=slate_date,
        pitcher_season_start=date(slate_date.year, 1, 1),
    )


def _url_for(request: ProviderRequest) -> str:
    if request.provider is CaptureProvider.MLB_STATS_API:
        return mlb_request_url(request)
    return savant_request_url(request)


def _extension_for(request: ProviderRequest) -> str:
    return "csv" if request.provider is CaptureProvider.BASEBALL_SAVANT else "json"


@dataclass(frozen=True, slots=True)
class _Fetched:
    request: ProviderRequest
    result: FetchResult

    @property
    def body(self) -> bytes:
        response = self.result.response
        if response is None:
            raise ProviderResponseError(f"capture '{self.request.label}' has no response body")
        return response.body


# --------------------------------------------------------------------------
# Failure bundles (never published as coordinated captures)
# --------------------------------------------------------------------------


def _attempts_document(fetched: tuple[_Fetched, ...]) -> dict[str, object]:
    return {
        "attempts_by_label": [
            {
                "label": item.request.label,
                "provider": item.request.provider.value,
                "endpoint": item.request.endpoint,
                "parameters": item.request.parameters,
                "succeeded": item.result.succeeded,
                "attempts": [
                    {
                        "index": attempt.index,
                        "started_at": attempt.started_at.isoformat(),
                        "completed_at": attempt.completed_at.isoformat(),
                        "outcome": attempt.outcome.value,
                        "http_status": attempt.http_status,
                        "error_category": attempt.error_category,
                    }
                    for attempt in item.result.attempts
                ],
            }
            for item in fetched
        ]
    }


def _failure(
    blockers: tuple[str, ...],
    notes: tuple[str, ...],
    fetched: tuple[_Fetched, ...],
) -> CaptureFailure:
    eligibility = IngestionEligibilityResult(eligible=False, blockers=blockers, notes=notes)
    files: list[tuple[str, bytes]] = [
        (
            "failed_run/eligibility.json",
            canonical_bytes({"eligible": False, "blockers": blockers, "notes": notes}),
        ),
        ("failed_run/attempts.json", canonical_bytes(_attempts_document(fetched))),
    ]
    for item in fetched:
        response = item.result.response
        if item.result.succeeded and response is not None:
            files.append(
                (
                    f"failed_run/raw/{item.request.label}.{_extension_for(item.request)}",
                    response.body,
                )
            )
    return CaptureFailure(eligibility=eligibility, files=tuple(files))


# --------------------------------------------------------------------------
# Manifest entries
# --------------------------------------------------------------------------


def _entry_for(
    fetched: _Fetched,
    *,
    mode: CaptureMode,
    fingerprint: str,
    contract_version: str,
    participates: bool,
) -> RawCaptureEntry:
    result = fetched.result
    response = result.response
    if response is None or result.body_sha256 is None:
        raise ProviderResponseError(
            f"capture '{fetched.request.label}' cannot enter a manifest without a "
            f"successful response"
        )
    success_completed = [
        attempt.completed_at
        for attempt in result.attempts
        if attempt.outcome is AttemptOutcome.SUCCESS
    ]
    return RawCaptureEntry(
        request=fetched.request,
        capture_mode=mode,
        retrieval_started_at=result.attempts[0].started_at,
        retrieval_completed_at=success_completed[-1],
        http_status=response.status,
        content_type=response.header("content-type"),
        byte_length=len(response.body),
        sha256=result.body_sha256,
        schema_fingerprint=fingerprint,
        required_field_contract_version=contract_version,
        attempts=result.attempts,
        artifact_relative_path=(f"raw/{fetched.request.label}.{_extension_for(fetched.request)}"),
        participates_in_snapshot=participates,
        error_category=None,
    )


# --------------------------------------------------------------------------
# Parsing + validation shared by capture and replay
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ParsedRun:
    game: GameRecord
    feed: GameFeedRecord
    expected_pitcher: ExpectedPitcherRecord
    batter_full_name: str
    recent: EligibleBatterEvents
    long_term: EligibleBatterEvents
    pitcher: EligiblePitcherEvents


def coordinated_as_of(manifest: CaptureManifest) -> datetime:
    """The coordinated snapshot ``as_of``: the latest **participating** completion.

    The audit-only pitcher capture never participates, so its retrieval timing
    can never move either hitter snapshot. Both profiles share this one
    instant. ``manifest.run_completed_at`` remains separate, global
    operational audit metadata.
    """
    return max(entry.retrieval_completed_at for entry in manifest.participating_entries)


def prospective_blockers(
    game: GameRecord, feed: GameFeedRecord, manifest: CaptureManifest
) -> tuple[str, ...]:
    """Every reason this run is not genuine prospective evidence.

    All timing is proven from **recorded** instants in the manifest and the
    archived provider statuses — never from the current time — so capture and
    replay reach the same verdict on any date. One deterministic blocker
    family exists per failure kind; "strictly before" means completion at
    exactly the scheduled first pitch fails.
    """
    blockers: list[str] = []
    if game.status_abstract != _PREGAME_ABSTRACT_STATE:
        blockers.append(
            f"schedule_status_not_pregame:{game.status_abstract}:{game.status_detailed}"
        )
    if feed.status_abstract != _PREGAME_ABSTRACT_STATE:
        blockers.append(f"feed_status_not_pregame:{feed.status_abstract}:{feed.status_detailed}")
    if "postponed" in game.status_detailed.lower() or "postponed" in feed.status_detailed.lower():
        blockers.append("game_postponed")
    if game.scheduled_start_utc != feed.scheduled_start_utc:
        blockers.append(
            "scheduled_start_disagreement:"
            f"{game.scheduled_start_utc.isoformat()}:{feed.scheduled_start_utc.isoformat()}"
        )

    scheduled_start = game.scheduled_start_utc
    if manifest.run_completed_at >= scheduled_start:
        blockers.append(
            "prospective_timing:run_completed_not_before_start:"
            f"{manifest.run_completed_at.isoformat()}"
        )
    for entry in manifest.entries:
        if entry.retrieval_completed_at > manifest.run_completed_at:
            blockers.append(
                f"prospective_timing:capture_completed_after_run_completion:{entry.request.label}"
            )
    for entry in manifest.participating_entries:
        if entry.retrieval_completed_at >= scheduled_start:
            blockers.append(f"prospective_timing:capture_not_before_start:{entry.request.label}")
    as_of = coordinated_as_of(manifest)
    if as_of >= scheduled_start:
        blockers.append(f"prospective_timing:as_of_not_before_start:{as_of.isoformat()}")
    return tuple(blockers)


def _cross_check_identities(
    request: VerticalSliceRequest, game: GameRecord, feed: GameFeedRecord
) -> None:
    if feed.game_pk != game.game_pk or game.game_pk != request.game_pk:
        raise IdentityMismatchError(
            f"game identity disagreement: requested {request.game_pk}, schedule "
            f"{game.game_pk}, feed {feed.game_pk}",
            ErrorContext(subject=str(request.game_pk)),
        )
    if feed.venue_id != game.venue_id:
        raise IdentityMismatchError(
            f"venue identity disagreement for game {game.game_pk}: schedule venue "
            f"{game.venue_id}, feed venue {feed.venue_id}",
            ErrorContext(subject=str(game.game_pk)),
        )
    if (feed.home_team_id, feed.away_team_id) != (game.home_team_id, game.away_team_id):
        raise IdentityMismatchError(
            f"team identity disagreement for game {game.game_pk}: schedule "
            f"({game.home_team_id}, {game.away_team_id}), feed "
            f"({feed.home_team_id}, {feed.away_team_id})",
            ErrorContext(subject=str(game.game_pk)),
        )


def _parse_and_validate(
    request: VerticalSliceRequest,
    schedule_raw: bytes,
    feed_raw: bytes,
    batter_recent_raw: bytes,
    batter_long_raw: bytes,
    pitcher_raw: bytes,
) -> _ParsedRun:
    windows = _windows_for(request.slate_date)

    slate = parse_schedule(schedule_raw, request.slate_date)
    game = slate.game(request.game_pk)
    feed = parse_game_feed(feed_raw)
    _cross_check_identities(request, game, feed)

    if game.game_type != "R":
        raise IngestionEligibilityError(
            f"game {game.game_pk} has game_type '{game.game_type}'; only regular-season "
            f"games (R) are eligible for the GM-020 slice",
            ErrorContext(subject=str(game.game_pk)),
        )
    if game.official_date != request.slate_date:
        raise IngestionEligibilityError(
            f"game {game.game_pk} has official date {game.official_date.isoformat()}, "
            f"not the selected slate date {request.slate_date.isoformat()}",
            ErrorContext(subject=str(game.game_pk)),
        )

    expected_pitcher = resolve_expected_pitcher(feed, request.batter_id)
    batter_full_name = feed.player_name(request.batter_id)
    if batter_full_name is None:
        raise IngestionEligibilityError(
            f"batter {request.batter_id} has no name entry in the game feed",
            ErrorContext(subject=str(request.batter_id)),
        )

    recent = normalize_batter_events(
        parse_batter_events(batter_recent_raw),
        profile=WindowProfile.RECENT_7D,
        window_start=windows.recent_start,
        window_end_exclusive=windows.end_exclusive,
        selected_game_pk=request.game_pk,
        expected_batter_id=request.batter_id,
    )
    long_term = normalize_batter_events(
        parse_batter_events(batter_long_raw),
        profile=WindowProfile.LONG_TERM_2Y,
        window_start=windows.long_term_start,
        window_end_exclusive=windows.end_exclusive,
        selected_game_pk=request.game_pk,
        expected_batter_id=request.batter_id,
    )
    pitcher = normalize_pitcher_events(
        parse_pitcher_events(pitcher_raw),
        profile=WindowProfile.LONG_TERM_2Y,
        window_start=windows.pitcher_season_start,
        window_end_exclusive=windows.end_exclusive,
        selected_game_pk=request.game_pk,
        expected_pitcher_id=expected_pitcher.pitcher_id,
    )
    return _ParsedRun(
        game=game,
        feed=feed,
        expected_pitcher=expected_pitcher,
        batter_full_name=batter_full_name,
        recent=recent,
        long_term=long_term,
        pitcher=pitcher,
    )


def _map_profiles(
    request: VerticalSliceRequest,
    parsed: _ParsedRun,
    manifest: CaptureManifest,
    sample_policy: SampleMinimumPolicy,
) -> tuple[SourceCaptureId, ProfileMappingResult, ProfileMappingResult]:
    source_capture_id = source_capture_identity(manifest)
    as_of = coordinated_as_of(manifest)
    recent_entry = manifest.entry(_LABEL_BATTER_RECENT)
    long_entry = manifest.entry(_LABEL_BATTER_LONG)

    recent = map_profile_snapshot(
        profile=WindowProfile.RECENT_7D,
        events=parsed.recent,
        game=parsed.game,
        venue_timezone=parsed.feed.venue_timezone,
        batter_id=request.batter_id,
        batter_full_name=parsed.batter_full_name,
        expected_pitcher=parsed.expected_pitcher,
        policy=sample_policy,
        source_capture_id=source_capture_id,
        as_of=as_of,
        source_as_of=recent_entry.retrieval_completed_at,
        retrieved_at=recent_entry.retrieval_completed_at,
    )
    long_term = map_profile_snapshot(
        profile=WindowProfile.LONG_TERM_2Y,
        events=parsed.long_term,
        game=parsed.game,
        venue_timezone=parsed.feed.venue_timezone,
        batter_id=request.batter_id,
        batter_full_name=parsed.batter_full_name,
        expected_pitcher=parsed.expected_pitcher,
        policy=sample_policy,
        source_capture_id=source_capture_id,
        as_of=as_of,
        source_as_of=long_entry.retrieval_completed_at,
        retrieved_at=long_entry.retrieval_completed_at,
    )
    return source_capture_id, recent, long_term


# --------------------------------------------------------------------------
# Report documents
# --------------------------------------------------------------------------


def _report_of(report: EventWindowReport) -> dict[str, object]:
    return {
        "profile": report.profile.value,
        "window_start": report.window_start.isoformat(),
        "window_end_exclusive": report.window_end_exclusive.isoformat(),
        "half_open_rule": "window_start <= event game_date < window_end_exclusive",
        "rows_received": report.rows_received,
        "duplicates_collapsed": report.duplicates_collapsed,
        "excluded_by_game_type": report.excluded_by_game_type,
        "excluded_missing_game_type": report.excluded_missing_game_type,
        "excluded_outside_window": report.excluded_outside_window,
        "excluded_selected_game": report.excluded_selected_game,
        "rows_eligible": report.rows_eligible,
        "game_type_policy": "R-only for the GM-020 slice; excluded types counted above",
    }


def _computation_doc(computation: MetricComputation) -> dict[str, object]:
    return {
        "name": computation.name,
        "value": computation.value,
        "numerator": computation.numerator,
        "sample_count": computation.sample_count,
        "unit": computation.unit,
        "exclusions": computation.exclusions,
        "notes": computation.notes,
    }


def _pull_document(audit: PullAudit) -> dict[str, object]:
    return {
        "chosen_pull_air": _computation_doc(audit.pull_air),
        "alternative_fly_only": _computation_doc(audit.alternative_fly_only),
        "alternative_fly_line_popup": _computation_doc(audit.alternative_fly_line_popup),
        "overall_pull_report_only": _computation_doc(audit.overall_pull),
        "statement": (
            "only chosen_pull_air may enter an InputSnapshot; the alternatives and "
            "Overall Pull % are audit/report-only by Product Owner ruling"
        ),
    }


def _schema_document(manifest: CaptureManifest) -> dict[str, object]:
    return {
        "entries": [
            {
                "label": entry.request.label,
                "provider": entry.request.provider.value,
                "endpoint": entry.request.endpoint,
                "required_field_contract_version": entry.required_field_contract_version,
                "schema_fingerprint": entry.schema_fingerprint,
                "policy": (
                    "missing/incompatible required fields fail closed; additive unknown "
                    "fields are accepted and audited via the fingerprint"
                ),
            }
            for entry in manifest.entries
        ]
    }


def _limitations_document(
    mode: CaptureMode, sample_policy: SampleMinimumPolicy
) -> dict[str, object]:
    notes: list[str] = [
        "GM-020 vertical-slice evidence: one slate, one game, one hitter, the expected pitcher",
        (
            "sample-minimum policy in force is explicitly injected and NON-PRODUCTION: "
            + sample_policy.disclaimer
        ),
        (
            "pitcher-matchup components are missing under the interim SOURCE_UNAVAILABLE "
            "label: the provider transport SUCCEEDED and the audit ingredients were "
            "captured; no approved Q15/Q16 formula exists, so no component value was "
            "manufactured; Q15/Q16 and the optional derivation-pending missing reason "
            "remain open Product Owner decisions, and this label is temporary — it does "
            "not claim the provider was unreachable"
        ),
        (
            "park and weather remain missing: no source has been selected for "
            "either component in this vertical slice"
        ),
        (
            "Ideal Attack Angle % is event-derived (5-20 inclusive over tracked "
            "attack-angle rows), not the official published leaderboard aggregate"
        ),
        "no scoring, grading, or signal evaluation exists in this slice",
    ]
    if mode is CaptureMode.RETROSPECTIVE_RECONSTRUCTION:
        notes.insert(0, RETROSPECTIVE_DISCLAIMER)
    return {"capture_mode": mode.value, "limitations": tuple(notes)}


def _replay_inputs_document(sample_policy_bytes: bytes) -> dict[str, object]:
    """The canonical replay-input record pinning the exact archived policy."""
    return {
        "replay_inputs_schema_version": REPLAY_INPUTS_SCHEMA_VERSION,
        "sample_policy_path": SAMPLE_POLICY_PATH,
        "sample_policy_sha256": hashlib.sha256(sample_policy_bytes).hexdigest(),
        "classification": REPLAY_INPUTS_CLASSIFICATION,
        "disclaimer": REPLAY_INPUTS_DISCLAIMER,
        "statement": REPLAY_INPUTS_STATEMENT,
    }


def _bundle_files(
    manifest: CaptureManifest,
    raw_by_label: dict[str, bytes],
    parsed: _ParsedRun,
    recent: ProfileMappingResult,
    long_term: ProfileMappingResult,
    sample_policy: SampleMinimumPolicy,
    sample_policy_bytes: bytes,
) -> tuple[tuple[str, bytes], ...]:
    ingredient_rows, ingredient_exclusions = pitcher_ingredient_rows(parsed.pitcher.rows)
    files: list[tuple[str, bytes]] = [(MANIFEST_PATH, canonical_bytes(manifest_document(manifest)))]
    for entry in manifest.entries:
        files.append((entry.artifact_relative_path, raw_by_label[entry.request.label]))
    files.append((SAMPLE_POLICY_PATH, sample_policy_bytes))
    files.append(
        (REPLAY_INPUTS_PATH, canonical_bytes(_replay_inputs_document(sample_policy_bytes)))
    )
    files.append((SNAPSHOT_PATHS[WindowProfile.RECENT_7D], serialize_record(recent.snapshot)))
    files.append((SNAPSHOT_PATHS[WindowProfile.LONG_TERM_2Y], serialize_record(long_term.snapshot)))
    files.extend(
        (
            (
                "reports/eligibility.json",
                canonical_bytes({"eligible": True, "blockers": (), "notes": ()}),
            ),
            (
                "reports/normalization_recent_7d.json",
                canonical_bytes(_report_of(parsed.recent.report)),
            ),
            (
                "reports/normalization_long_term_2y.json",
                canonical_bytes(_report_of(parsed.long_term.report)),
            ),
            (
                "reports/normalization_pitcher_season.json",
                canonical_bytes(_report_of(parsed.pitcher.report)),
            ),
            ("reports/schema.json", canonical_bytes(_schema_document(manifest))),
            (
                "reports/pull_audit_recent_7d.json",
                canonical_bytes(_pull_document(recent.pull_audit)),
            ),
            (
                "reports/pull_audit_long_term_2y.json",
                canonical_bytes(_pull_document(long_term.pull_audit)),
            ),
            (
                "reports/pitcher_ingredients.json",
                canonical_bytes(
                    {
                        "rows": [
                            {
                                "stand": row.stand,
                                "pitch_type": row.pitch_type,
                                "pitches": row.pitches,
                                "usage_percent_within_stand": row.usage_percent_within_stand,
                                "two_strike_pitches": row.two_strike_pitches,
                                "putaway_finishes": row.putaway_finishes,
                            }
                            for row in ingredient_rows
                        ],
                        "exclusions": ingredient_exclusions,
                        "statement": (
                            "transparent audit ingredients only, captured from a "
                            "successful provider transport; Pitch Mix Pressure and "
                            "Put-Away Pitch Exploitation remain missing because the "
                            "Q15/Q16 formulas are undefined and no value is manufactured"
                        ),
                    }
                ),
            ),
            (
                "reports/limitations.json",
                canonical_bytes(_limitations_document(manifest.capture_mode, sample_policy)),
            ),
        )
    )
    return tuple(files)


# --------------------------------------------------------------------------
# Capture
# --------------------------------------------------------------------------


def run_capture(
    request: VerticalSliceRequest,
    *,
    transport: HttpTransport,
    clock: Clock,
    sleeper: Sleeper,
    retry_policy: RetryPolicy,
    sample_policy_bytes: bytes,
) -> PublishedRun | CaptureFailure:
    """Execute one coordinated capture; publish atomically or fail with evidence.

    The sample-minimum policy arrives as **exact bytes**: they are validated
    strictly before any network activity, archived verbatim inside the
    published bundle, and digest-pinned so replay can never run under
    different minimums.
    """
    sample_policy = load_sample_policy(sample_policy_bytes)
    run_started_at = clock.now()
    windows = _windows_for(request.slate_date)
    fetched: list[_Fetched] = []

    def fetch(provider_request: ProviderRequest) -> _Fetched:
        result = fetch_with_retry(
            transport, _url_for(provider_request), retry_policy, clock, sleeper
        )
        item = _Fetched(request=provider_request, result=result)
        fetched.append(item)
        return item

    schedule_fetch = fetch(schedule_request(request.slate_date))
    if not schedule_fetch.result.succeeded:
        return _failure(("capture_failed:mlb_schedule",), (), tuple(fetched))

    feed_fetch = fetch(live_feed_request(request.game_pk))
    if not feed_fetch.result.succeeded:
        return _failure(("capture_failed:mlb_game_feed",), (), tuple(fetched))

    batter_recent_fetch = fetch(
        batter_events_request(
            _LABEL_BATTER_RECENT,
            request.batter_id,
            windows.recent_start,
            windows.end_exclusive,
        )
    )
    if not batter_recent_fetch.result.succeeded:
        return _failure(("capture_failed:batter_events_recent_7d",), (), tuple(fetched))

    batter_long_fetch = fetch(
        batter_events_request(
            _LABEL_BATTER_LONG,
            request.batter_id,
            windows.long_term_start,
            windows.end_exclusive,
        )
    )
    if not batter_long_fetch.result.succeeded:
        return _failure(("capture_failed:batter_events_long_term_2y",), (), tuple(fetched))

    # The expected pitcher is only knowable after the feed parses; parse the
    # MLB responses now so the pitcher request can be built — any parse or
    # eligibility failure still preserves everything fetched so far.
    try:
        preliminary_feed = parse_game_feed(feed_fetch.body)
        expected = resolve_expected_pitcher(preliminary_feed, request.batter_id)
    except (SchemaDriftError, IngestionEligibilityError, IdentityMismatchError) as blocked:
        return _failure((f"{type(blocked).__name__}:{blocked.message}",), (), tuple(fetched))

    pitcher_fetch = fetch(
        pitcher_events_request(
            _LABEL_PITCHER,
            expected.pitcher_id,
            windows.pitcher_season_start,
            windows.end_exclusive,
        )
    )
    if not pitcher_fetch.result.succeeded:
        return _failure(("capture_failed:pitcher_events_season",), (), tuple(fetched))

    try:
        parsed = _parse_and_validate(
            request,
            schedule_fetch.body,
            feed_fetch.body,
            batter_recent_fetch.body,
            batter_long_fetch.body,
            pitcher_fetch.body,
        )
    except (
        SchemaDriftError,
        IngestionEligibilityError,
        IdentityMismatchError,
        ProviderResponseError,
    ) as blocked:
        return _failure((f"{type(blocked).__name__}:{blocked.message}",), (), tuple(fetched))

    run_completed_at = clock.now()
    manifest = CaptureManifest(
        manifest_schema_version=1,
        slate_date=request.slate_date,
        game_id=str(request.game_pk),
        batter_id=str(request.batter_id),
        capture_mode=request.capture_mode,
        run_started_at=run_started_at,
        run_completed_at=run_completed_at,
        entries=tuple(
            sorted(
                (
                    _entry_for(
                        schedule_fetch,
                        mode=request.capture_mode,
                        fingerprint=schedule_fingerprint_of(schedule_fetch.body),
                        contract_version=SCHEDULE_CONTRACT_VERSION,
                        participates=True,
                    ),
                    _entry_for(
                        feed_fetch,
                        mode=request.capture_mode,
                        fingerprint=feed_fingerprint_of(feed_fetch.body),
                        contract_version=FEED_CONTRACT_VERSION,
                        participates=True,
                    ),
                    _entry_for(
                        batter_recent_fetch,
                        mode=request.capture_mode,
                        fingerprint=header_fingerprint_of(batter_recent_fetch.body),
                        contract_version=BATTER_EVENTS_CONTRACT_VERSION,
                        participates=True,
                    ),
                    _entry_for(
                        batter_long_fetch,
                        mode=request.capture_mode,
                        fingerprint=header_fingerprint_of(batter_long_fetch.body),
                        contract_version=BATTER_EVENTS_CONTRACT_VERSION,
                        participates=True,
                    ),
                    _entry_for(
                        pitcher_fetch,
                        mode=request.capture_mode,
                        fingerprint=header_fingerprint_of(pitcher_fetch.body),
                        contract_version=PITCHER_EVENTS_CONTRACT_VERSION,
                        # Audit ingredients only: does not affect any snapshot
                        # observation in GM-020, so it must not contribute to
                        # SourceCaptureId.
                        participates=False,
                    ),
                ),
                key=lambda entry: entry.request.label,
            )
        ),
    )

    # The same coherence contract replay enforces, applied at the source: a
    # capture that cannot satisfy its own semantic contract must never publish.
    _validate_manifest_semantics(manifest)

    if request.capture_mode is CaptureMode.PROSPECTIVE:
        blockers = prospective_blockers(parsed.game, parsed.feed, manifest)
        if blockers:
            return _failure(blockers, (), tuple(fetched))

    source_capture_id, recent, long_term = _map_profiles(request, parsed, manifest, sample_policy)
    raw_by_label = {item.request.label: item.body for item in fetched}
    files = _bundle_files(
        manifest, raw_by_label, parsed, recent, long_term, sample_policy, sample_policy_bytes
    )
    return PublishedRun(
        manifest=manifest,
        manifest_id=manifest_identity(manifest),
        source_capture_id=source_capture_id,
        recent=recent,
        long_term=long_term,
        files=files,
    )


# --------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------


# The GreenMachine-owned manifest document is a strict contract: exactly
# these fields, no more, no fewer. Unknown fields are rejected until a future
# manifest schema version explicitly approves them.
_MANIFEST_FIELDS = frozenset(
    {
        "manifest_schema_version",
        "manifest_id",
        "slate_date",
        "game_id",
        "batter_id",
        "capture_mode",
        "run_started_at",
        "run_completed_at",
        "entries",
    }
)
_ENTRY_FIELDS = frozenset(
    {
        "label",
        "capture_id",
        "provider",
        "endpoint",
        "parameters",
        "capture_mode",
        "retrieval_started_at",
        "retrieval_completed_at",
        "http_status",
        "content_type",
        "byte_length",
        "sha256",
        "schema_fingerprint",
        "required_field_contract_version",
        "attempts",
        "artifact_relative_path",
        "participates_in_snapshot",
        "error_category",
    }
)
_ATTEMPT_FIELDS = frozenset(
    {"index", "started_at", "completed_at", "outcome", "http_status", "error_category"}
)


def _manifest_error(detail: str) -> ProviderResponseError:
    return ProviderResponseError(f"manifest.json fails the strict document contract: {detail}")


def _exact_fields(mapping: dict[str, object], required: frozenset[str], where: str) -> None:
    unknown = sorted(set(mapping) - required)
    if unknown:
        raise _manifest_error(f"{where} carries unknown field(s) {unknown}")
    missing = sorted(required - set(mapping))
    if missing:
        raise _manifest_error(f"{where} is missing required field(s) {missing}")


def _text(mapping: dict[str, object], key: str, where: str) -> str:
    value = mapping[key]
    if not isinstance(value, str):
        raise _manifest_error(f"{where} field '{key}' must be a string")
    return value


def _integer(mapping: dict[str, object], key: str, where: str) -> int:
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _manifest_error(f"{where} field '{key}' must be an integer")
    return value


def _boolean(mapping: dict[str, object], key: str, where: str) -> bool:
    value = mapping[key]
    if not isinstance(value, bool):
        raise _manifest_error(f"{where} field '{key}' must be a JSON boolean, not a lookalike")
    return value


def _optional_text(mapping: dict[str, object], key: str, where: str) -> str | None:
    value = mapping[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise _manifest_error(f"{where} field '{key}' must be a string or null")
    return value


def _optional_integer(mapping: dict[str, object], key: str, where: str) -> int | None:
    value = mapping[key]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise _manifest_error(f"{where} field '{key}' must be an integer or null")
    return value


def _instant(mapping: dict[str, object], key: str, where: str) -> datetime:
    rendered = _text(mapping, key, where)
    try:
        value = datetime.fromisoformat(rendered)
    except ValueError as exc:
        raise _manifest_error(f"{where} field '{key}' is not an ISO-8601 instant") from exc
    if value.tzinfo is None:
        raise _manifest_error(f"{where} field '{key}' must be timezone-aware")
    return value.astimezone(UTC)


_E = TypeVar("_E", bound=Enum)


def _enum_value(kind: type[_E], mapping: dict[str, object], key: str, where: str) -> _E:
    rendered = _text(mapping, key, where)
    try:
        return kind(rendered)
    except ValueError as exc:
        raise _manifest_error(f"{where} field '{key}' has unknown value '{rendered}'") from exc


def _parameters_of(raw_entry: dict[str, object], where: str) -> tuple[tuple[str, str], ...]:
    raw_parameters = raw_entry["parameters"]
    if not isinstance(raw_parameters, list):
        raise _manifest_error(f"{where} field 'parameters' must be an array")
    parameters: list[tuple[str, str]] = []
    for pair in raw_parameters:
        if not isinstance(pair, list) or len(pair) != 2:
            raise _manifest_error(f"{where} has a malformed parameter item: {pair!r}")
        key, value = pair
        if not isinstance(key, str) or not isinstance(value, str):
            raise _manifest_error(f"{where} parameter elements must both be strings: {pair!r}")
        parameters.append((key, value))
    return tuple(parameters)


def _attempts_of(raw_entry: dict[str, object], where: str) -> tuple[AttemptRecord, ...]:
    raw_attempts = raw_entry["attempts"]
    if not isinstance(raw_attempts, list) or not raw_attempts:
        raise _manifest_error(f"{where} field 'attempts' must be a non-empty array")
    attempts: list[AttemptRecord] = []
    for position, raw_attempt in enumerate(raw_attempts, start=1):
        if not isinstance(raw_attempt, dict):
            raise _manifest_error(f"{where} has a malformed attempt item: {raw_attempt!r}")
        attempt_where = f"{where} attempt {position}"
        _exact_fields(raw_attempt, _ATTEMPT_FIELDS, attempt_where)
        index = _integer(raw_attempt, "index", attempt_where)
        if index != position:
            raise _manifest_error(
                f"{attempt_where} has index {index}; attempt indexes must be "
                f"consecutive ascending from 1"
            )
        outcome = _enum_value(AttemptOutcome, raw_attempt, "outcome", attempt_where)
        attempts.append(
            AttemptRecord(
                index=index,
                started_at=_instant(raw_attempt, "started_at", attempt_where),
                completed_at=_instant(raw_attempt, "completed_at", attempt_where),
                outcome=outcome,
                http_status=_optional_integer(raw_attempt, "http_status", attempt_where),
                error_category=_optional_text(raw_attempt, "error_category", attempt_where),
            )
        )
    return tuple(attempts)


def _entry_of(raw_entry: object, position: int) -> tuple[str, RawCaptureEntry]:
    if not isinstance(raw_entry, dict):
        raise _manifest_error(f"entry {position} must be an object")
    where = f"entry {position}"
    _exact_fields(raw_entry, _ENTRY_FIELDS, where)
    provider = _enum_value(CaptureProvider, raw_entry, "provider", where)
    mode = _enum_value(CaptureMode, raw_entry, "capture_mode", where)
    entry = RawCaptureEntry(
        request=ProviderRequest(
            label=_text(raw_entry, "label", where),
            provider=provider,
            endpoint=_text(raw_entry, "endpoint", where),
            parameters=_parameters_of(raw_entry, where),
        ),
        capture_mode=mode,
        retrieval_started_at=_instant(raw_entry, "retrieval_started_at", where),
        retrieval_completed_at=_instant(raw_entry, "retrieval_completed_at", where),
        http_status=_integer(raw_entry, "http_status", where),
        content_type=_optional_text(raw_entry, "content_type", where),
        byte_length=_integer(raw_entry, "byte_length", where),
        sha256=_text(raw_entry, "sha256", where),
        schema_fingerprint=_text(raw_entry, "schema_fingerprint", where),
        required_field_contract_version=_text(raw_entry, "required_field_contract_version", where),
        attempts=_attempts_of(raw_entry, where),
        artifact_relative_path=_text(raw_entry, "artifact_relative_path", where),
        participates_in_snapshot=_boolean(raw_entry, "participates_in_snapshot", where),
        error_category=_optional_text(raw_entry, "error_category", where),
    )
    return _text(raw_entry, "capture_id", where), entry


# The exact GM-020 coordinated run shape for manifest schema version 1: these
# five labels, with exactly these participation flags.
_EXPECTED_PARTICIPATION = {
    _LABEL_BATTER_LONG: True,
    _LABEL_BATTER_RECENT: True,
    _LABEL_FEED: True,
    _LABEL_PITCHER: False,
    _LABEL_SCHEDULE: True,
}


def _positive_decimal(value: str, field: str) -> int:
    """A positive canonical decimal identifier string, or a focused error."""
    if not (value.isascii() and value.isdigit()):
        raise _manifest_error(f"the manifest field '{field}' must be a decimal string")
    number = int(value)
    if number <= 0 or str(number) != value:
        raise _manifest_error(
            f"the manifest field '{field}' must be a positive canonical decimal string"
        )
    return number


def _validate_manifest_semantics(manifest: CaptureManifest) -> None:
    """The v1 semantic contract: one coherent GM-020 coordinated run.

    Field-set strictness alone accepts a well-formed lie; this layer requires
    the manifest to describe the actual GM-020 shape — the exact five labeled
    captures with the exact participation split, coherent attempt histories,
    successful responses, and provider requests that are byte-for-byte the
    requests GM-020 would construct for the recorded slate/game/batter. A
    self-consistent digest over false request metadata is rejected.
    """
    labels = sorted(entry.request.label for entry in manifest.entries)
    if labels != sorted(_EXPECTED_PARTICIPATION):
        raise _manifest_error(
            f"a v1 coordinated manifest must contain exactly the labels "
            f"{sorted(_EXPECTED_PARTICIPATION)}; found {labels}"
        )
    game_pk = _positive_decimal(manifest.game_id, "game_id")
    batter_id = _positive_decimal(manifest.batter_id, "batter_id")

    artifact_paths = [entry.artifact_relative_path for entry in manifest.entries]
    if len(set(artifact_paths)) != len(artifact_paths):
        raise _manifest_error("entry artifact_relative_path values must be unique")

    windows = _windows_for(manifest.slate_date)
    expected_requests = {
        _LABEL_SCHEDULE: schedule_request(manifest.slate_date),
        _LABEL_FEED: live_feed_request(game_pk),
        _LABEL_BATTER_RECENT: batter_events_request(
            _LABEL_BATTER_RECENT, batter_id, windows.recent_start, windows.end_exclusive
        ),
        _LABEL_BATTER_LONG: batter_events_request(
            _LABEL_BATTER_LONG, batter_id, windows.long_term_start, windows.end_exclusive
        ),
    }

    for entry in manifest.entries:
        label = entry.request.label
        where = f"entry '{label}'"
        if entry.capture_mode is not manifest.capture_mode:
            raise _manifest_error(
                f"{where} records capture mode {entry.capture_mode.value}, but the "
                f"manifest records {manifest.capture_mode.value}"
            )
        if entry.participates_in_snapshot is not _EXPECTED_PARTICIPATION[label]:
            raise _manifest_error(
                f"{where} must have participates_in_snapshot="
                f"{_EXPECTED_PARTICIPATION[label]} in a v1 coordinated manifest"
            )
        if not 200 <= entry.http_status < 300:
            raise _manifest_error(
                f"{where} records HTTP status {entry.http_status}; a published entry "
                f"must be a successful 2xx response"
            )
        if entry.error_category is not None:
            raise _manifest_error(
                f"{where} records error_category {entry.error_category!r}; a published "
                f"entry must record null"
            )
        final_attempt = entry.attempts[-1]
        if final_attempt.outcome is not AttemptOutcome.SUCCESS:
            raise _manifest_error(
                f"{where} ends with attempt outcome {final_attempt.outcome.value}; the "
                f"final attempt of a published entry must be SUCCESS"
            )
        if final_attempt.http_status != entry.http_status:
            raise _manifest_error(
                f"{where} final attempt HTTP status {final_attempt.http_status} "
                f"disagrees with the entry HTTP status {entry.http_status}"
            )
        if entry.attempts[0].started_at != entry.retrieval_started_at:
            raise _manifest_error(
                f"{where} retrieval_started_at disagrees with its first attempt start"
            )
        if final_attempt.completed_at != entry.retrieval_completed_at:
            raise _manifest_error(
                f"{where} retrieval_completed_at disagrees with its successful final "
                f"attempt completion"
            )
        for attempt in entry.attempts:
            if not (
                manifest.run_started_at
                <= attempt.started_at
                <= attempt.completed_at
                <= manifest.run_completed_at
            ):
                raise _manifest_error(
                    f"{where} attempt {attempt.index} instants fall outside the manifest run bounds"
                )
        expected = expected_requests.get(label)
        if expected is not None and entry.request != expected:
            raise _manifest_error(
                f"{where} does not match the request GM-020 constructs for the "
                f"recorded slate/game/batter (provider, endpoint, parameters, "
                f"identifiers, date bounds, and game-type scope must all agree)"
            )


def _read_manifest(reader: Callable[[str], bytes]) -> CaptureManifest:
    """Parse ``manifest.json`` under the strict fail-closed document contract.

    Duplicate JSON keys are rejected at every nesting level. Every recorded
    per-entry ``capture_id`` is verified against its recomputed identity
    **before any raw artifact is parsed**; the recorded overall
    ``manifest_id`` must match its recomputed identity; and the manifest must
    satisfy the v1 semantic contract as one coherent GM-020 record. No
    malformed member is skipped or coerced.
    """
    document = strict_json_loads(
        reader(MANIFEST_PATH), describe="manifest.json", on_error=_manifest_error
    )
    if not isinstance(document, dict):
        raise _manifest_error("the root must be a JSON object")
    _exact_fields(document, _MANIFEST_FIELDS, "the manifest")

    raw_entries = document["entries"]
    if not isinstance(raw_entries, list):
        raise _manifest_error("the manifest field 'entries' must be an array")

    entries: list[RawCaptureEntry] = []
    labels: set[str] = set()
    for position, raw_entry in enumerate(raw_entries, start=1):
        recorded_capture_id, entry = _entry_of(raw_entry, position)
        if entry.request.label in labels:
            raise _manifest_error(f"duplicate entry label '{entry.request.label}'")
        labels.add(entry.request.label)
        recomputed_capture_id = capture_entry_identity(entry)
        if recorded_capture_id != recomputed_capture_id:
            raise _manifest_error(
                f"entry '{entry.request.label}' records capture_id "
                f"{recorded_capture_id}, but its content recomputes to "
                f"{recomputed_capture_id}; the entry is not the entry that was published"
            )
        entries.append(entry)

    slate_rendered = _text(document, "slate_date", "the manifest")
    try:
        slate = date.fromisoformat(slate_rendered)
    except ValueError as exc:
        raise _manifest_error("the manifest field 'slate_date' is not an ISO date") from exc
    manifest_mode = _enum_value(CaptureMode, document, "capture_mode", "the manifest")
    manifest = CaptureManifest(
        manifest_schema_version=_integer(document, "manifest_schema_version", "the manifest"),
        slate_date=slate,
        game_id=_text(document, "game_id", "the manifest"),
        batter_id=_text(document, "batter_id", "the manifest"),
        capture_mode=manifest_mode,
        run_started_at=_instant(document, "run_started_at", "the manifest"),
        run_completed_at=_instant(document, "run_completed_at", "the manifest"),
        entries=tuple(entries),
    )
    recorded_id = _text(document, "manifest_id", "the manifest")
    recomputed = manifest_identity(manifest)
    if recorded_id != recomputed:
        raise _manifest_error(
            f"manifest identity mismatch: recorded {recorded_id}, recomputed {recomputed}; "
            f"the manifest content is not the content that was published"
        )
    _validate_manifest_semantics(manifest)
    return manifest


_REPLAY_INPUT_FIELDS = frozenset(
    {
        "replay_inputs_schema_version",
        "sample_policy_path",
        "sample_policy_sha256",
        "classification",
        "disclaimer",
        "statement",
    }
)


def _replay_inputs_error(detail: str) -> SamplePolicyError:
    return SamplePolicyError(detail)


_SHA256_HEX_LENGTH = 64


def _read_archived_policy(reader: Callable[[str], bytes]) -> SampleMinimumPolicy:
    """Load the bundle's own archived sample policy, digest-verified.

    Replay accepts **no caller-supplied policy**: the exact bytes the capture
    validated are the only bytes that can govern a replay, so a run can never
    be silently replayed under different minimums. Every metadata field is
    validated for exact type and exact value — a bundle cannot present itself
    as production, drop its disclaimer, or weaken its statement.
    """
    document = strict_json_loads(
        reader(REPLAY_INPUTS_PATH),
        describe="replay_inputs.json",
        on_error=_replay_inputs_error,
    )
    if not isinstance(document, dict):
        raise SamplePolicyError("replay_inputs.json root must be a JSON object")
    unknown = sorted(set(document) - _REPLAY_INPUT_FIELDS)
    if unknown:
        raise SamplePolicyError(f"replay_inputs.json carries unknown field(s): {unknown}")
    missing = sorted(_REPLAY_INPUT_FIELDS - set(document))
    if missing:
        raise SamplePolicyError(f"replay_inputs.json is missing required field(s): {missing}")
    version: object = document["replay_inputs_schema_version"]
    if isinstance(version, bool) or version != REPLAY_INPUTS_SCHEMA_VERSION:
        raise SamplePolicyError(
            f"replay_inputs.json schema version {version!r} is not the supported "
            f"version {REPLAY_INPUTS_SCHEMA_VERSION}"
        )
    recorded_path: object = document["sample_policy_path"]
    if recorded_path != SAMPLE_POLICY_PATH:
        raise SamplePolicyError(
            f"replay_inputs.json records policy path {recorded_path!r}; the stable "
            f"bundle path is '{SAMPLE_POLICY_PATH}'"
        )
    for field, required_value in (
        ("classification", REPLAY_INPUTS_CLASSIFICATION),
        ("disclaimer", REPLAY_INPUTS_DISCLAIMER),
        ("statement", REPLAY_INPUTS_STATEMENT),
    ):
        recorded: object = document[field]
        if not isinstance(recorded, str):
            raise SamplePolicyError(
                f"replay_inputs.json '{field}' must be a string, not {type(recorded).__name__}"
            )
        if recorded != required_value:
            raise SamplePolicyError(
                f"replay_inputs.json '{field}' does not carry the exact required v1 "
                f"value; found {recorded!r}"
            )
    recorded_digest: object = document["sample_policy_sha256"]
    if not isinstance(recorded_digest, str):
        raise SamplePolicyError("replay_inputs.json 'sample_policy_sha256' must be a string")
    if len(recorded_digest) != _SHA256_HEX_LENGTH or any(
        character not in "0123456789abcdef" for character in recorded_digest
    ):
        raise SamplePolicyError(
            "replay_inputs.json 'sample_policy_sha256' must be a lowercase "
            "64-character hexadecimal SHA-256 digest"
        )

    policy_bytes = reader(SAMPLE_POLICY_PATH)
    actual_digest = hashlib.sha256(policy_bytes).hexdigest()
    if actual_digest != recorded_digest:
        raise SamplePolicyError(
            f"the archived sample policy has digest {actual_digest}, but the run "
            f"recorded {recorded_digest}; the policy is not the policy the capture "
            f"validated, so replay refuses to proceed"
        )
    return load_sample_policy(policy_bytes)


def replay_run(reader: Callable[[str], bytes]) -> ReplayResult:
    """Regenerate both snapshots offline from exact archived bytes and compare.

    ``reader`` maps a run-relative path to bytes; no network, clock, or
    environment participates — a copied run directory alone is sufficient.
    The manifest is parsed strictly (per-entry ``capture_id`` and the overall
    ``manifest_id`` verified), every raw artifact's digest is checked before
    parsing, the bundle's own archived sample policy is reloaded and
    digest-verified, and a prospective run's recorded timing is re-validated
    from the manifest instants — the current date never participates.
    """
    manifest = _read_manifest(reader)
    sample_policy = _read_archived_policy(reader)
    raw_by_label: dict[str, bytes] = {}
    for entry in manifest.entries:
        raw = reader(entry.artifact_relative_path)
        verify_raw_bytes(entry, raw)
        raw_by_label[entry.request.label] = raw

    request = VerticalSliceRequest(
        slate_date=manifest.slate_date,
        game_pk=int(manifest.game_id),
        batter_id=int(manifest.batter_id),
        capture_mode=manifest.capture_mode,
    )
    parsed = _parse_and_validate(
        request,
        raw_by_label[_LABEL_SCHEDULE],
        raw_by_label[_LABEL_FEED],
        raw_by_label[_LABEL_BATTER_RECENT],
        raw_by_label[_LABEL_BATTER_LONG],
        raw_by_label[_LABEL_PITCHER],
    )
    # The pitcher request can only be validated once the feed has resolved
    # the expected pitcher: it must be exactly the request GM-020 constructs
    # for that pitcher and the declared season window.
    windows = _windows_for(manifest.slate_date)
    expected_pitcher_request = pitcher_events_request(
        _LABEL_PITCHER,
        parsed.expected_pitcher.pitcher_id,
        windows.pitcher_season_start,
        windows.end_exclusive,
    )
    if manifest.entry(_LABEL_PITCHER).request != expected_pitcher_request:
        raise _manifest_error(
            "the pitcher capture request does not match the feed-resolved expected "
            "pitcher and declared season window"
        )
    if manifest.capture_mode is CaptureMode.PROSPECTIVE:
        blockers = prospective_blockers(parsed.game, parsed.feed, manifest)
        if blockers:
            raise IngestionEligibilityError(
                "the archived run does not qualify as prospective under its own "
                "recorded instants: " + "; ".join(blockers)
            )
    source_capture_id, recent, long_term = _map_profiles(request, parsed, manifest, sample_policy)

    archived_recent = reader(SNAPSHOT_PATHS[WindowProfile.RECENT_7D])
    archived_long = reader(SNAPSHOT_PATHS[WindowProfile.LONG_TERM_2Y])
    regenerated_recent = serialize_record(recent.snapshot)
    regenerated_long = serialize_record(long_term.snapshot)

    recent_identical = archived_recent == regenerated_recent
    long_identical = archived_long == regenerated_long
    report: dict[str, object] = {
        "manifest_id": manifest_identity(manifest),
        "source_capture_id": source_capture_id.value,
        "raw_digests_verified": True,
        "recent_snapshot_byte_identical": recent_identical,
        "long_term_snapshot_byte_identical": long_identical,
        "statement": (
            "offline replay from exact archived bytes; no network, clock, or "
            "environment participated"
        ),
    }
    return ReplayResult(
        manifest_id=manifest_identity(manifest),
        source_capture_id=source_capture_id,
        recent_identical=recent_identical,
        long_term_identical=long_identical,
        report_document=report,
    )

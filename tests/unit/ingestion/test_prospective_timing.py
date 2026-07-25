"""Prospective integrity from recorded instants — never from the current time.

Every case constructs the manifest instants explicitly and asserts the exact
deterministic blocker family, proving publication and replay reach the same
verdict on any date: the wall clock never participates (the src-wide
architecture guard already forbids clock reads inside ``src/``).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from tests.fixtures.ingestion import synthetic_provider_fixtures as fixtures

from greenmachine.ingestion.mlb.parser import parse_game_feed, parse_schedule
from greenmachine.ingestion.models import (
    AttemptOutcome,
    AttemptRecord,
    CaptureManifest,
    CaptureMode,
    CaptureProvider,
    ProviderRequest,
    RawCaptureEntry,
)
from greenmachine.ingestion.orchestration import coordinated_as_of, prospective_blockers

SLATE = date(2026, 7, 15)
SCHEDULED_START = datetime(2026, 7, 15, 23, 10, tzinfo=UTC)  # fixtures.GAME_START_UTC
BEFORE_START = datetime(2026, 7, 15, 18, 0, tzinfo=UTC)

GAME = parse_schedule(fixtures.schedule_json(), SLATE).game(fixtures.GAME_PK)
FEED = parse_game_feed(fixtures.feed_json())


def _entry(label: str, completed_at: datetime, *, participates: bool) -> RawCaptureEntry:
    attempt = AttemptRecord(
        index=1,
        started_at=completed_at - timedelta(seconds=1),
        completed_at=completed_at,
        outcome=AttemptOutcome.SUCCESS,
        http_status=200,
        error_category=None,
    )
    return RawCaptureEntry(
        request=ProviderRequest(
            label=label,
            provider=CaptureProvider.MLB_STATS_API,
            endpoint="schedule",
            parameters=(("date", "2026-07-15"),),
        ),
        capture_mode=CaptureMode.PROSPECTIVE,
        retrieval_started_at=attempt.started_at,
        retrieval_completed_at=completed_at,
        http_status=200,
        content_type="application/json",
        byte_length=4,
        sha256="a" * 64,
        schema_fingerprint="fp",
        required_field_contract_version="v1",
        attempts=(attempt,),
        artifact_relative_path=f"raw/{label}.json",
        participates_in_snapshot=participates,
    )


def _manifest(
    *entries: RawCaptureEntry, run_completed_at: datetime = BEFORE_START
) -> CaptureManifest:
    return CaptureManifest(
        manifest_schema_version=1,
        slate_date=SLATE,
        game_id=str(fixtures.GAME_PK),
        batter_id=str(fixtures.BATTER_ID),
        capture_mode=CaptureMode.PROSPECTIVE,
        run_started_at=BEFORE_START - timedelta(hours=1),
        run_completed_at=run_completed_at,
        entries=tuple(sorted(entries, key=lambda entry: entry.request.label)),
    )


# --------------------------------------------------------------------------
# Passing case
# --------------------------------------------------------------------------


def test_preview_responses_completed_before_first_pitch_pass() -> None:
    manifest = _manifest(
        _entry("alpha", BEFORE_START - timedelta(minutes=5), participates=True),
        _entry("beta", BEFORE_START - timedelta(minutes=3), participates=False),
    )
    assert prospective_blockers(GAME, FEED, manifest) == ()


def test_coordinated_as_of_is_the_latest_participating_completion() -> None:
    early = BEFORE_START - timedelta(minutes=30)
    late_participating = BEFORE_START - timedelta(minutes=2)
    later_but_audit_only = BEFORE_START - timedelta(minutes=1)
    manifest = _manifest(
        _entry("alpha", early, participates=True),
        _entry("beta", late_participating, participates=True),
        _entry("gamma", later_but_audit_only, participates=False),
    )
    assert coordinated_as_of(manifest) == late_participating  # the audit capture is ignored


# --------------------------------------------------------------------------
# Timing failures (recorded instants; stale Preview does not bypass them)
# --------------------------------------------------------------------------


def test_participating_completion_after_first_pitch_fails() -> None:
    manifest = _manifest(
        _entry("alpha", SCHEDULED_START + timedelta(minutes=1), participates=True),
        run_completed_at=SCHEDULED_START + timedelta(minutes=2),
    )
    blockers = prospective_blockers(GAME, FEED, manifest)
    assert any(
        blocker.startswith("prospective_timing:capture_not_before_start:alpha")
        for blocker in blockers
    ), blockers


def test_completion_exactly_at_first_pitch_fails() -> None:
    """'Strictly before' means the boundary instant itself is rejected."""
    manifest = _manifest(
        _entry("alpha", SCHEDULED_START, participates=True),
        run_completed_at=SCHEDULED_START,
    )
    blockers = prospective_blockers(GAME, FEED, manifest)
    assert any("capture_not_before_start:alpha" in blocker for blocker in blockers)
    assert any("run_completed_not_before_start" in blocker for blocker in blockers)
    assert any("as_of_not_before_start" in blocker for blocker in blockers)


def test_stale_preview_status_does_not_bypass_timing_validation() -> None:
    """A feed still claiming Preview cannot rescue post-start recorded timing."""
    assert GAME.status_abstract == "Preview" and FEED.status_abstract == "Preview"
    manifest = _manifest(
        _entry("alpha", SCHEDULED_START + timedelta(hours=1), participates=True),
        run_completed_at=SCHEDULED_START + timedelta(hours=1, minutes=1),
    )
    assert prospective_blockers(GAME, FEED, manifest) != ()


def test_run_completed_at_must_be_strictly_before_the_start() -> None:
    manifest = _manifest(
        _entry("alpha", BEFORE_START, participates=True),
        run_completed_at=SCHEDULED_START,
    )
    blockers = prospective_blockers(GAME, FEED, manifest)
    assert any("run_completed_not_before_start" in blocker for blocker in blockers)


def test_a_capture_completed_after_run_completion_fails() -> None:
    manifest = _manifest(
        _entry("alpha", BEFORE_START + timedelta(minutes=5), participates=True),
        run_completed_at=BEFORE_START,
    )
    blockers = prospective_blockers(GAME, FEED, manifest)
    assert any("capture_completed_after_run_completion:alpha" in blocker for blocker in blockers)


def test_schedule_and_feed_scheduled_starts_must_agree() -> None:
    disagreeing_feed = parse_game_feed(
        fixtures.feed_json(gameData={"datetime": {"dateTime": "2026-07-15T23:40:00Z"}})
    )
    manifest = _manifest(_entry("alpha", BEFORE_START, participates=True))
    blockers = prospective_blockers(GAME, disagreeing_feed, manifest)
    assert any(blocker.startswith("scheduled_start_disagreement:") for blocker in blockers)


def test_each_failure_family_is_deterministic() -> None:
    """The same recorded instants always yield the same blocker strings."""
    manifest = _manifest(
        _entry("alpha", SCHEDULED_START, participates=True),
        run_completed_at=SCHEDULED_START,
    )
    first = prospective_blockers(GAME, FEED, manifest)
    second = prospective_blockers(GAME, FEED, manifest)
    assert first == second

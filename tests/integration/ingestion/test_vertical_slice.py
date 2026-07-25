"""End-to-end vertical slice: capture, atomic publication, failure, and replay."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from tests.fixtures.ingestion import synthetic_provider_fixtures as fixtures

from greenmachine.domain import WindowProfile
from greenmachine.ingestion.archive import bundle_reader, publish_bundle
from greenmachine.ingestion.capture import RetryPolicy
from greenmachine.ingestion.errors import CapturePublicationError, DigestMismatchError
from greenmachine.ingestion.models import CaptureMode
from greenmachine.ingestion.orchestration import (
    SAMPLE_POLICY_PATH,
    SNAPSHOT_PATHS,
    VerticalSliceRequest,
    replay_run,
    run_capture,
)

POLICY_BYTES = fixtures.sample_policy_bytes()
RETRY = RetryPolicy(timeout_seconds=10, max_attempts=3, backoff_seconds=(1, 2))
REQUEST = VerticalSliceRequest(
    slate_date=date(2026, 7, 15),
    game_pk=fixtures.GAME_PK,
    batter_id=fixtures.BATTER_ID,
    capture_mode=CaptureMode.PROSPECTIVE,
)


def capture(routes: list | None = None, request: VerticalSliceRequest = REQUEST) -> object:
    return run_capture(
        request,
        transport=fixtures.FakeTransport(
            routes=fixtures.default_routes() if routes is None else routes
        ),
        clock=fixtures.SteppingClock(),
        sleeper=fixtures.RecordingSleeper(),
        retry_policy=RETRY,
        sample_policy_bytes=POLICY_BYTES,
    )


# --------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------


def test_a_coordinated_capture_publishes_both_profile_snapshots() -> None:
    outcome = capture()
    assert outcome.published  # type: ignore[attr-defined]

    recent = outcome.recent.snapshot  # type: ignore[attr-defined]
    long_term = outcome.long_term.snapshot  # type: ignore[attr-defined]
    assert recent.window_profile is WindowProfile.RECENT_7D
    assert long_term.window_profile is WindowProfile.LONG_TERM_2Y
    assert recent.source_capture_id == long_term.source_capture_id
    assert recent.snapshot_id != long_term.snapshot_id
    assert recent.input_hash != long_term.input_hash

    labels = [entry.request.label for entry in outcome.manifest.entries]  # type: ignore[attr-defined]
    assert labels == sorted(labels)
    participating = {
        entry.request.label
        for entry in outcome.manifest.participating_entries  # type: ignore[attr-defined]
    }
    assert participating == {
        "mlb_schedule",
        "mlb_game_feed",
        "batter_events_recent_7d",
        "batter_events_long_term_2y",
    }
    # The pitcher capture is audit-only and must not participate.
    assert "pitcher_events_season" not in participating

    paths = [path for path, _ in outcome.files]  # type: ignore[attr-defined]
    assert "manifest.json" in paths
    assert SNAPSHOT_PATHS[WindowProfile.RECENT_7D] in paths
    assert "reports/pull_audit_recent_7d.json" in paths
    assert "reports/pitcher_ingredients.json" in paths
    assert "reports/limitations.json" in paths
    # The bundle is self-contained: the exact policy bytes travel with the run.
    assert SAMPLE_POLICY_PATH in paths
    assert "inputs/replay_inputs.json" in paths
    assert dict(outcome.files)[SAMPLE_POLICY_PATH] == POLICY_BYTES  # type: ignore[attr-defined]


def test_the_r_only_exclusions_and_duplicates_are_audited() -> None:
    outcome = capture()
    report_bytes = dict(outcome.files)["reports/normalization_recent_7d.json"]  # type: ignore[attr-defined]
    report = json.loads(report_bytes.decode("utf-8"))
    assert report["rows_received"] == 13
    assert report["excluded_by_game_type"] == [["S", 1]]
    assert report["excluded_missing_game_type"] == 1
    assert report["duplicates_collapsed"] == 1
    assert report["excluded_selected_game"] == 1
    assert report["excluded_outside_window"] == 2
    # 13 received - 1 duplicate - 5 exclusions = 7 eligible rows.
    assert report["rows_eligible"] == 7


def test_publication_is_atomic_and_immutable(tmp_path: Path) -> None:
    outcome = capture()
    run_dir = tmp_path / "run_001"
    publish_bundle(run_dir, outcome.files)  # type: ignore[attr-defined]
    assert (run_dir / "manifest.json").is_file()
    assert not run_dir.with_name("run_001.staging").exists()

    with pytest.raises(CapturePublicationError, match="immutable"):
        publish_bundle(run_dir, outcome.files)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# Failures never publish
# --------------------------------------------------------------------------


def test_one_failed_provider_prevents_any_publication() -> None:
    routes = [
        route for route in fixtures.default_routes() if "game_date_gt=2024-07-15" not in route[0]
    ]  # the long-term batter capture now has no route -> transport error x3
    outcome = capture(routes=routes)

    assert not outcome.published  # type: ignore[attr-defined]
    assert outcome.eligibility.blockers == (  # type: ignore[attr-defined]
        "capture_failed:batter_events_long_term_2y",
    )
    paths = [path for path, _ in outcome.files]  # type: ignore[attr-defined]
    assert all(path.startswith("failed_run/") for path in paths)
    assert "failed_run/attempts.json" in paths
    # Raw evidence of the captures that DID succeed is preserved…
    assert "failed_run/raw/mlb_schedule.json" in paths
    # …but nothing publishable exists: no manifest, no snapshots.
    assert not any("manifest.json" in path and "failed" not in path for path in paths)
    assert not any(path.startswith("snapshots/") for path in paths)


def test_a_postponed_game_is_ineligible_in_prospective_mode() -> None:
    postponed = fixtures.schedule_game(
        status={
            "abstractGameState": "Final",
            "detailedState": "Postponed",
            "codedGameState": "D",
        }
    )
    routes = [("/api/v1/schedule", fixtures.ok(fixtures.schedule_json([postponed])))] + [
        route for route in fixtures.default_routes() if "/api/v1/schedule" not in route[0]
    ]
    outcome = capture(routes=routes)
    assert not outcome.published  # type: ignore[attr-defined]
    blockers = outcome.eligibility.blockers  # type: ignore[attr-defined]
    assert any("game_postponed" in blocker for blocker in blockers)


def test_a_non_regular_season_game_is_ineligible() -> None:
    exhibition = fixtures.schedule_game(gameType="E")
    routes = [("/api/v1/schedule", fixtures.ok(fixtures.schedule_json([exhibition])))] + [
        route for route in fixtures.default_routes() if "/api/v1/schedule" not in route[0]
    ]
    outcome = capture(routes=routes)
    assert not outcome.published  # type: ignore[attr-defined]
    assert any(
        "only regular-season" in blocker
        for blocker in outcome.eligibility.blockers  # type: ignore[attr-defined]
    )


def test_conflicting_schedule_and_feed_identities_fail_closed() -> None:
    conflicting_feed = fixtures.feed_json(gameData={"venue": {"id": 9999}})
    routes = [("/feed/live", fixtures.ok(conflicting_feed))] + [
        route for route in fixtures.default_routes() if "/feed/live" not in route[0]
    ]
    outcome = capture(routes=routes)
    assert not outcome.published  # type: ignore[attr-defined]
    assert any(
        "IdentityMismatchError" in blocker
        for blocker in outcome.eligibility.blockers  # type: ignore[attr-defined]
    )


def test_a_suspended_game_keeps_its_canonical_id_and_is_blocked_prospectively() -> None:
    suspended = fixtures.schedule_game(
        status={
            "abstractGameState": "Live",
            "detailedState": "Suspended",
            "codedGameState": "U",
        }
    )
    routes = [("/api/v1/schedule", fixtures.ok(fixtures.schedule_json([suspended])))] + [
        route for route in fixtures.default_routes() if "/api/v1/schedule" not in route[0]
    ]
    outcome = capture(routes=routes)
    assert not outcome.published  # type: ignore[attr-defined]
    # The blocker names the same official game id — never a replacement.
    assert any(
        "schedule_status_not_pregame" in blocker
        for blocker in outcome.eligibility.blockers  # type: ignore[attr-defined]
    )


def test_retrospective_mode_permits_a_non_pregame_game() -> None:
    final = fixtures.schedule_game(
        status={
            "abstractGameState": "Final",
            "detailedState": "Final",
            "codedGameState": "F",
        }
    )
    final_feed = fixtures.feed_json(
        gameData={"status": {"abstractGameState": "Final", "detailedState": "Final"}}
    )
    routes = [
        ("/api/v1/schedule", fixtures.ok(fixtures.schedule_json([final]))),
        ("/feed/live", fixtures.ok(final_feed)),
    ] + [
        route
        for route in fixtures.default_routes()
        if "/api/v1/schedule" not in route[0] and "/feed/live" not in route[0]
    ]
    retrospective = VerticalSliceRequest(
        slate_date=REQUEST.slate_date,
        game_pk=REQUEST.game_pk,
        batter_id=REQUEST.batter_id,
        capture_mode=CaptureMode.RETROSPECTIVE_RECONSTRUCTION,
    )
    outcome = capture(routes=routes, request=retrospective)
    assert outcome.published  # type: ignore[attr-defined]
    limitations = json.loads(
        dict(outcome.files)["reports/limitations.json"].decode("utf-8")  # type: ignore[attr-defined]
    )
    assert any("Retrospectively reconstructed" in note for note in limitations["limitations"])


def test_a_changed_probable_pitcher_produces_a_new_run_and_new_snapshots() -> None:
    first = capture()
    changed_feed = fixtures.feed_json(
        gameData={
            "players": {
                "ID600010": {"id": 600010, "fullName": "Synthetic Pitcher Ten"},
            },
            "probablePitchers": {"away": {"id": 600010, "fullName": "Synthetic Pitcher Ten"}},
        }
    )
    routes = [
        ("/feed/live", fixtures.ok(changed_feed)),
        ("pitchers_lookup[]=600010", fixtures.ok(fixtures.pitcher_csv([]), "text/csv")),
    ] + [route for route in fixtures.default_routes() if "/feed/live" not in route[0]]
    second = capture(routes=routes)

    assert first.published and second.published  # type: ignore[attr-defined]
    assert first.manifest_id != second.manifest_id  # type: ignore[attr-defined]
    assert (
        first.recent.snapshot.snapshot_id != second.recent.snapshot.snapshot_id  # type: ignore[attr-defined]
    )
    assert (
        second.recent.snapshot.expected_starting_pitcher.player_id.value == "600010"  # type: ignore[attr-defined]
    )


# --------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------


def test_replay_regenerates_both_snapshots_byte_identically(tmp_path: Path) -> None:
    outcome = capture()
    run_dir = tmp_path / "run_replay"
    publish_bundle(run_dir, outcome.files)  # type: ignore[attr-defined]

    result = replay_run(bundle_reader(run_dir))
    assert result.byte_identical
    assert result.source_capture_id == outcome.source_capture_id  # type: ignore[attr-defined]


def test_replay_detects_one_byte_raw_corruption(tmp_path: Path) -> None:
    outcome = capture()
    run_dir = tmp_path / "run_corrupt"
    publish_bundle(run_dir, outcome.files)  # type: ignore[attr-defined]

    target = run_dir / "raw" / "batter_events_recent_7d.csv"
    original = bytearray(target.read_bytes())
    original[10] ^= 0x01
    target.write_bytes(bytes(original))

    with pytest.raises(DigestMismatchError, match="not the captured bytes"):
        replay_run(bundle_reader(run_dir))


def test_replay_is_independent_of_the_working_directory(tmp_path: Path) -> None:
    import os

    outcome = capture()
    run_dir = tmp_path / "run_cwd"
    publish_bundle(run_dir, outcome.files)  # type: ignore[attr-defined]

    previous = Path.cwd()
    other = tmp_path / "elsewhere"
    other.mkdir()
    os.chdir(other)
    try:
        result = replay_run(bundle_reader(run_dir))
    finally:
        os.chdir(previous)
    assert result.byte_identical

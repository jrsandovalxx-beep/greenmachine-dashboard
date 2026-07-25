"""GM-040 end-to-end: the operator layer composed over the frozen pipeline.

Everything runs against the injected fake transport — no live network is
possible (the suite-wide guard is active), and replay subprocesses go through
the guarded child bootstrap.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from tests.fixtures.ingestion import synthetic_provider_fixtures as fixtures
from tests.network_guard.guarded_child import run_guarded_python

from greenmachine.domain import MissingReason, WindowProfile
from greenmachine.ingestion.archive import bundle_reader
from greenmachine.ingestion.capture import RetryPolicy
from greenmachine.ingestion.errors import IngestionEligibilityError
from greenmachine.ingestion.models import CaptureMode
from greenmachine.ingestion.operator import (
    OPERATOR_REPORT_JSON_PATH,
    OPERATOR_REPORT_MARKDOWN_PATH,
    LineupStatus,
    OperatorRun,
    OperatorSelection,
    execute_real_slice,
    publish_or_verify,
)
from greenmachine.ingestion.orchestration import replay_run
from greenmachine.reporting import discover_runs, load_dashboard

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "scripts" / "run_gm040_real_slice.py"

RETRY = RetryPolicy(timeout_seconds=10, max_attempts=3, backoff_seconds=(1, 2))
AFTER_GAME = datetime(2026, 7, 16, 3, 0, tzinfo=UTC)  # past the 23:10Z scheduled start


def _selection(**overrides: object) -> OperatorSelection:
    values: dict[str, object] = {
        "slate_date": date(2026, 7, 15),
        "game_pk": fixtures.GAME_PK,
        "batter_id": fixtures.BATTER_ID,
        "lineup_status": LineupStatus.PROJECTED,
        "capture_mode": CaptureMode.PROSPECTIVE,
    }
    values.update(overrides)
    return OperatorSelection(**values)  # type: ignore[arg-type]


def _execute(
    selection: OperatorSelection,
    routes: list | None = None,
    clock_start: datetime = fixtures.CAPTURE_INSTANT,
) -> OperatorRun:
    return execute_real_slice(
        selection,
        transport=fixtures.FakeTransport(
            routes=fixtures.default_routes() if routes is None else routes
        ),
        clock=fixtures.SteppingClock(start=clock_start),
        sleeper=fixtures.RecordingSleeper(),
        retry_policy=RETRY,
        sample_policy_bytes=fixtures.sample_policy_bytes(),
    )


# --------------------------------------------------------------------------
# Composition: the GM-020 bundle plus exactly the operator reports
# --------------------------------------------------------------------------


def test_the_operator_run_is_the_frozen_bundle_plus_operator_reports() -> None:
    run = _execute(_selection(expected_pitcher_id=fixtures.PITCHER_ID))
    assert run.published
    pipeline_paths = [path for path, _ in run.outcome.files]
    operator_paths = [path for path, _ in run.files]
    assert operator_paths[: len(pipeline_paths)] == pipeline_paths  # untouched plan
    assert operator_paths[len(pipeline_paths) :] == [
        OPERATOR_REPORT_JSON_PATH,
        OPERATOR_REPORT_MARKDOWN_PATH,
    ]


def test_prospective_classification_states_proven_timing() -> None:
    run = _execute(_selection())
    assert run.classification is not None
    assert run.classification.label == "prospective"
    assert run.classification.captured_before_scheduled_start
    assert "recorded manifest instants" in run.classification.statement

    report = json.loads(dict(run.files)[OPERATOR_REPORT_JSON_PATH].decode("utf-8"))
    assert report["classification"]["label"] == "prospective"
    assert report["selection"]["lineup_status"] == "projected"
    assert report["identities"]["manifest_id"] == run.outcome.manifest_id  # type: ignore[union-attr]
    assert any("operator-supplied metadata" in note for note in report["notes"])
    assert any("no score" in note for note in report["notes"])


def test_retrospective_before_start_is_distinguished_not_rejected() -> None:
    """A useful development capture before first pitch still publishes, but is
    labeled retrospective-development — never a locked pregame prediction."""
    run = _execute(_selection(capture_mode=CaptureMode.RETROSPECTIVE_RECONSTRUCTION))
    assert run.published
    assert run.classification is not None
    assert run.classification.label == "retrospective-development"
    assert run.classification.captured_before_scheduled_start
    assert "never represented as a locked pregame prediction" in run.classification.statement
    assert "explicitly marked" in run.classification.statement


def test_a_capture_after_the_scheduled_start_is_labeled_honestly() -> None:
    run = _execute(
        _selection(capture_mode=CaptureMode.RETROSPECTIVE_RECONSTRUCTION),
        clock_start=AFTER_GAME,
    )
    assert run.published
    assert run.classification is not None
    assert run.classification.label == "retrospective-development"
    assert not run.classification.captured_before_scheduled_start
    assert "does not precede the scheduled start" in run.classification.statement
    markdown = dict(run.files)[OPERATOR_REPORT_MARKDOWN_PATH].decode("utf-8")
    assert "captured before scheduled start: false" in markdown


def test_prospective_mode_still_fails_closed_after_the_start() -> None:
    """GM-040 adds labeling, not leniency: the frozen timing contract holds."""
    run = _execute(_selection(), clock_start=AFTER_GAME)
    assert not run.published
    blockers = run.outcome.eligibility.blockers  # type: ignore[union-attr]
    assert any("prospective_timing" in blocker for blocker in blockers)
    paths = [path for path, _ in run.files]
    assert "failed_run/operator_report.json" in paths  # selection still documented


# --------------------------------------------------------------------------
# Expected-pitcher cross-check (verification only, never an override)
# --------------------------------------------------------------------------


def test_a_matching_pitcher_crosscheck_publishes() -> None:
    run = _execute(_selection(expected_pitcher_id=fixtures.PITCHER_ID))
    assert run.published
    markdown = dict(run.files)[OPERATOR_REPORT_MARKDOWN_PATH].decode("utf-8")
    assert f"`{fixtures.PITCHER_ID}` (matched)" in markdown


def test_a_mismatched_pitcher_crosscheck_fails_closed() -> None:
    with pytest.raises(IngestionEligibilityError, match="cross-check failed"):
        _execute(_selection(expected_pitcher_id=600010))


# --------------------------------------------------------------------------
# Idempotent execution end-to-end
# --------------------------------------------------------------------------


def test_repeating_an_identical_run_verifies_and_preserves_identities(
    tmp_path: Path,
) -> None:
    first = _execute(_selection())
    second = _execute(_selection())  # same injected clock start: identical instants
    assert first.files == second.files  # byte-identical plans
    assert first.outcome.source_capture_id == second.outcome.source_capture_id  # type: ignore[union-attr]
    assert first.outcome.manifest_id == second.outcome.manifest_id  # type: ignore[union-attr]

    target = tmp_path / "run_gm040"
    assert publish_or_verify(target, first.files) == "published"
    assert publish_or_verify(target, second.files) == "verified-existing"


def test_a_true_content_conflict_fails_explicitly(tmp_path: Path) -> None:
    baseline = _execute(_selection())
    target = tmp_path / "run_gm040"
    publish_or_verify(target, baseline.files)

    changed_routes = [
        (
            f"pitchers_lookup[]={fixtures.PITCHER_ID}",
            fixtures.ok(
                fixtures.pitcher_csv(
                    [*fixtures.default_pitcher_rows(), fixtures.pitcher_row(at_bat_number="9")]
                ),
                "text/csv",
            ),
        ),
        *[route for route in fixtures.default_routes() if "pitchers_lookup" not in route[0]],
    ]
    conflicting = _execute(_selection(), routes=changed_routes)
    with pytest.raises(Exception, match="conflicting content"):
        publish_or_verify(target, conflicting.files)
    # The original bundle is untouched.
    original = dict(baseline.files)["raw/pitcher_events_season.csv"]
    assert (target / "raw" / "pitcher_events_season.csv").read_bytes() == original


# --------------------------------------------------------------------------
# Zero-row Savant results and separate windows
# --------------------------------------------------------------------------


def test_a_zero_row_recent_window_publishes_with_honest_missing_reasons() -> None:
    routes = [
        (
            f"batters_lookup[]={fixtures.BATTER_ID}&game_date_gt=2026-07-08",
            fixtures.ok(fixtures.batter_csv([]), "text/csv"),
        ),
        *[
            route
            for route in fixtures.default_routes()
            if "game_date_gt=2026-07-08" not in route[0]
        ],
    ]
    run = _execute(_selection(capture_mode=CaptureMode.RETROSPECTIVE_RECONSTRUCTION), routes)
    assert run.published
    recent = run.outcome.recent.snapshot  # type: ignore[union-attr]
    long_term = run.outcome.long_term.snapshot  # type: ignore[union-attr]
    assert recent.present_observations == ()
    reasons = {
        observation.component_id.value: observation.missing_reason
        for observation in recent.missing_observations
    }
    assert reasons["exit_velocity"] is MissingReason.NO_EVENTS_IN_WINDOW
    # The long-term window is untouched by the empty recent window.
    assert long_term.window_profile is WindowProfile.LONG_TERM_2Y
    assert len(long_term.present_observations) == 7
    assert recent.source_capture_id == long_term.source_capture_id
    assert recent.snapshot_id != long_term.snapshot_id


# --------------------------------------------------------------------------
# Replay, Streamlit discovery, and the operator runner
# --------------------------------------------------------------------------


def _published_gm040_bundle(evidence_root: Path, name: str = "run_gm040_test") -> Path:
    run = _execute(_selection(capture_mode=CaptureMode.RETROSPECTIVE_RECONSTRUCTION))
    target = evidence_root / name
    publish_or_verify(target, run.files)
    return target


def test_a_gm040_bundle_replays_byte_identically(tmp_path: Path) -> None:
    """The two operator report files change nothing about frozen replay."""
    target = _published_gm040_bundle(tmp_path)
    result = replay_run(bundle_reader(target))
    assert result.byte_identical


def test_streamlit_discovery_and_loading_of_a_gm040_bundle(tmp_path: Path) -> None:
    target = _published_gm040_bundle(tmp_path)
    handles = discover_runs(tmp_path)
    assert [handle.name for handle in handles] == ["run_gm040_test"]
    data = load_dashboard(handles[0])
    assert data.run_name == "run_gm040_test"
    assert data.recent.profile is WindowProfile.RECENT_7D
    assert data.header.source_capture_id.startswith("source_capture-")
    # The operator report never leaks provider wire vocabulary into the app;
    # the bundle stays byte-identical after loading.
    before = sorted(path.name for path in target.rglob("*") if path.is_file())
    load_dashboard(handles[0])
    after = sorted(path.name for path in target.rglob("*") if path.is_file())
    assert after == before


def test_the_app_selector_offers_a_gm040_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from streamlit.testing.v1 import AppTest

    _published_gm040_bundle(tmp_path, name="run_gm040_apptest")
    monkeypatch.setenv("GREENMACHINE_EVIDENCE_ROOT", str(tmp_path))
    app = AppTest.from_file(str(REPO_ROOT / "streamlit_app.py"), default_timeout=300)
    app.run()
    assert not list(app.exception)
    selector = app.selectbox(key="run_select")
    assert "run_gm040_apptest" in list(selector.options)
    app.button(key="nav_overview").click().run()
    text = " ".join(str(element.value) for element in app.markdown)
    assert fixtures.BATTER_NAME in text


def test_the_gm040_runner_replays_offline_via_the_guarded_child(tmp_path: Path) -> None:
    """No network can occur: the replay subprocess runs under the child guard."""
    target = _published_gm040_bundle(tmp_path)
    completed = run_guarded_python(
        str(RUNNER), "replay", "--run-dir", str(target), cwd=tmp_path, timeout=240
    )
    assert completed.returncode == 0, completed.stderr
    assert "replay OK" in completed.stdout


def test_the_gm040_runner_requires_every_explicit_argument(tmp_path: Path) -> None:
    completed = run_guarded_python(str(RUNNER), "capture", cwd=tmp_path, timeout=240)
    assert completed.returncode != 0  # nothing is guessed or defaulted

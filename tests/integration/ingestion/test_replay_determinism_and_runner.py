"""Replay determinism across interpreters/hash seeds, and the developer runner."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from tests.fixtures.ingestion import synthetic_provider_fixtures as fixtures
from tests.network_guard.guarded_child import run_guarded_python

from greenmachine.ingestion.archive import publish_bundle
from greenmachine.ingestion.capture import RetryPolicy
from greenmachine.ingestion.models import CaptureMode
from greenmachine.ingestion.orchestration import VerticalSliceRequest, run_capture

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "scripts" / "run_gm020_vertical_slice.py"


def _published_run(tmp_path: Path) -> Path:
    outcome = run_capture(
        VerticalSliceRequest(
            slate_date=date(2026, 7, 15),
            game_pk=fixtures.GAME_PK,
            batter_id=fixtures.BATTER_ID,
            capture_mode=CaptureMode.RETROSPECTIVE_RECONSTRUCTION,
        ),
        transport=fixtures.FakeTransport(routes=fixtures.default_routes()),
        clock=fixtures.SteppingClock(),
        sleeper=fixtures.RecordingSleeper(),
        retry_policy=RetryPolicy(timeout_seconds=10, max_attempts=3, backoff_seconds=(1, 2)),
        sample_policy_bytes=fixtures.sample_policy_bytes(),
    )
    assert outcome.published  # type: ignore[attr-defined]
    run_dir = tmp_path / "published_run"
    publish_bundle(run_dir, outcome.files)  # type: ignore[attr-defined]
    return run_dir


# Replay needs nothing beyond the bundle itself: the probe supplies no policy.
_REPLAY_PROBE = """
import sys

sys.path.insert(0, {repo!r})

from pathlib import Path

from greenmachine.ingestion.archive import bundle_reader
from greenmachine.ingestion.orchestration import replay_run

result = replay_run(bundle_reader(Path({run_dir!r})))
print(result.manifest_id)
print(result.source_capture_id.value)
print(result.recent_identical, result.long_term_identical)
"""


def test_replay_is_stable_across_hash_seeds_and_timezones(tmp_path: Path) -> None:
    """Fresh interpreters under different PYTHONHASHSEED and TZ settings agree."""
    run_dir = _published_run(tmp_path)
    program = _REPLAY_PROBE.format(repo=str(REPO_ROOT), run_dir=str(run_dir))

    transcripts: list[str] = []
    for hash_seed, timezone_name in (
        ("0", "UTC"),
        ("1", "America/Los_Angeles"),
        ("7", "Asia/Tokyo"),
        ("123", "UTC"),
        ("424242", "Australia/Eucla"),
    ):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = hash_seed
        environment["TZ"] = timezone_name
        completed = run_guarded_python("-c", program, env=environment, timeout=240)
        assert completed.returncode == 0, completed.stderr
        transcripts.append(completed.stdout)

    assert len(set(transcripts)) == 1, "replay diverged across hash seeds / timezones"
    assert "True True" in transcripts[0]


def test_the_runner_replays_a_published_run_offline(tmp_path: Path) -> None:
    """Runner replay: no network, no policy argument, nonzero exit on drift."""
    run_dir = _published_run(tmp_path)
    completed = run_guarded_python(
        str(RUNNER),
        "replay",
        "--run-dir",
        str(run_dir),
        cwd=tmp_path,  # cwd-independent
        timeout=240,
    )
    assert completed.returncode == 0, completed.stderr
    assert "replay OK" in completed.stdout
    replay_report = json.loads((run_dir / "reports" / "replay.json").read_bytes())
    assert replay_report["recent_snapshot_byte_identical"] is True
    assert replay_report["long_term_snapshot_byte_identical"] is True


def test_the_runner_replay_is_repeatable(tmp_path: Path) -> None:
    """First replay writes the report; a second succeeds byte-identically."""
    run_dir = _published_run(tmp_path)
    report_path = run_dir / "reports" / "replay.json"
    assert not report_path.exists()

    first = run_guarded_python(str(RUNNER), "replay", "--run-dir", str(run_dir), timeout=240)
    assert first.returncode == 0, first.stderr
    first_bytes = report_path.read_bytes()

    second = run_guarded_python(str(RUNNER), "replay", "--run-dir", str(run_dir), timeout=240)
    assert second.returncode == 0, second.stderr
    assert report_path.read_bytes() == first_bytes  # untouched, not rewritten


def test_a_conflicting_existing_report_fails_the_runner(tmp_path: Path) -> None:
    run_dir = _published_run(tmp_path)
    report_path = run_dir / "reports" / "replay.json"
    report_path.write_bytes(b'{"forged": true}')

    completed = run_guarded_python(str(RUNNER), "replay", "--run-dir", str(run_dir), timeout=240)
    assert completed.returncode != 0
    assert "different replay report" in completed.stderr
    assert report_path.read_bytes() == b'{"forged": true}'  # never overwritten


def test_the_shipped_evidence_replays_as_is_without_modification() -> None:
    """The documented command works on the shipped bundle exactly as shipped,
    and modifies nothing."""
    evidence = REPO_ROOT / "evidence" / "gm020_vertical_slice" / "prospective_run"
    before = {
        path.relative_to(evidence).as_posix(): path.read_bytes()
        for path in sorted(evidence.rglob("*"))
        if path.is_file()
    }
    assert "reports/replay.json" in before  # the report already exists

    completed = run_guarded_python(str(RUNNER), "replay", "--run-dir", str(evidence), timeout=240)
    assert completed.returncode == 0, completed.stderr
    assert "replay OK" in completed.stdout

    after = {
        path.relative_to(evidence).as_posix(): path.read_bytes()
        for path in sorted(evidence.rglob("*"))
        if path.is_file()
    }
    assert after == before  # no snapshot, raw file, manifest, or input changed


def test_the_runner_fails_replay_on_corruption(tmp_path: Path) -> None:
    run_dir = _published_run(tmp_path)
    target = run_dir / "raw" / "batter_events_long_term_2y.csv"
    corrupted = bytearray(target.read_bytes())
    corrupted[5] ^= 0x01
    target.write_bytes(bytes(corrupted))

    completed = run_guarded_python(
        str(RUNNER),
        "replay",
        "--run-dir",
        str(run_dir),
        cwd=tmp_path,
        timeout=240,
    )
    assert completed.returncode != 0
    assert "DigestMismatchError" in completed.stderr


def test_the_runner_replay_accepts_no_policy_argument(tmp_path: Path) -> None:
    """The self-contained contract is structural: no substitute can be supplied."""
    run_dir = _published_run(tmp_path)
    completed = run_guarded_python(
        str(RUNNER),
        "replay",
        "--run-dir",
        str(run_dir),
        "--sample-policy",
        str(tmp_path / "anything.json"),
        cwd=tmp_path,
        timeout=240,
    )
    assert completed.returncode != 0  # argparse rejects the unknown argument


def test_the_runner_requires_every_explicit_argument(tmp_path: Path) -> None:
    completed = run_guarded_python(str(RUNNER), "capture", cwd=tmp_path, timeout=240)
    assert completed.returncode != 0  # nothing is inferred or defaulted


def test_the_runner_rejects_a_malformed_sample_policy_before_any_capture(
    tmp_path: Path,
) -> None:
    bad_policy = tmp_path / "bad_policy.json"
    bad_policy.write_text('{"disclaimer": "x"}', encoding="utf-8")
    completed = run_guarded_python(
        str(RUNNER),
        "capture",
        "--slate-date",
        "2026-07-15",
        "--game-pk",
        str(fixtures.GAME_PK),
        "--batter-id",
        str(fixtures.BATTER_ID),
        "--output-dir",
        str(tmp_path / "never_written"),
        "--sample-policy",
        str(bad_policy),
        "--capture-mode",
        "retrospective",
        cwd=tmp_path,
        timeout=240,
    )
    assert completed.returncode != 0
    assert "SamplePolicyError" in completed.stderr
    # The policy failed validation before any capture: nothing was written.
    assert not (tmp_path / "never_written").exists()

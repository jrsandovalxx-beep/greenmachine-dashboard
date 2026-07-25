"""Hostile v1 semantic-contract tests: a well-formed lie is still rejected.

Every mutation here keeps the document **self-consistent** — the per-entry
``capture_id`` values and the overall ``manifest_id`` are recomputed after
the mutation with the real identity functions — so the only thing standing
between the lie and acceptance is the semantic contract itself.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from tests.fixtures.ingestion import synthetic_provider_fixtures as fixtures

from greenmachine.common.serialization import canonical_bytes
from greenmachine.ingestion.archive import bundle_reader, publish_bundle
from greenmachine.ingestion.capture import RetryPolicy
from greenmachine.ingestion.errors import ProviderResponseError
from greenmachine.ingestion.manifest import capture_entry_identity, manifest_identity
from greenmachine.ingestion.models import (
    AttemptOutcome,
    AttemptRecord,
    CaptureManifest,
    CaptureMode,
    CaptureProvider,
    ProviderRequest,
    RawCaptureEntry,
)
from greenmachine.ingestion.orchestration import VerticalSliceRequest, replay_run, run_capture

_JSON = dict[str, object]


def _published(tmp_path: Path) -> Path:
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
    run_dir = tmp_path / "run"
    publish_bundle(run_dir, outcome.files)  # type: ignore[attr-defined]
    return run_dir


def _entry_from_document(raw_entry: _JSON) -> RawCaptureEntry:
    """Reconstruct a RawCaptureEntry from its published document form."""

    def instant(value: object) -> datetime:
        assert isinstance(value, str)
        return datetime.fromisoformat(value)

    parameters_raw = raw_entry["parameters"]
    assert isinstance(parameters_raw, list)
    attempts_raw = raw_entry["attempts"]
    assert isinstance(attempts_raw, list)
    return RawCaptureEntry(
        request=ProviderRequest(
            label=str(raw_entry["label"]),
            provider=CaptureProvider(str(raw_entry["provider"])),
            endpoint=str(raw_entry["endpoint"]),
            parameters=tuple((str(pair[0]), str(pair[1])) for pair in parameters_raw),
        ),
        capture_mode=CaptureMode(str(raw_entry["capture_mode"])),
        retrieval_started_at=instant(raw_entry["retrieval_started_at"]),
        retrieval_completed_at=instant(raw_entry["retrieval_completed_at"]),
        http_status=int(str(raw_entry["http_status"])),
        content_type=(
            str(raw_entry["content_type"]) if raw_entry["content_type"] is not None else None
        ),
        byte_length=int(str(raw_entry["byte_length"])),
        sha256=str(raw_entry["sha256"]),
        schema_fingerprint=str(raw_entry["schema_fingerprint"]),
        required_field_contract_version=str(raw_entry["required_field_contract_version"]),
        attempts=tuple(
            AttemptRecord(
                index=int(str(attempt["index"])),
                started_at=instant(attempt["started_at"]),
                completed_at=instant(attempt["completed_at"]),
                outcome=AttemptOutcome(str(attempt["outcome"])),
                http_status=(
                    attempt["http_status"]
                    if isinstance(attempt["http_status"], int)
                    and not isinstance(attempt["http_status"], bool)
                    else None
                ),
                error_category=(
                    str(attempt["error_category"])
                    if attempt["error_category"] is not None
                    else None
                ),
            )
            for attempt in attempts_raw
        ),
        artifact_relative_path=str(raw_entry["artifact_relative_path"]),
        participates_in_snapshot=bool(raw_entry["participates_in_snapshot"]),
        error_category=(
            str(raw_entry["error_category"]) if raw_entry["error_category"] is not None else None
        ),
    )


def _reidentified_reader(run_dir: Path, mutate: Callable[[_JSON], None]) -> Callable[[str], bytes]:
    """Mutate the manifest document, then make the lie self-consistent:
    recompute every capture_id and the manifest_id with the real functions."""
    document = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    mutate(document)

    entries_raw = document["entries"]
    assert isinstance(entries_raw, list)
    # The best possible forgery keeps the document label-sorted, as the
    # manifest model requires.
    entries_raw.sort(key=lambda raw_entry: str(raw_entry["label"]))
    entries: list[RawCaptureEntry] = []
    for raw_entry in entries_raw:
        assert isinstance(raw_entry, dict)
        entry = _entry_from_document(raw_entry)
        raw_entry["capture_id"] = capture_entry_identity(entry)
        entries.append(entry)
    manifest = CaptureManifest(
        manifest_schema_version=int(str(document["manifest_schema_version"])),
        slate_date=date.fromisoformat(str(document["slate_date"])),
        game_id=str(document["game_id"]),
        batter_id=str(document["batter_id"]),
        capture_mode=CaptureMode(str(document["capture_mode"])),
        run_started_at=datetime.fromisoformat(str(document["run_started_at"])),
        run_completed_at=datetime.fromisoformat(str(document["run_completed_at"])),
        entries=tuple(entries),
    )
    document["manifest_id"] = manifest_identity(manifest)
    replaced = canonical_bytes(document)
    inner = bundle_reader(run_dir)

    def reader(relative_path: str) -> bytes:
        if relative_path == "manifest.json":
            return replaced
        return inner(relative_path)

    return reader


def _entry_named(document: _JSON, label: str) -> _JSON:
    entries = document["entries"]
    assert isinstance(entries, list)
    for entry in entries:
        assert isinstance(entry, dict)
        if entry["label"] == label:
            return entry
    raise AssertionError(f"no entry labeled {label}")


def _expect(run_dir: Path, mutate: Callable[[_JSON], None], match: str) -> None:
    with pytest.raises(ProviderResponseError, match=match):
        replay_run(_reidentified_reader(run_dir, mutate))


# --------------------------------------------------------------------------
# Hostile cases (each self-consistent after mutation)
# --------------------------------------------------------------------------


def test_a_nonnumeric_game_id_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        document["game_id"] = "not-a-gamepk"

    _expect(run_dir, mutate, "must be a decimal string")


def test_a_zero_or_negative_id_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def zero(document: _JSON) -> None:
        document["batter_id"] = "0"

    _expect(run_dir, zero, "positive canonical decimal")

    def negative(document: _JSON) -> None:
        document["game_id"] = "-5"

    _expect(run_dir, negative, "must be a decimal string")


def test_a_missing_required_label_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        entries = document["entries"]
        assert isinstance(entries, list)
        document["entries"] = [
            entry for entry in entries if entry["label"] != "pitcher_events_season"
        ]

    _expect(run_dir, mutate, "exactly the labels")


def test_an_extra_label_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        entries = document["entries"]
        assert isinstance(entries, list)
        extra = json.loads(json.dumps(_entry_named(document, "mlb_schedule")))
        extra["label"] = "extra_capture"
        extra["artifact_relative_path"] = "raw/extra_capture.json"
        entries.append(extra)

    _expect(run_dir, mutate, "exactly the labels")


def test_a_wrong_provider_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        _entry_named(document, "mlb_schedule")["provider"] = "baseball_savant"

    _expect(run_dir, mutate, "does not match the request GM-020 constructs")


def test_a_wrong_endpoint_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        _entry_named(document, "mlb_game_feed")["endpoint"] = "boxscore"

    _expect(run_dir, mutate, "does not match the request GM-020 constructs")


def test_an_altered_request_parameter_is_rejected(tmp_path: Path) -> None:
    """A self-consistent digest over false request metadata is worthless."""
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        parameters = _entry_named(document, "batter_events_recent_7d")["parameters"]
        assert isinstance(parameters, list)
        for pair in parameters:
            if pair[0] == "game_date_gt":
                pair[1] = "2020-01-01"  # claims a different window than declared

    _expect(run_dir, mutate, "does not match the request GM-020 constructs")


def test_an_entry_capture_mode_mismatch_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        _entry_named(document, "mlb_schedule")["capture_mode"] = "PROSPECTIVE"

    _expect(run_dir, mutate, "records capture mode")


def test_a_wrong_participation_flag_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def pitcher_participates(document: _JSON) -> None:
        _entry_named(document, "pitcher_events_season")["participates_in_snapshot"] = True

    _expect(run_dir, pitcher_participates, "participates_in_snapshot")

    def schedule_does_not(document: _JSON) -> None:
        _entry_named(document, "mlb_schedule")["participates_in_snapshot"] = False

    _expect(run_dir, schedule_does_not, "participates_in_snapshot")


def test_an_unsuccessful_final_attempt_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        attempts = _entry_named(document, "mlb_schedule")["attempts"]
        assert isinstance(attempts, list)
        attempts[-1]["outcome"] = "FATAL_HTTP_STATUS"

    _expect(run_dir, mutate, "must be SUCCESS")


def test_an_entry_attempt_timestamp_disagreement_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        entry = _entry_named(document, "mlb_schedule")
        moved = datetime.fromisoformat(str(entry["retrieval_completed_at"])) + timedelta(seconds=1)
        entry["retrieval_completed_at"] = moved.isoformat()

    _expect(run_dir, mutate, "disagrees with its successful final attempt completion")


def test_a_duplicate_artifact_path_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        schedule_path = _entry_named(document, "mlb_schedule")["artifact_relative_path"]
        _entry_named(document, "pitcher_events_season")["artifact_relative_path"] = schedule_path

    _expect(run_dir, mutate, "must be unique")


def test_a_false_pitcher_request_is_rejected_after_feed_resolution(tmp_path: Path) -> None:
    """The pitcher request must match the feed-resolved pitcher, not merely
    carry a self-consistent digest."""
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        parameters = _entry_named(document, "pitcher_events_season")["parameters"]
        assert isinstance(parameters, list)
        for pair in parameters:
            if pair[0] == "pitchers_lookup[]":
                pair[1] = "600010"  # not the feed-resolved expected pitcher

    _expect(run_dir, mutate, "feed-resolved expected pitcher")


def test_the_untouched_bundle_still_replays(tmp_path: Path) -> None:
    """Anti-vacuity: the strictness above does not break a legitimate run."""
    run_dir = _published(tmp_path)
    result = replay_run(bundle_reader(run_dir))
    assert result.byte_identical

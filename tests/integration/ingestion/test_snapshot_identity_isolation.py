"""Snapshot identity isolation: the audit-only pitcher capture cannot move it.

The coordinated snapshot ``as_of`` is the latest **participating** retrieval
completion, so nonparticipating timing and bytes are provably inert for both
hitter snapshots — while participating provenance remains honestly
behavior-affecting.
"""

from __future__ import annotations

from datetime import date

from tests.fixtures.ingestion import synthetic_provider_fixtures as fixtures

from greenmachine.domain import WindowProfile
from greenmachine.evaluation import serialize_record
from greenmachine.ingestion.capture import HttpResponse, RetryPolicy
from greenmachine.ingestion.errors import ProviderTransportError
from greenmachine.ingestion.models import CaptureMode
from greenmachine.ingestion.orchestration import (
    VerticalSliceRequest,
    coordinated_as_of,
    run_capture,
)

REQUEST = VerticalSliceRequest(
    slate_date=date(2026, 7, 15),
    game_pk=fixtures.GAME_PK,
    batter_id=fixtures.BATTER_ID,
    capture_mode=CaptureMode.PROSPECTIVE,
)
RETRY = RetryPolicy(timeout_seconds=10, max_attempts=3, backoff_seconds=(1, 2))


class _FlakyOnce:
    """Delegates to a FakeTransport, failing the first request whose URL
    contains ``flaky_marker`` — so that one capture retries and completes at a
    later recorded instant while its final bytes are unchanged."""

    def __init__(self, inner: fixtures.FakeTransport, flaky_marker: str) -> None:
        self._inner = inner
        self._marker = flaky_marker
        self._failed_once = False

    def request(self, url: str, timeout_seconds: int) -> HttpResponse:
        if self._marker in url and not self._failed_once:
            self._failed_once = True
            raise ProviderTransportError("synthetic transient failure for retry timing")
        return self._inner.request(url, timeout_seconds)


def _run(transport: object) -> object:
    return run_capture(
        REQUEST,
        transport=transport,  # type: ignore[arg-type]
        clock=fixtures.SteppingClock(),
        sleeper=fixtures.RecordingSleeper(),
        retry_policy=RETRY,
        sample_policy_bytes=fixtures.sample_policy_bytes(),
    )


def _snapshots(outcome: object) -> tuple[bytes, bytes]:
    return (
        serialize_record(outcome.recent.snapshot),  # type: ignore[attr-defined]
        serialize_record(outcome.long_term.snapshot),  # type: ignore[attr-defined]
    )


BASELINE = _run(fixtures.FakeTransport(routes=fixtures.default_routes()))
assert BASELINE.published  # type: ignore[attr-defined]


def test_nonparticipating_pitcher_timing_cannot_alter_snapshots() -> None:
    """A pitcher retry shifts its recorded instants (and run completion), yet
    both serialized snapshots, hashes, ids, and the SourceCaptureId hold."""
    delayed = _run(
        _FlakyOnce(
            fixtures.FakeTransport(routes=fixtures.default_routes()),
            flaky_marker=f"pitchers_lookup[]={fixtures.PITCHER_ID}",
        )
    )
    assert delayed.published  # type: ignore[attr-defined]

    baseline_pitcher = BASELINE.manifest.entry("pitcher_events_season")  # type: ignore[attr-defined]
    delayed_pitcher = delayed.manifest.entry("pitcher_events_season")  # type: ignore[attr-defined]
    assert baseline_pitcher.retrieval_completed_at != delayed_pitcher.retrieval_completed_at
    assert len(delayed_pitcher.attempts) == 2  # the retry really happened

    # Participating instants are untouched, so the coordinated as_of holds …
    assert coordinated_as_of(delayed.manifest) == coordinated_as_of(BASELINE.manifest)  # type: ignore[attr-defined]
    # … and nothing snapshot-identifying moves.
    assert delayed.source_capture_id == BASELINE.source_capture_id  # type: ignore[attr-defined]
    assert _snapshots(delayed) == _snapshots(BASELINE)
    for profile_attribute in ("recent", "long_term"):
        baseline_snapshot = getattr(BASELINE, profile_attribute).snapshot
        delayed_snapshot = getattr(delayed, profile_attribute).snapshot
        assert delayed_snapshot.snapshot_id == baseline_snapshot.snapshot_id
        assert delayed_snapshot.input_hash == baseline_snapshot.input_hash
    # The refreshed run is still a distinct operational record.
    assert delayed.manifest_id != BASELINE.manifest_id  # type: ignore[attr-defined]


def test_nonparticipating_pitcher_bytes_cannot_alter_snapshots() -> None:
    """Different pitcher bytes change that entry's digest/identity and the
    pitcher audit report — but neither hitter snapshot."""
    changed_rows = [*fixtures.default_pitcher_rows(), fixtures.pitcher_row(at_bat_number="9")]
    routes = [
        (
            f"pitchers_lookup[]={fixtures.PITCHER_ID}",
            fixtures.ok(fixtures.pitcher_csv(changed_rows), "text/csv"),
        )
    ] + [route for route in fixtures.default_routes() if "pitchers_lookup" not in route[0]]
    changed = _run(fixtures.FakeTransport(routes=routes))
    assert changed.published  # type: ignore[attr-defined]

    baseline_pitcher = BASELINE.manifest.entry("pitcher_events_season")  # type: ignore[attr-defined]
    changed_pitcher = changed.manifest.entry("pitcher_events_season")  # type: ignore[attr-defined]
    assert changed_pitcher.sha256 != baseline_pitcher.sha256  # raw digest moved

    from greenmachine.ingestion.manifest import capture_entry_identity

    assert capture_entry_identity(changed_pitcher) != capture_entry_identity(baseline_pitcher)
    assert changed.manifest_id != BASELINE.manifest_id  # type: ignore[attr-defined]
    assert (
        dict(changed.files)["reports/pitcher_ingredients.json"]  # type: ignore[attr-defined]
        != dict(BASELINE.files)["reports/pitcher_ingredients.json"]  # type: ignore[attr-defined]
    )

    # And yet: identical snapshots, identical SourceCaptureId.
    assert changed.source_capture_id == BASELINE.source_capture_id  # type: ignore[attr-defined]
    assert _snapshots(changed) == _snapshots(BASELINE)


def test_participating_retrieval_provenance_remains_behavior_affecting() -> None:
    """Delaying a participating capture (same bytes) honestly moves as_of —
    snapshot content and identity change while SourceCaptureId may hold."""
    delayed = _run(
        _FlakyOnce(
            fixtures.FakeTransport(routes=fixtures.default_routes()),
            flaky_marker="game_date_gt=2024-07-15",  # the long-term batter capture
        )
    )
    assert delayed.published  # type: ignore[attr-defined]

    # Bytes unchanged everywhere -> the SourceCaptureId legitimately holds …
    assert delayed.source_capture_id == BASELINE.source_capture_id  # type: ignore[attr-defined]
    # … but the coordinated as_of moved, so both snapshots change honestly.
    assert coordinated_as_of(delayed.manifest) != coordinated_as_of(BASELINE.manifest)  # type: ignore[attr-defined]
    assert _snapshots(delayed) != _snapshots(BASELINE)
    assert (
        delayed.recent.snapshot.snapshot_id  # type: ignore[attr-defined]
        != BASELINE.recent.snapshot.snapshot_id  # type: ignore[attr-defined]
    )


def test_every_observation_timestamp_is_at_or_before_the_coordinated_as_of() -> None:
    for profile_attribute in ("recent", "long_term"):
        snapshot = getattr(BASELINE, profile_attribute).snapshot
        as_of = snapshot.as_of
        assert as_of == coordinated_as_of(BASELINE.manifest)  # type: ignore[attr-defined]
        for observation in snapshot.present_observations:
            assert observation.source_as_of <= as_of
            assert observation.retrieved_at <= as_of
        for observation in snapshot.missing_observations:
            assert observation.as_of == as_of


def test_one_source_capture_id_remains_shared_across_both_profiles() -> None:
    recent = BASELINE.recent.snapshot  # type: ignore[attr-defined]
    long_term = BASELINE.long_term.snapshot  # type: ignore[attr-defined]
    assert recent.source_capture_id == long_term.source_capture_id
    assert recent.window_profile is WindowProfile.RECENT_7D
    assert long_term.window_profile is WindowProfile.LONG_TERM_2Y

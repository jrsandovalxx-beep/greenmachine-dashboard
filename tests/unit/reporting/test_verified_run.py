"""GM-041.5: the verified-run boundary between reporting and the composition root.

``load_verified_run`` is what lets the Streamlit composition root score a run
without ``reporting`` ever importing ``greenmachine.scoring``: reporting returns
the frozen domain snapshots it already deserialized, and the app decides what to
do with them.

The record is validated rather than trusted. A crossed run, a reused snapshot, or
a profile in the wrong field would silently score the wrong game, so each is
refused at construction.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from greenmachine.domain import WindowProfile
from greenmachine.reporting import (
    DashboardLoadError,
    RunHandle,
    VerifiedRun,
    discover_runs,
    load_dashboard,
    load_verified_run,
)
from greenmachine.reporting.dashboard_loader import bundle_reader

REPO_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_ROOT = REPO_ROOT / "evidence" / "gm020_vertical_slice"


def _handles() -> list[RunHandle]:
    return list(discover_runs(EVIDENCE_ROOT))


def _first() -> RunHandle:
    return _handles()[0]


# --------------------------------------------------------------------------
# What it returns
# --------------------------------------------------------------------------


@pytest.mark.parametrize("handle", _handles(), ids=lambda h: h.name)
def test_both_frozen_snapshots_are_returned_in_the_right_field(handle: RunHandle) -> None:
    run = load_verified_run(handle)

    assert run.recent_snapshot.window_profile is WindowProfile.RECENT_7D
    assert run.long_term_snapshot.window_profile is WindowProfile.LONG_TERM_2Y


@pytest.mark.parametrize("handle", _handles(), ids=lambda h: h.name)
def test_the_two_snapshots_are_genuinely_distinct_records(handle: RunHandle) -> None:
    run = load_verified_run(handle)

    assert run.recent_snapshot.snapshot_id != run.long_term_snapshot.snapshot_id
    assert run.recent_snapshot.input_hash != run.long_term_snapshot.input_hash
    # ...but they came from one capture operation.
    assert run.recent_snapshot.source_capture_id == run.long_term_snapshot.source_capture_id


@pytest.mark.parametrize("handle", _handles(), ids=lambda h: h.name)
def test_the_snapshots_agree_with_the_dashboard_header(handle: RunHandle) -> None:
    run = load_verified_run(handle)
    header = run.dashboard.header

    for snapshot in (run.recent_snapshot, run.long_term_snapshot):
        assert snapshot.batter.player_id.value == header.batter_id
        assert snapshot.game_context.game_id.value == header.game_id


@pytest.mark.parametrize("handle", _handles(), ids=lambda h: h.name)
def test_load_dashboard_remains_backward_compatible(handle: RunHandle) -> None:
    """Every pre-GM-041.5 caller keeps working, and gets the identical view."""
    assert load_dashboard(handle) == load_verified_run(handle).dashboard


def test_the_verified_run_is_frozen_and_slotted() -> None:
    run = load_verified_run(_first())

    assert dataclasses.is_dataclass(run)
    with pytest.raises(dataclasses.FrozenInstanceError):
        run.recent_snapshot = run.long_term_snapshot  # type: ignore[misc]
    assert not hasattr(run, "__dict__"), "slots=True keeps the record compact and closed"


def test_repeated_loads_produce_equal_records() -> None:
    """No clock, no randomness: the same bundle always yields the same record."""
    handle = _first()

    first = load_verified_run(handle)
    second = load_verified_run(handle)

    assert first.recent_snapshot == second.recent_snapshot
    assert first.long_term_snapshot == second.long_term_snapshot
    assert first.dashboard == second.dashboard


# --------------------------------------------------------------------------
# Exactly one verification pass
# --------------------------------------------------------------------------


def test_one_call_replays_the_bundle_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second replay would double the cost and could drift from the first."""
    from greenmachine.reporting import dashboard_loader

    calls: list[object] = []
    original = dashboard_loader.replay_run

    def counting_replay(reader: object) -> object:
        calls.append(reader)
        return original(reader)  # type: ignore[arg-type]

    monkeypatch.setattr(dashboard_loader, "replay_run", counting_replay)
    load_verified_run(_first())

    assert len(calls) == 1


def test_each_snapshot_is_deserialized_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from greenmachine.reporting import dashboard_loader

    seen: list[bytes] = []
    original = dashboard_loader.deserialize_snapshot

    def counting_deserialize(payload: bytes) -> object:
        seen.append(payload)
        return original(payload)

    monkeypatch.setattr(dashboard_loader, "deserialize_snapshot", counting_deserialize)
    load_verified_run(_first())

    assert len(seen) == 2
    assert len(set(seen)) == 2, "two distinct snapshot payloads, neither read twice"


# --------------------------------------------------------------------------
# Read-only, location-independent, fail-closed
# --------------------------------------------------------------------------


@pytest.mark.parametrize("handle", _handles(), ids=lambda h: h.name)
def test_loading_writes_nothing_into_the_bundle(handle: RunHandle) -> None:
    before = {
        path: path.stat().st_mtime_ns
        for path in sorted(handle.directory.rglob("*"))
        if path.is_file()
    }

    load_verified_run(handle)

    after = {
        path: path.stat().st_mtime_ns
        for path in sorted(handle.directory.rglob("*"))
        if path.is_file()
    }
    assert after == before


def test_loading_is_independent_of_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    handle = _first()
    baseline = load_verified_run(handle)

    monkeypatch.chdir(tmp_path)
    relocated = load_verified_run(handle)

    assert relocated.recent_snapshot == baseline.recent_snapshot
    assert relocated.long_term_snapshot == baseline.long_term_snapshot


def test_a_corrupted_bundle_fails_closed(tmp_path: Path) -> None:
    """A snapshot that no longer regenerates byte-identically is refused."""
    import shutil

    source = _first().directory
    corrupted = tmp_path / source.name
    shutil.copytree(source, corrupted)
    target = corrupted / "snapshots" / "input_snapshot_recent_7d.json"
    payload = target.read_bytes()
    target.write_bytes(payload.replace(b'"unit":"mph"', b'"unit":"MPH"', 1))

    with pytest.raises(DashboardLoadError):
        load_verified_run(RunHandle(name=corrupted.name, directory=corrupted))


# --------------------------------------------------------------------------
# The record refuses an incoherent construction
# --------------------------------------------------------------------------


def test_swapped_profiles_are_refused() -> None:
    run = load_verified_run(_first())

    with pytest.raises(DashboardLoadError, match="RECENT_7D"):
        VerifiedRun(
            dashboard=run.dashboard,
            recent_snapshot=run.long_term_snapshot,
            long_term_snapshot=run.long_term_snapshot,
        )


def test_a_reused_snapshot_is_refused() -> None:
    """One snapshot cannot fill both fields.

    The profile guard catches this first, which is the correct ordering: the
    wrong-profile message is more actionable than an identity one.
    """
    run = load_verified_run(_first())

    with pytest.raises(DashboardLoadError, match="LONG_TERM_2Y"):
        VerifiedRun(
            dashboard=run.dashboard,
            recent_snapshot=run.recent_snapshot,
            long_term_snapshot=run.recent_snapshot,
        )


def test_a_colliding_snapshot_identity_is_unconstructable_at_the_domain() -> None:
    """Why the identity guards on VerifiedRun are defence in depth.

    ``snapshot_id`` and ``input_hash`` are content-derived, and ``InputSnapshot``
    refuses direct construction, so two snapshots with the same id cannot be
    built through the domain at all. The guards stay because they are cheap and
    would catch a future loader bug that assembled a record another way — but
    this test records that they are unreachable today, rather than pretending a
    test exercises them.
    """
    import dataclasses as _dataclasses

    from greenmachine.domain import DomainValidationError

    run = load_verified_run(_first())

    with pytest.raises(DomainValidationError, match="content-derived"):
        _dataclasses.replace(run.long_term_snapshot, snapshot_id=run.recent_snapshot.snapshot_id)


def test_snapshots_from_a_different_run_are_refused() -> None:
    """The failure that would otherwise score the wrong game."""
    handles = _handles()
    if len(handles) < 2:  # pragma: no cover - both bundles ship in-repo
        pytest.skip("needs two approved bundles")
    first, second = load_verified_run(handles[0]), load_verified_run(handles[1])

    with pytest.raises(DashboardLoadError, match=r"batter|game"):
        VerifiedRun(
            dashboard=first.dashboard,
            recent_snapshot=second.recent_snapshot,
            long_term_snapshot=second.long_term_snapshot,
        )


def test_the_reader_helper_stays_available_for_the_loader() -> None:
    """Anti-vacuity: the bundle reader the verification path depends on exists."""
    reader = bundle_reader(_first().directory)

    assert reader("manifest.json")

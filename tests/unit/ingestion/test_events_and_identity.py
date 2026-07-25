"""Window enforcement, duplicates, game types, and deterministic identities."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from tests.fixtures.ingestion import synthetic_provider_fixtures as fixtures

from greenmachine.domain import WindowProfile
from greenmachine.ingestion.errors import (
    DigestMismatchError,
    IdentityMismatchError,
    ProviderResponseError,
)
from greenmachine.ingestion.events import normalize_batter_events
from greenmachine.ingestion.manifest import (
    capture_entry_identity,
    manifest_identity,
    source_capture_identity,
    verify_raw_bytes,
)
from greenmachine.ingestion.models import (
    AttemptOutcome,
    AttemptRecord,
    CaptureManifest,
    CaptureMode,
    CaptureProvider,
    ProviderRequest,
    RawCaptureEntry,
)
from greenmachine.ingestion.savant.parser import parse_batter_events

SLATE = date(2026, 7, 15)
RECENT_START = date(2026, 7, 8)


def normalize(rows_csv: list[dict[str, str]]) -> object:
    return normalize_batter_events(
        parse_batter_events(fixtures.batter_csv(rows_csv)),
        profile=WindowProfile.RECENT_7D,
        window_start=RECENT_START,
        window_end_exclusive=SLATE,
        selected_game_pk=fixtures.GAME_PK,
        expected_batter_id=fixtures.BATTER_ID,
    )


# --------------------------------------------------------------------------
# Windows, game types, duplicates
# --------------------------------------------------------------------------


def test_half_open_window_boundaries_are_exact() -> None:
    rows = [
        fixtures.batter_row(game_date="2026-07-07", at_bat_number="1"),  # start-1: out
        fixtures.batter_row(game_date="2026-07-08", at_bat_number="2"),  # start: in
        fixtures.batter_row(game_date="2026-07-14", at_bat_number="3"),  # end-1: in
        fixtures.batter_row(game_date="2026-07-15", at_bat_number="4"),  # slate: out
    ]
    normalized = normalize(rows)
    dates = sorted(row.game_date.isoformat() for row in normalized.rows)  # type: ignore[attr-defined]
    assert dates == ["2026-07-08", "2026-07-14"]
    assert normalized.report.excluded_outside_window == 2  # type: ignore[attr-defined]


def test_r_only_policy_counts_every_excluded_type() -> None:
    rows = [
        fixtures.batter_row(at_bat_number="1"),
        fixtures.batter_row(at_bat_number="2", game_type="S"),
        fixtures.batter_row(at_bat_number="3", game_type="E"),
        fixtures.batter_row(at_bat_number="4", game_type="S"),
        fixtures.batter_row(at_bat_number="5", game_type="X"),  # unknown: excluded too
        fixtures.batter_row(at_bat_number="6", game_type=""),  # missing: never treated as R
    ]
    normalized = normalize(rows)
    assert normalized.report.rows_eligible == 1  # type: ignore[attr-defined]
    assert normalized.report.excluded_by_game_type == (  # type: ignore[attr-defined]
        ("E", 1),
        ("S", 2),
        ("X", 1),
    )
    assert normalized.report.excluded_missing_game_type == 1  # type: ignore[attr-defined]


def test_the_selected_game_is_always_excluded() -> None:
    rows = [
        fixtures.batter_row(at_bat_number="1", game_pk=str(fixtures.GAME_PK)),
        fixtures.batter_row(at_bat_number="2"),
    ]
    normalized = normalize(rows)
    assert normalized.report.excluded_selected_game == 1  # type: ignore[attr-defined]
    assert all(row.game_pk != fixtures.GAME_PK for row in normalized.rows)  # type: ignore[attr-defined]


def test_exact_duplicates_collapse_and_are_counted() -> None:
    row = fixtures.batter_row()
    normalized = normalize([row, dict(row)])
    assert normalized.report.duplicates_collapsed == 1  # type: ignore[attr-defined]
    assert normalized.report.rows_eligible == 1  # type: ignore[attr-defined]


def test_conflicting_rows_under_one_event_key_fail_closed() -> None:
    first = fixtures.batter_row(launch_speed="100")
    second = fixtures.batter_row(launch_speed="90")
    with pytest.raises(ProviderResponseError, match="conflicting event rows"):
        normalize([first, second])


def test_output_ordering_is_deterministic_and_input_order_independent() -> None:
    rows = [
        fixtures.batter_row(at_bat_number="3", game_date="2026-07-12"),
        fixtures.batter_row(at_bat_number="1", game_date="2026-07-10"),
        fixtures.batter_row(at_bat_number="2", game_date="2026-07-11"),
    ]
    forward = normalize(rows)
    backward = normalize(list(reversed(rows)))
    assert forward.rows == backward.rows  # type: ignore[attr-defined]
    keys = [row.event_key for row in forward.rows]  # type: ignore[attr-defined]
    assert keys == sorted(keys)


def test_a_foreign_batter_row_is_an_identity_mismatch() -> None:
    with pytest.raises(IdentityMismatchError, match="identities must agree"):
        normalize([fixtures.batter_row(batter="123456")])


# --------------------------------------------------------------------------
# Deterministic identities (no UUIDs, no randomness, no paths, no OS time)
# --------------------------------------------------------------------------

_INSTANT = datetime(2026, 7, 15, 18, 0, tzinfo=UTC)


def _entry(label: str, sha: str, participates: bool, path: str = "raw/a.json") -> RawCaptureEntry:
    request = ProviderRequest(
        label=label,
        provider=CaptureProvider.MLB_STATS_API,
        endpoint="schedule",
        parameters=(("date", "2026-07-15"),),
    )
    attempt = AttemptRecord(
        index=1,
        started_at=_INSTANT,
        completed_at=_INSTANT,
        outcome=AttemptOutcome.SUCCESS,
        http_status=200,
        error_category=None,
    )
    return RawCaptureEntry(
        request=request,
        capture_mode=CaptureMode.RETROSPECTIVE_RECONSTRUCTION,
        retrieval_started_at=_INSTANT,
        retrieval_completed_at=_INSTANT,
        http_status=200,
        content_type="application/json",
        byte_length=4,
        sha256=sha,
        schema_fingerprint="fp",
        required_field_contract_version="v1",
        attempts=(attempt,),
        artifact_relative_path=path,
        participates_in_snapshot=participates,
    )


_SHA_A = "a" * 64
_SHA_B = "b" * 64


def _manifest(entries: tuple[RawCaptureEntry, ...]) -> CaptureManifest:
    return CaptureManifest(
        manifest_schema_version=1,
        slate_date=SLATE,
        game_id="999001",
        batter_id="500001",
        capture_mode=CaptureMode.RETROSPECTIVE_RECONSTRUCTION,
        run_started_at=_INSTANT,
        run_completed_at=_INSTANT,
        entries=entries,
    )


def test_request_and_manifest_identities_are_deterministic() -> None:
    manifest = _manifest((_entry("alpha", _SHA_A, True),))
    again = _manifest((_entry("alpha", _SHA_A, True),))
    assert capture_entry_identity(manifest.entries[0]) == capture_entry_identity(again.entries[0])
    assert manifest_identity(manifest) == manifest_identity(again)
    assert manifest_identity(manifest).startswith("capture_manifest-")


def test_source_capture_id_uses_only_participating_labels_and_digests() -> None:
    participating_only = _manifest((_entry("alpha", _SHA_A, True),))
    with_audit_extra = _manifest(
        (
            _entry("alpha", _SHA_A, True),
            _entry("beta", _SHA_B, False, path="raw/b.json"),  # non-participating
        )
    )
    assert source_capture_identity(participating_only) == source_capture_identity(with_audit_extra)


def test_a_changed_participating_digest_changes_the_source_capture_id() -> None:
    original = _manifest((_entry("alpha", _SHA_A, True),))
    refreshed = _manifest((_entry("alpha", _SHA_B, True),))
    assert source_capture_identity(original) != source_capture_identity(refreshed)


def test_a_byte_identical_refresh_may_retain_the_source_capture_id() -> None:
    later = datetime(2026, 7, 15, 19, 0, tzinfo=UTC)
    original = _manifest((_entry("alpha", _SHA_A, True),))
    refresh_entry = RawCaptureEntry(
        request=original.entries[0].request,
        capture_mode=CaptureMode.RETROSPECTIVE_RECONSTRUCTION,
        retrieval_started_at=later,
        retrieval_completed_at=later,
        http_status=200,
        content_type="application/json",
        byte_length=4,
        sha256=_SHA_A,
        schema_fingerprint="fp",
        required_field_contract_version="v1",
        attempts=(
            AttemptRecord(
                index=1,
                started_at=later,
                completed_at=later,
                outcome=AttemptOutcome.SUCCESS,
                http_status=200,
                error_category=None,
            ),
        ),
        artifact_relative_path="raw/a.json",
        participates_in_snapshot=True,
    )
    refresh = CaptureManifest(
        manifest_schema_version=1,
        slate_date=SLATE,
        game_id="999001",
        batter_id="500001",
        capture_mode=CaptureMode.RETROSPECTIVE_RECONSTRUCTION,
        run_started_at=later,
        run_completed_at=later,
        entries=(refresh_entry,),
    )
    # Same participating bytes: the SourceCaptureId may stay identical …
    assert source_capture_identity(original) == source_capture_identity(refresh)
    # … while the refresh remains a distinct immutable manifest.
    assert manifest_identity(original) != manifest_identity(refresh)


def test_paths_and_artifact_locations_do_not_influence_identity() -> None:
    at_one_path = _manifest((_entry("alpha", _SHA_A, True, path="raw/a.json"),))
    at_another = _manifest((_entry("alpha", _SHA_A, True, path="raw/moved.json"),))
    assert source_capture_identity(at_one_path) == source_capture_identity(at_another)
    assert capture_entry_identity(at_one_path.entries[0]) == capture_entry_identity(
        at_another.entries[0]
    )


def test_no_identity_contains_uuid_or_randomness() -> None:
    manifest = _manifest((_entry("alpha", _SHA_A, True),))
    first = (
        capture_entry_identity(manifest.entries[0]),
        manifest_identity(manifest),
        source_capture_identity(manifest).value,
    )
    second = (
        capture_entry_identity(manifest.entries[0]),
        manifest_identity(manifest),
        source_capture_identity(manifest).value,
    )
    assert first == second  # repeated derivation is bit-stable


def test_digest_verification_detects_one_byte_corruption() -> None:
    import hashlib

    body = b"synthetic raw bytes"
    entry = _entry("alpha", hashlib.sha256(body).hexdigest(), True)
    entry = RawCaptureEntry(
        request=entry.request,
        capture_mode=entry.capture_mode,
        retrieval_started_at=entry.retrieval_started_at,
        retrieval_completed_at=entry.retrieval_completed_at,
        http_status=entry.http_status,
        content_type=entry.content_type,
        byte_length=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        schema_fingerprint=entry.schema_fingerprint,
        required_field_contract_version=entry.required_field_contract_version,
        attempts=entry.attempts,
        artifact_relative_path=entry.artifact_relative_path,
        participates_in_snapshot=True,
    )
    verify_raw_bytes(entry, body)  # exact bytes pass
    corrupted = b"Synthetic raw bytes"  # one byte differs
    with pytest.raises(DigestMismatchError, match="not the captured bytes"):
        verify_raw_bytes(entry, corrupted)

"""GM-040 operator layer: selection validation and idempotent publication."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from greenmachine.ingestion.errors import CapturePublicationError, IngestionModelError
from greenmachine.ingestion.models import CaptureMode
from greenmachine.ingestion.operator import (
    LineupStatus,
    OperatorSelection,
    publish_or_verify,
)

SLATE = date(2026, 7, 25)


def _selection(**overrides: object) -> OperatorSelection:
    values: dict[str, object] = {
        "slate_date": SLATE,
        "game_pk": 823650,
        "batter_id": 665742,
        "lineup_status": LineupStatus.PROJECTED,
        "capture_mode": CaptureMode.PROSPECTIVE,
    }
    values.update(overrides)
    return OperatorSelection(**values)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Selection validation: nothing ambiguous is accepted
# --------------------------------------------------------------------------


def test_a_valid_selection_constructs() -> None:
    selection = _selection(expected_pitcher_id=680570, operator_note="dev check")
    assert selection.lineup_status is LineupStatus.PROJECTED
    assert selection.expected_pitcher_id == 680570


@pytest.mark.parametrize(
    ("field_name", "bad_value", "match"),
    [
        ("game_pk", 0, "game_pk must be positive"),
        ("game_pk", -5, "game_pk must be positive"),
        ("batter_id", 0, "batter_id must be positive"),
        ("expected_pitcher_id", 0, "expected_pitcher_id must be positive"),
        ("lineup_status", "projected", "must be a LineupStatus"),
        ("operator_note", 7, "must be a string"),
    ],
)
def test_invalid_selections_fail_closed(field_name: str, bad_value: object, match: str) -> None:
    with pytest.raises(IngestionModelError, match=match):
        _selection(**{field_name: bad_value})


def test_lineup_status_vocabulary_is_exactly_projected_and_confirmed() -> None:
    assert {status.value for status in LineupStatus} == {"projected", "confirmed"}


# --------------------------------------------------------------------------
# Idempotent publication: publish, verify, conflict — never overwrite
# --------------------------------------------------------------------------

_PLAN: tuple[tuple[str, bytes], ...] = (
    ("manifest.json", b"{}"),
    ("raw/artifact.csv", b"a,b\n"),
    ("OPERATOR_REPORT.md", b"# report\n"),
)


def test_first_publication_publishes(tmp_path: Path) -> None:
    target = tmp_path / "run"
    assert publish_or_verify(target, _PLAN) == "published"
    assert (target / "raw" / "artifact.csv").read_bytes() == b"a,b\n"


def test_an_identical_plan_verifies_without_writing(tmp_path: Path) -> None:
    target = tmp_path / "run"
    publish_or_verify(target, _PLAN)
    before = {path: path.read_bytes() for path in sorted(target.rglob("*")) if path.is_file()}
    assert publish_or_verify(target, _PLAN) == "verified-existing"
    after = {path: path.read_bytes() for path in sorted(target.rglob("*")) if path.is_file()}
    assert after == before  # byte-for-byte untouched


def test_a_later_replay_report_does_not_break_verification(tmp_path: Path) -> None:
    target = tmp_path / "run"
    publish_or_verify(target, _PLAN)
    (target / "reports").mkdir()
    (target / "reports" / "replay.json").write_bytes(b'{"ok": true}')
    assert publish_or_verify(target, _PLAN) == "verified-existing"


def test_a_content_conflict_fails_explicitly_and_overwrites_nothing(tmp_path: Path) -> None:
    target = tmp_path / "run"
    publish_or_verify(target, _PLAN)
    conflicting = (
        ("manifest.json", b"{}"),
        ("raw/artifact.csv", b"a,b,c\n"),  # different participating bytes
        ("OPERATOR_REPORT.md", b"# report\n"),
    )
    with pytest.raises(CapturePublicationError, match="conflicting content"):
        publish_or_verify(target, conflicting)
    assert (target / "raw" / "artifact.csv").read_bytes() == b"a,b\n"  # original intact


def test_an_unexpected_extra_file_is_a_conflict(tmp_path: Path) -> None:
    target = tmp_path / "run"
    publish_or_verify(target, _PLAN)
    (target / "stray.txt").write_bytes(b"tampering")
    with pytest.raises(CapturePublicationError, match="conflicting content"):
        publish_or_verify(target, _PLAN)


def test_a_missing_file_is_a_conflict(tmp_path: Path) -> None:
    target = tmp_path / "run"
    publish_or_verify(target, _PLAN)
    (target / "OPERATOR_REPORT.md").unlink()
    with pytest.raises(CapturePublicationError, match="conflicting content"):
        publish_or_verify(target, _PLAN)

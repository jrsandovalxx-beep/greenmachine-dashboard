"""Event-set normalization: identity checks, duplicates, game types, windows.

The provider request already narrows dates and asks for regular-season rows,
but nothing here trusts that: identity, the R-only game-type policy, the
selected-game exclusion, and the exact half-open window
(``window_start <= game_date < slate_date``) are all re-enforced locally, with
every exclusion counted in the :class:`~greenmachine.ingestion.models.EventWindowReport`.

Duplicate handling follows the verified Statcast event key
``(game_pk, at_bat_number, pitch_number)``: byte-identical duplicate rows are
collapsed deterministically and counted; conflicting rows under one key fail
closed. Output ordering is deterministic — sorted by event key — never
filesystem, hash, or arrival order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from greenmachine.common.errors import ErrorContext
from greenmachine.domain import WindowProfile

from .errors import IdentityMismatchError, ProviderResponseError
from .models import BatterEventRecord, EventWindowReport, PitcherEventRecord

__all__ = [
    "EligibleBatterEvents",
    "EligiblePitcherEvents",
    "normalize_batter_events",
    "normalize_pitcher_events",
]

ELIGIBLE_GAME_TYPE = "R"


@dataclass(frozen=True, slots=True)
class EligibleBatterEvents:
    """The eligible, deduplicated, window-enforced batter rows plus their report."""

    rows: tuple[BatterEventRecord, ...]
    report: EventWindowReport


@dataclass(frozen=True, slots=True)
class EligiblePitcherEvents:
    """The eligible pitcher rows (audit ingredients) plus their report."""

    rows: tuple[PitcherEventRecord, ...]
    report: EventWindowReport


def _collapse_duplicates(
    rows: tuple[BatterEventRecord, ...] | tuple[PitcherEventRecord, ...],
) -> tuple[list[BatterEventRecord | PitcherEventRecord], int]:
    by_key: dict[tuple[int, int, int], BatterEventRecord | PitcherEventRecord] = {}
    collapsed = 0
    for row in rows:
        key = row.event_key
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = row
        elif existing == row:
            collapsed += 1
        else:
            raise ProviderResponseError(
                f"conflicting event rows share the key (game_pk={key[0]}, "
                f"at_bat_number={key[1]}, pitch_number={key[2]}); the response is "
                f"internally inconsistent",
                ErrorContext(provider="baseball_savant", subject=str(key[0])),
            )
    ordered = [by_key[key] for key in sorted(by_key)]
    return ordered, collapsed


def _window_filter(
    rows: list[BatterEventRecord | PitcherEventRecord],
    *,
    window_start: date,
    window_end_exclusive: date,
    selected_game_pk: int,
) -> tuple[list[BatterEventRecord | PitcherEventRecord], dict[str, int], list[tuple[str, int]]]:
    excluded_by_type: dict[str, int] = {}
    counters = {
        "missing_game_type": 0,
        "selected_game": 0,
        "outside_window": 0,
    }
    eligible: list[BatterEventRecord | PitcherEventRecord] = []
    for row in rows:
        if row.game_type is None:
            # Never silently treated as regular season.
            counters["missing_game_type"] += 1
            continue
        if row.game_type != ELIGIBLE_GAME_TYPE:
            excluded_by_type[row.game_type] = excluded_by_type.get(row.game_type, 0) + 1
            continue
        if row.game_pk == selected_game_pk:
            counters["selected_game"] += 1
            continue
        if not window_start <= row.game_date < window_end_exclusive:
            counters["outside_window"] += 1
            continue
        eligible.append(row)
    return eligible, counters, sorted(excluded_by_type.items())


def normalize_batter_events(
    rows: tuple[BatterEventRecord, ...],
    *,
    profile: WindowProfile,
    window_start: date,
    window_end_exclusive: date,
    selected_game_pk: int,
    expected_batter_id: int,
) -> EligibleBatterEvents:
    """Enforce identity, uniqueness, game type, and the exact half-open window."""
    for row in rows:
        if row.batter_id != expected_batter_id:
            raise IdentityMismatchError(
                f"Savant returned a row for batter {row.batter_id}, but batter "
                f"{expected_batter_id} was requested; identities must agree exactly",
                ErrorContext(provider="baseball_savant", subject=str(expected_batter_id)),
            )
    deduped, collapsed = _collapse_duplicates(rows)
    eligible, counters, by_type = _window_filter(
        deduped,
        window_start=window_start,
        window_end_exclusive=window_end_exclusive,
        selected_game_pk=selected_game_pk,
    )
    report = EventWindowReport(
        profile=profile,
        window_start=window_start,
        window_end_exclusive=window_end_exclusive,
        rows_received=len(rows),
        duplicates_collapsed=collapsed,
        excluded_by_game_type=tuple(by_type),
        excluded_missing_game_type=counters["missing_game_type"],
        excluded_outside_window=counters["outside_window"],
        excluded_selected_game=counters["selected_game"],
        rows_eligible=len(eligible),
    )
    batter_rows = tuple(row for row in eligible if isinstance(row, BatterEventRecord))
    return EligibleBatterEvents(rows=batter_rows, report=report)


def normalize_pitcher_events(
    rows: tuple[PitcherEventRecord, ...],
    *,
    profile: WindowProfile,
    window_start: date,
    window_end_exclusive: date,
    selected_game_pk: int,
    expected_pitcher_id: int,
) -> EligiblePitcherEvents:
    """The pitcher-side counterpart; audit ingredients only in GM-020."""
    for row in rows:
        if row.pitcher_id != expected_pitcher_id:
            raise IdentityMismatchError(
                f"Savant returned a row for pitcher {row.pitcher_id}, but pitcher "
                f"{expected_pitcher_id} was requested; identities must agree exactly",
                ErrorContext(provider="baseball_savant", subject=str(expected_pitcher_id)),
            )
    deduped, collapsed = _collapse_duplicates(rows)
    eligible, counters, by_type = _window_filter(
        deduped,
        window_start=window_start,
        window_end_exclusive=window_end_exclusive,
        selected_game_pk=selected_game_pk,
    )
    report = EventWindowReport(
        profile=profile,
        window_start=window_start,
        window_end_exclusive=window_end_exclusive,
        rows_received=len(rows),
        duplicates_collapsed=collapsed,
        excluded_by_game_type=tuple(by_type),
        excluded_missing_game_type=counters["missing_game_type"],
        excluded_outside_window=counters["outside_window"],
        excluded_selected_game=counters["selected_game"],
        rows_eligible=len(eligible),
    )
    pitcher_rows = tuple(row for row in eligible if isinstance(row, PitcherEventRecord))
    return EligiblePitcherEvents(rows=pitcher_rows, report=report)

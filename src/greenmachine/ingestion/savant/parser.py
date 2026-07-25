"""Strict Baseball Savant CSV parsing: required headers, Decimal-only numerics.

Fail-closed policy: a missing required header, an unparseable required value,
or malformed CSV raises :class:`~greenmachine.ingestion.errors.SchemaDriftError`.
Additive unknown columns are accepted and land in the deterministic header
fingerprint so drift stays visible. Zero data rows with valid headers parse
successfully into an empty tuple — a genuinely different thing from parser
failure.

Every numeric field becomes a ``Decimal`` built from the provider's own string
(never through ``float``); an empty or ``null`` cell becomes ``None``, never
zero. Provider column names stop at this module: what leaves is the neutral
``BatterEventRecord`` / ``PitcherEventRecord``.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

from greenmachine.common.errors import ErrorContext
from greenmachine.common.ids import content_digest

from ..errors import SchemaDriftError
from ..models import BatterEventRecord, PitcherEventRecord

__all__ = [
    "BATTER_EVENTS_CONTRACT_VERSION",
    "PITCHER_EVENTS_CONTRACT_VERSION",
    "header_fingerprint_of",
    "parse_batter_events",
    "parse_pitcher_events",
]

BATTER_EVENTS_CONTRACT_VERSION = "savant-batter-events-1"
PITCHER_EVENTS_CONTRACT_VERSION = "savant-pitcher-events-1"

_PROVIDER = "baseball_savant"

_BATTER_REQUIRED_COLUMNS = (
    "game_pk",
    "game_date",
    "game_type",
    "at_bat_number",
    "pitch_number",
    "batter",
    "pitcher",
    "stand",
    "bb_type",
    "launch_speed",
    "launch_angle",
    "launch_speed_angle",
    "bat_speed",
    "attack_angle",
    "hc_x",
    "hc_y",
)

_PITCHER_REQUIRED_COLUMNS = (
    "game_pk",
    "game_date",
    "game_type",
    "at_bat_number",
    "pitch_number",
    "pitcher",
    "stand",
    "pitch_type",
    "strikes",
    "description",
    "events",
)

_NULL_CELLS = frozenset({"", "null", "NULL", "NA", "N/A"})


def _drift(
    message: str, *, column: str | None = None, observed: str | None = None
) -> SchemaDriftError:
    return SchemaDriftError(
        message,
        ErrorContext(
            provider=_PROVIDER,
            key_path=(column,) if column else (),
            observed=observed,
        ),
    )


def _rows_of(raw: bytes, required: tuple[str, ...]) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _drift("Savant CSV response is not UTF-8") from exc

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise _drift("Savant CSV response is empty (no header row)") from None
    except csv.Error as exc:
        raise _drift(f"Savant CSV header is malformed: {exc}") from exc

    header_tuple = tuple(header)
    missing = sorted(set(required) - set(header_tuple))
    if missing:
        raise _drift(
            f"Savant CSV is missing required column(s): {missing}",
            observed=",".join(sorted(header_tuple)[:20]),
        )
    if len(set(header_tuple)) != len(header_tuple):
        raise _drift("Savant CSV header contains duplicate column names")

    index_of = {name: index for index, name in enumerate(header_tuple)}
    rows: list[dict[str, str]] = []
    try:
        for line_number, cells in enumerate(reader, start=2):
            if not cells:
                continue
            if len(cells) != len(header_tuple):
                raise _drift(
                    f"Savant CSV row at line {line_number} has {len(cells)} cells, "
                    f"expected {len(header_tuple)}"
                )
            rows.append({name: cells[index_of[name]] for name in required})
    except csv.Error as exc:
        raise _drift(f"Savant CSV body is malformed: {exc}") from exc
    return header_tuple, rows


def header_fingerprint_of(raw: bytes) -> str:
    """Deterministic fingerprint of the observed header set (order-independent)."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _drift("Savant CSV response is not UTF-8") from exc
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise _drift("Savant CSV response is empty (no header row)") from None
    except csv.Error as exc:
        raise _drift(f"Savant CSV header is malformed: {exc}") from exc
    return content_digest(sorted(header))


def _cell(row: dict[str, str], column: str) -> str | None:
    value = row[column].strip()
    if value in _NULL_CELLS:
        return None
    return value


def _required_int(row: dict[str, str], column: str, line: int) -> int:
    value = _cell(row, column)
    if value is None:
        raise _drift(
            f"Savant CSV required column '{column}' is empty at data row {line}",
            column=column,
        )
    try:
        return int(value)
    except ValueError as exc:
        raise _drift(
            f"Savant CSV column '{column}' is not an integer at data row {line}",
            column=column,
            observed=value,
        ) from exc


def _required_date(row: dict[str, str], column: str, line: int) -> date:
    value = _cell(row, column)
    if value is None:
        raise _drift(
            f"Savant CSV required column '{column}' is empty at data row {line}",
            column=column,
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _drift(
            f"Savant CSV column '{column}' is not an ISO date at data row {line}",
            column=column,
            observed=value,
        ) from exc


def _optional_decimal(row: dict[str, str], column: str, line: int) -> Decimal | None:
    value = _cell(row, column)
    if value is None:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise _drift(
            f"Savant CSV column '{column}' is not a decimal number at data row {line}",
            column=column,
            observed=value,
        ) from exc
    if not parsed.is_finite():
        raise _drift(
            f"Savant CSV column '{column}' is not finite at data row {line}",
            column=column,
            observed=value,
        )
    return parsed


def _optional_int(row: dict[str, str], column: str, line: int) -> int | None:
    value = _cell(row, column)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise _drift(
            f"Savant CSV column '{column}' is not an integer at data row {line}",
            column=column,
            observed=value,
        ) from exc


def parse_batter_events(raw: bytes) -> tuple[BatterEventRecord, ...]:
    """Parse batter pitch-level rows strictly; zero rows is a valid empty result."""
    _, rows = _rows_of(raw, _BATTER_REQUIRED_COLUMNS)
    records: list[BatterEventRecord] = []
    for offset, row in enumerate(rows):
        line = offset + 2
        records.append(
            BatterEventRecord(
                game_pk=_required_int(row, "game_pk", line),
                at_bat_number=_required_int(row, "at_bat_number", line),
                pitch_number=_required_int(row, "pitch_number", line),
                game_date=_required_date(row, "game_date", line),
                game_type=_cell(row, "game_type"),
                batter_id=_required_int(row, "batter", line),
                pitcher_id=_required_int(row, "pitcher", line),
                stand=_cell(row, "stand"),
                bb_type=_cell(row, "bb_type"),
                launch_speed=_optional_decimal(row, "launch_speed", line),
                launch_angle=_optional_decimal(row, "launch_angle", line),
                launch_speed_angle=_cell(row, "launch_speed_angle"),
                bat_speed=_optional_decimal(row, "bat_speed", line),
                attack_angle=_optional_decimal(row, "attack_angle", line),
                hit_x=_optional_decimal(row, "hc_x", line),
                hit_y=_optional_decimal(row, "hc_y", line),
            )
        )
    return tuple(records)


def parse_pitcher_events(raw: bytes) -> tuple[PitcherEventRecord, ...]:
    """Parse pitcher pitch-level rows strictly; zero rows is a valid empty result."""
    _, rows = _rows_of(raw, _PITCHER_REQUIRED_COLUMNS)
    records: list[PitcherEventRecord] = []
    for offset, row in enumerate(rows):
        line = offset + 2
        records.append(
            PitcherEventRecord(
                game_pk=_required_int(row, "game_pk", line),
                at_bat_number=_required_int(row, "at_bat_number", line),
                pitch_number=_required_int(row, "pitch_number", line),
                game_date=_required_date(row, "game_date", line),
                game_type=_cell(row, "game_type"),
                pitcher_id=_required_int(row, "pitcher", line),
                stand=_cell(row, "stand"),
                pitch_type=_cell(row, "pitch_type"),
                strikes=_optional_int(row, "strikes", line),
                description=_cell(row, "description"),
                events=_cell(row, "events"),
            )
        )
    return tuple(records)

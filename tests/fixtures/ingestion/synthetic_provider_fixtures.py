"""Synthetic provider payloads for GM-020 ingestion tests.

Everything is visibly synthetic: fake ids (game 999001, teams 901/902, batter
500001, pitcher 600009, venue 9001), the fictional Synthetic Test Park, and
deliberately odd measurement values. No real player, game, venue, or provider
capture appears, and no value could be mistaken for a production threshold.

The builders produce byte payloads shaped exactly like the provider responses
the parsers contract for (plus additive unknown fields, which must be
accepted), and a route-based fake transport for end-to-end tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from greenmachine.ingestion.capture import HttpResponse
from greenmachine.ingestion.errors import ProviderTransportError
from greenmachine.ingestion.models import POLICY_COMPONENTS

SLATE_DATE = "2026-07-15"
GAME_PK = 999001
HOME_TEAM_ID = 901
AWAY_TEAM_ID = 902
VENUE_ID = 9001
VENUE_NAME = "Synthetic Test Park"
VENUE_TZ = "America/New_York"
BATTER_ID = 500001
BATTER_NAME = "Synthetic Batter One"
PITCHER_ID = 600009
PITCHER_NAME = "Synthetic Pitcher Nine"
GAME_START_UTC = "2026-07-15T23:10:00Z"

CAPTURE_INSTANT = datetime(2026, 7, 15, 18, 0, tzinfo=UTC)


class SteppingClock:
    """Deterministic clock advancing one second per read. Test-only."""

    def __init__(self, start: datetime = CAPTURE_INSTANT) -> None:
        self._current = start

    def now(self) -> datetime:
        value = self._current
        self._current = value + timedelta(seconds=1)
        return value


class RecordingSleeper:
    """Records requested delays; never actually sleeps."""

    def __init__(self) -> None:
        self.delays: list[int] = []

    def sleep(self, seconds: int) -> None:
        self.delays.append(seconds)


# --------------------------------------------------------------------------
# Sample-minimum policy bytes (validation-only, clearly synthetic)
# --------------------------------------------------------------------------


def sample_policy_document(recent: int = 2, long_term: int = 13) -> dict[str, object]:
    return {
        "disclaimer": (
            "Synthetic GM-020 test policy: validation only, arbitrary values, "
            "not a production model configuration."
        ),
        "minimums": {
            component.value: {"RECENT_7D": recent, "LONG_TERM_2Y": long_term}
            for component in POLICY_COMPONENTS
        },
    }


def sample_policy_bytes(recent: int = 2, long_term: int = 13) -> bytes:
    """Exact policy bytes accepted by the strict src loader."""
    return json.dumps(sample_policy_document(recent, long_term)).encode("utf-8")


# --------------------------------------------------------------------------
# MLB payloads
# --------------------------------------------------------------------------


def schedule_game(**overrides: object) -> dict[str, object]:
    game: dict[str, object] = {
        "gamePk": GAME_PK,
        "gameType": "R",
        "officialDate": SLATE_DATE,
        "gameDate": GAME_START_UTC,
        "status": {
            "abstractGameState": "Preview",
            "detailedState": "Scheduled",
            "codedGameState": "S",
        },
        "teams": {
            "home": {"team": {"id": HOME_TEAM_ID, "name": "Synthetic Home Nine"}},
            "away": {"team": {"id": AWAY_TEAM_ID, "name": "Synthetic Away Nine"}},
        },
        "venue": {"id": VENUE_ID, "name": VENUE_NAME},
        "syntheticExtraField": "additive-unknown-accepted",
    }
    game.update(overrides)
    return game


def schedule_json(games: list[dict[str, object]] | None = None) -> bytes:
    payload = {
        "totalGames": 1 if games is None else len(games),
        "dates": [
            {
                "date": SLATE_DATE,
                "games": [schedule_game()] if games is None else games,
            }
        ],
    }
    return json.dumps(payload).encode("utf-8")


def feed_json(**overrides: object) -> bytes:
    document: dict[str, object] = {
        "gamePk": GAME_PK,
        "gameData": {
            "datetime": {"dateTime": GAME_START_UTC, "officialDate": SLATE_DATE},
            "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},
            "teams": {"home": {"id": HOME_TEAM_ID}, "away": {"id": AWAY_TEAM_ID}},
            "venue": {
                "id": VENUE_ID,
                "name": VENUE_NAME,
                "timeZone": {"id": VENUE_TZ, "offset": -4},
            },
            "players": {
                f"ID{BATTER_ID}": {"id": BATTER_ID, "fullName": BATTER_NAME},
                f"ID{PITCHER_ID}": {"id": PITCHER_ID, "fullName": PITCHER_NAME},
            },
            "probablePitchers": {
                "away": {"id": PITCHER_ID, "fullName": PITCHER_NAME},
            },
        },
        "liveData": {
            "boxscore": {
                "teams": {
                    # Real MLB boxscore teams carry "players" (verified against
                    # the live v1.1 feed during the GM-020 prospective capture).
                    "home": {"players": {f"ID{BATTER_ID}": {}}},
                    "away": {"players": {f"ID{PITCHER_ID}": {}}},
                }
            }
        },
    }
    _deep_update(document, overrides)
    return json.dumps(document).encode("utf-8")


def _deep_update(target: dict[str, object], overrides: dict[str, object]) -> None:
    for key, value in overrides.items():
        existing = target.get(key)
        if isinstance(value, dict) and isinstance(existing, dict):
            _deep_update(existing, value)
        else:
            target[key] = value


# --------------------------------------------------------------------------
# Savant CSV payloads
# --------------------------------------------------------------------------

BATTER_COLUMNS = (
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
    "synthetic_extra_column",
)

PITCHER_COLUMNS = (
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
    "synthetic_extra_column",
)


def batter_row(**overrides: str) -> dict[str, str]:
    row = {
        "game_pk": "888001",
        "game_date": "2026-07-10",
        "game_type": "R",
        "at_bat_number": "1",
        "pitch_number": "1",
        "batter": str(BATTER_ID),
        "pitcher": "700100",
        "stand": "R",
        "bb_type": "fly_ball",
        "launch_speed": "101.3",
        "launch_angle": "24.5",
        "launch_speed_angle": "6",
        "bat_speed": "73.1",
        "attack_angle": "12.4",
        "hc_x": "95.0",
        "hc_y": "60.0",
        "synthetic_extra_column": "ignored",
    }
    row.update(overrides)
    return row


def pitcher_row(**overrides: str) -> dict[str, str]:
    row = {
        "game_pk": "888002",
        "game_date": "2026-06-20",
        "game_type": "R",
        "at_bat_number": "1",
        "pitch_number": "1",
        "pitcher": str(PITCHER_ID),
        "stand": "R",
        "pitch_type": "FF",
        "strikes": "0",
        "description": "called_strike",
        "events": "",
        "synthetic_extra_column": "ignored",
    }
    row.update(overrides)
    return row


def _csv_bytes(columns: tuple[str, ...], rows: list[dict[str, str]]) -> bytes:
    lines = [",".join(columns)]
    for row in rows:
        lines.append(",".join(row.get(column, "") for column in columns))
    return ("\n".join(lines) + "\n").encode("utf-8")


def batter_csv(rows: list[dict[str, str]]) -> bytes:
    return _csv_bytes(BATTER_COLUMNS, rows)


def pitcher_csv(rows: list[dict[str, str]]) -> bytes:
    return _csv_bytes(PITCHER_COLUMNS, rows)


def default_recent_rows() -> list[dict[str, str]]:
    """A small, boundary-rich recent window (2026-07-08 .. 2026-07-14)."""
    return [
        # Pulled fly ball by a right-handed stand (pull side = left field).
        batter_row(at_bat_number="1", pitch_number="3"),
        # Line drive, left-handed stand, opposite field (not pulled).
        batter_row(
            at_bat_number="2",
            pitch_number="2",
            game_date="2026-07-11",
            stand="L",
            bb_type="line_drive",
            launch_speed="94.999",
            launch_angle="8",
            launch_speed_angle="4",
            bat_speed="70.5",
            attack_angle="5",
            hc_x="90.0",
            hc_y="120.0",
        ),
        # Ground ball (outside every air denominator), hard-hit boundary at 95.
        batter_row(
            at_bat_number="3",
            pitch_number="4",
            game_date="2026-07-12",
            bb_type="ground_ball",
            launch_speed="95",
            launch_angle="-12.5",
            launch_speed_angle="3",
            bat_speed="",
            attack_angle="",
            hc_x="110.0",
            hc_y="150.0",
        ),
        # Popup: in the fly+line+popup alternative only. Sweet-spot upper bound.
        batter_row(
            at_bat_number="4",
            pitch_number="1",
            game_date="2026-07-12",
            bb_type="popup",
            launch_speed="82.2",
            launch_angle="32",
            launch_speed_angle="2",
            bat_speed="",
            attack_angle="20",
            hc_x="120.0",
            hc_y="170.0",
        ),
        # Swinging strike: no BBE, but tracked bat speed and attack angle.
        batter_row(
            at_bat_number="5",
            pitch_number="2",
            game_date="2026-07-13",
            bb_type="",
            launch_speed="",
            launch_angle="",
            launch_speed_angle="",
            bat_speed="74.4",
            attack_angle="21",
            hc_x="",
            hc_y="",
        ),
        # Fly ball with a missing stand: excluded from pull, counted.
        batter_row(
            at_bat_number="6",
            pitch_number="5",
            game_date="2026-07-13",
            stand="",
            launch_speed="99.1",
            launch_angle="30",
            launch_speed_angle="5",
            bat_speed="",
            attack_angle="",
            hc_x="100.0",
            hc_y="80.0",
        ),
        # Fly ball with unusable coordinates: excluded from pull, counted.
        batter_row(
            at_bat_number="7",
            pitch_number="1",
            game_date="2026-07-14",
            launch_speed="97.6",
            launch_angle="28",
            launch_speed_angle="5",
            bat_speed="72.0",
            attack_angle="13",
            hc_x="",
            hc_y="",
        ),
        # Spring-training row: excluded by the R-only policy, counted by type.
        batter_row(
            at_bat_number="8",
            pitch_number="1",
            game_date="2026-07-09",
            game_type="S",
        ),
        # Missing game_type: excluded and counted, never treated as R.
        batter_row(
            at_bat_number="9",
            pitch_number="1",
            game_date="2026-07-09",
            game_type="",
        ),
        # On the slate date itself: outside the half-open window.
        batter_row(at_bat_number="10", pitch_number="1", game_date="2026-07-15", game_pk="888009"),
        # Before the recent window start: outside.
        batter_row(at_bat_number="11", pitch_number="1", game_date="2026-07-07", game_pk="888010"),
        # A row claiming the selected game: excluded explicitly.
        batter_row(
            at_bat_number="12",
            pitch_number="1",
            game_date="2026-07-14",
            game_pk=str(GAME_PK),
        ),
        # An exact duplicate of the first row: collapsed and counted.
        batter_row(at_bat_number="1", pitch_number="3"),
    ]


def default_long_term_rows() -> list[dict[str, str]]:
    """Long-term rows including the recent ones plus older boundary rows."""
    rows = default_recent_rows()
    rows.extend(
        [
            # Exactly at the long-term window start (2024-07-15): included.
            batter_row(
                at_bat_number="1",
                pitch_number="1",
                game_date="2024-07-15",
                game_pk="777001",
                launch_speed="88.8",
                launch_angle="15",
                launch_speed_angle="4",
                bat_speed="",
                attack_angle="",
                hc_x="105.0",
                hc_y="100.0",
                bb_type="line_drive",
            ),
            # One day before the long-term window start: excluded.
            batter_row(
                at_bat_number="1",
                pitch_number="1",
                game_date="2024-07-14",
                game_pk="777000",
            ),
        ]
    )
    return rows


def default_pitcher_rows() -> list[dict[str, str]]:
    return [
        pitcher_row(at_bat_number="1", pitch_number="1", stand="R", pitch_type="FF"),
        pitcher_row(
            at_bat_number="1",
            pitch_number="2",
            stand="R",
            pitch_type="SL",
            strikes="2",
            description="swinging_strike",
            events="strikeout",
        ),
        pitcher_row(at_bat_number="2", pitch_number="1", stand="L", pitch_type="FF"),
        pitcher_row(at_bat_number="2", pitch_number="2", stand="L", pitch_type="CH", strikes="2"),
        pitcher_row(at_bat_number="3", pitch_number="1", stand="", pitch_type="FF"),
        pitcher_row(at_bat_number="3", pitch_number="2", stand="R", pitch_type=""),
    ]


# --------------------------------------------------------------------------
# Fake transport
# --------------------------------------------------------------------------


@dataclass
class FakeTransport:
    """Routes URLs to canned responses by substring; records every request."""

    routes: list[tuple[str, HttpResponse | ProviderTransportError]]
    requested_urls: list[str] = field(default_factory=list)

    def request(self, url: str, timeout_seconds: int) -> HttpResponse:
        self.requested_urls.append(url)
        for marker, outcome in self.routes:
            if marker in url:
                if isinstance(outcome, ProviderTransportError):
                    raise outcome
                return outcome
        raise ProviderTransportError(f"no fake route matches the requested URL: {url}")


def ok(body: bytes, content_type: str = "application/json") -> HttpResponse:
    return HttpResponse(status=200, headers=(("Content-Type", content_type),), body=body)


def default_routes() -> list[tuple[str, HttpResponse | ProviderTransportError]]:
    """The happy-path routing for one coordinated synthetic capture."""
    return [
        ("/api/v1/schedule", ok(schedule_json())),
        ("/feed/live", ok(feed_json())),
        (
            f"batters_lookup[]={BATTER_ID}&game_date_gt=2026-07-08",
            ok(batter_csv(default_recent_rows()), "text/csv"),
        ),
        (
            f"batters_lookup[]={BATTER_ID}&game_date_gt=2024-07-15",
            ok(batter_csv(default_long_term_rows()), "text/csv"),
        ),
        (
            f"pitchers_lookup[]={PITCHER_ID}",
            ok(pitcher_csv(default_pitcher_rows()), "text/csv"),
        ),
    ]

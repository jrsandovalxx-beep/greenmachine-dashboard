"""Strict MLB Stats API JSON parsing with endpoint schema contracts.

Fail-closed policy: a missing required field path, an incompatible required
type, or a malformed payload raises
:class:`~greenmachine.ingestion.errors.SchemaDriftError`. Additive unknown
fields are accepted — the live feed carries hundreds — and the observed shape
of the *selected structural paths* is captured in a deterministic fingerprint,
so drift in what this adapter actually relies on surfaces prominently without
hashing every incidental key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from greenmachine.common.errors import ErrorContext
from greenmachine.common.ids import content_digest
from greenmachine.domain import PitcherRole

from ..errors import IngestionEligibilityError, SchemaDriftError
from ..models import ExpectedPitcherRecord, GameRecord, SlateRecord

__all__ = [
    "FEED_CONTRACT_VERSION",
    "SCHEDULE_CONTRACT_VERSION",
    "GameFeedRecord",
    "feed_fingerprint_of",
    "parse_game_feed",
    "parse_schedule",
    "resolve_expected_pitcher",
    "schedule_fingerprint_of",
]

SCHEDULE_CONTRACT_VERSION = "mlb-schedule-1"
FEED_CONTRACT_VERSION = "mlb-game-feed-1"

_PROVIDER = "mlb_stats_api"

_T = TypeVar("_T")


def _drift(path: str, expected: str, observed: object) -> SchemaDriftError:
    return SchemaDriftError(
        f"MLB response field '{path}' does not match the schema contract",
        ErrorContext(
            provider=_PROVIDER,
            key_path=tuple(path.split(".")),
            expected=expected,
            observed=type(observed).__name__ if observed is not None else "missing",
        ),
    )


def _load_json(raw: bytes, what: str) -> dict[str, object]:
    try:
        parsed: object = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise SchemaDriftError(f"{what} is not UTF-8", ErrorContext(provider=_PROVIDER)) from exc
    except json.JSONDecodeError as exc:
        raise SchemaDriftError(
            f"{what} is not valid JSON (line {exc.lineno}, column {exc.colno})",
            ErrorContext(provider=_PROVIDER),
        ) from exc
    if not isinstance(parsed, dict):
        raise _drift(what, "object", parsed)
    return parsed


def _walk(mapping: dict[str, object], path: str) -> object:
    node: object = mapping
    walked: list[str] = []
    for part in path.split("."):
        walked.append(part)
        if not isinstance(node, dict) or part not in node:
            raise _drift(".".join(walked), "present", None)
        node = node[part]
    return node


def _required(mapping: dict[str, object], path: str, expected: type[_T]) -> _T:
    value = _walk(mapping, path)
    if expected is int and isinstance(value, bool):
        raise _drift(path, "int", value)
    if not isinstance(value, expected):
        raise _drift(path, expected.__name__, value)
    return value


def _optional_str(mapping: dict[str, object], path: str) -> str | None:
    try:
        value = _walk(mapping, path)
    except SchemaDriftError:
        return None
    if value is None:
        return None
    if not isinstance(value, str):
        raise _drift(path, "str", value)
    return value


def _utc_instant(text: str, path: str) -> datetime:
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SchemaDriftError(
            f"MLB field '{path}' is not an ISO-8601 instant",
            ErrorContext(provider=_PROVIDER, key_path=tuple(path.split("."))),
        ) from exc
    if moment.tzinfo is None:
        raise _drift(path, "timezone-aware instant", text)
    return moment.astimezone(UTC)


def _iso_date(text: str, path: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise SchemaDriftError(
            f"MLB field '{path}' is not an ISO-8601 date",
            ErrorContext(provider=_PROVIDER, key_path=tuple(path.split("."))),
        ) from exc


def _json_type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "number"  # floats: never *used*, but fingerprinted honestly


def _fingerprint(mapping: dict[str, object], paths: tuple[str, ...]) -> str:
    """Deterministic digest of the selected structural paths and observed types."""
    observed: list[tuple[str, str]] = []
    for path in sorted(paths):
        try:
            value = _walk(mapping, path)
        except SchemaDriftError:
            observed.append((path, "missing"))
            continue
        observed.append((path, _json_type_name(value)))
    return content_digest(observed)


# --------------------------------------------------------------------------
# Schedule
# --------------------------------------------------------------------------

_SCHEDULE_GAME_PATHS = (
    "gamePk",
    "gameType",
    "officialDate",
    "gameDate",
    "status.abstractGameState",
    "status.detailedState",
    "teams.home.team.id",
    "teams.away.team.id",
    "venue.id",
    "venue.name",
)


def schedule_fingerprint_of(raw: bytes) -> str:
    """Fingerprint the first scheduled game's selected paths (or the empty shape)."""
    document = _load_json(raw, "MLB schedule response")
    dates = _required(document, "dates", list)
    if not dates:
        return content_digest([("dates", "empty")])
    first_date = dates[0]
    if not isinstance(first_date, dict):
        raise _drift("dates[0]", "object", first_date)
    games = _required(first_date, "games", list)
    if not games:
        return content_digest([("dates.games", "empty")])
    first_game = games[0]
    if not isinstance(first_game, dict):
        raise _drift("dates[0].games[0]", "object", first_game)
    return _fingerprint(first_game, _SCHEDULE_GAME_PATHS)


def parse_schedule(raw: bytes, slate_date: date) -> SlateRecord:
    """Parse one day's schedule strictly into a provider-neutral slate record."""
    document = _load_json(raw, "MLB schedule response")
    dates = _required(document, "dates", list)

    games: list[GameRecord] = []
    for date_index, date_entry in enumerate(dates):
        if not isinstance(date_entry, dict):
            raise _drift(f"dates[{date_index}]", "object", date_entry)
        entry_date = _iso_date(_required(date_entry, "date", str), f"dates[{date_index}].date")
        if entry_date != slate_date:
            continue
        raw_games = _required(date_entry, "games", list)
        for game_index, game_entry in enumerate(raw_games):
            where = f"dates[{date_index}].games[{game_index}]"
            if not isinstance(game_entry, dict):
                raise _drift(where, "object", game_entry)
            games.append(
                GameRecord(
                    game_pk=_required(game_entry, "gamePk", int),
                    game_type=_required(game_entry, "gameType", str),
                    official_date=_iso_date(
                        _required(game_entry, "officialDate", str),
                        f"{where}.officialDate",
                    ),
                    scheduled_start_utc=_utc_instant(
                        _required(game_entry, "gameDate", str), f"{where}.gameDate"
                    ),
                    status_abstract=_required(game_entry, "status.abstractGameState", str),
                    status_detailed=_required(game_entry, "status.detailedState", str),
                    home_team_id=_required(game_entry, "teams.home.team.id", int),
                    away_team_id=_required(game_entry, "teams.away.team.id", int),
                    venue_id=_required(game_entry, "venue.id", int),
                    venue_name=_required(game_entry, "venue.name", str),
                )
            )
    return SlateRecord(slate_date=slate_date, games=tuple(games))


# --------------------------------------------------------------------------
# Live feed
# --------------------------------------------------------------------------

_FEED_PATHS = (
    "gamePk",
    "gameData.datetime.dateTime",
    "gameData.status.abstractGameState",
    "gameData.status.detailedState",
    "gameData.teams.home.id",
    "gameData.teams.away.id",
    "gameData.venue.id",
    "gameData.venue.name",
    "gameData.venue.timeZone.id",
    "gameData.probablePitchers",
    "gameData.players",
    "liveData.boxscore.teams.home.players",
    "liveData.boxscore.teams.away.players",
)


@dataclass(frozen=True, slots=True)
class GameFeedRecord:
    """The provider-neutral projection of one pregame live feed."""

    game_pk: int
    scheduled_start_utc: datetime
    status_abstract: str
    status_detailed: str
    home_team_id: int
    away_team_id: int
    venue_id: int
    venue_name: str
    venue_timezone: str
    home_roster_ids: tuple[int, ...]
    away_roster_ids: tuple[int, ...]
    player_names: tuple[tuple[int, str], ...]
    probable_home_id: int | None
    probable_home_name: str | None
    probable_home_note: str | None
    probable_away_id: int | None
    probable_away_name: str | None
    probable_away_note: str | None

    def player_name(self, person_id: int) -> str | None:
        for candidate_id, name in self.player_names:
            if candidate_id == person_id:
                return name
        return None


def feed_fingerprint_of(raw: bytes) -> str:
    document = _load_json(raw, "MLB game feed response")
    return _fingerprint(document, _FEED_PATHS)


def _roster_ids(document: dict[str, object], path: str) -> tuple[int, ...]:
    players = _required(document, path, dict)
    identities: list[int] = []
    for key in players:
        if not key.startswith("ID"):
            raise _drift(f"{path}.{key}", "IDnnnnn key", key)
        suffix = key[2:]
        if not suffix.isdigit():
            raise _drift(f"{path}.{key}", "IDnnnnn key", key)
        identities.append(int(suffix))
    return tuple(sorted(identities))


def _probable(document: dict[str, object], side: str) -> tuple[int | None, str | None, str | None]:
    pitchers = _required(document, "gameData.probablePitchers", dict)
    entry = pitchers.get(side)
    if entry is None:
        return (None, None, None)
    if not isinstance(entry, dict):
        raise _drift(f"gameData.probablePitchers.{side}", "object", entry)
    person_id = _required(entry, "id", int)
    full_name = _required(entry, "fullName", str)
    note = entry.get("note")
    if note is not None and not isinstance(note, str):
        raise _drift(f"gameData.probablePitchers.{side}.note", "str", note)
    return (person_id, full_name, note)


def parse_game_feed(raw: bytes) -> GameFeedRecord:
    """Parse a pregame live feed strictly into its provider-neutral projection."""
    document = _load_json(raw, "MLB game feed response")

    player_names: list[tuple[int, str]] = []
    players = _required(document, "gameData.players", dict)
    for key, entry in players.items():
        if not isinstance(entry, dict):
            raise _drift(f"gameData.players.{key}", "object", entry)
        person_id = _required(entry, "id", int)
        full_name = _required(entry, "fullName", str)
        player_names.append((person_id, full_name))
    player_names.sort()

    timezone_id = _required(document, "gameData.venue.timeZone.id", str)
    try:
        ZoneInfo(timezone_id)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise SchemaDriftError(
            f"MLB venue timezone '{timezone_id}' is not a valid IANA zone",
            ErrorContext(provider=_PROVIDER, key_path=("gameData", "venue", "timeZone", "id")),
        ) from exc

    home_probable = _probable(document, "home")
    away_probable = _probable(document, "away")

    return GameFeedRecord(
        game_pk=_required(document, "gamePk", int),
        scheduled_start_utc=_utc_instant(
            _required(document, "gameData.datetime.dateTime", str),
            "gameData.datetime.dateTime",
        ),
        status_abstract=_required(document, "gameData.status.abstractGameState", str),
        status_detailed=_required(document, "gameData.status.detailedState", str),
        home_team_id=_required(document, "gameData.teams.home.id", int),
        away_team_id=_required(document, "gameData.teams.away.id", int),
        venue_id=_required(document, "gameData.venue.id", int),
        venue_name=_required(document, "gameData.venue.name", str),
        venue_timezone=timezone_id,
        home_roster_ids=_roster_ids(document, "liveData.boxscore.teams.home.players"),
        away_roster_ids=_roster_ids(document, "liveData.boxscore.teams.away.players"),
        player_names=tuple(player_names),
        probable_home_id=home_probable[0],
        probable_home_name=home_probable[1],
        probable_home_note=home_probable[2],
        probable_away_id=away_probable[0],
        probable_away_name=away_probable[1],
        probable_away_note=away_probable[2],
    )


# --------------------------------------------------------------------------
# Expected-pitcher resolution (Product Owner ruling 4)
# --------------------------------------------------------------------------

_UNCERTAIN_MARKERS = ("tbd", "uncertain", "likely", "possible", "expected to")
_OPENER_MARKER = "opener"


def _role_from_note(note: str | None) -> PitcherRole:
    if note is None:
        return PitcherRole.EXPECTED_STARTER
    lowered = note.lower()
    if _OPENER_MARKER in lowered:
        return PitcherRole.OPENER
    if any(marker in lowered for marker in _UNCERTAIN_MARKERS):
        return PitcherRole.UNCERTAIN
    return PitcherRole.EXPECTED_STARTER


def resolve_expected_pitcher(feed: GameFeedRecord, batter_id: int) -> ExpectedPitcherRecord:
    """The expected opposing pitcher for the selected batter, or a focused failure.

    The batter's side comes from the pregame boxscore rosters; the opposing
    probable pitcher is MLB's assignment known at the capture instant. An
    announced opener maps to ``OPENER`` and an explicitly uncertain note to
    ``UNCERTAIN`` (deterministic marker words, documented in
    ``docs/GM_020_VERTICAL_SLICE.md``). No pitcher is ever invented: an absent
    probable raises :class:`IngestionEligibilityError` and no snapshot is
    published.
    """
    if batter_id in feed.home_roster_ids:
        batter_side = "home"
        pitcher_id = feed.probable_away_id
        pitcher_name = feed.probable_away_name
        note = feed.probable_away_note
    elif batter_id in feed.away_roster_ids:
        batter_side = "away"
        pitcher_id = feed.probable_home_id
        pitcher_name = feed.probable_home_name
        note = feed.probable_home_note
    else:
        raise IngestionEligibilityError(
            f"batter {batter_id} is on neither pregame roster of game {feed.game_pk}",
            ErrorContext(provider=_PROVIDER, subject=str(batter_id)),
        )

    if pitcher_id is None or pitcher_name is None:
        raise IngestionEligibilityError(
            f"game {feed.game_pk} has no identified expected opposing pitcher for the "
            f"selected batter; no snapshot can be published",
            ErrorContext(provider=_PROVIDER, subject=str(batter_id)),
        )

    return ExpectedPitcherRecord(
        game_pk=feed.game_pk,
        pitcher_id=pitcher_id,
        full_name=pitcher_name,
        role=_role_from_note(note),
        batter_team_side=batter_side,
        note=note,
    )

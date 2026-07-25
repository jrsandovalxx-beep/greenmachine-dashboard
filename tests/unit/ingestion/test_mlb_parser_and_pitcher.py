"""MLB JSON schema contracts and expected-pitcher resolution."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from tests.fixtures.ingestion import synthetic_provider_fixtures as fixtures

from greenmachine.domain import PitcherRole
from greenmachine.ingestion.errors import IngestionEligibilityError, SchemaDriftError
from greenmachine.ingestion.mlb.parser import (
    feed_fingerprint_of,
    parse_game_feed,
    parse_schedule,
    resolve_expected_pitcher,
    schedule_fingerprint_of,
)

SLATE = date(2026, 7, 15)


def test_a_valid_schedule_parses() -> None:
    slate = parse_schedule(fixtures.schedule_json(), SLATE)
    game = slate.game(fixtures.GAME_PK)
    assert game.game_type == "R"
    assert game.official_date == SLATE
    assert game.scheduled_start_utc == datetime(2026, 7, 15, 23, 10, tzinfo=UTC)
    assert game.venue_name == fixtures.VENUE_NAME
    assert (game.home_team_id, game.away_team_id) == (
        fixtures.HOME_TEAM_ID,
        fixtures.AWAY_TEAM_ID,
    )


def test_a_missing_required_schedule_field_fails_closed() -> None:
    game = fixtures.schedule_game()
    status = game["status"]
    assert isinstance(status, dict)
    del status["abstractGameState"]
    with pytest.raises(SchemaDriftError, match="abstractGameState"):
        parse_schedule(fixtures.schedule_json([game]), SLATE)


def test_a_required_type_change_fails_closed() -> None:
    game = fixtures.schedule_game(gamePk="999001")  # string where int is required
    with pytest.raises(SchemaDriftError, match="gamePk"):
        parse_schedule(fixtures.schedule_json([game]), SLATE)


def test_malformed_json_fails_closed() -> None:
    with pytest.raises(SchemaDriftError, match="not valid JSON"):
        parse_schedule(b'{"dates": [', SLATE)


def test_additive_unknown_schedule_fields_are_accepted() -> None:
    slate = parse_schedule(fixtures.schedule_json(), SLATE)  # carries syntheticExtraField
    assert slate.games


def test_schedule_fingerprint_is_deterministic() -> None:
    first = schedule_fingerprint_of(fixtures.schedule_json())
    second = schedule_fingerprint_of(fixtures.schedule_json())
    assert first == second


def test_a_valid_feed_parses_with_rosters_and_probables() -> None:
    feed = parse_game_feed(fixtures.feed_json())
    assert feed.game_pk == fixtures.GAME_PK
    assert feed.venue_timezone == fixtures.VENUE_TZ
    assert fixtures.BATTER_ID in feed.home_roster_ids
    assert feed.probable_away_id == fixtures.PITCHER_ID
    assert feed.player_name(fixtures.BATTER_ID) == fixtures.BATTER_NAME
    assert feed_fingerprint_of(fixtures.feed_json()) == feed_fingerprint_of(fixtures.feed_json())


def test_an_invalid_venue_timezone_fails_closed() -> None:
    body = fixtures.feed_json(gameData={"venue": {"timeZone": {"id": "Synthetic/Nowhere"}}})
    with pytest.raises(SchemaDriftError, match="not a valid IANA zone"):
        parse_game_feed(body)


# --------------------------------------------------------------------------
# Expected-pitcher resolution (ruling 4)
# --------------------------------------------------------------------------


def test_an_ordinary_probable_maps_to_expected_starter() -> None:
    record = resolve_expected_pitcher(parse_game_feed(fixtures.feed_json()), fixtures.BATTER_ID)
    assert record.pitcher_id == fixtures.PITCHER_ID
    assert record.role is PitcherRole.EXPECTED_STARTER
    assert record.batter_team_side == "home"


def test_an_announced_opener_maps_to_opener() -> None:
    body = fixtures.feed_json(
        gameData={
            "probablePitchers": {
                "away": {
                    "id": fixtures.PITCHER_ID,
                    "fullName": fixtures.PITCHER_NAME,
                    "note": "Scheduled Opener",
                }
            }
        }
    )
    record = resolve_expected_pitcher(parse_game_feed(body), fixtures.BATTER_ID)
    assert record.role is PitcherRole.OPENER


def test_an_uncertain_named_pitcher_maps_to_uncertain() -> None:
    body = fixtures.feed_json(
        gameData={
            "probablePitchers": {
                "away": {
                    "id": fixtures.PITCHER_ID,
                    "fullName": fixtures.PITCHER_NAME,
                    "note": "Likely to start, TBD",
                }
            }
        }
    )
    record = resolve_expected_pitcher(parse_game_feed(body), fixtures.BATTER_ID)
    assert record.role is PitcherRole.UNCERTAIN


def test_no_identified_pitcher_is_a_focused_eligibility_failure() -> None:
    document = json.loads(fixtures.feed_json().decode("utf-8"))
    document["gameData"]["probablePitchers"] = {}
    body = json.dumps(document).encode("utf-8")
    with pytest.raises(IngestionEligibilityError, match="no identified expected"):
        resolve_expected_pitcher(parse_game_feed(body), fixtures.BATTER_ID)


def test_a_batter_on_neither_roster_is_a_focused_eligibility_failure() -> None:
    with pytest.raises(IngestionEligibilityError, match="neither pregame roster"):
        resolve_expected_pitcher(parse_game_feed(fixtures.feed_json()), 599999)

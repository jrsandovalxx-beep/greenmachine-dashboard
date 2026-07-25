"""Subject entities: batter, pitcher, venue, and canonical game identity."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta

import pytest
from domain_builders import (
    SLATE_DATE,
    START_LOCAL,
    START_UTC,
    make_game_context,
    make_venue,
)

from greenmachine.domain import (
    Batter,
    DomainValidationError,
    GameContext,
    GameId,
    Pitcher,
    PitcherRole,
    PlayerId,
)

# --------------------------------------------------------------------------
# Batter / Pitcher / Venue
# --------------------------------------------------------------------------


def test_batter_construction() -> None:
    batter = Batter(PlayerId("player-000001"), "Synthetic Batter")

    assert batter.player_id == PlayerId("player-000001")
    assert batter.full_name == "Synthetic Batter"


@pytest.mark.parametrize("bad_name", ["", "   "])
def test_batter_rejects_blank_name(bad_name: str) -> None:
    with pytest.raises(DomainValidationError, match=r"full_name"):
        Batter(PlayerId("player-000001"), bad_name)


def test_pitcher_carries_its_role() -> None:
    """MODEL_SPEC 7.1: bullpen games record opener / expected_starter / uncertain."""
    pitcher = Pitcher(PlayerId("player-000002"), "Synthetic Opener", PitcherRole.OPENER)

    assert pitcher.role is PitcherRole.OPENER


def test_pitcher_requires_a_role() -> None:
    with pytest.raises(TypeError):
        Pitcher(PlayerId("player-000002"), "Synthetic Pitcher")  # type: ignore[call-arg]


def test_venue_requires_name_and_timezone() -> None:
    with pytest.raises(DomainValidationError, match=r"name"):
        make_venue(name="")
    with pytest.raises(DomainValidationError, match=r"timezone"):
        make_venue(timezone="  ")


# Immutability and hashability for Batter, Pitcher, and Venue live in
# test_immutability.py, which parameterises every domain type with a field that
# actually exists on it. The generic version that used to sit here assigned
# ``full_name`` to all three, including Venue, which has no such field — on a
# frozen slotted dataclass that raises TypeError on CPython 3.13 rather than
# FrozenInstanceError, so it passed on one interpreter and failed on another
# without ever testing immutability. It is removed rather than duplicated.


def test_entity_equality_is_by_value() -> None:
    assert Batter(PlayerId("p-1"), "Name") == Batter(PlayerId("p-1"), "Name")
    assert Batter(PlayerId("p-1"), "Name") != Batter(PlayerId("p-2"), "Name")


def test_batter_and_pitcher_are_distinct_types() -> None:
    """Same person-shaped data, different roles in the model."""
    assert Batter(PlayerId("p-1"), "Name") != Pitcher(
        PlayerId("p-1"), "Name", PitcherRole.EXPECTED_STARTER
    )


# --------------------------------------------------------------------------
# GameContext — canonical game identity (MODEL_SPEC 7.2)
# --------------------------------------------------------------------------


def test_game_context_carries_the_full_identity() -> None:
    context = make_game_context()

    assert context.game_id == GameId("official-game-000123")
    assert context.slate_date == SLATE_DATE
    assert context.scheduled_start_utc == START_UTC
    assert context.venue_local_scheduled_time == START_LOCAL
    assert context.venue_timezone == "America/New_York"


def test_game_context_venue_timezone_comes_from_the_venue() -> None:
    context = make_game_context(venue=make_venue(timezone="America/Chicago"))

    assert context.venue_timezone == "America/Chicago"


def test_game_context_requires_an_explicit_official_game_id() -> None:
    """No internal replacement game id is generated (MODEL_SPEC 7.2)."""
    with pytest.raises(TypeError):
        GameContext(  # type: ignore[call-arg]
            slate_date=SLATE_DATE,
            scheduled_start_utc=START_UTC,
            venue_local_scheduled_time=START_LOCAL,
            venue=make_venue(),
        )


def test_game_context_rejects_a_naive_scheduled_start() -> None:
    with pytest.raises(DomainValidationError, match=r"timezone-aware"):
        make_game_context(scheduled_start_utc=datetime(2026, 7, 15, 23, 10))


def test_game_context_rejects_a_non_utc_scheduled_start() -> None:
    """The scheduled start is stored in UTC, alongside the venue-local time."""
    with pytest.raises(DomainValidationError, match=r"UTC"):
        make_game_context(scheduled_start_utc=START_LOCAL)


def test_game_context_rejects_a_naive_venue_local_time() -> None:
    with pytest.raises(DomainValidationError, match=r"timezone-aware"):
        make_game_context(venue_local_scheduled_time=datetime(2026, 7, 15, 19, 10))


def test_game_context_accepts_an_offset_venue_local_time() -> None:
    """The venue-local time is aware but deliberately not required to be UTC."""
    context = make_game_context()

    assert context.venue_local_scheduled_time.utcoffset() == timedelta(hours=-4)


def test_game_context_rejects_a_datetime_as_the_slate_date() -> None:
    """MODEL_SPEC 7.2: slate_date is the official scheduled MLB date, never
    derived from UTC. A datetime would smuggle in a time and an offset."""
    with pytest.raises(DomainValidationError, match=r"slate_date"):
        make_game_context(slate_date=START_UTC)


def test_game_context_is_frozen() -> None:
    context = make_game_context()

    with pytest.raises(dataclasses.FrozenInstanceError):
        context.game_id = GameId("other")


def test_game_context_equality_and_hashing() -> None:
    assert make_game_context() == make_game_context()
    assert hash(make_game_context()) == hash(make_game_context())
    assert make_game_context() != make_game_context(game_id=GameId("official-game-000999"))


def test_doubleheader_games_are_distinct_by_official_id() -> None:
    """MODEL_SPEC 7.2: doubleheader games have separate official game ids."""
    first = make_game_context(game_id=GameId("official-game-000123-1"))
    second = make_game_context(game_id=GameId("official-game-000123-2"))

    assert first != second
    assert len({first, second}) == 2
    assert first.slate_date == second.slate_date

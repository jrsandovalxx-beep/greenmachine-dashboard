"""Immutable subject entities: the people, place, and game an evaluation is about.

These carry identity and the point-in-time-relevant scheduling facts only. They
hold no baseball measurements and no scoring state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from ._guards import ensure_aware_datetime, ensure_instance, ensure_non_empty_text, ensure_utc
from .enums import PitcherRole
from .errors import DomainValidationError
from .values import GameId, PlayerId, VenueId

__all__ = ["Batter", "GameContext", "Pitcher", "Venue"]


@dataclass(frozen=True, slots=True)
class Batter:
    """The hitter being evaluated."""

    player_id: PlayerId
    full_name: str

    def __post_init__(self) -> None:
        ensure_instance(self.player_id, PlayerId, "Batter.player_id")
        ensure_non_empty_text(self.full_name, "Batter.full_name")


@dataclass(frozen=True, slots=True)
class Pitcher:
    """The expected opposing pitcher, tagged with how the role was known.

    A change of expected starter produces a new snapshot and evaluation
    (``MODEL_SPEC.md`` §7.1); this type never mutates in place.
    """

    player_id: PlayerId
    full_name: str
    role: PitcherRole

    def __post_init__(self) -> None:
        ensure_instance(self.player_id, PlayerId, "Pitcher.player_id")
        ensure_non_empty_text(self.full_name, "Pitcher.full_name")
        ensure_instance(self.role, PitcherRole, "Pitcher.role")


@dataclass(frozen=True, slots=True)
class Venue:
    """The ballpark, carrying its IANA timezone for venue-local scheduling."""

    venue_id: VenueId
    name: str
    timezone: str

    def __post_init__(self) -> None:
        ensure_instance(self.venue_id, VenueId, "Venue.venue_id")
        ensure_non_empty_text(self.name, "Venue.name")
        ensure_non_empty_text(self.timezone, "Venue.timezone")


@dataclass(frozen=True, slots=True)
class GameContext:
    """Canonical game identity and scheduling (``MODEL_SPEC.md`` §7.2).

    ``slate_date`` is the official scheduled MLB date, never derived from UTC. The
    scheduled start is stored in UTC alongside the venue-local scheduled time and
    the venue timezone (exposed via :attr:`venue_timezone`). The ``game_id`` is the
    official provider identifier; no replacement id is generated.

    The two scheduled times are two renderings of one first pitch, so they must
    name the same instant. Both supplied values are preserved exactly — neither is
    derived from nor overwritten by the other; a disagreement is rejected instead,
    because silently trusting one would discard a real upstream defect.
    """

    game_id: GameId
    slate_date: date
    scheduled_start_utc: datetime
    venue_local_scheduled_time: datetime
    venue: Venue

    def __post_init__(self) -> None:
        ensure_instance(self.game_id, GameId, "GameContext.game_id")
        # ``datetime`` is a subtype of ``date``, so a datetime satisfies the
        # annotation while smuggling in a time and offset. Reject it: the slate
        # date is the official scheduled MLB date and is never derived from UTC.
        if isinstance(self.slate_date, datetime):
            raise DomainValidationError(
                "GameContext.slate_date must be a datetime.date (the official "
                "scheduled MLB date), not a datetime"
            )
        ensure_instance(self.slate_date, date, "GameContext.slate_date")
        start_utc = ensure_utc(self.scheduled_start_utc, "GameContext.scheduled_start_utc")
        local = ensure_aware_datetime(
            self.venue_local_scheduled_time, "GameContext.venue_local_scheduled_time"
        )
        ensure_instance(self.venue, Venue, "GameContext.venue")

        if local.astimezone(UTC) != start_utc:
            raise DomainValidationError(
                f"GameContext.venue_local_scheduled_time ({local.isoformat()}) must be the "
                f"same instant as scheduled_start_utc ({start_utc.isoformat()}), but "
                f"resolves to {local.astimezone(UTC).isoformat()}"
            )

    @property
    def venue_timezone(self) -> str:
        """The venue's IANA timezone, carried on the game identity per §7.2."""
        return self.venue.timezone

"""MLB Stats API request construction (no I/O here).

Builds canonical :class:`~greenmachine.ingestion.models.ProviderRequest`
records and their URLs. The schedule request asks for one official slate date;
the live-feed request asks for one game. Retrieval itself happens through the
injected transport in orchestration.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from ..models import CaptureProvider, ProviderRequest

__all__ = [
    "MLB_API_BASE",
    "live_feed_request",
    "request_url",
    "schedule_request",
]

MLB_API_BASE = "https://statsapi.mlb.com"

_SCHEDULE_ENDPOINT = "schedule"
_LIVE_FEED_ENDPOINT = "game_feed_live"


def schedule_request(slate_date: date) -> ProviderRequest:
    """The schedule for one official MLB date (sportId 1)."""
    return ProviderRequest(
        label="mlb_schedule",
        provider=CaptureProvider.MLB_STATS_API,
        endpoint=_SCHEDULE_ENDPOINT,
        parameters=(
            ("date", slate_date.isoformat()),
            ("sportId", "1"),
        ),
    )


def live_feed_request(game_pk: int) -> ProviderRequest:
    """The live feed for one game — pregame it carries probable pitchers and rosters."""
    return ProviderRequest(
        label="mlb_game_feed",
        provider=CaptureProvider.MLB_STATS_API,
        endpoint=_LIVE_FEED_ENDPOINT,
        parameters=(("gamePk", str(game_pk)),),
    )


def request_url(request: ProviderRequest) -> str:
    """The concrete URL for an MLB request."""
    parameters = dict(request.parameters)
    if request.endpoint == _SCHEDULE_ENDPOINT:
        query = urlencode(sorted(parameters.items()))
        return f"{MLB_API_BASE}/api/v1/schedule?{query}"
    if request.endpoint == _LIVE_FEED_ENDPOINT:
        game_pk = parameters["gamePk"]
        return f"{MLB_API_BASE}/api/v1.1/game/{game_pk}/feed/live"
    raise ValueError(f"unknown MLB endpoint {request.endpoint!r}")

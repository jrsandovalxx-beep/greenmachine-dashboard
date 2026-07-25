"""Baseball Savant statcast-search CSV request construction (no I/O here).

Provider requests carry inclusive calendar bounds ending on
``slate_date - 1 day`` (the approved spike observed inclusive endpoint
behavior), and explicitly ask for regular-season rows — while the local window
and game-type filters are always re-enforced after parsing, never trusted to
the request alone.
"""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote

from ..models import CaptureProvider, ProviderRequest

__all__ = [
    "SAVANT_API_BASE",
    "batter_events_request",
    "pitcher_events_request",
    "request_url",
]

SAVANT_API_BASE = "https://baseballsavant.mlb.com"

_EVENTS_ENDPOINT = "statcast_search_csv"


def _events_request(
    label: str,
    player_type: str,
    player_parameter: str,
    player_id: int,
    start_date: date,
    end_date_exclusive: date,
) -> ProviderRequest:
    inclusive_end = end_date_exclusive - timedelta(days=1)
    return ProviderRequest(
        label=label,
        provider=CaptureProvider.BASEBALL_SAVANT,
        endpoint=_EVENTS_ENDPOINT,
        parameters=tuple(
            sorted(
                (
                    ("all", "true"),
                    ("type", "details"),
                    ("player_type", player_type),
                    (player_parameter, str(player_id)),
                    ("game_date_gt", start_date.isoformat()),
                    ("game_date_lt", inclusive_end.isoformat()),
                    ("hfGT", "R|"),
                )
            )
        ),
    )


def batter_events_request(
    label: str, batter_id: int, start_date: date, end_date_exclusive: date
) -> ProviderRequest:
    """Pitch-level rows for one batter over an inclusive request window."""
    return _events_request(
        label, "batter", "batters_lookup[]", batter_id, start_date, end_date_exclusive
    )


def pitcher_events_request(
    label: str, pitcher_id: int, start_date: date, end_date_exclusive: date
) -> ProviderRequest:
    """Pitch-level rows for one pitcher (audit-only ingredients in GM-020)."""
    return _events_request(
        label, "pitcher", "pitchers_lookup[]", pitcher_id, start_date, end_date_exclusive
    )


def request_url(request: ProviderRequest) -> str:
    """The concrete statcast-search CSV URL for a Savant request."""
    if request.endpoint != _EVENTS_ENDPOINT:
        raise ValueError(f"unknown Savant endpoint {request.endpoint!r}")
    encoded = "&".join(
        f"{quote(key, safe='[]')}={quote(value, safe='|')}" for key, value in request.parameters
    )
    return f"{SAVANT_API_BASE}/statcast_search/csv?{encoded}"

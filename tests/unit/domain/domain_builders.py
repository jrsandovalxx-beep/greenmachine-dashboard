"""Builders for domain unit tests.

Every value here is **obviously synthetic** and could not be mistaken for a
production threshold, allocation, or sample minimum — GM-002 introduces no
baseball numbers, and neither do its fixtures. Timestamps are fixed literals so
no test depends on the current date.

The observation builder derives ``sample_status`` and the coverage sample count
from the counts it was given, so a test that varies one number stays coherent
without restating the other three. Any of those may still be overridden
explicitly, which is how the coherence rules themselves get tested.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from greenmachine.domain import (
    AcquisitionMethod,
    ComponentId,
    CoverageStatus,
    CoverageWindow,
    DataCoverage,
    FallbackRecord,
    GameContext,
    GameId,
    MeasurementId,
    MethodIneligibility,
    MetricObservation,
    MissingObservation,
    MissingReason,
    ProviderId,
    SampleStatus,
    SampleType,
    SourceCaptureId,
    Venue,
    VenueId,
    WindowProfile,
)

AS_OF = datetime(2026, 7, 15, 16, 30, tzinfo=UTC)
WINDOW_START = datetime(2026, 7, 8, 16, 30, tzinfo=UTC)
WINDOW_END = datetime(2026, 7, 15, 16, 30, tzinfo=UTC)
SOURCE_AS_OF = datetime(2026, 7, 15, 15, 0, tzinfo=UTC)
RETRIEVED_AT = datetime(2026, 7, 15, 16, 0, tzinfo=UTC)

SOURCE_CAPTURE_ID = SourceCaptureId("capture-synthetic-0001")

EASTERN = timezone(timedelta(hours=-4))
SLATE_DATE = date(2026, 7, 15)
START_UTC = datetime(2026, 7, 15, 23, 10, tzinfo=UTC)
START_LOCAL = datetime(2026, 7, 15, 19, 10, tzinfo=EASTERN)

DEFAULT_SAMPLE_COUNT = 42
DEFAULT_MINIMUM_SAMPLE = 7


def _is_count(value: object) -> bool:
    """True when ``value`` is usable as a sample count."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def coverage_kwargs(**overrides: Any) -> dict[str, Any]:
    """Keyword arguments for a fully populated :class:`DataCoverage`."""
    params: dict[str, Any] = {
        "requested": CoverageWindow(WINDOW_START, WINDOW_END),
        "actual": CoverageWindow(WINDOW_START, WINDOW_END),
        "status": CoverageStatus.COMPLETE,
        "source_available": True,
        "sample_count": DEFAULT_SAMPLE_COUNT,
    }
    params.update(overrides)
    return params


def make_coverage(**overrides: Any) -> DataCoverage:
    return DataCoverage(**coverage_kwargs(**overrides))


def make_ineligibility(**overrides: Any) -> MethodIneligibility:
    params: dict[str, Any] = {
        "method": AcquisitionMethod.DIRECT_AGGREGATE,
        "reason": "cannot reproduce the historical as_of window",
    }
    params.update(overrides)
    return MethodIneligibility(**params)


def make_fallback(**overrides: Any) -> FallbackRecord:
    params: dict[str, Any] = {
        "selected_method": AcquisitionMethod.EVENT_DERIVED,
        "higher_priority_ineligible": (make_ineligibility(),),
    }
    params.update(overrides)
    return FallbackRecord(**params)


def observation_kwargs(**overrides: Any) -> dict[str, Any]:
    """Keyword arguments for a fully populated :class:`MetricObservation`."""
    sample_count = overrides.get("sample_count", DEFAULT_SAMPLE_COUNT)
    minimum = overrides.get("minimum_sample_required", DEFAULT_MINIMUM_SAMPLE)

    if _is_count(sample_count) and _is_count(minimum) and sample_count < minimum:
        status = SampleStatus.INSUFFICIENT
    else:
        status = SampleStatus.SUFFICIENT

    coverage_count = sample_count if _is_count(sample_count) else DEFAULT_SAMPLE_COUNT

    params: dict[str, Any] = {
        "component_id": ComponentId.EXIT_VELOCITY,
        "measurement_id": None,
        "window_profile": WindowProfile.RECENT_7D,
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "as_of": AS_OF,
        "raw_value": Decimal("12.3456"),
        "unit": "mph",
        "sample_type": SampleType.BATTED_BALL_EVENTS,
        "sample_count": sample_count,
        "minimum_sample_required": minimum,
        "sample_status": status,
        "data_coverage": make_coverage(sample_count=coverage_count),
        "provider_id": ProviderId.BASEBALL_SAVANT,
        "acquisition_method": AcquisitionMethod.DIRECT_AGGREGATE,
        "source_as_of": SOURCE_AS_OF,
        "retrieved_at": RETRIEVED_AT,
        "source_capture_id": SOURCE_CAPTURE_ID,
    }
    params.update(overrides)
    return params


def make_observation(**overrides: Any) -> MetricObservation:
    return MetricObservation(**observation_kwargs(**overrides))


def missing_observation_kwargs(**overrides: Any) -> dict[str, Any]:
    """Keyword arguments for a fully populated :class:`MissingObservation`."""
    params: dict[str, Any] = {
        "component_id": ComponentId.ATTACK_ANGLE_QUALITY,
        "measurement_id": MeasurementId.IDEAL_ATTACK_ANGLE_PCT,
        "window_profile": WindowProfile.RECENT_7D,
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "as_of": AS_OF,
        "sample_type": SampleType.BATTED_BALL_EVENTS,
        "provider_id": ProviderId.BASEBALL_SAVANT,
        "source_capture_id": SOURCE_CAPTURE_ID,
        "missing_reason": MissingReason.TRACKING_UNAVAILABLE,
        "data_coverage": make_coverage(
            actual=None,
            status=CoverageStatus.NONE,
            source_available=False,
            sample_count=0,
        ),
    }
    params.update(overrides)
    return params


def make_missing_observation(**overrides: Any) -> MissingObservation:
    return MissingObservation(**missing_observation_kwargs(**overrides))


def make_venue(**overrides: Any) -> Venue:
    params: dict[str, Any] = {
        "venue_id": VenueId("venue-synthetic-01"),
        "name": "Synthetic Park",
        "timezone": "America/New_York",
    }
    params.update(overrides)
    return Venue(**params)


def make_game_context(**overrides: Any) -> GameContext:
    params: dict[str, Any] = {
        "game_id": GameId("official-game-000123"),
        "slate_date": SLATE_DATE,
        "scheduled_start_utc": START_UTC,
        "venue_local_scheduled_time": START_LOCAL,
        "venue": make_venue(),
    }
    params.update(overrides)
    return GameContext(**params)

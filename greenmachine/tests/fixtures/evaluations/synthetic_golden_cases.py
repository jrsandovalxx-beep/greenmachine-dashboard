"""Extra synthetic builders supporting the GM-008 committed golden cases.

Complements :mod:`synthetic_records` without modifying it (that file is part of
the frozen GM-006/GM-007 deliverables). Everything here is visibly synthetic:
placeholder identifiers, a fictional park, fixed 2026-07-15 instants — nothing
can be mistaken for a real player, game, provider capture, or production
threshold.
"""

from __future__ import annotations

import synthetic_records
from synthetic_records import AS_OF, WINDOW_END, WINDOW_START

from greenmachine.domain import (
    ComponentId,
    CoverageStatus,
    CoverageWindow,
    DataCoverage,
    InputSnapshot,
    MissingObservation,
    MissingReason,
    PitcherRole,
    SampleType,
    SourceCaptureId,
    WindowProfile,
)
from greenmachine.evaluation import freeze_input_snapshot

# The configuration version reference every committed golden case uses. A
# synthetic fixture identifier, not a production model configuration version.
GOLDEN_CONFIG_VERSION = "synthetic-fixture-0"

# The two evaluated cases share synthetic_records.CAPTURE ("SYNTHETIC-CAPTURE-0001").
# The not-evaluable case is a separate synthetic collection operation.
NOT_EVALUABLE_CAPTURE = SourceCaptureId("SYNTHETIC-CAPTURE-0002")


def _missing(
    component: ComponentId,
    reason: MissingReason,
    sample_type: SampleType,
    capture: SourceCaptureId,
) -> MissingObservation:
    return MissingObservation(
        component_id=component,
        measurement_id=None,
        window_profile=WindowProfile.RECENT_7D,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        as_of=AS_OF,
        sample_type=sample_type,
        provider_id=None,
        source_capture_id=capture,
        missing_reason=reason,
        data_coverage=DataCoverage(
            requested=CoverageWindow(start=WINDOW_START, end=WINDOW_END),
            actual=None,
            status=CoverageStatus.NONE,
            source_available=False,
            sample_count=0,
        ),
    )


def not_evaluable_input_snapshot() -> InputSnapshot:
    """A RECENT_7D snapshot with no present observations at all.

    The stub scorer maps this generically to a ``NotEvaluableGradeResult``,
    giving the committed golden tree a not-evaluable case without any scoring
    logic existing yet.
    """
    return freeze_input_snapshot(
        source_capture_id=NOT_EVALUABLE_CAPTURE,
        game_context=synthetic_records.game_context(),
        batter=synthetic_records.batter(),
        expected_starting_pitcher=synthetic_records.pitcher(),
        pitcher_role=PitcherRole.EXPECTED_STARTER,
        as_of=AS_OF,
        window_profile=WindowProfile.RECENT_7D,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        present_observations=(),
        missing_observations=(
            _missing(
                ComponentId.EXIT_VELOCITY,
                MissingReason.SOURCE_UNAVAILABLE,
                SampleType.BATTED_BALL_EVENTS,
                NOT_EVALUABLE_CAPTURE,
            ),
            _missing(
                ComponentId.BAT_SPEED,
                MissingReason.TRACKING_UNAVAILABLE,
                SampleType.SWINGS,
                NOT_EVALUABLE_CAPTURE,
            ),
        ),
        validation_inputs=(),
        weather_is_forecast=False,
    )

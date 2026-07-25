"""Hand-authored synthetic GM-006 records for tests and fixtures.

Every value here is *visibly* synthetic — placeholder ids, a fictional park, and
deliberately odd numbers — so nothing can be mistaken for a real player, a real
MLB game, a production threshold, or a betting recommendation. The builders
compose coherent records so a test can start from a valid object and mutate one
field to prove a specific invariant.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

from greenmachine.domain import (
    AcquisitionMethod,
    AuditEntry,
    Batter,
    BucketHit,
    Category,
    CategoryScore,
    ComponentId,
    ComponentScore,
    CoverageStatus,
    CoverageWindow,
    DataCoverage,
    EvaluatedGradeResult,
    EvaluationEnvelope,
    EvaluationId,
    GameContext,
    GameId,
    Grade,
    InputSnapshot,
    MethodIneligibility,
    MetricObservation,
    MissingObservation,
    MissingReason,
    NotEvaluableGradeResult,
    OutcomeRecord,
    Pitcher,
    PitcherRole,
    PlayerId,
    ProvenanceEntry,
    ProviderId,
    SampleStatus,
    SampleType,
    Sha256Digest,
    Signal,
    SourceCaptureId,
    UnavailableRequiredInput,
    ValidationFinding,
    ValidationInputId,
    ValidationInputRecord,
    Venue,
    VenueId,
    WindowProfile,
)
from greenmachine.evaluation import freeze_input_snapshot

# --------------------------------------------------------------------------
# Fixed synthetic instants (all pregame: window closes at as_of, before start)
# --------------------------------------------------------------------------

AS_OF = datetime(2026, 7, 15, 22, 0, tzinfo=UTC)
WINDOW_START = datetime(2026, 7, 8, 22, 0, tzinfo=UTC)
WINDOW_END = AS_OF
SOURCE_AS_OF = datetime(2026, 7, 15, 21, 0, tzinfo=UTC)
RETRIEVED_AT = datetime(2026, 7, 15, 21, 30, tzinfo=UTC)
SCHEDULED_START_UTC = datetime(2026, 7, 15, 23, 10, tzinfo=UTC)
VENUE_LOCAL_START = datetime(2026, 7, 15, 19, 10, tzinfo=timezone(timedelta(hours=-4)))
EVALUATED_AT = datetime(2026, 7, 15, 22, 5, tzinfo=UTC)
SLATE_DATE = date(2026, 7, 15)

CAPTURE = SourceCaptureId("SYNTHETIC-CAPTURE-0001")


def game_context() -> GameContext:
    return GameContext(
        game_id=GameId("SYNTHETIC-GAME-0001"),
        slate_date=SLATE_DATE,
        scheduled_start_utc=SCHEDULED_START_UTC,
        venue_local_scheduled_time=VENUE_LOCAL_START,
        venue=Venue(
            venue_id=VenueId("SYNTHETIC-VENUE-0001"),
            name="Synthetic Test Park",
            timezone="America/New_York",
        ),
    )


def batter() -> Batter:
    return Batter(player_id=PlayerId("SYNTHETIC-BATTER-0001"), full_name="Synthetic Batter One")


def pitcher() -> Pitcher:
    return Pitcher(
        player_id=PlayerId("SYNTHETIC-PITCHER-0009"),
        full_name="Synthetic Pitcher Nine",
        role=PitcherRole.EXPECTED_STARTER,
    )


def _coverage(sample_count: int, status: CoverageStatus = CoverageStatus.COMPLETE) -> DataCoverage:
    window = CoverageWindow(start=WINDOW_START, end=WINDOW_END)
    if status is CoverageStatus.NONE:
        return DataCoverage(
            requested=window, actual=None, status=status, source_available=False, sample_count=0
        )
    return DataCoverage(
        requested=window,
        actual=window,
        status=status,
        source_available=True,
        sample_count=sample_count,
    )


def metric_observation(
    component: ComponentId,
    *,
    raw_value: str,
    unit: str,
    sample_type: SampleType,
    sample_count: int,
    minimum: int,
    measurement_id: object = None,
) -> MetricObservation:
    status = SampleStatus.SUFFICIENT if sample_count >= minimum else SampleStatus.INSUFFICIENT
    return MetricObservation(
        component_id=component,
        measurement_id=measurement_id,  # type: ignore[arg-type]
        window_profile=WindowProfile.RECENT_7D,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        as_of=AS_OF,
        raw_value=Decimal(raw_value),
        unit=unit,
        sample_type=sample_type,
        sample_count=sample_count,
        minimum_sample_required=minimum,
        sample_status=status,
        data_coverage=_coverage(sample_count),
        provider_id=ProviderId.BASEBALL_SAVANT,
        acquisition_method=AcquisitionMethod.DIRECT_AGGREGATE,
        source_as_of=SOURCE_AS_OF,
        retrieved_at=RETRIEVED_AT,
        source_capture_id=CAPTURE,
        fallback_used=None,
    )


def missing_observation(
    component: ComponentId, reason: MissingReason, sample_type: SampleType
) -> MissingObservation:
    return MissingObservation(
        component_id=component,
        measurement_id=None,
        window_profile=WindowProfile.RECENT_7D,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        as_of=AS_OF,
        sample_type=sample_type,
        provider_id=ProviderId.BASEBALL_SAVANT,
        source_capture_id=CAPTURE,
        missing_reason=reason,
        data_coverage=_coverage(0, status=CoverageStatus.NONE),
    )


def present_exit_velocity() -> MetricObservation:
    return metric_observation(
        ComponentId.EXIT_VELOCITY,
        raw_value="42.7",
        unit="mph",
        sample_type=SampleType.BATTED_BALL_EVENTS,
        sample_count=12,
        minimum=3,
    )


def present_barrel_insufficient() -> MetricObservation:
    return metric_observation(
        ComponentId.BARREL_PCT,
        raw_value="3.9",
        unit="percent",
        sample_type=SampleType.BATTED_BALL_EVENTS,
        sample_count=1,
        minimum=3,
    )


def present_weather_forecast() -> MetricObservation:
    return metric_observation(
        ComponentId.WEATHER,
        raw_value="1.7",
        unit="forecast_index",
        sample_type=SampleType.GAMES,
        sample_count=1,
        minimum=1,
    )


def missing_bat_speed() -> MissingObservation:
    return missing_observation(
        ComponentId.BAT_SPEED, MissingReason.TRACKING_UNAVAILABLE, SampleType.SWINGS
    )


def validation_inputs() -> tuple[ValidationInputRecord, ...]:
    return (
        ValidationInputRecord(
            input_id=ValidationInputId.WOBA_WINDOW,
            summary="synthetic wOBA window advisory summary",
        ),
        ValidationInputRecord(
            input_id=ValidationInputId.SAMPLE_WARNINGS,
            summary="synthetic insufficient-sample advisory for barrel_pct",
            component_id=ComponentId.BARREL_PCT,
        ),
    )


def input_snapshot() -> InputSnapshot:
    """A frozen, content-identified RECENT_7D snapshot."""
    return freeze_input_snapshot(
        source_capture_id=CAPTURE,
        game_context=game_context(),
        batter=batter(),
        expected_starting_pitcher=pitcher(),
        pitcher_role=PitcherRole.EXPECTED_STARTER,
        as_of=AS_OF,
        window_profile=WindowProfile.RECENT_7D,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        present_observations=(
            present_exit_velocity(),
            present_barrel_insufficient(),
            present_weather_forecast(),
        ),
        missing_observations=(missing_bat_speed(),),
        validation_inputs=validation_inputs(),
        weather_is_forecast=True,
    )


LONG_TERM_WINDOW_START = datetime(2024, 7, 15, 22, 0, tzinfo=UTC)


def input_snapshot_long_term() -> InputSnapshot:
    """A LONG_TERM_2Y snapshot frozen from the *same* source capture.

    Shares ``source_capture_id`` with :func:`input_snapshot` but differs in
    profile, window bounds, and observations, so ADR-0005 requires a distinct
    ``snapshot_id`` and ``input_hash``.
    """
    long_term_exit = MetricObservation(
        component_id=ComponentId.EXIT_VELOCITY,
        measurement_id=None,
        window_profile=WindowProfile.LONG_TERM_2Y,
        window_start=LONG_TERM_WINDOW_START,
        window_end=WINDOW_END,
        as_of=AS_OF,
        raw_value=Decimal("41.9"),
        unit="mph",
        sample_type=SampleType.BATTED_BALL_EVENTS,
        sample_count=250,
        minimum_sample_required=11,
        sample_status=SampleStatus.SUFFICIENT,
        data_coverage=DataCoverage(
            requested=CoverageWindow(start=LONG_TERM_WINDOW_START, end=WINDOW_END),
            actual=CoverageWindow(start=LONG_TERM_WINDOW_START, end=WINDOW_END),
            status=CoverageStatus.COMPLETE,
            source_available=True,
            sample_count=250,
        ),
        provider_id=ProviderId.BASEBALL_SAVANT,
        acquisition_method=AcquisitionMethod.DIRECT_AGGREGATE,
        source_as_of=SOURCE_AS_OF,
        retrieved_at=RETRIEVED_AT,
        source_capture_id=CAPTURE,
        fallback_used=None,
    )
    return freeze_input_snapshot(
        source_capture_id=CAPTURE,
        game_context=game_context(),
        batter=batter(),
        expected_starting_pitcher=pitcher(),
        pitcher_role=PitcherRole.EXPECTED_STARTER,
        as_of=AS_OF,
        window_profile=WindowProfile.LONG_TERM_2Y,
        window_start=LONG_TERM_WINDOW_START,
        window_end=WINDOW_END,
        present_observations=(long_term_exit,),
        missing_observations=(),
        validation_inputs=(),
        weather_is_forecast=False,
    )


def audit_trail() -> tuple[AuditEntry, ...]:
    return (
        AuditEntry(
            sequence=1,
            stage="bucket_resolution",
            rule_reference="synthetic-fixture-0/exit_velocity/RECENT_7D",
            input_summary="raw exit velocity 42.7 mph",
            output_summary="terminal bucket, 0.9 points",
            explanation="synthetic bucket resolution for the exit velocity component",
            component_id=ComponentId.EXIT_VELOCITY,
        ),
        AuditEntry(
            sequence=2,
            stage="grade_assignment",
            rule_reference="synthetic-fixture-0/grade_cutoffs",
            input_summary="total score 2.2",
            output_summary="grade C",
            explanation="synthetic grade assignment from the total score",
        ),
    )


def evaluated_grade_result() -> EvaluatedGradeResult:
    exit_score = ComponentScore(
        component_id=ComponentId.EXIT_VELOCITY,
        measurement_id=None,
        points_awarded=Decimal("0.9"),
        bucket_hit=BucketHit(
            lower_bound=Decimal("40"),
            upper_bound=None,
            is_terminal=True,
            points_awarded=Decimal("0.9"),
        ),
    )
    barrel_score = ComponentScore(
        component_id=ComponentId.BARREL_PCT,
        measurement_id=None,
        points_awarded=Decimal("0.5"),
        bucket_hit=BucketHit(
            lower_bound=Decimal("1"),
            upper_bound=Decimal("5"),
            is_terminal=False,
            points_awarded=Decimal("0.5"),
        ),
    )
    weather_score = ComponentScore(
        component_id=ComponentId.WEATHER,
        measurement_id=None,
        points_awarded=Decimal("0.8"),
    )
    return EvaluatedGradeResult(
        window_profile=WindowProfile.RECENT_7D,
        present_observations=(
            present_exit_velocity(),
            present_barrel_insufficient(),
            present_weather_forecast(),
        ),
        missing_observations=(missing_bat_speed(),),
        validation_findings=(
            ValidationFinding(
                input_id=ValidationInputId.SAMPLE_WARNINGS,
                message="barrel_pct sample below the configured minimum",
                component_id=ComponentId.BARREL_PCT,
            ),
        ),
        audit_derivation=audit_trail(),
        component_scores=(exit_score, barrel_score, weather_score),
        category_scores=(
            CategoryScore(
                category=Category.POWER_PROFILE,
                points_awarded=Decimal("1.4"),
                component_scores=(exit_score, barrel_score),
            ),
            CategoryScore(
                category=Category.ENVIRONMENT,
                points_awarded=Decimal("0.8"),
                component_scores=(weather_score,),
            ),
        ),
        total_score=Decimal("2.2"),
        grade=Grade.C,
        signal=Signal.LEAN,
        signal_reason="synthetic_lean_reason",
    )


def not_evaluable_grade_result() -> NotEvaluableGradeResult:
    missing_exit = missing_observation(
        ComponentId.EXIT_VELOCITY, MissingReason.SOURCE_UNAVAILABLE, SampleType.BATTED_BALL_EVENTS
    )
    return NotEvaluableGradeResult(
        window_profile=WindowProfile.RECENT_7D,
        present_observations=(),
        missing_observations=(missing_exit,),
        validation_findings=(),
        audit_derivation=(
            AuditEntry(
                sequence=1,
                stage="evaluability_check",
                rule_reference="synthetic-fixture-0/required_components",
                input_summary="required component exit_velocity unavailable",
                output_summary="NOT_EVALUABLE",
                explanation="synthetic not-evaluable determination: a required input was missing",
                component_id=ComponentId.EXIT_VELOCITY,
            ),
        ),
        unavailable_required_inputs=(
            UnavailableRequiredInput(
                component_id=ComponentId.EXIT_VELOCITY,
                measurement_id=None,
                missing_reason=MissingReason.SOURCE_UNAVAILABLE,
                missing_observation=missing_exit,
                attempted_methods=(
                    MethodIneligibility(
                        method=AcquisitionMethod.DIRECT_AGGREGATE,
                        reason="synthetic: aggregate table had no data for the window",
                    ),
                ),
            ),
        ),
    )


def provenance() -> tuple[ProvenanceEntry, ...]:
    return (
        ProvenanceEntry(
            provider_id=ProviderId.BASEBALL_SAVANT,
            acquisition_method=AcquisitionMethod.DIRECT_AGGREGATE,
            source_as_of=SOURCE_AS_OF,
            retrieved_at=RETRIEVED_AT,
            component_id=ComponentId.EXIT_VELOCITY,
        ),
        ProvenanceEntry(
            provider_id=ProviderId.BASEBALL_SAVANT,
            acquisition_method=AcquisitionMethod.DIRECT_AGGREGATE,
            source_as_of=SOURCE_AS_OF,
            retrieved_at=RETRIEVED_AT,
        ),
    )


SYNTHETIC_CONFIG_HASH = Sha256Digest(
    "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"
)
SYNTHETIC_INPUT_HASH = Sha256Digest(
    "f0e1d2c3b4a5968778695a4b3c2d1e0fa1b2c3d4e5f60718293a4b5c6d7e8f90"
)


def evaluation_envelope() -> EvaluationEnvelope:
    """An envelope wrapping the evaluated result, with a frozen snapshot's identity."""
    snapshot = input_snapshot()
    return EvaluationEnvelope(
        evaluation_id=EvaluationId("SYNTHETIC-EVAL-0001"),
        snapshot_id=snapshot.snapshot_id,
        source_capture_id=CAPTURE,
        evaluated_at=EVALUATED_AT,
        code_version="0.1.0",
        model_configuration_version="synthetic-fixture-0",
        product_specification_version="v6.3",
        schema_version=1,
        config_hash=SYNTHETIC_CONFIG_HASH,
        input_hash=snapshot.input_hash,
        game_id=GameId("SYNTHETIC-GAME-0001"),
        slate_date=SLATE_DATE,
        batter_id=PlayerId("SYNTHETIC-BATTER-0001"),
        expected_starting_pitcher_id=PlayerId("SYNTHETIC-PITCHER-0009"),
        window_profile=WindowProfile.RECENT_7D,
        pitcher_role=PitcherRole.EXPECTED_STARTER,
        provenance=provenance(),
        supersedes=None,
        grade_result=evaluated_grade_result(),
    )


def outcome_record() -> OutcomeRecord:
    return OutcomeRecord(
        game_id=GameId("SYNTHETIC-GAME-0001"),
        batter_id=PlayerId("SYNTHETIC-BATTER-0001"),
        hit_at_least_one_home_run=True,
    )


def rebuild_snapshot(snapshot: InputSnapshot, **overrides: object) -> InputSnapshot:
    """Test-only reconstruction through the internal construction authority.

    Lets a test build a deliberately inconsistent snapshot — a tampered identity,
    a mismatched observation context — to prove the guards fire. This is not a
    public path: production code creates snapshots only through
    ``freeze_input_snapshot`` or by decoding a stored record.
    """
    from greenmachine.domain.snapshot import _SNAPSHOT_CONSTRUCTION_AUTHORITY

    field_values = {
        field.name: getattr(snapshot, field.name) for field in dataclasses.fields(InputSnapshot)
    }
    field_values.update(overrides)
    return InputSnapshot(**field_values, _authority=_SNAPSHOT_CONSTRUCTION_AUTHORITY)

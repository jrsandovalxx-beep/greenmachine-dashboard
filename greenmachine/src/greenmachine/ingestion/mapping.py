"""Mapping normalized provider records into the frozen domain contracts.

This is where ingestion meets the frozen GM-006 world: eligible event rows and
their metric computations become ``MetricObservation``/``MissingObservation``
records, and one coordinated capture becomes exactly two profile-specific
``InputSnapshot``s — frozen through the unmodified
:func:`~greenmachine.evaluation.freeze_input_snapshot` factory and sharing one
content-derived ``SourceCaptureId``.

Policy honored here (Product Owner rulings):

* the sample-minimum policy is **injected and complete** — no hidden default
  exists anywhere in this module (Q14 stays open);
* zero eligible events map to ``NO_EVENTS_IN_WINDOW``; untracked bat-speed /
  attack-angle data maps to ``TRACKING_UNAVAILABLE``; rows present but all
  unusable map to ``INVALID_SOURCE_VALUE``;
* every present observation is ``EVENT_DERIVED``. **Only Ideal Attack Angle %
  carries a ``FallbackRecord``**: it is the one metric with an approved
  higher-priority acquisition hierarchy (the official published aggregate)
  that GM-020 deliberately bypasses because that route cannot be
  point-in-time verified for the exact profile window. The other metrics are
  event-derived by definition here, with no bypassed hierarchy, so recording
  a fallback for them would be false provenance — their ``fallback_used`` is
  ``None``;
* the pitcher-matchup components stay missing (Q15/Q16 formulas are undefined).
  The provider transport **succeeded** and the audit ingredients exist;
  ``SOURCE_UNAVAILABLE`` is only the closest frozen ``MissingReason`` for a
  derivation that does not exist yet — an interim mapping recorded in
  ``docs/GM_020_VERTICAL_SLICE.md`` pending the open derivation-pending-reason
  decision, and never a claim that the provider was unreachable;
* park stays missing (no provider chosen); weather stays missing with
  ``WEATHER_UNAVAILABLE`` and ``weather_is_forecast=False``;
* Overall Pull % and the alternative Pull Air denominators never enter a
  snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from greenmachine.domain import (
    AcquisitionMethod,
    Batter,
    ComponentId,
    CoverageStatus,
    CoverageWindow,
    DataCoverage,
    FallbackRecord,
    GameContext,
    GameId,
    InputSnapshot,
    MeasurementId,
    MethodIneligibility,
    MetricObservation,
    MissingObservation,
    MissingReason,
    Pitcher,
    PlayerId,
    ProviderId,
    SampleStatus,
    SampleType,
    SourceCaptureId,
    Venue,
    VenueId,
    WindowProfile,
)
from greenmachine.evaluation import freeze_input_snapshot

from .events import EligibleBatterEvents
from .models import ExpectedPitcherRecord, GameRecord, SampleMinimumPolicy
from .savant.metrics import (
    MetricComputation,
    PullAudit,
    compute_barrel_rate,
    compute_bat_speed,
    compute_exit_velocity,
    compute_hard_hit_rate,
    compute_ideal_attack_angle,
    compute_pull_audit,
    compute_sweet_spot_rate,
)

__all__ = ["ProfileMappingResult", "build_game_context", "map_profile_snapshot"]

# Fallback provenance exists for exactly one component in GM-020: Ideal
# Attack Angle %. Savant publishes an official IAA aggregate, so an approved
# acquisition hierarchy precedes EVENT_DERIVED for this metric, and choosing
# event derivation is a genuine fallback that must record why each
# higher-priority method was ineligible. Deterministic wording: these strings
# enter the frozen snapshot content.
#
# No other GM-020 metric carries a FallbackRecord: they are event-derived by
# definition in this slice, with no bypassed higher-priority route, and
# attaching this IAA-specific hierarchy to them would be false provenance.
_IAA_HIGHER_PRIORITY_INELIGIBLE = (
    MethodIneligibility(
        method=AcquisitionMethod.DIRECT_AGGREGATE,
        reason=(
            "the official published Ideal Attack Angle aggregate reflects the "
            "provider's current season-to-date state; it cannot be point-in-time "
            "verified for the exact profile window ending the day before the "
            "slate, and the official acquisition route remains unresolved (Q19)"
        ),
    ),
    MethodIneligibility(
        method=AcquisitionMethod.STRUCTURED_EXTRACT,
        reason=(
            "no structured official Ideal Attack Angle endpoint with "
            "point-in-time window control is available to the GM-020 slice"
        ),
    ),
    MethodIneligibility(
        method=AcquisitionMethod.RENDERED_SCRAPE,
        reason=(
            "the rendered Ideal Attack Angle leaderboard exposes only the "
            "provider's current aggregate, which cannot be point-in-time "
            "verified for the exact profile window"
        ),
    ),
)

_IAA_EVENT_DERIVED_FALLBACK = FallbackRecord(
    selected_method=AcquisitionMethod.EVENT_DERIVED,
    higher_priority_ineligible=_IAA_HIGHER_PRIORITY_INELIGIBLE,
)


@dataclass(frozen=True, slots=True)
class ProfileMappingResult:
    """One profile's frozen snapshot plus its audit companions."""

    snapshot: InputSnapshot
    pull_audit: PullAudit
    metric_computations: tuple[MetricComputation, ...]


def build_game_context(game: GameRecord, venue_timezone: str) -> GameContext:
    """The frozen-domain game identity from the provider-neutral records.

    The official MLB ``gamePk`` is the canonical ``GameId`` (never replaced),
    ``officialDate`` is the slate date (never derived from UTC), and the
    venue-local scheduled time is the same first-pitch instant rendered in the
    venue's IANA zone.
    """
    scheduled_utc = game.scheduled_start_utc
    local = scheduled_utc.astimezone(ZoneInfo(venue_timezone))
    return GameContext(
        game_id=GameId(str(game.game_pk)),
        slate_date=game.official_date,
        scheduled_start_utc=scheduled_utc,
        venue_local_scheduled_time=local,
        venue=Venue(
            venue_id=VenueId(str(game.venue_id)),
            name=game.venue_name,
            timezone=venue_timezone,
        ),
    )


def _window_instant(day: date) -> datetime:
    """Midnight UTC of an official date — the datetime rendering of a date bound."""
    return datetime.combine(day, time(0, 0), tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _ObservationContext:
    profile: WindowProfile
    window_start: datetime
    window_end: datetime
    as_of: datetime
    source_as_of: datetime
    retrieved_at: datetime
    source_capture_id: SourceCaptureId
    policy: SampleMinimumPolicy


def _coverage(context: _ObservationContext, sample_count: int, available: bool) -> DataCoverage:
    requested = CoverageWindow(start=context.window_start, end=context.window_end)
    if sample_count > 0:
        return DataCoverage(
            requested=requested,
            actual=requested,
            status=CoverageStatus.COMPLETE,
            source_available=True,
            sample_count=sample_count,
        )
    return DataCoverage(
        requested=requested,
        actual=None,
        status=CoverageStatus.NONE,
        source_available=available,
        sample_count=0,
    )


def _present(
    context: _ObservationContext,
    component: ComponentId,
    measurement: MeasurementId | None,
    computation: MetricComputation,
    sample_type: SampleType,
    fallback: FallbackRecord | None,
) -> MetricObservation:
    if computation.value is None:
        raise ValueError(f"_present requires a computed value for {computation.name}")
    minimum = context.policy.minimum_for(component, context.profile)
    status = (
        SampleStatus.SUFFICIENT
        if computation.sample_count >= minimum
        else SampleStatus.INSUFFICIENT
    )
    return MetricObservation(
        component_id=component,
        measurement_id=measurement,
        window_profile=context.profile,
        window_start=context.window_start,
        window_end=context.window_end,
        as_of=context.as_of,
        raw_value=computation.value,
        unit=computation.unit,
        sample_type=sample_type,
        sample_count=computation.sample_count,
        minimum_sample_required=minimum,
        sample_status=status,
        data_coverage=_coverage(context, computation.sample_count, True),
        provider_id=ProviderId.BASEBALL_SAVANT,
        acquisition_method=AcquisitionMethod.EVENT_DERIVED,
        source_as_of=context.source_as_of,
        retrieved_at=context.retrieved_at,
        source_capture_id=context.source_capture_id,
        fallback_used=fallback,
    )


def _missing(
    context: _ObservationContext,
    component: ComponentId,
    measurement: MeasurementId | None,
    sample_type: SampleType,
    reason: MissingReason,
    provider: ProviderId | None,
    source_reached: bool,
) -> MissingObservation:
    return MissingObservation(
        component_id=component,
        measurement_id=measurement,
        window_profile=context.profile,
        window_start=context.window_start,
        window_end=context.window_end,
        as_of=context.as_of,
        sample_type=sample_type,
        provider_id=provider,
        source_capture_id=context.source_capture_id,
        missing_reason=reason,
        data_coverage=_coverage(context, 0, source_reached),
    )


def _event_metric_reason(
    computation: MetricComputation, rows_eligible: int, tracked_metric: bool
) -> MissingReason:
    """The accurate missing reason for an empty event-derived denominator."""
    if rows_eligible == 0:
        return MissingReason.NO_EVENTS_IN_WINDOW
    if tracked_metric:
        return MissingReason.TRACKING_UNAVAILABLE
    excluded_total = sum(count for _, count in computation.exclusions)
    if excluded_total > 0:
        return MissingReason.INVALID_SOURCE_VALUE
    return MissingReason.NO_EVENTS_IN_WINDOW


def map_profile_snapshot(
    *,
    profile: WindowProfile,
    events: EligibleBatterEvents,
    game: GameRecord,
    venue_timezone: str,
    batter_id: int,
    batter_full_name: str,
    expected_pitcher: ExpectedPitcherRecord,
    policy: SampleMinimumPolicy,
    source_capture_id: SourceCaptureId,
    as_of: datetime,
    source_as_of: datetime,
    retrieved_at: datetime,
) -> ProfileMappingResult:
    """Freeze one profile-specific ``InputSnapshot`` from its eligible events.

    The caller supplies the coordinated run's shared ``SourceCaptureId`` and
    instants; the sample-minimum policy is explicit and complete or this
    function never runs (the policy type rejects incompleteness at
    construction). Every metric that cannot produce a value becomes a typed
    ``MissingObservation`` with an accurate reason — never zero, never ``None``.
    """
    report = events.report
    context = _ObservationContext(
        profile=profile,
        window_start=_window_instant(report.window_start),
        window_end=_window_instant(report.window_end_exclusive),
        as_of=as_of,
        source_as_of=source_as_of,
        retrieved_at=retrieved_at,
        source_capture_id=source_capture_id,
        policy=policy,
    )
    rows = events.rows
    rows_eligible = report.rows_eligible

    exit_velocity = compute_exit_velocity(rows)
    barrel = compute_barrel_rate(rows)
    hard_hit = compute_hard_hit_rate(rows)
    sweet_spot = compute_sweet_spot_rate(rows)
    bat_speed = compute_bat_speed(rows)
    ideal_attack_angle = compute_ideal_attack_angle(rows)
    pull_audit = compute_pull_audit(rows)

    present: list[MetricObservation] = []
    missing: list[MissingObservation] = []

    def place(
        component: ComponentId,
        measurement: MeasurementId | None,
        computation: MetricComputation,
        sample_type: SampleType,
        tracked_metric: bool,
        fallback: FallbackRecord | None = None,
    ) -> None:
        if computation.value is not None:
            present.append(
                _present(context, component, measurement, computation, sample_type, fallback)
            )
        else:
            missing.append(
                _missing(
                    context,
                    component,
                    measurement,
                    sample_type,
                    _event_metric_reason(computation, rows_eligible, tracked_metric),
                    ProviderId.BASEBALL_SAVANT,
                    True,
                )
            )

    place(ComponentId.EXIT_VELOCITY, None, exit_velocity, SampleType.BATTED_BALL_EVENTS, False)
    place(ComponentId.BARREL_PCT, None, barrel, SampleType.BATTED_BALL_EVENTS, False)
    place(ComponentId.HARD_HIT_PCT, None, hard_hit, SampleType.BATTED_BALL_EVENTS, False)
    place(ComponentId.SWEET_SPOT_PCT, None, sweet_spot, SampleType.BATTED_BALL_EVENTS, False)
    place(ComponentId.BAT_SPEED, None, bat_speed, SampleType.SWINGS, True)
    place(
        ComponentId.ATTACK_ANGLE_QUALITY,
        MeasurementId.IDEAL_ATTACK_ANGLE_PCT,
        ideal_attack_angle,
        SampleType.SWINGS,
        True,
        fallback=_IAA_EVENT_DERIVED_FALLBACK,
    )
    place(
        ComponentId.PULL_PCT_AIR_BALLS,
        None,
        pull_audit.pull_air,
        SampleType.AIR_BALLS,
        False,
    )

    # Pitcher-matchup components: ingredients are captured and audited, but the
    # Q15/Q16 formulas are undefined, so no value may be invented. Interim
    # frozen-vocabulary mapping: SOURCE_UNAVAILABLE (no eligible source can
    # produce the undefined derivation) — see docs/GM_020_VERTICAL_SLICE.md.
    for matchup_component in (
        ComponentId.PITCH_MIX_PRESSURE,
        ComponentId.PUT_AWAY_PITCH_EXPLOITATION,
    ):
        missing.append(
            _missing(
                context,
                matchup_component,
                None,
                SampleType.PITCHES,
                MissingReason.SOURCE_UNAVAILABLE,
                ProviderId.BASEBALL_SAVANT,
                True,
            )
        )

    # Park: no provider chosen in GM-020. Weather: no forecast source exists,
    # and weather_is_forecast stays False because no present weather
    # observation exists at all.
    missing.append(
        _missing(
            context,
            ComponentId.PARK,
            None,
            SampleType.GAMES,
            MissingReason.SOURCE_UNAVAILABLE,
            None,
            False,
        )
    )
    missing.append(
        _missing(
            context,
            ComponentId.WEATHER,
            None,
            SampleType.GAMES,
            MissingReason.WEATHER_UNAVAILABLE,
            None,
            False,
        )
    )

    snapshot = freeze_input_snapshot(
        source_capture_id=source_capture_id,
        game_context=build_game_context(game, venue_timezone),
        batter=Batter(player_id=PlayerId(str(batter_id)), full_name=batter_full_name),
        expected_starting_pitcher=Pitcher(
            player_id=PlayerId(str(expected_pitcher.pitcher_id)),
            full_name=expected_pitcher.full_name,
            role=expected_pitcher.role,
        ),
        pitcher_role=expected_pitcher.role,
        as_of=as_of,
        window_profile=profile,
        window_start=context.window_start,
        window_end=context.window_end,
        present_observations=tuple(present),
        missing_observations=tuple(missing),
        validation_inputs=(),
        weather_is_forecast=False,
    )
    return ProfileMappingResult(
        snapshot=snapshot,
        pull_audit=pull_audit,
        metric_computations=(
            exit_velocity,
            barrel,
            hard_hit,
            sweet_spot,
            bat_speed,
            ideal_attack_angle,
            pull_audit.pull_air,
        ),
    )

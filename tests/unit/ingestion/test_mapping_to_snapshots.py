"""Mapping eligible events into the frozen InputSnapshot contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from tests.fixtures.ingestion import synthetic_provider_fixtures as fixtures
from tests.unit.ingestion.test_models_and_policy import complete_policy_entries

from greenmachine.domain import (
    AcquisitionMethod,
    ComponentId,
    MeasurementId,
    MissingReason,
    PitcherRole,
    ProviderId,
    SampleStatus,
    SourceCaptureId,
    WindowProfile,
)
from greenmachine.ingestion.errors import SamplePolicyError
from greenmachine.ingestion.events import normalize_batter_events
from greenmachine.ingestion.mapping import map_profile_snapshot
from greenmachine.ingestion.models import (
    ExpectedPitcherRecord,
    GameRecord,
    SampleMinimumPolicy,
)
from greenmachine.ingestion.savant.parser import parse_batter_events

SLATE = date(2026, 7, 15)
AS_OF = datetime(2026, 7, 15, 18, 0, tzinfo=UTC)
CAPTURE = SourceCaptureId("source_capture-" + "c" * 64)

GAME = GameRecord(
    game_pk=fixtures.GAME_PK,
    game_type="R",
    official_date=SLATE,
    scheduled_start_utc=datetime(2026, 7, 15, 23, 10, tzinfo=UTC),
    status_abstract="Preview",
    status_detailed="Scheduled",
    home_team_id=fixtures.HOME_TEAM_ID,
    away_team_id=fixtures.AWAY_TEAM_ID,
    venue_id=fixtures.VENUE_ID,
    venue_name=fixtures.VENUE_NAME,
)
PITCHER = ExpectedPitcherRecord(
    game_pk=fixtures.GAME_PK,
    pitcher_id=fixtures.PITCHER_ID,
    full_name=fixtures.PITCHER_NAME,
    role=PitcherRole.EXPECTED_STARTER,
    batter_team_side="home",
    note=None,
)
POLICY = SampleMinimumPolicy(
    disclaimer="GM-020 vertical-slice validation only; not production.",
    entries=complete_policy_entries(recent=2, long_term=13),
)


def mapped(rows: list[dict[str, str]], policy: SampleMinimumPolicy = POLICY) -> object:
    events = normalize_batter_events(
        parse_batter_events(fixtures.batter_csv(rows)),
        profile=WindowProfile.RECENT_7D,
        window_start=date(2026, 7, 8),
        window_end_exclusive=SLATE,
        selected_game_pk=fixtures.GAME_PK,
        expected_batter_id=fixtures.BATTER_ID,
    )
    return map_profile_snapshot(
        profile=WindowProfile.RECENT_7D,
        events=events,
        game=GAME,
        venue_timezone=fixtures.VENUE_TZ,
        batter_id=fixtures.BATTER_ID,
        batter_full_name=fixtures.BATTER_NAME,
        expected_pitcher=PITCHER,
        policy=policy,
        source_capture_id=CAPTURE,
        as_of=AS_OF,
        source_as_of=AS_OF,
        retrieved_at=AS_OF,
    )


def test_only_ideal_attack_angle_carries_fallback_provenance() -> None:
    """The exact fallback set: {ATTACK_ANGLE_QUALITY} — and nothing else.

    IAA is the one GM-020 metric with an approved higher-priority acquisition
    hierarchy (the official published aggregate) that event derivation
    deliberately bypasses. Attaching that record to any other metric would be
    false provenance.
    """
    result = mapped(fixtures.default_recent_rows())
    snapshot = result.snapshot  # type: ignore[attr-defined]

    by_component = {
        observation.component_id: observation for observation in snapshot.present_observations
    }
    with_fallback = {
        component
        for component, observation in by_component.items()
        if observation.fallback_used is not None
    }
    assert with_fallback == {ComponentId.ATTACK_ANGLE_QUALITY}

    attack_angle = by_component[ComponentId.ATTACK_ANGLE_QUALITY]
    assert attack_angle.fallback_used is not None
    assert attack_angle.fallback_used.selected_method is AcquisitionMethod.EVENT_DERIVED
    ineligible = {
        record.method: record.reason
        for record in attack_angle.fallback_used.higher_priority_ineligible
    }
    # Only methods that genuinely precede EVENT_DERIVED in the IAA hierarchy,
    # each with an IAA-specific explanation.
    assert set(ineligible) == {
        AcquisitionMethod.DIRECT_AGGREGATE,
        AcquisitionMethod.STRUCTURED_EXTRACT,
        AcquisitionMethod.RENDERED_SCRAPE,
    }
    for reason in ineligible.values():
        assert "Ideal Attack Angle" in reason


def test_present_observations_are_event_derived_and_typed() -> None:
    result = mapped(fixtures.default_recent_rows())
    snapshot = result.snapshot  # type: ignore[attr-defined]

    by_component = {
        observation.component_id: observation for observation in snapshot.present_observations
    }
    exit_velocity = by_component[ComponentId.EXIT_VELOCITY]
    assert exit_velocity.acquisition_method is AcquisitionMethod.EVENT_DERIVED
    assert exit_velocity.provider_id is ProviderId.BASEBALL_SAVANT
    assert exit_velocity.fallback_used is None
    assert isinstance(exit_velocity.raw_value, Decimal)

    attack_angle = by_component[ComponentId.ATTACK_ANGLE_QUALITY]
    assert attack_angle.measurement_id is MeasurementId.IDEAL_ATTACK_ANGLE_PCT

    # Every other component carries no measurement id and no fallback record —
    # so no IAA-specific ineligibility reason can appear on another component.
    for component, observation in by_component.items():
        if component is not ComponentId.ATTACK_ANGLE_QUALITY:
            assert observation.measurement_id is None
            assert observation.fallback_used is None


def test_sample_status_comes_only_from_the_injected_policy() -> None:
    demanding = SampleMinimumPolicy(
        disclaimer="GM-020 vertical-slice validation only; not production.",
        entries=complete_policy_entries(recent=999, long_term=999),
    )
    result = mapped(fixtures.default_recent_rows(), policy=demanding)
    snapshot = result.snapshot  # type: ignore[attr-defined]
    statuses = {observation.sample_status for observation in snapshot.present_observations}
    assert statuses == {SampleStatus.INSUFFICIENT}
    minimums = {
        observation.minimum_sample_required for observation in snapshot.present_observations
    }
    assert minimums == {999}


def test_zero_eligible_events_map_to_no_events_in_window() -> None:
    result = mapped([])
    snapshot = result.snapshot  # type: ignore[attr-defined]
    assert snapshot.present_observations == ()
    reasons = {
        observation.component_id: observation.missing_reason
        for observation in snapshot.missing_observations
    }
    for component in (
        ComponentId.EXIT_VELOCITY,
        ComponentId.BARREL_PCT,
        ComponentId.HARD_HIT_PCT,
        ComponentId.SWEET_SPOT_PCT,
        ComponentId.BAT_SPEED,
        ComponentId.ATTACK_ANGLE_QUALITY,
        ComponentId.PULL_PCT_AIR_BALLS,
    ):
        assert reasons[component] is MissingReason.NO_EVENTS_IN_WINDOW, component


def test_untracked_metrics_map_to_tracking_unavailable() -> None:
    rows = [
        fixtures.batter_row(bat_speed="", attack_angle=""),
        fixtures.batter_row(at_bat_number="2", bat_speed="", attack_angle=""),
    ]
    result = mapped(rows)
    snapshot = result.snapshot  # type: ignore[attr-defined]
    reasons = {
        observation.component_id: observation.missing_reason
        for observation in snapshot.missing_observations
    }
    assert reasons[ComponentId.BAT_SPEED] is MissingReason.TRACKING_UNAVAILABLE
    assert reasons[ComponentId.ATTACK_ANGLE_QUALITY] is MissingReason.TRACKING_UNAVAILABLE


def test_air_balls_present_but_all_unusable_map_to_invalid_source_value() -> None:
    rows = [
        fixtures.batter_row(stand=""),  # air ball, invalid stand
        fixtures.batter_row(at_bat_number="2", hc_x="", hc_y=""),  # unusable coords
    ]
    result = mapped(rows)
    snapshot = result.snapshot  # type: ignore[attr-defined]
    reasons = {
        observation.component_id: observation.missing_reason
        for observation in snapshot.missing_observations
    }
    assert reasons[ComponentId.PULL_PCT_AIR_BALLS] is MissingReason.INVALID_SOURCE_VALUE


def test_pitch_composites_park_and_weather_remain_missing() -> None:
    result = mapped(fixtures.default_recent_rows())
    snapshot = result.snapshot  # type: ignore[attr-defined]
    reasons = {
        observation.component_id: observation.missing_reason
        for observation in snapshot.missing_observations
    }
    assert reasons[ComponentId.PITCH_MIX_PRESSURE] is MissingReason.SOURCE_UNAVAILABLE
    assert reasons[ComponentId.PUT_AWAY_PITCH_EXPLOITATION] is MissingReason.SOURCE_UNAVAILABLE
    assert reasons[ComponentId.PARK] is MissingReason.SOURCE_UNAVAILABLE
    assert reasons[ComponentId.WEATHER] is MissingReason.WEATHER_UNAVAILABLE
    assert snapshot.weather_is_forecast is False


def test_overall_pull_never_enters_the_snapshot() -> None:
    result = mapped(fixtures.default_recent_rows())
    snapshot = result.snapshot  # type: ignore[attr-defined]
    components = {
        observation.component_id
        for observation in snapshot.present_observations + snapshot.missing_observations
    }
    # Exactly the eleven scored components appear — nothing extra for Overall
    # Pull %, and its value lives only in the audit companion.
    assert components == set(ComponentId)
    assert result.pull_audit.overall_pull.name == "overall_pull_rate"  # type: ignore[attr-defined]


def test_the_snapshot_window_and_identity_are_exact() -> None:
    result = mapped(fixtures.default_recent_rows())
    snapshot = result.snapshot  # type: ignore[attr-defined]
    assert snapshot.window_start == datetime(2026, 7, 8, 0, 0, tzinfo=UTC)
    assert snapshot.window_end == datetime(2026, 7, 15, 0, 0, tzinfo=UTC)
    assert snapshot.as_of == AS_OF
    assert snapshot.game_context.game_id.value == str(fixtures.GAME_PK)
    assert snapshot.game_context.slate_date == SLATE
    assert snapshot.batter.player_id.value == str(fixtures.BATTER_ID)
    assert snapshot.expected_starting_pitcher.player_id.value == str(fixtures.PITCHER_ID)
    assert snapshot.source_capture_id == CAPTURE


def test_an_incomplete_policy_prevents_any_mapping() -> None:
    with pytest.raises(SamplePolicyError, match="incomplete"):
        SampleMinimumPolicy(
            disclaimer="validation only",
            entries=complete_policy_entries()[:-1],
        )

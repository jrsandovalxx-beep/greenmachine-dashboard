"""Snapshot builders for GM-041 engine tests.

Builds frozen RECENT_7D snapshots covering exactly the eleven components of
``tests/fixtures/config/valid/gm041_engine_synthetic.yaml``, with per-test
control over values, missing components, insufficient samples, absent
observations, and the attack-angle measurement. Values default to the middle
of known synthetic buckets so the expected derivation is easy to compute by
hand in tests. Everything is visibly synthetic.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

import synthetic_records

from greenmachine.domain import (
    ComponentId,
    InputSnapshot,
    MeasurementId,
    MetricObservation,
    MissingObservation,
    MissingReason,
    PitcherRole,
    SampleType,
)
from greenmachine.evaluation import freeze_input_snapshot

# component -> (default value, unit, sample type, sufficient count, configured minimum)
_DEFAULTS: dict[ComponentId, tuple[str, str, SampleType, int, int]] = {
    ComponentId.EXIT_VELOCITY: ("95", "mph", SampleType.BATTED_BALL_EVENTS, 5, 2),
    ComponentId.BARREL_PCT: ("8", "percent", SampleType.BATTED_BALL_EVENTS, 5, 2),
    ComponentId.HARD_HIT_PCT: ("60", "percent", SampleType.BATTED_BALL_EVENTS, 5, 2),
    ComponentId.PITCH_MIX_PRESSURE: ("60", "index", SampleType.PITCHES, 5, 2),
    ComponentId.PUT_AWAY_PITCH_EXPLOITATION: ("60", "index", SampleType.PITCHES, 5, 2),
    ComponentId.SWEET_SPOT_PCT: ("30", "percent", SampleType.BATTED_BALL_EVENTS, 5, 2),
    ComponentId.ATTACK_ANGLE_QUALITY: ("55", "percent", SampleType.SWINGS, 5, 2),
    ComponentId.BAT_SPEED: ("75", "mph", SampleType.SWINGS, 5, 2),
    ComponentId.PULL_PCT_AIR_BALLS: ("33", "percent", SampleType.AIR_BALLS, 5, 2),
    ComponentId.PARK: ("60", "index", SampleType.GAMES, 1, 1),
    ComponentId.WEATHER: ("60", "index", SampleType.GAMES, 1, 1),
}

# With every default value, the synthetic fixture awards:
# power 1.1+0.45+0.8=2.35 · matchup 1.6+1.5=3.1 · form 0.7+0.8+0.6=2.1 ·
# pull 2.2 · environment 1+0.8=1.8 → total 11.55 → grade S.
DEFAULT_TOTAL = "11.55"


def engine_snapshot(
    *,
    values: Mapping[ComponentId, str] | None = None,
    missing: Mapping[ComponentId, MissingReason] | None = None,
    insufficient: Collection[ComponentId] = (),
    absent: Collection[ComponentId] = (),
    aaq_measurement: MeasurementId = MeasurementId.IDEAL_ATTACK_ANGLE_PCT,
    minimum_overrides: Mapping[ComponentId, int] | None = None,
    sample_type_overrides: Mapping[ComponentId, SampleType] | None = None,
) -> InputSnapshot:
    """A frozen snapshot over the eleven GM-041 fixture components.

    ``values`` overrides observed values; ``missing`` turns components into
    typed missing observations; ``insufficient`` drops a component's sample
    below its configured minimum (still present, still scored, labeled
    INSUFFICIENT); ``absent`` removes the component's observation entirely
    (to prove the engine fails closed on snapshot/config disagreement).

    ``minimum_overrides`` and ``sample_type_overrides`` deliberately
    desynchronise an observation from the configuration that describes it, so
    the coherence guard can be tested. They exist only to build snapshots the
    engine must refuse; nothing in production produces one.
    """
    values = dict(values or {})
    missing = dict(missing or {})
    minimum_overrides = dict(minimum_overrides or {})
    sample_type_overrides = dict(sample_type_overrides or {})
    present_observations: list[MetricObservation] = []
    missing_observations: list[MissingObservation] = []

    for component, (value, unit, base_type, count, base_minimum) in _DEFAULTS.items():
        if component in absent:
            continue
        sample_type = sample_type_overrides.get(component, base_type)
        minimum = minimum_overrides.get(component, base_minimum)
        if component in missing:
            missing_observations.append(
                synthetic_records.missing_observation(component, missing[component], sample_type)
            )
            continue
        sample_count = base_minimum - 1 if component in insufficient else count
        measurement = aaq_measurement if component is ComponentId.ATTACK_ANGLE_QUALITY else None
        present_observations.append(
            synthetic_records.metric_observation(
                component,
                raw_value=values.get(component, value),
                unit=unit,
                sample_type=sample_type,
                sample_count=sample_count,
                minimum=minimum,
                measurement_id=measurement,
            )
        )

    return freeze_input_snapshot(
        source_capture_id=synthetic_records.CAPTURE,
        game_context=synthetic_records.game_context(),
        batter=synthetic_records.batter(),
        expected_starting_pitcher=synthetic_records.pitcher(),
        pitcher_role=PitcherRole.EXPECTED_STARTER,
        as_of=synthetic_records.AS_OF,
        window_profile=present_observations[0].window_profile
        if present_observations
        else missing_observations[0].window_profile,
        window_start=synthetic_records.WINDOW_START,
        window_end=synthetic_records.WINDOW_END,
        present_observations=tuple(present_observations),
        missing_observations=tuple(missing_observations),
        validation_inputs=(),
        weather_is_forecast=any(
            observation.component_id is ComponentId.WEATHER for observation in present_observations
        ),
    )

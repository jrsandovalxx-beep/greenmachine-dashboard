"""The test-only stub scorer: deterministic, profile-distinct, and unmistakably a stub.

The stub must never resemble a scoring engine: fixed synthetic constants keyed
only by :class:`WindowProfile`, observations preserved verbatim, required
advisory findings emitted, and an audit trail that says it is a stub.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import synthetic_golden_cases
import synthetic_records
from tests.golden.stub_scorer import score_snapshot

from greenmachine.domain import (
    ComponentId,
    EvaluatedGradeResult,
    Grade,
    NotEvaluableGradeResult,
    SampleStatus,
    SampleType,
    ValidationInputId,
    WindowProfile,
)
from greenmachine.evaluation import serialize_record

CONFIG_VERSION = synthetic_golden_cases.GOLDEN_CONFIG_VERSION


def test_stub_output_is_deterministic() -> None:
    snapshot = synthetic_records.input_snapshot()
    first = score_snapshot(snapshot, CONFIG_VERSION)
    second = score_snapshot(snapshot, CONFIG_VERSION)
    assert first == second
    assert serialize_record(first) == serialize_record(second)


def test_profiles_produce_distinct_results() -> None:
    recent = score_snapshot(synthetic_records.input_snapshot(), CONFIG_VERSION)
    long_term = score_snapshot(synthetic_records.input_snapshot_long_term(), CONFIG_VERSION)

    assert isinstance(recent, EvaluatedGradeResult)
    assert isinstance(long_term, EvaluatedGradeResult)
    assert recent.window_profile is WindowProfile.RECENT_7D
    assert long_term.window_profile is WindowProfile.LONG_TERM_2Y
    assert recent.total_score != long_term.total_score
    assert recent.grade is not long_term.grade
    assert serialize_record(recent) != serialize_record(long_term)


def test_snapshot_observations_and_profile_are_preserved_verbatim() -> None:
    snapshot = synthetic_records.input_snapshot()
    result = score_snapshot(snapshot, CONFIG_VERSION)

    assert result.window_profile is snapshot.window_profile
    assert result.present_observations == snapshot.present_observations
    assert result.missing_observations == snapshot.missing_observations


def test_every_present_observation_receives_exactly_one_component_score() -> None:
    snapshot = synthetic_records.input_snapshot()
    result = score_snapshot(snapshot, CONFIG_VERSION)

    assert isinstance(result, EvaluatedGradeResult)
    scored = [(s.component_id, s.measurement_id) for s in result.component_scores]
    observed = [(o.component_id, o.measurement_id) for o in snapshot.present_observations]
    assert scored == observed
    assert all(s.bucket_hit is None for s in result.component_scores)


def _frozen_recent_snapshot(
    observations: tuple,  # type: ignore[type-arg]
    *,
    weather_is_forecast: bool = False,
) -> object:
    """Freeze a RECENT_7D snapshot around the given present observations."""
    from greenmachine.domain import PitcherRole
    from greenmachine.evaluation import freeze_input_snapshot

    return freeze_input_snapshot(
        source_capture_id=synthetic_records.CAPTURE,
        game_context=synthetic_records.game_context(),
        batter=synthetic_records.batter(),
        expected_starting_pitcher=synthetic_records.pitcher(),
        pitcher_role=PitcherRole.EXPECTED_STARTER,
        as_of=synthetic_records.AS_OF,
        window_profile=WindowProfile.RECENT_7D,
        window_start=synthetic_records.WINDOW_START,
        window_end=synthetic_records.WINDOW_END,
        present_observations=observations,
        missing_observations=(),
        validation_inputs=(),
        weather_is_forecast=weather_is_forecast,
    )


def test_two_insufficient_attack_angle_measurements_produce_one_warning() -> None:
    """The frozen contract requires one advisory per insufficient *component*.

    A coherent snapshot may hold both attack_angle_quality measurements, each
    with an insufficient sample; the stub must collapse them to exactly one
    SAMPLE_WARNINGS finding for the component.
    """
    from greenmachine.domain import MeasurementId

    ideal = synthetic_records.metric_observation(
        ComponentId.ATTACK_ANGLE_QUALITY,
        raw_value="7.7",
        unit="percent",
        sample_type=SampleType.BATTED_BALL_EVENTS,
        sample_count=1,
        minimum=4,
        measurement_id=MeasurementId.IDEAL_ATTACK_ANGLE_PCT,
    )
    proxy = synthetic_records.metric_observation(
        ComponentId.ATTACK_ANGLE_QUALITY,
        raw_value="6.6",
        unit="synthetic_proxy_units",
        sample_type=SampleType.BATTED_BALL_EVENTS,
        sample_count=2,
        minimum=4,
        measurement_id=MeasurementId.ATTACK_ANGLE_THRESHOLD_PROXY,
    )
    snapshot = _frozen_recent_snapshot((ideal, proxy))

    result = score_snapshot(snapshot, CONFIG_VERSION)

    assert isinstance(result, EvaluatedGradeResult)
    warnings = [
        finding
        for finding in result.validation_findings
        if finding.input_id is ValidationInputId.SAMPLE_WARNINGS
    ]
    assert len(warnings) == 1
    assert warnings[0].component_id is ComponentId.ATTACK_ANGLE_QUALITY
    # Both measurements are still preserved and scored as observations:
    assert len(result.present_observations) == 2
    assert len(result.component_scores) == 2


def test_two_different_insufficient_components_produce_two_warnings() -> None:
    barrel = synthetic_records.metric_observation(
        ComponentId.BARREL_PCT,
        raw_value="3.9",
        unit="percent",
        sample_type=SampleType.BATTED_BALL_EVENTS,
        sample_count=1,
        minimum=3,
    )
    weather = synthetic_records.metric_observation(
        ComponentId.WEATHER,
        raw_value="1.7",
        unit="forecast_index",
        sample_type=SampleType.GAMES,
        sample_count=1,
        minimum=5,
    )
    snapshot = _frozen_recent_snapshot((barrel, weather), weather_is_forecast=True)

    result = score_snapshot(snapshot, CONFIG_VERSION)

    warnings = [
        finding
        for finding in result.validation_findings
        if finding.input_id is ValidationInputId.SAMPLE_WARNINGS
    ]
    # Exactly one warning per distinct component, in first-occurrence order.
    assert [warning.component_id for warning in warnings] == [
        ComponentId.BARREL_PCT,
        ComponentId.WEATHER,
    ]


def test_warning_deduplication_is_deterministic_across_repeated_runs() -> None:
    from greenmachine.domain import MeasurementId

    ideal = synthetic_records.metric_observation(
        ComponentId.ATTACK_ANGLE_QUALITY,
        raw_value="7.7",
        unit="percent",
        sample_type=SampleType.BATTED_BALL_EVENTS,
        sample_count=1,
        minimum=4,
        measurement_id=MeasurementId.IDEAL_ATTACK_ANGLE_PCT,
    )
    proxy = synthetic_records.metric_observation(
        ComponentId.ATTACK_ANGLE_QUALITY,
        raw_value="6.6",
        unit="synthetic_proxy_units",
        sample_type=SampleType.BATTED_BALL_EVENTS,
        sample_count=2,
        minimum=4,
        measurement_id=MeasurementId.ATTACK_ANGLE_THRESHOLD_PROXY,
    )
    snapshot = _frozen_recent_snapshot((ideal, proxy))

    first = score_snapshot(snapshot, CONFIG_VERSION)
    second = score_snapshot(snapshot, CONFIG_VERSION)

    assert first == second
    assert serialize_record(first) == serialize_record(second)


def test_committed_expected_files_are_exactly_the_stub_output() -> None:
    """The deduplication change leaves every committed golden byte-identical."""
    from tests.golden.runner import CASES_ROOT, discover_cases

    for case in discover_cases(CASES_ROOT):
        committed = (case.directory / case.expected_filename).read_bytes()
        regenerated = serialize_record(
            score_snapshot(case.snapshot, case.config_version_identifier)
        )
        assert regenerated == committed, case.case_id


def test_insufficient_samples_get_one_advisory_finding_each() -> None:
    snapshot = synthetic_records.input_snapshot()
    insufficient = [
        o.component_id
        for o in snapshot.present_observations
        if o.sample_status is SampleStatus.INSUFFICIENT
    ]
    assert insufficient == [ComponentId.BARREL_PCT]  # fixture sanity

    result = score_snapshot(snapshot, CONFIG_VERSION)
    warnings = [
        finding
        for finding in result.validation_findings
        if finding.input_id is ValidationInputId.SAMPLE_WARNINGS
    ]
    assert [w.component_id for w in warnings] == insufficient


def test_audit_trail_is_nonempty_ordered_and_names_the_stub() -> None:
    result = score_snapshot(synthetic_records.input_snapshot(), CONFIG_VERSION)

    assert len(result.audit_derivation) >= 1
    sequences = [entry.sequence for entry in result.audit_derivation]
    assert sequences == sorted(sequences)
    for entry in result.audit_derivation:
        assert "stub" in entry.explanation.lower()
        assert entry.rule_reference == CONFIG_VERSION


def test_config_version_is_used_only_as_an_audit_reference() -> None:
    """A different config identifier changes audit text, never any value."""
    snapshot = synthetic_records.input_snapshot()
    first = score_snapshot(snapshot, CONFIG_VERSION)
    second = score_snapshot(snapshot, "synthetic-fixture-other")

    assert isinstance(first, EvaluatedGradeResult)
    assert isinstance(second, EvaluatedGradeResult)
    assert first.total_score == second.total_score
    assert first.grade is second.grade
    assert first.component_scores == second.component_scores
    assert {e.rule_reference for e in second.audit_derivation} == {"synthetic-fixture-other"}


def test_metric_values_do_not_influence_the_stub() -> None:
    """Different raw values, same structure: identical points and grade."""
    baseline = synthetic_records.input_snapshot()
    alternate_exit = synthetic_records.metric_observation(
        ComponentId.EXIT_VELOCITY,
        raw_value="77.7",
        unit="mph",
        sample_type=SampleType.BATTED_BALL_EVENTS,
        sample_count=12,
        minimum=3,
    )
    from greenmachine.domain import PitcherRole
    from greenmachine.evaluation import freeze_input_snapshot

    altered = freeze_input_snapshot(
        source_capture_id=synthetic_records.CAPTURE,
        game_context=synthetic_records.game_context(),
        batter=synthetic_records.batter(),
        expected_starting_pitcher=synthetic_records.pitcher(),
        pitcher_role=PitcherRole.EXPECTED_STARTER,
        as_of=synthetic_records.AS_OF,
        window_profile=WindowProfile.RECENT_7D,
        window_start=synthetic_records.WINDOW_START,
        window_end=synthetic_records.WINDOW_END,
        present_observations=(
            alternate_exit,
            synthetic_records.present_barrel_insufficient(),
            synthetic_records.present_weather_forecast(),
        ),
        missing_observations=(synthetic_records.missing_bat_speed(),),
        validation_inputs=synthetic_records.validation_inputs(),
        weather_is_forecast=True,
    )

    first = score_snapshot(baseline, CONFIG_VERSION)
    second = score_snapshot(altered, CONFIG_VERSION)

    assert isinstance(first, EvaluatedGradeResult)
    assert isinstance(second, EvaluatedGradeResult)
    assert first.total_score == second.total_score
    assert first.grade is second.grade
    assert [s.points_awarded for s in first.component_scores] == [
        s.points_awarded for s in second.component_scores
    ]


def test_stub_values_are_visibly_synthetic() -> None:
    recent = score_snapshot(synthetic_records.input_snapshot(), CONFIG_VERSION)
    assert isinstance(recent, EvaluatedGradeResult)
    assert recent.total_score == Decimal("1.111")
    assert recent.grade is Grade.C


def test_snapshot_without_present_observations_becomes_not_evaluable() -> None:
    snapshot = synthetic_golden_cases.not_evaluable_input_snapshot()
    result = score_snapshot(snapshot, CONFIG_VERSION)

    assert isinstance(result, NotEvaluableGradeResult)
    assert result.window_profile is WindowProfile.RECENT_7D
    cited = [
        (entry.component_id, entry.missing_reason) for entry in result.unavailable_required_inputs
    ]
    expected = [(o.component_id, o.missing_reason) for o in snapshot.missing_observations]
    assert cited == expected
    for entry in result.unavailable_required_inputs:
        assert entry.missing_observation in snapshot.missing_observations
    assert not hasattr(result, "total_score")
    assert not hasattr(result, "grade")


def test_snapshot_with_no_observations_at_all_is_rejected() -> None:
    """A snapshot with neither present nor missing observations is incoherent."""
    from greenmachine.domain import PitcherRole
    from greenmachine.evaluation import freeze_input_snapshot

    empty = freeze_input_snapshot(
        source_capture_id=synthetic_golden_cases.NOT_EVALUABLE_CAPTURE,
        game_context=synthetic_records.game_context(),
        batter=synthetic_records.batter(),
        expected_starting_pitcher=synthetic_records.pitcher(),
        pitcher_role=PitcherRole.EXPECTED_STARTER,
        as_of=synthetic_records.AS_OF,
        window_profile=WindowProfile.RECENT_7D,
        window_start=synthetic_records.WINDOW_START,
        window_end=synthetic_records.WINDOW_END,
        present_observations=(),
        missing_observations=(),
        validation_inputs=(),
        weather_is_forecast=False,
    )
    with pytest.raises(ValueError, match="at least one observation"):
        score_snapshot(empty, CONFIG_VERSION)


def test_invalid_arguments_are_rejected() -> None:
    with pytest.raises(TypeError, match="expects an InputSnapshot"):
        score_snapshot("not a snapshot", CONFIG_VERSION)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-blank"):
        score_snapshot(synthetic_records.input_snapshot(), "   ")


def test_stub_results_serialize_as_canonical_records() -> None:
    """Both variants round-trip through the frozen GM-006 serialization."""
    from greenmachine.evaluation import deserialize_record

    recent = score_snapshot(synthetic_records.input_snapshot(), CONFIG_VERSION)
    not_evaluable = score_snapshot(
        synthetic_golden_cases.not_evaluable_input_snapshot(), CONFIG_VERSION
    )
    assert deserialize_record(serialize_record(recent)) == recent
    assert deserialize_record(serialize_record(not_evaluable)) == not_evaluable

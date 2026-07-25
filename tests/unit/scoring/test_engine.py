"""GM-041 engine unit suite, driven by the disclaimed synthetic configuration.

Every expected number below is derivable by hand from
``tests/fixtures/config/valid/gm041_engine_synthetic.yaml`` — deliberately
wrong-for-baseball values that can never be mistaken for the approved model
(Q11-Q16 remain open).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from gm041_engine_snapshots import DEFAULT_TOTAL, engine_snapshot

from greenmachine.config import (
    ConfigSemanticError,
    FuzzyScoringPolicy,
    GreenMachineConfig,
    load_config,
    load_config_text,
)
from greenmachine.domain import (
    Category,
    ComponentId,
    EvaluatedGradeResult,
    Grade,
    MeasurementId,
    MissingReason,
    NotEvaluableGradeResult,
    SampleType,
    ValidationInputId,
)
from greenmachine.evaluation import serialize_record
from greenmachine.scoring import (
    OBSERVED_VALUE_INPUT_NAME,
    ScoringConfigError,
    ScoringInputError,
    score_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "config" / "valid" / ("gm041_engine_synthetic.yaml")
)


@pytest.fixture(scope="module")
def config() -> GreenMachineConfig:
    return load_config(FIXTURE_PATH)


def _fixture_text() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


def _variant(original: str, replacement: str, occurrences: int = 1) -> GreenMachineConfig:
    text = _fixture_text()
    assert original in text, f"variant anchor not found: {original!r}"
    return load_config_text(text.replace(original, replacement, occurrences), file_path="variant")


ZEROING_VALUES = {
    ComponentId.EXIT_VELOCITY: "50",
    ComponentId.BARREL_PCT: "5",
    ComponentId.HARD_HIT_PCT: "30",
    ComponentId.PITCH_MIX_PRESSURE: "40",
    ComponentId.PUT_AWAY_PITCH_EXPLOITATION: "40",
    ComponentId.SWEET_SPOT_PCT: "20",
    ComponentId.ATTACK_ANGLE_QUALITY: "40",
    ComponentId.BAT_SPEED: "70",
    ComponentId.PULL_PCT_AIR_BALLS: "10",
    ComponentId.PARK: "40",
    ComponentId.WEATHER: "40",
}


def _points(result: EvaluatedGradeResult, component: ComponentId) -> Decimal:
    for score in result.component_scores:
        if score.component_id is component:
            return score.points_awarded
    raise AssertionError(f"no component score for {component.value}")


# --------------------------------------------------------------------------
# The synthetic fixture itself
# --------------------------------------------------------------------------


def test_the_synthetic_fixture_loads_and_is_loudly_disclaimed(
    config: GreenMachineConfig,
) -> None:
    assert config.model_configuration_version == "gm041-engine-synthetic-0"
    header = _fixture_text().splitlines()[0]
    assert "SYNTHETIC" in header and "NOT A MODEL CONFIGURATION" in header


# --------------------------------------------------------------------------
# Full evaluation over the default snapshot
# --------------------------------------------------------------------------


def test_a_full_snapshot_evaluates_with_exact_arithmetic(
    config: GreenMachineConfig,
) -> None:
    result = score_snapshot(engine_snapshot(), config)
    assert isinstance(result, EvaluatedGradeResult)
    assert result.total_score == Decimal("11.55")
    assert result.grade is Grade.S

    by_category = {score.category: score.points_awarded for score in result.category_scores}
    assert by_category == {
        Category.POWER_PROFILE: Decimal("2.35"),
        Category.PITCHER_MATCHUP: Decimal("3.1"),
        Category.FORM: Decimal("2.1"),
        Category.PULL_POWER: Decimal("2.2"),
        Category.ENVIRONMENT: Decimal("1.8"),
    }
    assert len(result.component_scores) == 11


def test_every_component_and_stage_appears_in_the_audit_derivation(
    config: GreenMachineConfig,
) -> None:
    result = score_snapshot(engine_snapshot(), config)
    audited_components = {
        entry.component_id for entry in result.audit_derivation if entry.component_id
    }
    assert audited_components == set(ZEROING_VALUES)  # all eleven components
    stages = [entry.stage for entry in result.audit_derivation]
    for expected_stage in (
        "validation",
        "bucket_resolution",
        "category_aggregation",
        "total_aggregation",
        "grade_assignment",
    ):
        assert expected_stage in stages, expected_stage
    sequences = [entry.sequence for entry in result.audit_derivation]
    assert sequences == sorted(set(sequences))  # strictly increasing


# --------------------------------------------------------------------------
# Bucket boundaries (§5.1 half-open, §4.1 terminal inclusive)
# --------------------------------------------------------------------------


def test_bucket_lower_bounds_are_inclusive_and_uppers_exclusive(
    config: GreenMachineConfig,
) -> None:
    at_boundary = score_snapshot(engine_snapshot(values={ComponentId.EXIT_VELOCITY: "90"}), config)
    assert _points(at_boundary, ComponentId.EXIT_VELOCITY) == Decimal("1.1")

    just_below = score_snapshot(
        engine_snapshot(values={ComponentId.EXIT_VELOCITY: "89.999"}), config
    )
    assert _points(just_below, ComponentId.EXIT_VELOCITY) == Decimal("0.55")


def test_the_terminal_bucket_is_closed_at_the_domain_maximum(
    config: GreenMachineConfig,
) -> None:
    result = score_snapshot(engine_snapshot(values={ComponentId.EXIT_VELOCITY: "130"}), config)
    score = next(
        component_score
        for component_score in result.component_scores
        if component_score.component_id is ComponentId.EXIT_VELOCITY
    )
    assert score.points_awarded == Decimal("1.1")
    assert score.bucket_hit is not None
    assert score.bucket_hit.is_terminal
    assert score.bucket_hit.upper_bound is None


@pytest.mark.parametrize("out_of_domain", ["130.001", "-0.001"])
def test_a_value_outside_the_declared_domain_fails_closed(
    config: GreenMachineConfig, out_of_domain: str
) -> None:
    with pytest.raises(ScoringInputError, match="outside the declared scoring domain"):
        score_snapshot(engine_snapshot(values={ComponentId.EXIT_VELOCITY: out_of_domain}), config)


# --------------------------------------------------------------------------
# Measurement-specific scoring (§9.1)
# --------------------------------------------------------------------------


def test_the_attack_angle_measurement_selects_its_own_buckets(
    config: GreenMachineConfig,
) -> None:
    """55 scores 0.8 under the IAA buckets but 0 under the proxy buckets."""
    via_ideal = score_snapshot(engine_snapshot(), config)
    assert _points(via_ideal, ComponentId.ATTACK_ANGLE_QUALITY) == Decimal("0.8")

    via_proxy = score_snapshot(
        engine_snapshot(aaq_measurement=MeasurementId.ATTACK_ANGLE_THRESHOLD_PROXY), config
    )
    assert _points(via_proxy, ComponentId.ATTACK_ANGLE_QUALITY) == Decimal("0")
    proxy_score = next(
        component_score
        for component_score in via_proxy.component_scores
        if component_score.component_id is ComponentId.ATTACK_ANGLE_QUALITY
    )
    assert proxy_score.measurement_id is MeasurementId.ATTACK_ANGLE_THRESHOLD_PROXY


# --------------------------------------------------------------------------
# Missing data (§8)
# --------------------------------------------------------------------------


def test_record_missing_awards_an_explicit_zero_with_the_reason(
    config: GreenMachineConfig,
) -> None:
    result = score_snapshot(
        engine_snapshot(missing={ComponentId.BAT_SPEED: MissingReason.TRACKING_UNAVAILABLE}),
        config,
    )
    assert isinstance(result, EvaluatedGradeResult)
    assert _points(result, ComponentId.BAT_SPEED) == Decimal("0")
    assert result.total_score == Decimal("10.95")  # 11.55 - 0.6
    entry = next(
        audit_entry
        for audit_entry in result.audit_derivation
        if audit_entry.stage == "missing_recorded_zero"
    )
    assert "TRACKING_UNAVAILABLE" in entry.input_summary  # MissingReason values are upper case
    assert "record_missing" in entry.explanation


def test_an_unanticipated_missing_reason_fails_closed(config: GreenMachineConfig) -> None:
    with pytest.raises(ScoringInputError, match="does not anticipate"):
        score_snapshot(
            engine_snapshot(missing={ComponentId.BAT_SPEED: MissingReason.WEATHER_UNAVAILABLE}),
            config,
        )


def test_a_not_evaluable_policy_produces_the_distinct_terminal_state() -> None:
    config = _variant(
        "    missing_data:\n      policy: record_missing\n"
        "      reasons: [NO_EVENTS_IN_WINDOW, TRACKING_UNAVAILABLE, "
        "INVALID_SOURCE_VALUE, SOURCE_UNAVAILABLE]",
        "    missing_data:\n      policy: not_evaluable\n"
        "      reasons: [NO_EVENTS_IN_WINDOW, TRACKING_UNAVAILABLE, "
        "INVALID_SOURCE_VALUE, SOURCE_UNAVAILABLE]",
    )  # first occurrence = exit_velocity
    result = score_snapshot(
        engine_snapshot(missing={ComponentId.EXIT_VELOCITY: MissingReason.SOURCE_UNAVAILABLE}),
        config,
    )
    assert isinstance(result, NotEvaluableGradeResult)
    assert [entry.component_id.value for entry in result.unavailable_required_inputs] == [
        "exit_velocity"
    ]
    stages = [entry.stage for entry in result.audit_derivation]
    assert "missing_required_input" in stages
    assert "evaluability_verdict" in stages
    assert not hasattr(result, "total_score")  # structurally scoreless


def test_a_component_with_no_observation_at_all_fails_closed(
    config: GreenMachineConfig,
) -> None:
    with pytest.raises(ScoringInputError, match="neither a present nor a missing"):
        score_snapshot(engine_snapshot(absent={ComponentId.PARK}), config)


# --------------------------------------------------------------------------
# Insufficient samples (§8.2): scored, warned once, never gated
# --------------------------------------------------------------------------


def test_an_insufficient_sample_is_scored_and_warned_exactly_once(
    config: GreenMachineConfig,
) -> None:
    result = score_snapshot(engine_snapshot(insufficient={ComponentId.BARREL_PCT}), config)
    assert isinstance(result, EvaluatedGradeResult)
    assert _points(result, ComponentId.BARREL_PCT) == Decimal("0.45")  # still scored
    assert result.total_score == Decimal("11.55")  # unchanged by the label
    warnings = [
        finding
        for finding in result.validation_findings
        if finding.input_id is ValidationInputId.SAMPLE_WARNINGS
    ]
    assert [finding.component_id for finding in warnings] == [ComponentId.BARREL_PCT]


# --------------------------------------------------------------------------
# Grade cutoffs
# --------------------------------------------------------------------------


def test_a_total_on_a_cutoff_boundary_lands_in_the_upper_grade(
    config: GreenMachineConfig,
) -> None:
    """3.7 sits exactly on the D/C boundary: [0, 3.7) is D, so 3.7 is C."""
    values = dict(ZEROING_VALUES)
    values[ComponentId.PULL_PCT_AIR_BALLS] = "20"  # 1.1
    values[ComponentId.PITCH_MIX_PRESSURE] = "60"  # 1.6
    values[ComponentId.PARK] = "60"  # 1
    result = score_snapshot(engine_snapshot(values=values), config)
    assert result.total_score == Decimal("3.7")
    assert result.grade is Grade.C


def test_a_perfect_total_lands_in_the_inclusive_terminal_cutoff(
    config: GreenMachineConfig,
) -> None:
    values = dict(ZEROING_VALUES)
    values.update(
        {
            ComponentId.EXIT_VELOCITY: "95",
            ComponentId.BARREL_PCT: "20",
            ComponentId.HARD_HIT_PCT: "60",
            ComponentId.PITCH_MIX_PRESSURE: "60",
            ComponentId.PUT_AWAY_PITCH_EXPLOITATION: "60",
            ComponentId.SWEET_SPOT_PCT: "30",
            ComponentId.ATTACK_ANGLE_QUALITY: "55",
            ComponentId.BAT_SPEED: "75",
            ComponentId.PULL_PCT_AIR_BALLS: "33",
            ComponentId.PARK: "60",
            ComponentId.WEATHER: "60",
        }
    )
    result = score_snapshot(engine_snapshot(values=values), config)
    assert result.total_score == Decimal("12.00")
    assert result.grade is Grade.S


def test_a_zeroed_category_still_grades_from_the_plain_arithmetic_total(
    config: GreenMachineConfig,
) -> None:
    """Power Profile zeroed, everything else at its default.

    Under the v6.3 signal engine this line was the AVOID-override case. GM-041
    removed betting classifications entirely, so the interesting property is now
    simply that a zeroed category neither vetoes the result nor perturbs the sum.
    """
    values = {
        ComponentId.EXIT_VELOCITY: "50",
        ComponentId.BARREL_PCT: "5",
        ComponentId.HARD_HIT_PCT: "30",
    }
    result = score_snapshot(engine_snapshot(values=values), config)
    assert result.total_score == Decimal("9.2")
    assert result.grade is Grade.A


def test_a_mid_range_combination_grades_from_its_exact_total(
    config: GreenMachineConfig,
) -> None:
    values = dict(ZEROING_VALUES)
    values.update(
        {
            ComponentId.EXIT_VELOCITY: "95",
            ComponentId.BARREL_PCT: "8",
            ComponentId.HARD_HIT_PCT: "60",
            ComponentId.SWEET_SPOT_PCT: "30",
            ComponentId.ATTACK_ANGLE_QUALITY: "55",
            ComponentId.PULL_PCT_AIR_BALLS: "20",
            ComponentId.PUT_AWAY_PITCH_EXPLOITATION: "60",
        }
    )
    result = score_snapshot(engine_snapshot(values=values), config)
    assert result.total_score == Decimal("6.45")
    assert result.grade is Grade.B


def test_a_near_floor_combination_grades_d(config: GreenMachineConfig) -> None:
    values = dict(ZEROING_VALUES)
    values[ComponentId.EXIT_VELOCITY] = "95"
    result = score_snapshot(engine_snapshot(values=values), config)
    assert result.grade is Grade.D


def test_the_result_carries_no_betting_classification(
    config: GreenMachineConfig,
) -> None:
    """GM-041: GreenMachine evaluates; it never advises.

    The engine's entire output is Total Score, Tier, Component Breakdown, Audit
    Trail, Warnings, and Fallbacks. No signal, signal reason, or equivalent may
    reappear on the record or anywhere in its serialized bytes.
    """
    result = score_snapshot(engine_snapshot(), config)
    for banned_attribute in ("signal", "signal_reason", "strong_categories"):
        assert not hasattr(result, banned_attribute), banned_attribute
    rendered = serialize_record(result).decode("utf-8")
    for banned in ("STRONG_BET", "LEAN", "AVOID", "signal", "strong_category"):
        assert banned not in rendered, banned


# --------------------------------------------------------------------------
# Binary scoring and its reserved input name
# --------------------------------------------------------------------------

_WEATHER_BUCKETED_BLOCK = """  - component_id: weather
    scoring_method: bucketed
    direction: higher_is_better
    max_points: "0.8"
    sample_type: games
    missing_data:
      policy: record_missing
      reasons: [WEATHER_UNAVAILABLE]
    applicable_profiles: [RECENT_7D, LONG_TERM_2Y]
    profiles:
      - window_profile: RECENT_7D
        minimum_sample_required: 1
        scoring:
          - method: bucketed
            domain_min: "0"
            domain_max: "100"
            buckets:
              - { lower: "0", upper: "50", points: "0" }
              - { lower: "50", upper: "100", points: "0.8" }
      - window_profile: LONG_TERM_2Y
        minimum_sample_required: 1
        scoring:
          - method: bucketed
            domain_min: "0"
            domain_max: "100"
            buckets:
              - { lower: "0", upper: "50", points: "0" }
              - { lower: "50", upper: "100", points: "0.8" }
"""


def _weather_binary_block(input_name: str) -> str:
    return f"""  - component_id: weather
    scoring_method: binary
    direction: higher_is_better
    max_points: "0.8"
    sample_type: games
    missing_data:
      policy: record_missing
      reasons: [WEATHER_UNAVAILABLE]
    applicable_profiles: [RECENT_7D, LONG_TERM_2Y]
    profiles:
      - window_profile: RECENT_7D
        minimum_sample_required: 1
        scoring:
          - method: binary
            predicate:
              all_of:
                - {{ input_name: {input_name}, operator: at_least, value: "50" }}
            qualified_points: "0.8"
      - window_profile: LONG_TERM_2Y
        minimum_sample_required: 1
        scoring:
          - method: binary
            predicate:
              all_of:
                - {{ input_name: {input_name}, operator: at_least, value: "50" }}
            qualified_points: "0.8"
"""


def test_binary_scoring_awards_all_or_nothing(config: GreenMachineConfig) -> None:
    binary_config = _variant(
        _WEATHER_BUCKETED_BLOCK, _weather_binary_block(OBSERVED_VALUE_INPUT_NAME)
    )
    qualified = score_snapshot(engine_snapshot(), binary_config)
    assert _points(qualified, ComponentId.WEATHER) == Decimal("0.8")
    weather_score = next(
        component_score
        for component_score in qualified.component_scores
        if component_score.component_id is ComponentId.WEATHER
    )
    assert weather_score.bucket_hit is None  # binary components have no bucket

    unqualified = score_snapshot(engine_snapshot(values={ComponentId.WEATHER: "40"}), binary_config)
    assert _points(unqualified, ComponentId.WEATHER) == Decimal("0")
    assert any(entry.stage == "binary_qualification" for entry in unqualified.audit_derivation)


def test_an_unsupported_predicate_input_name_fails_closed() -> None:
    hostile_config = _variant(_WEATHER_BUCKETED_BLOCK, _weather_binary_block("wind_speed"))
    with pytest.raises(ScoringConfigError, match="can resolve only 'observed_value'"):
        score_snapshot(engine_snapshot(), hostile_config)


# --------------------------------------------------------------------------
# Fuzzy scoring stays refused, and determinism holds
# --------------------------------------------------------------------------


def test_the_loader_refuses_an_enabled_fuzzy_policy_before_the_engine_sees_it() -> None:
    """§19 validation is the first of two independent refusals."""
    with pytest.raises(ConfigSemanticError, match="fuzzy scoring is not implemented"):
        _variant("fuzzy_scoring:\n  enabled: false", "fuzzy_scoring:\n  enabled: true")


def test_an_enabled_fuzzy_policy_is_refused(config: GreenMachineConfig) -> None:
    """The engine refuses independently of the loader.

    A loaded configuration can never carry an enabled fuzzy policy, so this
    constructs one directly: the guard exists so that any future path reaching
    the engine without §19 validation still fails closed rather than scoring as
    though the policy were absent (MODEL_SPEC §5.2).
    """
    fuzzy_config = config.model_copy(update={"fuzzy_scoring": FuzzyScoringPolicy(enabled=True)})
    with pytest.raises(ScoringConfigError, match="fuzzy scoring is enabled"):
        score_snapshot(engine_snapshot(), fuzzy_config)


def test_identical_inputs_give_byte_identical_serialized_results(
    config: GreenMachineConfig,
) -> None:
    first = score_snapshot(engine_snapshot(), config)
    second = score_snapshot(engine_snapshot(), config)
    assert first == second
    assert serialize_record(first) == serialize_record(second)


def _config_with_minimum(
    config: GreenMachineConfig, component_id: ComponentId, minimum: int
) -> GreenMachineConfig:
    """The same configuration with one component's profile minimum replaced.

    Built by model_copy rather than by editing YAML so the test targets exactly
    one field and cannot accidentally depend on unrelated fixture text.
    """
    components = []
    for component in config.components:
        if component.component_id is not component_id:
            components.append(component)
            continue
        profiles = tuple(
            profile.model_copy(update={"minimum_sample_required": minimum})
            for profile in component.profiles
        )
        components.append(component.model_copy(update={"profiles": profiles}))
    return config.model_copy(update={"components": tuple(components)})


# --------------------------------------------------------------------------
# Snapshot / configuration coherence (independent review, GM-041)
# --------------------------------------------------------------------------
#
# The snapshot's SampleStatus was decided by the ingestion layer against the
# minimum stored ON THE OBSERVATION. Scoring under a configuration declaring a
# different minimum would make every warning and audit line disagree with the
# status the snapshot carries, so the engine refuses rather than reconciling.
# It never recalculates, mutates, or replaces snapshot metadata.


def test_a_configured_minimum_above_the_snapshot_minimum_is_refused(
    config: GreenMachineConfig,
) -> None:
    """Snapshot minimum 2, configuration minimum 999."""
    snapshot = engine_snapshot(minimum_overrides={ComponentId.EXIT_VELOCITY: 2})
    hostile = _config_with_minimum(config, ComponentId.EXIT_VELOCITY, 999)

    with pytest.raises(ScoringInputError) as caught:
        score_snapshot(snapshot, hostile)

    message = str(caught.value)
    assert "exit_velocity" in message
    assert "minimum_sample_required" in message
    assert "2" in message
    assert "999" in message


def test_a_configured_minimum_below_the_snapshot_minimum_is_refused(
    config: GreenMachineConfig,
) -> None:
    """The inverse mismatch: snapshot minimum 999, configuration minimum 2."""
    snapshot = engine_snapshot(minimum_overrides={ComponentId.EXIT_VELOCITY: 999})

    with pytest.raises(ScoringInputError) as caught:
        score_snapshot(snapshot, config)

    message = str(caught.value)
    assert "exit_velocity" in message
    assert "minimum_sample_required" in message
    assert "999" in message


def test_a_present_observation_sample_type_mismatch_is_refused(
    config: GreenMachineConfig,
) -> None:
    snapshot = engine_snapshot(
        sample_type_overrides={ComponentId.EXIT_VELOCITY: SampleType.PLATE_APPEARANCES}
    )

    with pytest.raises(ScoringInputError) as caught:
        score_snapshot(snapshot, config)

    message = str(caught.value)
    assert "exit_velocity" in message
    assert "sample_type" in message
    assert "plate_appearances" in message
    assert "batted_ball_events" in message


def test_a_missing_observation_sample_type_mismatch_is_refused(
    config: GreenMachineConfig,
) -> None:
    """A missing observation carries no minimum, so only the sample type binds."""
    snapshot = engine_snapshot(
        missing={ComponentId.BAT_SPEED: MissingReason.TRACKING_UNAVAILABLE},
        sample_type_overrides={ComponentId.BAT_SPEED: SampleType.GAMES},
    )

    with pytest.raises(ScoringInputError) as caught:
        score_snapshot(snapshot, config)

    message = str(caught.value)
    assert "bat_speed" in message
    assert "sample_type" in message
    assert "games" in message
    assert "swings" in message


def test_matching_metadata_continues_to_score_normally(config: GreenMachineConfig) -> None:
    """Anti-vacuity: the guard must not reject the coherent default snapshot."""
    result = score_snapshot(engine_snapshot(), config)

    assert isinstance(result, EvaluatedGradeResult)
    assert result.total_score == Decimal(DEFAULT_TOTAL)
    assert result.grade is Grade.S


def test_insufficient_warnings_survive_the_coherence_checks(
    config: GreenMachineConfig,
) -> None:
    """An INSUFFICIENT sample is coherent: below the minimum, not disagreeing with it.

    The component is still scored, and exactly one advisory warning names it.
    """
    snapshot = engine_snapshot(insufficient=[ComponentId.BARREL_PCT])
    result = score_snapshot(snapshot, config)

    assert isinstance(result, EvaluatedGradeResult)
    warnings = [
        finding
        for finding in result.validation_findings
        if finding.input_id is ValidationInputId.SAMPLE_WARNINGS
    ]
    assert [finding.component_id for finding in warnings] == [ComponentId.BARREL_PCT]
    barrel = next(
        score for score in result.component_scores if score.component_id is ComponentId.BARREL_PCT
    )
    assert barrel.points_awarded > 0

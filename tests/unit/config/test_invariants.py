"""Every invariant in ``MODEL_SPEC.md`` §19, proven to be a load failure.

Each case is a one-line mutation of the valid fixture, so the diff between a
working configuration and a rejected one is exactly the rule under test. Every
assertion also checks the reported key path: an error that fails to say *where*
is barely better than no error at all.
"""

from __future__ import annotations

import pytest
from config_fixtures import (
    DESCENDING_BUCKETS,
    EV_BUCKETS,
    EV_PROFILE_RECENT,
    FUZZY_DISABLED,
    GRADE_C,
    GRADE_D,
    GRADE_S,
    PROXY_DEFINITION,
    WEATHER_BINARY,
    mutate,
)

from greenmachine.config import ConfigSchemaError, ConfigSemanticError, load_config_text


def reject(text: str) -> ConfigSemanticError:
    """Load and require a semantic rejection, returning the error."""
    with pytest.raises(ConfigSemanticError) as caught:
        load_config_text(text, file_path="synthetic.yaml")
    assert caught.value.context.file_path == "synthetic.yaml"
    return caught.value


# --------------------------------------------------------------------------
# Buckets (invariants 1, 2, 3, 7, 8, 9, 10)
# --------------------------------------------------------------------------


def test_overlapping_buckets_are_rejected() -> None:
    error = reject(mutate(EV_BUCKETS, EV_BUCKETS.replace('{ lower: "62.4"', '{ lower: "55.0"')))

    assert "meet exactly" in str(error)
    assert error.context.metric == "exit_velocity"


def test_a_bucket_gap_is_rejected() -> None:
    error = reject(mutate(EV_BUCKETS, EV_BUCKETS.replace('{ lower: "62.4"', '{ lower: "70.0"')))

    assert "meet exactly" in str(error)


def test_bucket_points_below_zero_are_rejected() -> None:
    error = reject(mutate(EV_BUCKETS, EV_BUCKETS.replace('points: "0" }', 'points: "-0.1" }')))

    assert "points must be >= 0" in str(error)
    assert error.context.key_path[-1] == "points"


def test_bucket_points_exceeding_max_points_are_rejected() -> None:
    error = reject(mutate(EV_BUCKETS, EV_BUCKETS.replace('points: "0.4" }', 'points: "1.7" }')))

    assert "exceed the component max_points" in str(error)


def test_a_strongest_bucket_that_does_not_award_max_points_is_rejected() -> None:
    error = reject(mutate(EV_BUCKETS, EV_BUCKETS.replace('points: "0.9" }', 'points: "0.8" }')))

    assert "strongest qualifying bucket must award" in str(error)


def test_non_monotonic_higher_is_better_points_are_rejected() -> None:
    """Points may never decrease as values increase."""
    error = reject(
        mutate(
            EV_BUCKETS,
            EV_BUCKETS.replace('upper: "62.4", points: "0" }', 'upper: "62.4", points: "0.6" }'),
        )
    )

    assert "never decrease" in str(error)


def test_non_monotonic_lower_is_better_points_are_rejected() -> None:
    """Points may never increase as values increase."""
    error = reject(
        mutate(
            DESCENDING_BUCKETS,
            DESCENDING_BUCKETS.replace(
                'upper: "19.2", points: "1.9" }', 'upper: "19.2", points: "0.5" }'
            ),
            count=2,
        )
    )

    assert "never increase" in str(error)
    assert error.context.metric == "put_away_pitch_exploitation"


def test_a_first_bucket_that_misses_the_domain_minimum_is_rejected() -> None:
    error = reject(
        mutate(EV_BUCKETS, EV_BUCKETS.replace('- { lower: "0",    upper', '- { lower: "1", upper'))
    )

    assert "must start at domain_min" in str(error)


def test_a_final_bucket_that_misses_the_domain_maximum_is_rejected() -> None:
    error = reject(
        mutate(EV_BUCKETS, EV_BUCKETS.replace('upper: "125",  points', 'upper: "124", points'))
    )

    assert "must end at domain_max" in str(error)


def test_a_reversed_bucket_is_rejected() -> None:
    error = reject(
        mutate(
            EV_BUCKETS,
            EV_BUCKETS.replace(
                '- { lower: "62.4", upper: "88.1"', '- { lower: "88.1", upper: "62.4"'
            ),
        )
    )

    assert "must be <" in str(error)


def test_an_inverted_domain_is_rejected() -> None:
    error = reject(
        mutate(
            EV_PROFILE_RECENT,
            EV_PROFILE_RECENT.replace('domain_max: "125"', 'domain_max: "0"'),
        )
    )

    assert "domain_min" in str(error)


# --------------------------------------------------------------------------
# Allocations (invariants 4, 5, 6, 14)
# --------------------------------------------------------------------------


def test_component_maxima_that_do_not_sum_to_the_category_maximum_are_rejected() -> None:
    error = reject(mutate('      max_points: "2.7"', '      max_points: "2.8"'))

    assert "sum to" in str(error)
    assert error.context.key_path[:2] == ("allocations", "categories")


def test_category_maxima_that_do_not_sum_to_twelve_are_rejected() -> None:
    """Changing one category and its components keeps the inner sum but breaks the total."""
    text = mutate('      max_points: "2.7"', '      max_points: "2.6"')
    text = text.replace(
        '    max_points: "0.9"\n    sample_type: batted_ball_events',
        '    max_points: "0.8"\n    sample_type: batted_ball_events',
        1,
    )
    error = reject(text)

    assert "category maximums sum to" in str(error)


def test_a_wrong_total_max_points_is_rejected() -> None:
    error = reject(mutate('  total_max_points: "12"', '  total_max_points: "11"'))

    assert "total_max_points must be 12" in str(error)
    assert error.context.key_path == ("allocations", "total_max_points")


def test_a_duplicate_category_is_rejected() -> None:
    error = reject(
        mutate(
            '    - category: pull_power\n      max_points: "2.4"\n'
            "      components: [pull_pct_air_balls]",
            '    - category: power_profile\n      max_points: "2.4"\n'
            "      components: [pull_pct_air_balls]",
        )
    )

    assert "declared more than once" in str(error)


def test_an_undefined_component_reference_is_rejected() -> None:
    error = reject(
        mutate(
            "      components: [pull_pct_air_balls]",
            "      components: [pull_pct_air_balls, park]",
        )
    )

    # `park` is already claimed by environment, so this reads as a double claim.
    assert "more than one category" in str(error)


def test_an_orphan_component_is_rejected() -> None:
    """A configured component that no category claims."""
    error = reject(
        mutate("      components: [park, weather]", "      components: [weather]").replace(
            '      max_points: "1.7"', '      max_points: "0.8"', 1
        )
    )

    assert "not placed in any category" in str(error)


def test_a_duplicate_component_definition_is_rejected() -> None:
    text = mutate(
        "  - component_id: weather\n    scoring_method: binary",
        "  - component_id: park\n    scoring_method: binary",
    )
    error = reject(text)

    assert "configured more than once" in str(error)


def test_an_unknown_component_identifier_is_refused_by_the_schema() -> None:
    with pytest.raises(ConfigSchemaError):
        load_config_text(mutate("  - component_id: park", "  - component_id: chase_rate"))


def test_a_retired_component_cannot_be_referenced() -> None:
    with pytest.raises(ConfigSchemaError):
        load_config_text(
            mutate("      components: [pull_pct_air_balls]", "      components: [whiff_rate]")
        )


# --------------------------------------------------------------------------
# Grade cutoffs (invariant 13)
# --------------------------------------------------------------------------


def test_unordered_grade_cutoffs_are_rejected() -> None:
    text = mutate(f"{GRADE_D}\n{GRADE_C}", f"{GRADE_C}\n{GRADE_D}")
    error = reject(text)

    assert "ascending order" in str(error)


def test_a_grade_cutoff_gap_is_rejected() -> None:
    error = reject(
        mutate(GRADE_C, '    - { grade: C, lower: "3.4", upper: "5.1", terminal: false }')
    )

    assert "meet exactly" in str(error)


def test_a_grade_cutoff_overlap_is_rejected() -> None:
    error = reject(
        mutate(GRADE_C, '    - { grade: C, lower: "3.2", upper: "5.1", terminal: false }')
    )

    assert "meet exactly" in str(error)


def test_a_missing_grade_is_rejected() -> None:
    error = reject(mutate(f"{GRADE_C}\n", ""))

    assert "grade missing" in str(error)


def test_a_duplicate_grade_is_rejected() -> None:
    error = reject(
        mutate(GRADE_C, '    - { grade: D, lower: "3.3", upper: "5.1", terminal: false }')
    )

    assert "declared more than once" in str(error)


def test_a_grade_table_that_does_not_start_at_zero_is_rejected() -> None:
    error = reject(
        mutate(GRADE_D, '    - { grade: D, lower: "0.5", upper: "3.3", terminal: false }')
    )

    assert "must start at 0" in str(error)


def test_a_grade_table_that_does_not_end_at_twelve_is_rejected() -> None:
    error = reject(mutate(GRADE_S, '    - { grade: S, lower: "9.4", upper: "11", terminal: true }'))

    assert "must end at 12" in str(error)


def test_a_missing_terminal_grade_is_rejected() -> None:
    error = reject(
        mutate(GRADE_S, '    - { grade: S, lower: "9.4", upper: "12",  terminal: false }')
    )

    assert "terminal" in str(error)


def test_more_than_one_terminal_grade_is_rejected() -> None:
    error = reject(
        mutate(GRADE_C, '    - { grade: C, lower: "3.3", upper: "5.1", terminal: true }')
    )

    assert "terminal" in str(error)


# --------------------------------------------------------------------------
# Profiles and measurements (invariants 15, 16)
# --------------------------------------------------------------------------


def test_a_missing_profile_definition_is_rejected() -> None:
    error = reject(mutate(f"{EV_PROFILE_RECENT}\n", ""))

    assert "do not match applicable_profiles" in str(error)
    assert error.context.metric == "exit_velocity"


def test_a_duplicate_profile_definition_is_rejected() -> None:
    error = reject(mutate(EV_PROFILE_RECENT, f"{EV_PROFILE_RECENT}\n{EV_PROFILE_RECENT}"))

    assert "defined more than once" in str(error)


def test_an_undeclared_profile_definition_is_rejected() -> None:
    error = reject(
        mutate(
            "    applicable_profiles: [RECENT_7D, LONG_TERM_2Y]\n    profiles:\n"
            "      - window_profile: RECENT_7D\n        minimum_sample_required: 3\n"
            '        scoring:\n          - method: bucketed\n            domain_min: "0"\n'
            '            domain_max: "125"',
            "    applicable_profiles: [RECENT_7D]\n    profiles:\n"
            "      - window_profile: RECENT_7D\n        minimum_sample_required: 3\n"
            '        scoring:\n          - method: bucketed\n            domain_min: "0"\n'
            '            domain_max: "125"',
        )
    )

    assert "do not match applicable_profiles" in str(error)


def test_a_missing_measurement_definition_is_rejected() -> None:
    error = reject(mutate(f"{PROXY_DEFINITION}\n", ""))

    assert "exactly one bucket set per measurement" in str(error)
    assert error.context.metric == "attack_angle_quality"


def test_a_duplicate_measurement_definition_is_rejected() -> None:
    error = reject(
        mutate(
            PROXY_DEFINITION,
            PROXY_DEFINITION.replace(
                "measurement_id: attack_angle_threshold_proxy",
                "measurement_id: ideal_attack_angle_pct",
            ),
        )
    )

    assert "more than once" in str(error) or "requires a bucket set for both" in str(error)


def test_a_measurement_on_a_non_attack_component_is_rejected() -> None:
    error = reject(
        mutate(
            EV_PROFILE_RECENT,
            EV_PROFILE_RECENT.replace(
                "          - method: bucketed\n",
                "          - method: bucketed\n"
                "            measurement_id: ideal_attack_angle_pct\n",
            ),
        )
    )

    assert "only attack_angle_quality may name a measurement" in str(error)


# --------------------------------------------------------------------------
# Schema-shape separation (invariants 11, 12)
# --------------------------------------------------------------------------


def test_a_binary_component_containing_bucket_fields_is_refused() -> None:
    text = mutate(
        WEATHER_BINARY,
        WEATHER_BINARY.replace(
            '            qualified_points: "0.8"',
            '            qualified_points: "0.8"\n            domain_min: "0"',
        ),
        count=2,
    )

    with pytest.raises(ConfigSchemaError, match=r"[Ee]xtra|not permitted"):
        load_config_text(text, file_path="synthetic.yaml")


def test_a_binary_component_declaring_buckets_is_refused() -> None:
    text = mutate(
        WEATHER_BINARY,
        WEATHER_BINARY.replace(
            '            qualified_points: "0.8"',
            '            qualified_points: "0.8"\n            buckets: []',
        ),
        count=2,
    )

    with pytest.raises(ConfigSchemaError):
        load_config_text(text, file_path="synthetic.yaml")


def test_a_bucketed_component_containing_binary_fields_is_refused() -> None:
    text = mutate(
        EV_PROFILE_RECENT,
        EV_PROFILE_RECENT.replace(
            '            domain_max: "125"',
            '            domain_max: "125"\n            qualified_points: "0.9"',
        ),
    )

    with pytest.raises(ConfigSchemaError):
        load_config_text(text, file_path="synthetic.yaml")


def test_a_declared_method_that_contradicts_the_definition_is_rejected() -> None:
    error = reject(mutate("    scoring_method: binary", "    scoring_method: bucketed"))

    assert "scoring_method" in str(error)


def test_a_binary_award_below_max_points_is_rejected() -> None:
    error = reject(
        mutate(
            WEATHER_BINARY,
            WEATHER_BINARY.replace('qualified_points: "0.8"', 'qualified_points: "0.5"'),
            count=2,
        )
    )

    assert "qualified_points must equal" in str(error)
    assert error.context.metric == "weather"


def test_a_predicate_with_neither_clause_is_refused() -> None:
    text = mutate(
        WEATHER_BINARY,
        WEATHER_BINARY.replace(
            "            predicate:\n              all_of:\n"
            "                - { input_name: synthetic_input_a, operator: at_least,"
            ' value: "41.7" }\n'
            "                - { input_name: synthetic_input_b, operator: greater_than,"
            ' value: "3.9" }',
            "            predicate: {}",
        ),
        count=2,
    )
    error = reject(text)

    assert "exactly one of 'all_of' or 'any_of'" in str(error)


# --------------------------------------------------------------------------
# Fuzzy scoring
# --------------------------------------------------------------------------


def test_fuzzy_scoring_enabled_is_rejected() -> None:
    error = reject(mutate(FUZZY_DISABLED, "  enabled: true"))

    assert "must be explicitly disabled" in str(error)
    assert error.context.key_path == ("fuzzy_scoring", "enabled")


def test_a_non_boolean_fuzzy_flag_is_refused() -> None:
    with pytest.raises(ConfigSchemaError):
        load_config_text(mutate(FUZZY_DISABLED, '  enabled: "false"'))


# --------------------------------------------------------------------------
# Numeric policy
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "old", "new"),
    [
        ("yaml float", '  total_max_points: "12"', "  total_max_points: 12.0"),
        ("yaml integer", '  total_max_points: "12"', "  total_max_points: 12"),
        ("boolean", '  total_max_points: "12"', "  total_max_points: true"),
        ("malformed string", '  total_max_points: "12"', '  total_max_points: "abc"'),
        ("NaN", '  total_max_points: "12"', '  total_max_points: "NaN"'),
        ("Infinity", '  total_max_points: "12"', '  total_max_points: "Infinity"'),
        ("empty string", '  total_max_points: "12"', '  total_max_points: ""'),
    ],
)
def test_scoring_numerics_must_be_quoted_decimal_strings(label: str, old: str, new: str) -> None:
    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(mutate(old, new), file_path="synthetic.yaml")

    assert caught.value.context.key_path[0] == "allocations"


@pytest.mark.parametrize(
    ("label", "new"),
    [
        ("boolean", "        minimum_sample_required: true"),
        ("float", "        minimum_sample_required: 5.5"),
        ("numeric string", '        minimum_sample_required: "5"'),
        ("negative", "        minimum_sample_required: -1"),
    ],
)
def test_count_fields_must_be_strict_non_negative_integers(label: str, new: str) -> None:
    with pytest.raises(ConfigSchemaError):
        load_config_text(
            mutate("        minimum_sample_required: 5", new), file_path="synthetic.yaml"
        )


def test_a_bucket_point_supplied_as_a_yaml_float_is_refused() -> None:
    text = mutate(EV_BUCKETS, EV_BUCKETS.replace('points: "0.4" }', "points: 0.4 }"))

    with pytest.raises(ConfigSchemaError, match=r"YAML float"):
        load_config_text(text, file_path="synthetic.yaml")

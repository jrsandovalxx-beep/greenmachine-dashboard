"""Regression tests for the GM-003 r1 correction pass.

Each area the review flagged: global-context independence, semantic grade order,
closed raw-exception escapes, and normalized union error paths.

The unconditional-fallback and override-reason sections were removed with the
signal engine in GM-041.
"""

from __future__ import annotations

import decimal
import subprocess
from collections.abc import Iterator

import pytest
import yaml
from config_fixtures import GRADE_D, GRADE_S, mutate
from pydantic import ValidationError

from greenmachine.common.errors import ConfigurationError
from greenmachine.common.numeric import NumericPolicyError
from greenmachine.config import (
    ConfigParseError,
    ConfigSchemaError,
    ConfigSemanticError,
    load_config,
    load_config_text,
)

VALID_PATH = "tests/fixtures/config/valid/complete_synthetic.yaml"


def reject_semantic(text: str) -> ConfigSemanticError:
    with pytest.raises(ConfigSemanticError) as caught:
        load_config_text(text, file_path="synthetic.yaml")
    return caught.value


@pytest.fixture(autouse=True)
def restore_global_context() -> Iterator[None]:
    saved = decimal.getcontext().copy()
    try:
        yield
    finally:
        decimal.setcontext(saved)


# --------------------------------------------------------------------------
# 1. Global Decimal context independence
# --------------------------------------------------------------------------

HOSTILE_CONTEXTS = [
    (1, decimal.ROUND_UP),
    (2, decimal.ROUND_CEILING),
    (3, decimal.ROUND_FLOOR),
    (2, decimal.ROUND_HALF_UP),
]


@pytest.mark.parametrize(("prec", "rounding"), HOSTILE_CONTEXTS)
def test_the_valid_fixture_loads_under_a_hostile_global_context(prec: int, rounding: str) -> None:
    normal = load_config(VALID_PATH)

    decimal.getcontext().prec = prec
    decimal.getcontext().rounding = rounding
    hostile = load_config(VALID_PATH)

    assert hostile == normal


def test_the_callers_global_context_is_unchanged_by_loading() -> None:
    decimal.getcontext().prec = 5
    decimal.getcontext().rounding = decimal.ROUND_UP

    load_config(VALID_PATH)

    assert decimal.getcontext().prec == 5
    assert decimal.getcontext().rounding == decimal.ROUND_UP


def test_the_result_is_identical_across_hostile_and_normal_contexts() -> None:
    normal = load_config(VALID_PATH)

    results = []
    for prec, rounding in HOSTILE_CONTEXTS:
        decimal.getcontext().prec = prec
        decimal.getcontext().rounding = rounding
        results.append(load_config(VALID_PATH))

    assert all(result == normal for result in results)


def test_extreme_finite_values_do_not_leak_a_raw_decimal_exception() -> None:
    """An overflowing category sum becomes a semantic error, not a raw Overflow."""
    text = mutate('      max_points: "2.7"', '      max_points: "1E+999999999"')

    with pytest.raises(ConfigurationError) as caught:
        load_config_text(text, file_path="synthetic.yaml")

    assert not isinstance(caught.value, decimal.DecimalException | NumericPolicyError)


def test_an_overflowing_sum_is_reported_as_a_semantic_error() -> None:
    # Make one component enormous so the category sum overflows the context.
    text = mutate(
        '    max_points: "0.9"\n    sample_type: batted_ball_events',
        '    max_points: "9.9E+999999999"\n    sample_type: batted_ball_events',
    )
    text = text.replace('      max_points: "2.7"', '      max_points: "9.9E+999999999"', 1)

    with pytest.raises(ConfigSemanticError) as caught:
        load_config_text(text, file_path="synthetic.yaml")

    # Either the overflow is caught, or the arithmetic simply disagrees; both are
    # semantic errors that name the file, never a raw exception.
    assert caught.value.context.file_path == "synthetic.yaml"


def test_the_context_isolation_holds_in_a_fresh_subprocess() -> None:
    """Proven in a clean interpreter so no earlier test can mask a dependence."""
    probe = (
        "import decimal\n"
        "decimal.getcontext().prec = 1\n"
        "decimal.getcontext().rounding = decimal.ROUND_UP\n"
        "from greenmachine.config import load_config\n"
        f"a = load_config({VALID_PATH!r})\n"
        "decimal.getcontext().prec = 28\n"
        "decimal.getcontext().rounding = decimal.ROUND_HALF_EVEN\n"
        f"b = load_config({VALID_PATH!r})\n"
        "print('EQUAL' if a == b else 'DIFFERENT')\n"
    )
    from tests.network_guard.guarded_child import guarded_python_command

    completed = subprocess.run(
        guarded_python_command("-c", probe), capture_output=True, text=True, check=True
    )

    assert completed.stdout.strip() == "EQUAL"


# --------------------------------------------------------------------------
# 2. Semantic grade order
# --------------------------------------------------------------------------


def test_swapping_s_and_d_is_rejected() -> None:
    """S in the lowest interval, D in the highest — tiles [0,12] but backwards."""
    text = mutate(GRADE_D, '    - { grade: S, lower: "0",   upper: "3.3", terminal: false }')
    text = text.replace(GRADE_S, '    - { grade: D, lower: "9.4", upper: "12",  terminal: true }')
    error = reject_semantic(text)

    assert "ascending score order" in str(error)
    assert error.context.key_path == ("allocations", "grade_cutoffs")


def test_a_grade_permutation_is_rejected() -> None:
    """C and B swapped between their intervals."""
    text = mutate(
        '    - { grade: C, lower: "3.3", upper: "5.1", terminal: false }',
        '    - { grade: B, lower: "3.3", upper: "5.1", terminal: false }',
    )
    text = text.replace(
        '    - { grade: B, lower: "5.1", upper: "7.7", terminal: false }',
        '    - { grade: C, lower: "5.1", upper: "7.7", terminal: false }',
    )
    error = reject_semantic(text)

    assert "ascending score order" in str(error)


def test_d_in_the_highest_interval_is_rejected() -> None:
    text = mutate(GRADE_S, '    - { grade: D, lower: "9.4", upper: "12",  terminal: true }')
    text = text.replace(GRADE_D, '    - { grade: S, lower: "0",   upper: "3.3", terminal: false }')
    error = reject_semantic(text)

    assert "ascending score order" in str(error)


def test_the_canonical_grade_order_is_accepted() -> None:
    """The valid fixture already runs D, C, B, A, S and must still load."""
    config = load_config(VALID_PATH)

    ordered = sorted(config.allocations.grade_cutoffs, key=lambda cutoff: cutoff.lower)
    assert [cutoff.grade.value for cutoff in ordered] == ["D", "C", "B", "A", "S"]


# --------------------------------------------------------------------------
# 5. No raw exception escapes
# --------------------------------------------------------------------------

RAW_EXCEPTIONS = (
    TypeError,
    yaml.YAMLError,
    ValidationError,
    decimal.DecimalException,
    NumericPolicyError,
)


@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("unhashable list key", "? [a, b]\n: value\n"),
        ("unhashable mapping key", "? {a: 1}\n: value\n"),
        ("malformed yaml", "allocations: { categories: [\n"),
        ("yaml float numeric", mutate('  total_max_points: "12"', "  total_max_points: 12.0")),
        ("missing key", mutate("schema_version: 1\n", "")),
        ("fuzzy enabled", mutate("  enabled: false", "  enabled: true")),
        (
            "overflow",
            mutate('      max_points: "2.7"', '      max_points: "1E+999999999"'),
        ),
    ],
)
def test_no_raw_exception_escapes_load_config_text(label: str, text: str) -> None:
    with pytest.raises(ConfigurationError) as caught:
        load_config_text(text, file_path="synthetic.yaml")

    assert not isinstance(caught.value, RAW_EXCEPTIONS), (
        f"{label} leaked a {type(caught.value).__name__}"
    )
    assert caught.value.context.file_path == "synthetic.yaml"


def test_an_unhashable_mapping_key_is_a_parse_error() -> None:
    with pytest.raises(ConfigParseError, match=r"mapping key must be a scalar"):
        load_config_text("? [a, b]\n: value\n")


@pytest.mark.parametrize("path", [123, None, 4.5, ["a"]])
def test_an_invalid_load_config_path_type_is_a_parse_error(path: object) -> None:
    with pytest.raises(ConfigParseError, match=r"path must be a str or path-like"):
        load_config(path)  # type: ignore[arg-type]


def test_the_original_exception_is_preserved_as_cause_for_a_parse_error() -> None:
    with pytest.raises(ConfigParseError) as caught:
        load_config_text("? [a, b]\n: value\n")

    assert caught.value.__cause__ is not None


# --------------------------------------------------------------------------
# 6. Normalized Pydantic union error paths
# --------------------------------------------------------------------------


def test_an_unknown_key_in_bucketed_scoring_has_no_discriminator_segment() -> None:
    # Anchor on exit_velocity's first bucket set specifically (its buckets are
    # unique to it), so this targets components[0].profiles[0].
    text = mutate(
        '            domain_max: "125"\n            buckets:\n'
        '              - { lower: "0",    upper: "62.4", points: "0" }',
        '            domain_max: "125"\n            mystery: 1\n            buckets:\n'
        '              - { lower: "0",    upper: "62.4", points: "0" }',
    )

    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(text, file_path="synthetic.yaml")

    key_path = caught.value.context.key_path
    assert "bucketed" not in key_path
    assert key_path == ("components", "0", "profiles", "0", "scoring", "0", "mystery")
    assert caught.value.context.metric == "exit_velocity"
    assert caught.value.context.window_profile == "RECENT_7D"


def test_an_unknown_key_in_binary_scoring_has_no_discriminator_segment() -> None:
    text = mutate(
        '            qualified_points: "0.8"',
        '            qualified_points: "0.8"\n            surprise: 1',
        count=2,
    )

    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(text, file_path="synthetic.yaml")

    key_path = caught.value.context.key_path
    assert "binary" not in key_path
    assert key_path[-1] == "surprise"
    assert caught.value.context.metric == "weather"


def test_an_unknown_key_in_a_binary_predicate_comparison_is_located() -> None:
    text = mutate(
        '                - { input_name: synthetic_input_a, operator: at_least, value: "41.7" }',
        '                - { input_name: synthetic_input_a, operator: at_least, value: "41.7",'
        " surprise: 1 }",
        count=2,
    )

    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(text, file_path="synthetic.yaml")

    key_path = caught.value.context.key_path
    assert "binary" not in key_path
    assert key_path[-1] == "surprise"
    assert "predicate" in key_path


def test_a_missing_key_inside_a_union_is_also_normalized() -> None:
    """A required field dropped from a bucket still reports a discriminator-free path."""
    text = mutate(
        '              - { lower: "0",    upper: "62.4", points: "0" }\n'
        '              - { lower: "62.4", upper: "88.1", points: "0.4" }',
        '              - { upper: "62.4", points: "0" }\n'
        '              - { lower: "62.4", upper: "88.1", points: "0.4" }',
    )

    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(text, file_path="synthetic.yaml")

    assert "bucketed" not in caught.value.context.key_path


# --------------------------------------------------------------------------
# 7. Parse-error context
# --------------------------------------------------------------------------


def test_a_duplicate_key_parse_error_identifies_the_key_and_file() -> None:
    text = mutate('  total_max_points: "12"', '  total_max_points: "12"\n  total_max_points: "9"')

    with pytest.raises(ConfigParseError) as caught:
        load_config_text(text, file_path="synthetic.yaml")

    assert caught.value.context.file_path == "synthetic.yaml"
    assert "total_max_points" in str(caught.value)


def test_a_parse_error_keeps_line_information_in_the_message() -> None:
    with pytest.raises(ConfigParseError) as caught:
        load_config_text("allocations: { categories: [\n", file_path="synthetic.yaml")

    assert "line" in str(caught.value).lower()

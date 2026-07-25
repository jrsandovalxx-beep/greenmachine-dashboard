"""Strict YAML loading: the dialect, the failure types, and the key paths."""

from __future__ import annotations

from pathlib import Path

import pytest
from config_fixtures import (
    FUZZY_DISABLED,
    STRONG_FRACTION,
    VALID_PATH,
    drop_line,
    invalid_path,
    mutate,
    valid_text,
)

from greenmachine.common.errors import ConfigurationError, GreenMachineError
from greenmachine.config import (
    ConfigParseError,
    ConfigSchemaError,
    ConfigSemanticError,
    load_config,
    load_config_text,
)

# --------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------


def test_the_valid_fixture_loads() -> None:
    config = load_config(VALID_PATH)

    assert len(config.components) == 11
    assert len(config.allocations.categories) == 5
    assert config.fuzzy_scoring.enabled is False


def test_text_and_file_entry_points_agree() -> None:
    from_file = load_config(VALID_PATH)
    from_text = load_config_text(valid_text(), file_path=str(VALID_PATH))

    assert from_file == from_text


def test_load_config_text_performs_no_file_io() -> None:
    """The text entry point works with a path that does not exist."""
    config = load_config_text(valid_text(), file_path="not/a/real/file.yaml")

    assert len(config.components) == 11


def test_a_missing_file_is_a_parse_error() -> None:
    with pytest.raises(ConfigParseError, match=r"could not read configuration file"):
        load_config(Path("no/such/config.yaml"))


def test_non_string_text_is_refused() -> None:
    with pytest.raises(ConfigParseError, match=r"must be a string"):
        load_config_text(b"schema_version: 1")  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# YAML dialect
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("duplicate_key.yaml", r"duplicate key"),
        ("yaml_alias.yaml", r"aliases are not allowed"),
        ("merge_key.yaml", r"merge keys"),
        ("two_documents.yaml", r"exactly one YAML document"),
        ("non_mapping_root.yaml", r"root must be a mapping"),
        ("malformed.yaml", r"could not parse YAML"),
        ("empty.yaml", r"configuration is empty"),
    ],
)
def test_the_yaml_dialect_is_narrow(name: str, expected: str) -> None:
    with pytest.raises(ConfigParseError, match=expected):
        load_config(invalid_path(name))


def test_a_duplicate_key_fails_before_schema_validation() -> None:
    """Last-one-wins would silently discard a threshold somebody set."""
    text = mutate(STRONG_FRACTION, f'{STRONG_FRACTION}\n  strong_category_fraction: "0.99"')

    with pytest.raises(ConfigParseError, match=r"duplicate key"):
        load_config_text(text)


def test_a_duplicate_key_deep_in_the_tree_is_caught() -> None:
    text = mutate(
        '    - category: power_profile\n      max_points: "2.7"',
        '    - category: power_profile\n      max_points: "2.7"\n      max_points: "9.9"',
    )

    with pytest.raises(ConfigParseError, match=r"duplicate key"):
        load_config_text(text)


def test_an_alias_inside_a_real_configuration_is_refused() -> None:
    """Anchors and aliases are how YAML creates shared state; both are refused."""
    text = mutate(
        '  strong_category_fraction: "0.62"',
        '  strong_category_fraction: &frac "0.62"\n  total_max_points: *frac',
    ).replace('  total_max_points: "12"\n', "", 1)

    with pytest.raises(ConfigParseError, match=r"aliases are not allowed"):
        load_config_text(text)


def test_environment_variables_are_never_interpolated() -> None:
    """A configuration means the same thing on every machine."""
    text = mutate(
        'model_configuration_version: "synthetic-fixture-0"',
        'model_configuration_version: "${HOME}-${PATH}"',
    )
    config = load_config_text(text)

    assert config.model_configuration_version == "${HOME}-${PATH}"


# --------------------------------------------------------------------------
# Failure typing and context
# --------------------------------------------------------------------------


def test_every_failure_is_a_configuration_error() -> None:
    """All three stages sit under the GM-009 hierarchy."""
    for error_type in (ConfigParseError, ConfigSchemaError, ConfigSemanticError):
        assert issubclass(error_type, ConfigurationError)
        assert issubclass(error_type, GreenMachineError)


def test_a_parse_failure_records_the_file() -> None:
    with pytest.raises(ConfigParseError) as caught:
        load_config(invalid_path("duplicate_key.yaml"))

    assert caught.value.context.file_path is not None
    assert "duplicate_key.yaml" in caught.value.context.file_path


def test_a_schema_failure_records_the_key_path() -> None:
    text = mutate('  strong_category_fraction: "0.62"', "  strong_category_fraction: 0.62")

    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(text, file_path="synthetic.yaml")

    context = caught.value.context
    assert context.file_path == "synthetic.yaml"
    assert context.key_path == ("allocations", "strong_category_fraction")
    assert "allocations.strong_category_fraction" in str(caught.value)


def test_a_semantic_failure_records_the_key_path() -> None:
    text = mutate(FUZZY_DISABLED, "  enabled: true")

    with pytest.raises(ConfigSemanticError) as caught:
        load_config_text(text, file_path="synthetic.yaml")

    assert caught.value.context.key_path == ("fuzzy_scoring", "enabled")
    assert caught.value.context.file_path == "synthetic.yaml"


def test_a_component_failure_records_the_metric_and_profile() -> None:
    text = mutate(
        '              - { lower: "0",    upper: "62.4", points: "0" }',
        '              - { lower: "0",    upper: "62.4", points: "-0.1" }',
    )

    with pytest.raises(ConfigSemanticError) as caught:
        load_config_text(text, file_path="synthetic.yaml")

    assert caught.value.context.metric == "exit_velocity"
    assert caught.value.context.window_profile == "RECENT_7D"


def test_the_original_exception_is_preserved_as_cause() -> None:
    text = mutate('  strong_category_fraction: "0.62"', "  strong_category_fraction: 0.62")

    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(text)

    assert caught.value.__cause__ is not None
    assert type(caught.value.__cause__).__name__ == "ValidationError"


def test_no_raw_pydantic_or_yaml_exception_escapes() -> None:
    """The package's public failure contract is its own three error types."""
    import yaml
    from pydantic import ValidationError

    cases = [
        mutate('  strong_category_fraction: "0.62"', "  strong_category_fraction: 0.62"),
        mutate(FUZZY_DISABLED, "  enabled: true"),
        "allocations: { categories: [",
    ]
    for text in cases:
        with pytest.raises(ConfigurationError) as caught:
            load_config_text(text)
        assert not isinstance(caught.value, ValidationError | yaml.YAMLError)


# --------------------------------------------------------------------------
# Missing required keys at each major level
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "old", "new"),
    [
        ("root schema_version", "schema_version: 1\n", ""),
        ("root specification_version", 'specification_version: "v6.3"\n', ""),
        ("root fuzzy policy", "fuzzy_scoring:\n  enabled: false\n", ""),
        ("allocations strong fraction", '  strong_category_fraction: "0.62"\n', ""),
        ("allocations total", '  total_max_points: "12"\n', ""),
        ("category max_points", '      max_points: "2.7"\n', ""),
        ("component sample_type", "    sample_type: air_balls\n", ""),
        ("component direction", "    direction: lower_is_better\n", ""),
        ("profile minimum sample", "        minimum_sample_required: 5\n", ""),
        (
            "missing-data policy",
            "      policy: record_missing\n      reasons: [WEATHER_UNAVAILABLE]\n",
            "      reasons: [WEATHER_UNAVAILABLE]\n",
        ),
        ("missing-data reasons", "      reasons: [WEATHER_UNAVAILABLE]\n", ""),
        ("fuzzy enabled", "  enabled: false\n", ""),
    ],
)
def test_a_missing_required_key_is_refused(label: str, old: str, new: str) -> None:
    """No behaviour-affecting field has a silent default."""
    with pytest.raises((ConfigSchemaError, ConfigParseError)):
        load_config_text(mutate(old, new), file_path="synthetic.yaml")


def test_a_missing_key_names_where_it_belongs() -> None:
    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(drop_line('  total_max_points: "12"'))

    assert caught.value.context.key_path == ("allocations", "total_max_points")


# --------------------------------------------------------------------------
# Unknown keys at every level
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "old", "new"),
    [
        ("root", "schema_version: 1", "schema_version: 1\nsurprise_root: 1"),
        (
            "allocations",
            '  total_max_points: "12"',
            '  total_max_points: "12"\n  surprise_alloc: 1',
        ),
        (
            "category",
            "      components: [exit_velocity, barrel_pct, hard_hit_pct]",
            "      components: [exit_velocity, barrel_pct, hard_hit_pct]\n      surprise_cat: 1",
        ),
        (
            "component",
            "    sample_type: pitches\n    missing_data:\n      policy: record_missing",
            "    sample_type: pitches\n    surprise_comp: 1\n    missing_data:"
            "\n      policy: record_missing",
        ),
        (
            "profile",
            "        minimum_sample_required: 5",
            "        minimum_sample_required: 5\n        surprise_profile: 1",
        ),
        (
            "bucket",
            '              - { lower: "0",    upper: "62.4", points: "0" }',
            '              - { lower: "0", upper: "62.4", points: "0", surprise_bucket: 1 }',
        ),
        (
            "binary predicate",
            "                - { input_name: synthetic_input_a, operator: at_least,"
            ' value: "41.7" }',
            "                - { input_name: synthetic_input_a, operator: at_least,"
            ' value: "41.7", surprise_pred: 1 }',
        ),
        (
            "grade cutoff",
            '    - { grade: D, lower: "0",   upper: "3.3", terminal: false }',
            '    - { grade: D, lower: "0", upper: "3.3", terminal: false, surprise_grade: 1 }',
        ),
        (
            "signal rule",
            "      signal: PASS",
            "      signal: PASS\n      surprise_rule: 1",
        ),
        (
            "signal condition",
            "            - { type: always }",
            "            - { type: always, surprise_condition: 1 }",
        ),
    ],
)
def test_an_unknown_key_is_refused_at_every_level(label: str, old: str, new: str) -> None:
    count = 2 if label in {"binary predicate"} else 1
    text = mutate(old, new, count=count)

    with pytest.raises(ConfigSchemaError, match=r"[Ee]xtra|not permitted|Unable to extract"):
        load_config_text(text, file_path="synthetic.yaml")


def test_an_unknown_key_names_its_location() -> None:
    text = mutate("schema_version: 1", "schema_version: 1\nsurprise_root: 1")

    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(text)

    assert caught.value.context.key_path == ("surprise_root",)

"""The loaded configuration is frozen, fully typed, and holds no mutable state."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

import pydantic
import pytest
from config_fixtures import VALID_PATH, valid_text

from greenmachine.config import (
    BinaryScoring,
    BucketedScoring,
    ComparisonOperator,
    Direction,
    GreenMachineConfig,
    ScoringMethod,
    load_config,
    load_config_text,
)
from greenmachine.domain import (
    Category,
    ComponentId,
    Grade,
    MeasurementId,
    MissingReason,
    SampleType,
    Signal,
    WindowProfile,
)


@pytest.fixture(scope="module")
def config() -> GreenMachineConfig:
    return load_config(VALID_PATH)


def walk(value: object, path: str = "<root>") -> list[tuple[str, object]]:
    """Every value in the loaded object graph, with its path."""
    found: list[tuple[str, object]] = [(path, value)]
    if isinstance(value, pydantic.BaseModel):
        for name in type(value).model_fields:
            found.extend(walk(getattr(value, name), f"{path}.{name}"))
    elif isinstance(value, tuple | list):
        for index, item in enumerate(value):
            found.extend(walk(item, f"{path}[{index}]"))
    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(walk(item, f"{path}[{key!r}]"))
    return found


# --------------------------------------------------------------------------
# Typed structure
# --------------------------------------------------------------------------


def test_domain_enums_are_used_directly(config: GreenMachineConfig) -> None:
    """Not restated as strings: the same members the domain defines."""
    assert {entry.category for entry in config.allocations.categories} == set(Category)
    assert {component.component_id for component in config.components} == set(ComponentId)
    assert {cutoff.grade for cutoff in config.allocations.grade_cutoffs} == set(Grade)
    assert {rule.signal for rule in config.allocations.signal_rules} == set(Signal)

    component = config.components[0]
    assert isinstance(component.sample_type, SampleType)
    assert isinstance(component.profiles[0].window_profile, WindowProfile)
    assert isinstance(component.missing_data.reasons[0], MissingReason)


def test_config_local_vocabulary_is_typed(config: GreenMachineConfig) -> None:
    for component in config.components:
        assert isinstance(component.scoring_method, ScoringMethod)
        assert isinstance(component.direction, Direction)


def test_both_profiles_are_represented_separately(config: GreenMachineConfig) -> None:
    for component in config.components:
        profiles = [profile.window_profile for profile in component.profiles]
        assert set(profiles) == set(WindowProfile)
        assert len(profiles) == len(set(profiles))


def test_attack_angle_measurements_stay_distinct(config: GreenMachineConfig) -> None:
    """Neither measurement may stand in for the other (MODEL_SPEC §9.1)."""
    component = next(
        c for c in config.components if c.component_id is ComponentId.ATTACK_ANGLE_QUALITY
    )

    for profile in component.profiles:
        definitions = [d for d in profile.scoring if isinstance(d, BucketedScoring)]
        measurements = [definition.measurement_id for definition in definitions]
        assert set(measurements) == set(MeasurementId)
        assert len({definition.buckets for definition in definitions}) == 2


def test_every_other_component_names_no_measurement(config: GreenMachineConfig) -> None:
    for component in config.components:
        if component.component_id is ComponentId.ATTACK_ANGLE_QUALITY:
            continue
        for profile in component.profiles:
            for definition in profile.scoring:
                if isinstance(definition, BucketedScoring):
                    assert definition.measurement_id is None


def test_binary_and_bucketed_are_separate_shapes(config: GreenMachineConfig) -> None:
    """A binary definition has no domain or buckets; a bucketed one has no predicate."""
    binary = [
        definition
        for component in config.components
        for profile in component.profiles
        for definition in profile.scoring
        if isinstance(definition, BinaryScoring)
    ]
    assert binary, "the fixture must exercise binary scoring"

    for definition in binary:
        assert not hasattr(definition, "buckets")
        assert not hasattr(definition, "domain_min")
        assert not hasattr(definition, "domain_max")

    bucketed = [
        definition
        for component in config.components
        for profile in component.profiles
        for definition in profile.scoring
        if isinstance(definition, BucketedScoring)
    ]
    for definition in bucketed:
        assert not hasattr(definition, "predicate")
        assert not hasattr(definition, "qualified_points")


def test_allocations_are_not_nested_under_a_profile(config: GreenMachineConfig) -> None:
    """A profile carries minimum samples and scoring only."""
    profile = config.components[0].profiles[0]
    fields = set(type(profile).model_fields)

    assert fields == {"window_profile", "minimum_sample_required", "scoring"}
    assert not fields & {"max_points", "grade_cutoffs", "strong_category_fraction"}


# --------------------------------------------------------------------------
# Immutability
# --------------------------------------------------------------------------


def test_no_dict_list_or_set_exists_in_the_object_graph(config: GreenMachineConfig) -> None:
    """No dictionary escapes the loader (ARCHITECTURE.md §4.2)."""
    offenders = [
        (path, type(value).__name__)
        for path, value in walk(config)
        if isinstance(value, dict | list | set | frozenset | bytearray)
    ]

    assert not offenders, f"mutable containers in the loaded configuration: {offenders}"


def test_every_sequence_is_a_tuple(config: GreenMachineConfig) -> None:
    assert isinstance(config.components, tuple)
    assert isinstance(config.allocations.categories, tuple)
    assert isinstance(config.allocations.categories[0].components, tuple)
    assert isinstance(config.allocations.signal_rules[0].any_of, tuple)
    assert isinstance(config.components[0].missing_data.reasons, tuple)


def test_no_float_exists_anywhere_in_the_object_graph(config: GreenMachineConfig) -> None:
    """ADR-0002: nothing on the scoring path has been through binary floating point."""
    offenders = [(path, value) for path, value in walk(config) if isinstance(value, float)]

    assert not offenders, f"float values in the loaded configuration: {offenders}"


def test_every_scoring_numeric_is_a_decimal(config: GreenMachineConfig) -> None:
    assert isinstance(config.allocations.total_max_points, Decimal)
    assert isinstance(config.allocations.strong_category_fraction, Decimal)
    assert isinstance(config.allocations.categories[0].max_points, Decimal)
    assert isinstance(config.allocations.grade_cutoffs[0].lower, Decimal)
    assert isinstance(config.components[0].max_points, Decimal)


def test_fractional_allocations_survive_exactly(config: GreenMachineConfig) -> None:
    total = sum((entry.max_points for entry in config.allocations.categories), Decimal(0))

    assert total == Decimal("12")
    assert config.allocations.strong_category_fraction == Decimal("0.62")


@pytest.mark.parametrize(
    ("path", "field"),
    [
        ("root", "schema_version"),
        ("allocations", "total_max_points"),
        ("component", "max_points"),
        ("profile", "minimum_sample_required"),
    ],
)
def test_mutation_is_refused(config: GreenMachineConfig, path: str, field: str) -> None:
    target: object = config
    if path == "allocations":
        target = config.allocations
    elif path == "component":
        target = config.components[0]
    elif path == "profile":
        target = config.components[0].profiles[0]

    with pytest.raises(pydantic.ValidationError):
        setattr(target, field, Decimal("1"))


def test_nested_models_are_frozen_too(config: GreenMachineConfig) -> None:
    for _, value in walk(config):
        if isinstance(value, pydantic.BaseModel):
            assert value.model_config.get("frozen") is True
            assert value.model_config.get("extra") == "forbid"


# --------------------------------------------------------------------------
# Value semantics and independence
# --------------------------------------------------------------------------


def test_equality_is_by_value() -> None:
    first = load_config_text(valid_text())
    second = load_config_text(valid_text())

    assert first == second
    assert first is not second


def test_two_loads_return_independent_objects() -> None:
    """No shared mutable state survives between calls."""
    first = load_config_text(valid_text())
    second = load_config_text(valid_text())

    assert first.components is not second.components
    assert first.allocations is not second.allocations
    assert first.components[0].profiles[0] is not second.components[0].profiles[0]


def test_the_same_text_twice_produces_equal_objects() -> None:
    text = valid_text()

    assert load_config_text(text) == load_config_text(text)


def test_loading_does_not_mutate_the_input_text() -> None:
    text = valid_text()
    before = str(text)

    load_config_text(text)

    assert text == before


def test_the_raw_mapping_is_never_exposed(config: GreenMachineConfig) -> None:
    """No field holds the parsed YAML, and no accessor hands it back."""
    for name in type(config).model_fields:
        assert not isinstance(getattr(config, name), dict)
    assert not hasattr(config, "raw")
    assert not hasattr(config, "document")


def test_comparison_operators_are_a_closed_vocabulary() -> None:
    from typing import get_args

    assert set(get_args(ComparisonOperator)) == {
        "at_least",
        "greater_than",
        "at_most",
        "less_than",
        "equal_to",
    }


def test_predicate_is_data_only(config: GreenMachineConfig) -> None:
    """Nothing executable is stored: comparisons are strings, enums, Decimals."""
    binary = next(
        definition
        for component in config.components
        for profile in component.profiles
        for definition in profile.scoring
        if isinstance(definition, BinaryScoring)
    )
    clauses = binary.predicate.all_of or binary.predicate.any_of
    assert clauses is not None

    for comparison in clauses:
        assert isinstance(comparison.input_name, str)
        assert isinstance(comparison.value, Decimal)
        assert not callable(comparison.value)
        assert isinstance(comparison.operator, str) and not isinstance(comparison.operator, Enum)

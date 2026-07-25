"""Remaining invariants and boundaries not reached by the main suites."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from config_fixtures import ENVIRONMENT_CATEGORY, WEATHER_COMPONENT, mutate

from greenmachine.config import ConfigParseError, ConfigSchemaError, load_config, load_config_text
from greenmachine.config.errors import key_path_text
from greenmachine.config.schema import _decimal_from_quoted_string, _strict_count
from greenmachine.config.validation_rules import ConfigSemanticError


def reject(text: str) -> ConfigSemanticError:
    with pytest.raises(ConfigSemanticError) as caught:
        load_config_text(text, file_path="synthetic.yaml")
    return caught.value


# --------------------------------------------------------------------------
# Category / component membership
# --------------------------------------------------------------------------


def test_a_missing_category_is_rejected() -> None:
    """All five categories must appear (MODEL_SPEC §2)."""
    error = reject(mutate(f"{ENVIRONMENT_CATEGORY}\n", ""))

    assert "category missing" in str(error)
    assert error.context.key_path == ("allocations", "categories")


def test_a_category_referencing_an_unconfigured_component_is_rejected() -> None:
    """Invariant 14: a category may only reference components that exist."""
    error = reject(mutate(WEATHER_COMPONENT, ""))

    assert "references undefined component" in str(error)
    assert "weather" in str(error)
    assert error.context.key_path[:2] == ("allocations", "categories")


def test_an_incomplete_component_set_is_rejected() -> None:
    """A complete configuration defines every scored component."""
    text = mutate(WEATHER_COMPONENT, "")
    text = text.replace("      components: [park, weather]", "      components: [park]", 1)
    error = reject(text)

    assert "must define every scored component" in str(error)
    assert "weather" in str(error)


def test_a_non_positive_category_maximum_is_rejected() -> None:
    text = mutate('      max_points: "2.7"', '      max_points: "0"')
    text = text.replace(
        '    max_points: "0.9"\n    sample_type: batted_ball_events',
        '    max_points: "0"\n    sample_type: batted_ball_events',
        1,
    )
    text = text.replace('    max_points: "1.1"', '    max_points: "0"', 1)
    text = text.replace('    max_points: "0.7"', '    max_points: "0"', 1)
    error = reject(text)

    assert "greater than 0" in str(error)


def test_a_non_positive_component_maximum_is_rejected() -> None:
    text = mutate('      max_points: "2.4"', '      max_points: "0"')
    text = text.replace('    max_points: "2.4"', '    max_points: "0"', 1)
    error = reject(text)

    assert "greater than 0" in str(error)


def test_a_duplicate_applicable_profile_is_rejected() -> None:
    error = reject(
        mutate(
            "    applicable_profiles: [RECENT_7D, LONG_TERM_2Y]\n"
            "    profiles:\n"
            "      - window_profile: RECENT_7D\n"
            "        minimum_sample_required: 5",
            "    applicable_profiles: [RECENT_7D, RECENT_7D, LONG_TERM_2Y]\n"
            "    profiles:\n"
            "      - window_profile: RECENT_7D\n"
            "        minimum_sample_required: 5",
        )
    )

    assert "listed more than once" in str(error)


# --------------------------------------------------------------------------
# Numeric field validators, exercised directly
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("float", 0.1),
        ("int", 7),
        ("bool", True),
        ("Decimal", Decimal("1.5")),
        ("None", None),
        ("list", ["1"]),
    ],
)
def test_only_a_quoted_string_becomes_a_config_decimal(label: str, value: object) -> None:
    with pytest.raises(ValueError, match=r"quoted decimal string"):
        _decimal_from_quoted_string(value)


@pytest.mark.parametrize("text", ["abc", "", "   ", "NaN", "Infinity", "1.2.3"])
def test_a_malformed_decimal_string_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match=r".+"):
        _decimal_from_quoted_string(text)


def test_a_well_formed_quoted_string_is_accepted() -> None:
    assert _decimal_from_quoted_string("2.50") == Decimal("2.50")


@pytest.mark.parametrize(("label", "value"), [("bool", True), ("float", 1.5), ("str", "1")])
def test_only_a_real_integer_becomes_a_count(label: str, value: object) -> None:
    with pytest.raises(ValueError, match=r"must be an integer"):
        _strict_count(value)


def test_a_real_integer_is_accepted_as_a_count() -> None:
    assert _strict_count(7) == 7


# --------------------------------------------------------------------------
# Error rendering and file handling
# --------------------------------------------------------------------------


def test_an_empty_key_path_renders_as_root() -> None:
    assert key_path_text(()) == "<root>"


def test_a_key_path_renders_indices_as_brackets() -> None:
    assert key_path_text(("allocations", "categories", "0", "max_points")) == (
        "allocations.categories[0].max_points"
    )


def test_a_non_utf8_file_is_a_parse_error(tmp_path: Path) -> None:
    """Configuration is UTF-8; anything else is refused rather than guessed at."""
    bad = tmp_path / "latin1.yaml"
    bad.write_bytes("schema_version: 1\nname: caf\xe9\n".encode("latin-1"))

    with pytest.raises(ConfigParseError):
        load_config(bad)


def test_a_directory_instead_of_a_file_is_a_parse_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigParseError, match=r"could not read configuration file"):
        load_config(tmp_path)


def test_a_schema_error_reports_how_many_problems_were_found() -> None:
    """One typed failure, but the count of the rest is not hidden."""
    text = mutate("schema_version: 1", "schema_version: 1\nfirst_extra: 1\nsecond_extra: 2")

    with pytest.raises(ConfigSchemaError, match=r"further schema problem"):
        load_config_text(text)

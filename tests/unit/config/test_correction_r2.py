"""Regression tests for the GM-003 r2 correction pass.

Three focused fixes: positional (not global-string) union-path normalization,
``file_path`` validation at the ``load_config_text`` boundary, and a full-string
override-reason check.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from config_fixtures import mutate, valid_text

from greenmachine.config import (
    ConfigParseError,
    ConfigSchemaError,
    ConfigSemanticError,
    load_config_text,
)

VALID_PATH = "tests/fixtures/config/valid/complete_synthetic.yaml"


# --------------------------------------------------------------------------
# 1. Positional union-path normalization
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["always", "bucketed", "binary", "grade_in", "total_score"])
def test_a_real_root_key_named_after_a_discriminator_is_preserved(name: str) -> None:
    """A discriminator-named key at the root is a real key, not a synthetic tag."""
    text = mutate("schema_version: 1", f"schema_version: 1\n{name}: nope")

    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(text, file_path="x.yaml")

    assert caught.value.context.key_path == (name,)


@pytest.mark.parametrize("name", ["always", "bucketed", "binary"])
def test_a_real_component_level_key_named_after_a_discriminator_is_preserved(
    name: str,
) -> None:
    text = mutate(
        "  - component_id: exit_velocity\n    scoring_method: bucketed",
        f"  - component_id: exit_velocity\n    {name}: nope\n    scoring_method: bucketed",
    )

    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(text, file_path="x.yaml")

    assert caught.value.context.key_path == ("components", "0", name)


def test_the_synthetic_scoring_branch_is_removed() -> None:
    """The tag Pydantic inserts after scoring[i] is dropped; the real key stays."""
    text = mutate(
        '            domain_max: "125"\n            buckets:\n'
        '              - { lower: "0",    upper: "62.4", points: "0" }',
        '            domain_max: "125"\n            mystery: 1\n            buckets:\n'
        '              - { lower: "0",    upper: "62.4", points: "0" }',
    )

    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(text, file_path="x.yaml")

    key_path = caught.value.context.key_path
    assert "bucketed" not in key_path
    assert key_path == ("components", "0", "profiles", "0", "scoring", "0", "mystery")


def test_a_real_key_equal_to_another_discriminator_survives_branch_removal() -> None:
    """method: bucketed + a real key named 'binary' -> keep only the real one.

    Pydantic reports ``... scoring, 0, bucketed, binary``. The first ``bucketed``
    is the synthetic branch tag; the trailing ``binary`` is a genuine unknown key.
    """
    text = mutate(
        '            domain_max: "125"\n            buckets:\n'
        '              - { lower: "0",    upper: "62.4", points: "0" }',
        '            domain_max: "125"\n            binary: unexpected\n            buckets:\n'
        '              - { lower: "0",    upper: "62.4", points: "0" }',
    )

    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(text, file_path="x.yaml")

    key_path = caught.value.context.key_path
    assert key_path == ("components", "0", "profiles", "0", "scoring", "0", "binary")


def test_the_synthetic_condition_branch_is_removed() -> None:
    text = mutate(
        "            - { type: grade_in, grades: [S] }",
        "            - { type: grade_in, grades: [S], mystery: 1 }",
    )

    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(text, file_path="x.yaml")

    key_path = caught.value.context.key_path
    assert "grade_in" not in key_path
    assert key_path[-1] == "mystery"
    assert key_path[:3] == ("allocations", "signal_rules", "1")


def test_a_condition_real_key_equal_to_another_discriminator_survives() -> None:
    """type: grade_in + a real key named 'always' -> keep only the real one."""
    text = mutate(
        "            - { type: grade_in, grades: [S] }",
        "            - { type: grade_in, grades: [S], always: unexpected }",
    )

    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(text, file_path="x.yaml")

    key_path = caught.value.context.key_path
    assert key_path[-1] == "always"
    assert key_path[-2] == "0"
    assert key_path[-3] == "all_of"


def test_branch_removal_does_not_depend_on_a_global_string_filter() -> None:
    """A discriminator-named key at any non-union position is never stripped."""
    # 'total_score' as an unknown key on a signal rule (not inside all_of).
    text = mutate(
        "      signal: PASS",
        "      signal: PASS\n      total_score: nope",
    )

    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(text, file_path="x.yaml")

    assert caught.value.context.key_path[-1] == "total_score"


# --------------------------------------------------------------------------
# 2. load_config_text file_path validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad", [123, True, b"bytes", Path("x.yaml"), object(), ["a"], {"a": 1}, 4.5]
)
def test_an_invalid_file_path_is_a_parse_error(bad: object) -> None:
    with pytest.raises(ConfigParseError, match=r"file_path must be a str or None"):
        load_config_text(valid_text(), file_path=bad)  # type: ignore[arg-type]


def test_an_invalid_file_path_is_refused_even_with_empty_text() -> None:
    """The boundary check runs before parsing, so the text does not matter."""
    with pytest.raises(ConfigParseError, match=r"file_path must be a str or None"):
        load_config_text("", file_path=123)  # type: ignore[arg-type]


def test_an_invalid_file_path_message_names_the_received_type() -> None:
    with pytest.raises(ConfigParseError, match=r"got int"):
        load_config_text(valid_text(), file_path=123)  # type: ignore[arg-type]


def test_an_invalid_file_path_never_leaks_a_raw_type_error() -> None:
    try:
        load_config_text(valid_text(), file_path=object())  # type: ignore[arg-type]
    except ConfigParseError as error:
        assert error.context.file_path is None
    else:  # pragma: no cover - the call must raise
        pytest.fail("expected a ConfigParseError")


def test_an_invalid_file_path_is_not_silently_stringified() -> None:
    """A bad file_path never becomes a nonsense label on the error context."""
    with pytest.raises(ConfigParseError) as caught:
        load_config_text(valid_text(), file_path=123)  # type: ignore[arg-type]

    assert caught.value.context.file_path is None


def test_a_string_file_path_succeeds() -> None:
    config = load_config_text(valid_text(), file_path="fixture.yaml")

    assert len(config.components) == 11


def test_a_none_file_path_succeeds() -> None:
    config = load_config_text(valid_text(), file_path=None)

    assert len(config.components) == 11


def test_the_default_file_path_is_none() -> None:
    config = load_config_text(valid_text())

    assert len(config.components) == 11


# --------------------------------------------------------------------------
# 3. Full-string override-reason match
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        "synthetic_power_veto\n",
        "synthetic_power_veto\r",
        "synthetic_power_veto\t",
        "synthetic_power_veto ",
        " synthetic_power_veto",
        "UPPER_CASE",
        "not-stable",
        "not.stable",
    ],
)
def test_an_override_reason_that_does_not_fully_match_is_rejected(reason: str) -> None:
    """A trailing newline no longer slips past the `$` anchor."""
    old = "      override_reason: synthetic_power_veto"
    text = mutate(old, f"      override_reason: {reason!r}")

    with pytest.raises(ConfigSemanticError) as caught:
        load_config_text(text, file_path="x.yaml")

    assert "stable identifier" in str(caught.value)
    assert caught.value.context.key_path == (
        "allocations",
        "signal_rules",
        "0",
        "override_reason",
    )


def test_an_empty_override_reason_is_rejected() -> None:
    text = mutate("      override_reason: synthetic_power_veto", '      override_reason: ""')

    with pytest.raises(ConfigSemanticError, match=r"stable identifier"):
        load_config_text(text, file_path="x.yaml")


@pytest.mark.parametrize(
    "reason", ["power_profile_veto", "synthetic_power_veto", "sample_override_2", "a"]
)
def test_a_valid_stable_code_is_accepted(reason: str) -> None:
    text = mutate("      override_reason: synthetic_power_veto", f"      override_reason: {reason}")

    config = load_config_text(text)

    assert config.allocations.signal_rules[0].override_reason == reason

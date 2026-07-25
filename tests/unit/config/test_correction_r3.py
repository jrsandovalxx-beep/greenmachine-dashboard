"""Regression tests for the GM-003 r3 correction pass.

One fix: the union-path normalizer identifies a discriminated union by its full
schema **position**, not by the immediate field name. ``all_of`` names a
discriminated ``SignalCondition`` union under a signal rule, but a plain
``PredicateComparison`` list under a binary component's qualification predicate.
A real key named after a discriminator (``grade_in``, ``always``, ...) inside a
binary predicate's ``all_of``/``any_of`` must therefore survive, while the
genuine synthetic branch tag of the two real unions is still removed.
"""

from __future__ import annotations

import pytest
from config_fixtures import mutate

from greenmachine.config import ConfigSchemaError, load_config_text

# The weather component is components[10]; its RECENT_7D profile is profiles[0]
# and its single binary scoring element is scoring[0]. This exact block is unique
# in the fixture — the only binary scoring under a RECENT_7D window profile — so
# a mutation of it targets one predicate unambiguously.
WEATHER_RECENT_PREDICATE = """      - window_profile: RECENT_7D
        minimum_sample_required: 1
        scoring:
          - method: binary
            qualified_points: "0.8"
            predicate:
              all_of:
                - { input_name: synthetic_input_a, operator: at_least, value: "41.7" }
                - { input_name: synthetic_input_b, operator: greater_than, value: "3.9" }"""

_PREDICATE_ITEM = (
    '                - { input_name: synthetic_input_a, operator: at_least, value: "41.7" }'
)

# Every discriminator value of the SignalCondition union. Each is a valid key
# name for the *signal* union but an unknown key for a PredicateComparison, so it
# is exactly the shape that would trip a name-only normalizer.
SIGNAL_TAGS = ["grade_in", "total_score", "category_score", "strong_category_count", "always"]


def _binary_predicate_with_extra(clause: str, name: str) -> str:
    """Fixture whose weather RECENT_7D predicate's first item carries a real key
    named after a signal-condition discriminator plus a matching ``type`` field.

    The ``type`` field is what makes the pre-r3 false positive fire: the old
    normalizer removed the segment when the document object carried
    ``type == <tag>``. ``clause`` selects ``all_of`` or ``any_of``.
    """
    replacement_item = (
        f"                - {name}: unexpected\n"
        f"                  type: {name}\n"
        "                  input_name: synthetic_input_a\n"
        "                  operator: at_least\n"
        '                  value: "41.7"'
    )
    block = WEATHER_RECENT_PREDICATE.replace(_PREDICATE_ITEM, replacement_item)
    if clause == "any_of":
        block = block.replace("              all_of:", "              any_of:")
    return mutate(WEATHER_RECENT_PREDICATE, block)


# --------------------------------------------------------------------------
# A / B. A binary predicate's all_of is NOT a union: real keys survive
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", SIGNAL_TAGS)
def test_a_binary_predicate_all_of_preserves_a_discriminator_named_key(name: str) -> None:
    text = _binary_predicate_with_extra("all_of", name)

    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(text, file_path="x.yaml")

    assert caught.value.context.key_path == (
        "components",
        "10",
        "profiles",
        "0",
        "scoring",
        "0",
        "predicate",
        "all_of",
        "0",
        name,
    )


# --------------------------------------------------------------------------
# C. A binary predicate's any_of is likewise not a union
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", SIGNAL_TAGS)
def test_a_binary_predicate_any_of_preserves_a_discriminator_named_key(name: str) -> None:
    text = _binary_predicate_with_extra("any_of", name)

    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(text, file_path="x.yaml")

    assert caught.value.context.key_path == (
        "components",
        "10",
        "profiles",
        "0",
        "scoring",
        "0",
        "predicate",
        "any_of",
        "0",
        name,
    )


# --------------------------------------------------------------------------
# D. The genuine signal-condition branch tag is still removed
# --------------------------------------------------------------------------


def test_the_signal_condition_branch_tag_is_still_removed() -> None:
    text = mutate(
        "            - { type: grade_in, grades: [S] }",
        "            - { type: grade_in, grades: [S], mystery: 1 }",
    )

    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(text, file_path="x.yaml")

    key_path = caught.value.context.key_path
    assert "grade_in" not in key_path
    assert key_path == (
        "allocations",
        "signal_rules",
        "1",
        "any_of",
        "0",
        "all_of",
        "0",
        "mystery",
    )


# --------------------------------------------------------------------------
# E. A real key after the genuine signal branch is preserved
# --------------------------------------------------------------------------


def test_a_real_key_after_the_signal_branch_is_preserved() -> None:
    text = mutate(
        "            - { type: grade_in, grades: [S] }",
        "            - { type: grade_in, grades: [S], always: unexpected }",
    )

    with pytest.raises(ConfigSchemaError) as caught:
        load_config_text(text, file_path="x.yaml")

    assert caught.value.context.key_path == (
        "allocations",
        "signal_rules",
        "1",
        "any_of",
        "0",
        "all_of",
        "0",
        "always",
    )


# --------------------------------------------------------------------------
# F. The scoring-union branch tag is still removed
# --------------------------------------------------------------------------


def test_the_scoring_branch_tag_is_still_removed() -> None:
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
    assert key_path == (
        "components",
        "0",
        "profiles",
        "0",
        "scoring",
        "0",
        "mystery",
    )

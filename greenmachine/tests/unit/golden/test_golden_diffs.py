"""Unit tests for the canonical-structure diff engine itself.

The engine compares parsed canonical JSON structures — mappings in sorted key
order, sequences in index order, scalars exactly — and never routes a value
through a binary float or an object repr.
"""

from __future__ import annotations

import pytest
from tests.golden.runner import (
    DifferenceKind,
    FieldDifference,
    canonical_structure_differences,
)

# --------------------------------------------------------------------------
# Equality
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "structure",
    [
        None,
        True,
        7,
        "1.111",
        [],
        {},
        {"a": 1, "b": [True, None, "x"], "c": {"nested": "2.250"}},
        [{"k": "v"}, [1, 2, 3], "text"],
    ],
    ids=["null", "bool", "int", "string", "empty-list", "empty-dict", "nested-dict", "mixed-list"],
)
def test_equal_structures_produce_an_empty_diff(structure: object) -> None:
    assert canonical_structure_differences(structure, structure) == ()


def test_key_order_does_not_matter_for_equality() -> None:
    assert canonical_structure_differences({"a": 1, "b": 2}, {"b": 2, "a": 1}) == ()


# --------------------------------------------------------------------------
# The four structural difference kinds
# --------------------------------------------------------------------------


def test_missing_key() -> None:
    differences = canonical_structure_differences({"present": 1, "gone": 2}, {"present": 1})
    assert differences == (
        FieldDifference(path="gone", kind=DifferenceKind.MISSING_KEY, expected="2", actual=None),
    )


def test_unexpected_key() -> None:
    differences = canonical_structure_differences({"present": 1}, {"present": 1, "extra": 2})
    assert differences == (
        FieldDifference(
            path="extra", kind=DifferenceKind.UNEXPECTED_KEY, expected=None, actual="2"
        ),
    )


def test_type_mismatch_between_string_and_integer() -> None:
    differences = canonical_structure_differences({"value": "1"}, {"value": 1})
    assert len(differences) == 1
    difference = differences[0]
    assert difference.kind is DifferenceKind.TYPE_MISMATCH
    assert difference.path == "value"
    assert difference.expected == 'string "1"'
    assert difference.actual == "integer 1"


def test_boolean_is_not_an_integer() -> None:
    """JSON true and JSON 1 are different types; Python bool must not collapse them."""
    differences = canonical_structure_differences({"flag": True}, {"flag": 1})
    assert differences[0].kind is DifferenceKind.TYPE_MISMATCH
    assert differences[0].expected == "boolean true"
    assert differences[0].actual == "integer 1"


def test_object_versus_array_is_a_type_mismatch() -> None:
    differences = canonical_structure_differences({"x": {"a": 1}}, {"x": [1]})
    assert differences[0].kind is DifferenceKind.TYPE_MISMATCH


def test_value_mismatch_renders_strings_exactly() -> None:
    differences = canonical_structure_differences({"score": "1.111"}, {"score": "2.222"})
    assert differences == (
        FieldDifference(
            path="score",
            kind=DifferenceKind.VALUE_MISMATCH,
            expected='"1.111"',
            actual='"2.222"',
        ),
    )


def test_decimal_strings_differing_only_in_trailing_zero_are_different() -> None:
    """Exact rendering: "2.25" and "2.250" must not be equated numerically."""
    differences = canonical_structure_differences({"points": "2.25"}, {"points": "2.250"})
    assert len(differences) == 1
    assert differences[0].kind is DifferenceKind.VALUE_MISMATCH
    assert differences[0].expected == '"2.25"'
    assert differences[0].actual == '"2.250"'


def test_integer_value_mismatch_renders_without_quotes() -> None:
    differences = canonical_structure_differences({"n": 1}, {"n": 2})
    assert differences[0].expected == "1"
    assert differences[0].actual == "2"


def test_null_versus_value() -> None:
    differences = canonical_structure_differences({"x": None}, {"x": "present"})
    assert differences[0].kind is DifferenceKind.TYPE_MISMATCH
    assert differences[0].expected == "null null"
    assert differences[0].actual == 'string "present"'


# --------------------------------------------------------------------------
# Paths, ordering, list semantics
# --------------------------------------------------------------------------


def test_nested_paths_use_dots_and_indexes() -> None:
    expected = {"payload": {"component_scores": [{"points_awarded": "1.111"}]}}
    actual = {"payload": {"component_scores": [{"points_awarded": "2.222"}]}}
    differences = canonical_structure_differences(expected, actual)
    assert differences[0].path == "payload.component_scores[0].points_awarded"


def test_list_index_order_is_preserved() -> None:
    differences = canonical_structure_differences(["a", "b", "c"], ["a", "x", "c"])
    assert differences == (
        FieldDifference(
            path="[1]", kind=DifferenceKind.VALUE_MISMATCH, expected='"b"', actual='"x"'
        ),
    )


def test_longer_expected_list_reports_missing_indexes() -> None:
    differences = canonical_structure_differences({"items": [1, 2, 3]}, {"items": [1]})
    assert [d.path for d in differences] == ["items[1]", "items[2]"]
    assert {d.kind for d in differences} == {DifferenceKind.MISSING_KEY}


def test_longer_actual_list_reports_unexpected_indexes() -> None:
    differences = canonical_structure_differences({"items": [1]}, {"items": [1, 2]})
    assert [d.path for d in differences] == ["items[1]"]
    assert differences[0].kind is DifferenceKind.UNEXPECTED_KEY


def test_multiple_differences_are_reported_in_deterministic_key_order() -> None:
    expected = {"b": 1, "a": 1, "c": 1}
    actual = {"b": 2, "a": 2, "c": 2}
    differences = canonical_structure_differences(expected, actual)
    assert [d.path for d in differences] == ["a", "b", "c"]


def test_repeated_calls_are_identical() -> None:
    expected = {"a": [1, {"x": "1.5"}], "b": None}
    actual = {"a": [2, {"x": "2.5"}], "c": True}
    first = canonical_structure_differences(expected, actual)
    second = canonical_structure_differences(expected, actual)
    assert first == second


def test_root_scalar_mismatch_renders_a_root_marker() -> None:
    differences = canonical_structure_differences("a", "b")
    assert differences[0].path == ""
    assert differences[0].describe().startswith("<root>: value mismatch")


def test_describe_format_matches_the_documented_shape() -> None:
    difference = FieldDifference(
        path="payload.component_scores[0].points_awarded",
        kind=DifferenceKind.VALUE_MISMATCH,
        expected='"1.111"',
        actual='"2.222"',
    )
    assert difference.describe() == (
        "payload.component_scores[0].points_awarded: value mismatch\n"
        '    expected "1.111"\n'
        '    actual   "2.222"'
    )


def test_differences_are_immutable() -> None:
    difference = canonical_structure_differences({"a": 1}, {"a": 2})[0]
    with pytest.raises(AttributeError):
        difference.path = "other"  # type: ignore[misc]

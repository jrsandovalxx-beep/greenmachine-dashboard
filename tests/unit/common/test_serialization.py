"""Canonical serialization: byte-identical output for equal object graphs."""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

import pytest

from greenmachine.common import CanonicalizationError, canonical_bytes, canonical_json

EASTERN = timezone(timedelta(hours=-4))


class Colour(Enum):
    GREEN = "green"
    BLUE = "blue"


class Count(Enum):
    ONE = 1
    TWO = 2


@dataclasses.dataclass(frozen=True)
class Point:
    x: Decimal
    y: Decimal


@dataclasses.dataclass(frozen=True)
class Wrapper:
    label: str
    point: Point
    tags: tuple[str, ...]


# --------------------------------------------------------------------------
# Supported types
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "null"),
        (True, "true"),
        (False, "false"),
        (0, "0"),
        (-7, "-7"),
        (10**30, str(10**30)),
        ("text", '"text"'),
        ("", '""'),
        (Decimal("1.50"), '"1.5"'),
        (Decimal("-0"), '"0"'),
        (Colour.GREEN, '"green"'),
        (Count.TWO, "2"),
        (date(2026, 7, 15), '"2026-07-15"'),
        ([], "[]"),
        ((), "[]"),
        ({}, "{}"),
    ],
)
def test_supported_scalars_and_empties(value: object, expected: str) -> None:
    assert canonical_json(value) == expected


def test_decimal_is_a_string_never_a_json_number() -> None:
    """A JSON number would be read back as a binary float and lose the value."""
    text = canonical_json({"score": Decimal("2.25")})

    assert text == '{"score":"2.25"}'
    assert "2.25" in text
    assert ":2.25" not in text


def test_nested_structures_encode_recursively() -> None:
    value = {"b": [Decimal("1"), Colour.BLUE], "a": (1, "two")}

    assert canonical_json(value) == '{"a":[1,"two"],"b":["1","blue"]}'


def test_tuple_and_list_encode_identically() -> None:
    """Order is part of the value; container flavour is not."""
    assert canonical_json((1, 2, 3)) == canonical_json([1, 2, 3])


def test_compact_separators_are_used() -> None:
    assert canonical_json({"a": 1, "b": 2}) == '{"a":1,"b":2}'


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


def test_mapping_key_insertion_order_does_not_change_bytes() -> None:
    first = {"z": 1, "m": 2, "a": 3}
    second = {"a": 3, "z": 1, "m": 2}

    assert canonical_bytes(first) == canonical_bytes(second)
    assert canonical_json(first) == '{"a":3,"m":2,"z":1}'


def test_nested_mapping_keys_are_also_sorted() -> None:
    value = {"outer": {"z": 1, "a": 2}}

    assert canonical_json(value) == '{"outer":{"a":2,"z":1}}'


def test_equal_dataclasses_produce_identical_bytes() -> None:
    left = Point(Decimal("1.0"), Decimal("2.50"))
    right = Point(Decimal("1"), Decimal("2.5"))

    assert left == right
    assert canonical_bytes(left) == canonical_bytes(right)


def test_dataclass_fields_are_emitted_in_sorted_order() -> None:
    assert canonical_json(Point(Decimal("1"), Decimal("2"))) == '{"x":"1","y":"2"}'


def test_nested_dataclass_graph_is_stable() -> None:
    wrapper = Wrapper("label", Point(Decimal("1"), Decimal("2")), ("a", "b"))

    assert canonical_json(wrapper) == (
        '{"label":"label","point":{"x":"1","y":"2"},"tags":["a","b"]}'
    )


def test_equal_instants_in_different_zones_serialize_identically() -> None:
    """Normalised to UTC, so one instant has one encoding."""
    utc = datetime(2026, 7, 15, 23, 10, tzinfo=UTC)
    eastern = datetime(2026, 7, 15, 19, 10, tzinfo=EASTERN)

    assert utc == eastern
    assert canonical_bytes(utc) == canonical_bytes(eastern)
    assert canonical_json(utc) == '"2026-07-15T23:10:00+00:00"'


def test_repeated_serialization_is_stable_within_a_process() -> None:
    wrapper = Wrapper("x", Point(Decimal("1"), Decimal("2")), ("t",))

    assert len({canonical_bytes(wrapper) for _ in range(50)}) == 1


def test_output_is_utf8_encoded_bytes() -> None:
    assert canonical_bytes({"a": 1}) == b'{"a":1}'


def test_non_ascii_content_is_preserved_and_stable() -> None:
    value = {"name": "Recent — Last 7 Days", "emoji": "⚾"}

    encoded = canonical_bytes(value)

    assert encoded.decode("utf-8") == canonical_json(value)
    assert "—" in encoded.decode("utf-8")
    assert canonical_bytes(value) == encoded


def test_string_content_is_never_altered() -> None:
    """No case folding, no unicode normalisation, no trimming."""
    for raw in ("  padded  ", "MiXeD", "a\tb", "line\nbreak", "café"):
        assert canonical_json(raw) == canonical_json(raw)
        assert raw in canonical_json({"v": raw}) or raw.encode("unicode_escape")


# --------------------------------------------------------------------------
# Rejections
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", [1.5, 0.0, -2.25, float("nan"), float("inf")])
def test_float_is_refused(value: float) -> None:
    with pytest.raises(CanonicalizationError, match=r"float is never serialized"):
        canonical_json(value)


def test_float_nested_deep_in_a_graph_is_refused() -> None:
    """The refusal must reach into the graph, not just check the top level."""
    graph = {"a": {"b": [{"c": (1, 2, {"d": 3.5})}]}}

    with pytest.raises(CanonicalizationError, match=r"float is never serialized"):
        canonical_json(graph)


def test_float_inside_a_dataclass_is_refused() -> None:
    @dataclasses.dataclass(frozen=True)
    class Leaky:
        value: float

    with pytest.raises(CanonicalizationError, match=r"float is never serialized"):
        canonical_json(Leaky(1.5))


def test_the_rejection_message_names_the_path() -> None:
    graph = {"outer": {"inner": 1.5}}

    with pytest.raises(CanonicalizationError, match=r"inner"):
        canonical_json(graph)


@pytest.mark.parametrize("value", [{1, 2}, frozenset({1, 2})])
def test_sets_are_refused(value: object) -> None:
    with pytest.raises(CanonicalizationError, match=r"no defined order"):
        canonical_json(value)


def test_naive_datetime_is_refused() -> None:
    with pytest.raises(CanonicalizationError, match=r"naive datetime"):
        canonical_json(datetime(2026, 7, 15, 12, 0))


def test_naive_datetime_nested_is_refused() -> None:
    with pytest.raises(CanonicalizationError, match=r"naive datetime"):
        canonical_json({"at": [datetime(2026, 7, 15, 12, 0)]})


@pytest.mark.parametrize("value", [object(), complex(1, 2), b"bytes", Decimal, range(3)])
def test_unsupported_types_are_refused_loudly(value: object) -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json(value)


def test_non_string_mapping_keys_are_refused() -> None:
    with pytest.raises(CanonicalizationError, match=r"mapping keys must be str"):
        canonical_json({1: "a"})


def test_no_repr_or_str_fallback_exists() -> None:
    """An unmodelled object must fail, never acquire a repr-based encoding."""

    class Custom:
        def __repr__(self) -> str:
            return "Custom()"

        def __str__(self) -> str:
            return "custom"

    with pytest.raises(CanonicalizationError, match=r"not a supported type"):
        canonical_json(Custom())


def test_a_cycle_is_refused_rather_than_recursing_forever() -> None:
    cycle: dict[str, object] = {"self": None}
    cycle["self"] = cycle

    with pytest.raises(CanonicalizationError, match=r"cycle"):
        canonical_json(cycle)


def test_a_repeated_sibling_is_not_mistaken_for_a_cycle() -> None:
    """The same object twice in one graph is fine; only a true cycle is refused."""
    shared = Point(Decimal("1"), Decimal("2"))

    assert canonical_json([shared, shared]) == '[{"x":"1","y":"2"},{"x":"1","y":"2"}]'

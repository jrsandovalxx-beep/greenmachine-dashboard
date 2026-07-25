"""Canonical Decimal text: one exact representation per value.

Equal Decimals must render identically, and the rendering must never round —
formatting a number is not an arithmetic operation.
"""

from __future__ import annotations

import decimal
from collections.abc import Iterator
from decimal import Decimal

import pytest

from greenmachine.common import (
    CanonicalizationError,
    canonical_decimal,
    parse_canonical_decimal,
)


@pytest.fixture(autouse=True)
def restore_global_context() -> Iterator[None]:
    saved = decimal.getcontext().copy()
    try:
        yield
    finally:
        decimal.setcontext(saved)


# --------------------------------------------------------------------------
# One representation per value
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spelling", ["1", "1.0", "1.00", "1.000000", "1E+0", "1e0", "0.1E+1", "10E-1"]
)
def test_every_spelling_of_one_renders_identically(spelling: str) -> None:
    assert canonical_decimal(Decimal(spelling)) == "1"


@pytest.mark.parametrize("spelling", ["0", "0.0", "0.000", "-0", "-0.000", "0E+5", "0E-5"])
def test_every_spelling_of_zero_renders_as_zero(spelling: str) -> None:
    """Negative zero is normalised away; there is one zero."""
    assert canonical_decimal(Decimal(spelling)) == "0"


def test_equal_decimals_always_share_a_representation() -> None:
    left, right = Decimal("2.50"), Decimal("2.5")

    assert left == right
    assert canonical_decimal(left) == canonical_decimal(right) == "2.5"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1E+2", "100"),
        ("1E-10", "0.0000000001"),
        ("-4.5000", "-4.5"),
        ("12.3400", "12.34"),
        ("0.75", "0.75"),
        ("-0.5", "-0.5"),
        ("1000", "1000"),
        ("1E+30", "1000000000000000000000000000000"),
    ],
)
def test_exponent_and_trailing_zero_normalisation(value: str, expected: str) -> None:
    assert canonical_decimal(Decimal(value)) == expected


# --------------------------------------------------------------------------
# Never rounds
# --------------------------------------------------------------------------


def test_a_value_wider_than_the_context_precision_is_not_rounded() -> None:
    """Formatting must not apply context precision.

    ``Decimal.normalize()`` would round this to 28 significant digits; the
    canonical renderer must not, because that would silently change the value it
    claims to represent.
    """
    digits = "1234567890123456789012345678901234567890"

    assert canonical_decimal(Decimal(digits)) == digits


def test_a_narrow_global_context_does_not_truncate_the_rendering() -> None:
    decimal.getcontext().prec = 5
    wide = Decimal("123456789012345678901234567890")

    assert canonical_decimal(wide) == "123456789012345678901234567890"


def test_a_very_small_exact_value_survives() -> None:
    assert canonical_decimal(Decimal("1E-40")) == "0." + "0" * 39 + "1"


def test_many_significant_fractional_digits_survive() -> None:
    value = "1.000000000000000000000000000000001"

    assert canonical_decimal(Decimal(value)) == value


# --------------------------------------------------------------------------
# Rejections
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_non_finite_decimals_are_refused(bad: Decimal) -> None:
    with pytest.raises(CanonicalizationError, match=r"non-finite"):
        canonical_decimal(bad)


@pytest.mark.parametrize("bad", [1.5, "1.5", 1, None])
def test_non_decimal_input_is_refused(bad: object) -> None:
    with pytest.raises(CanonicalizationError, match=r"expects a Decimal"):
        canonical_decimal(bad)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Round trip
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "0",
        "1",
        "-1",
        "0.75",
        "2.25",
        "12.3456",
        "-4.5",
        "1E+2",
        "1E-10",
        "1.000000000000000000000000000000001",
        "1234567890123456789012345678901234567890",
    ],
)
def test_round_trip_preserves_value_exactly(raw: str) -> None:
    original = Decimal(raw)
    restored = parse_canonical_decimal(canonical_decimal(original))

    assert restored == original


@pytest.mark.parametrize("raw", ["1.00", "2.50", "-0.000", "0E+5"])
def test_round_trip_is_idempotent_for_non_canonical_spellings(raw: str) -> None:
    """The second pass changes nothing: canonical form is a fixed point."""
    once = canonical_decimal(Decimal(raw))
    twice = canonical_decimal(parse_canonical_decimal(once))

    assert once == twice


@pytest.mark.parametrize(
    "text", ["1.0", "1.00", "01", "+1", "1E+2", "-0", "", " 1", "1.", ".5", "abc", "1,5"]
)
def test_parser_refuses_non_canonical_text(text: str) -> None:
    """A non-canonical spelling must not sneak in and re-serialize differently."""
    with pytest.raises(CanonicalizationError, match=r"not a canonical decimal string"):
        parse_canonical_decimal(text)


def test_parser_refuses_non_string_input() -> None:
    with pytest.raises(CanonicalizationError, match=r"expects a str"):
        parse_canonical_decimal(Decimal("1"))  # type: ignore[arg-type]


def test_parser_accepts_every_string_the_renderer_produces() -> None:
    for raw in ("0", "1", "-1", "0.75", "-0.5", "100", "0.0000000001", "1.25"):
        rendered = canonical_decimal(Decimal(raw))
        assert parse_canonical_decimal(rendered) == Decimal(raw)

"""Decimal construction: strings and ints in, everything else refused.

ADR-0002 makes one rule load-bearing — a Decimal is never built from a binary
float — and ``decimal_from`` is the single door that rule is enforced at.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from greenmachine.common import NumericPolicyError, decimal_from

# --------------------------------------------------------------------------
# Accepted
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0", Decimal("0")),
        ("1", Decimal("1")),
        ("12.3456", Decimal("12.3456")),
        ("-4.5", Decimal("-4.5")),
        ("0.75", Decimal("0.75")),
        ("2.25", Decimal("2.25")),
        ("1E+3", Decimal("1000")),
        ("1e-4", Decimal("0.0001")),
        ("+7", Decimal("7")),
    ],
)
def test_valid_strings_are_accepted(text: str, expected: Decimal) -> None:
    assert decimal_from(text) == expected


@pytest.mark.parametrize("number", [0, 1, 42, -7, 10**40])
def test_valid_integers_are_accepted(number: int) -> None:
    assert decimal_from(number) == Decimal(number)


def test_surrounding_whitespace_is_tolerated() -> None:
    """Trimming whitespace is not coercion; the numeral itself is unchanged."""
    assert decimal_from("  12.50  ") == Decimal("12.50")


def test_scale_is_preserved_exactly() -> None:
    """Trailing zeros are part of the value's scale and survive construction."""
    assert str(decimal_from("12.3400")) == "12.3400"


def test_a_large_integer_is_not_rounded_to_context_precision() -> None:
    """Construction stores the exact value; precision applies to arithmetic."""
    digits = "1" * 40

    assert str(decimal_from(digits)) == digits


# --------------------------------------------------------------------------
# Rejected
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", [True, False])
def test_bool_is_rejected(value: bool) -> None:
    """bool is an int subclass, so it would otherwise slip through as 0 or 1."""
    with pytest.raises(NumericPolicyError, match=r"bool is not a numeric value"):
        decimal_from(value)


@pytest.mark.parametrize("value", [0.1, 1.0, -2.5, 1e10])
def test_float_is_rejected(value: float) -> None:
    """ADR-0002: a value that has been through float has already lost the guarantee."""
    with pytest.raises(NumericPolicyError, match=r"never be built from a binary float"):
        decimal_from(value)  # type: ignore[arg-type]


def test_decimal_input_is_rejected() -> None:
    """Passing a Decimal hides where it was originally constructed."""
    with pytest.raises(NumericPolicyError, match=r"already a Decimal"):
        decimal_from(Decimal("1.5"))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "text", ["", "   ", "abc", "1.2.3", "1,5", "twelve", "0x10", "1/2", "--1", "1 2"]
)
def test_malformed_strings_are_rejected(text: str) -> None:
    with pytest.raises(NumericPolicyError):
        decimal_from(text)


@pytest.mark.parametrize("text", ["NaN", "nan", "-NaN", "sNaN"])
def test_nan_strings_are_rejected(text: str) -> None:
    """No NaN may enter the numeric path (ENGINEERING_GUIDELINES D6)."""
    with pytest.raises(NumericPolicyError, match=r"NaN|malformed"):
        decimal_from(text)


@pytest.mark.parametrize("text", ["Infinity", "-Infinity", "inf", "-inf"])
def test_infinity_strings_are_rejected(text: str) -> None:
    with pytest.raises(NumericPolicyError, match=r"infinity|malformed"):
        decimal_from(text)


@pytest.mark.parametrize("value", [None, [], {}, (), object()])
def test_unsupported_types_are_rejected(value: object) -> None:
    with pytest.raises(NumericPolicyError, match=r"only from str or int|not a numeric"):
        decimal_from(value)  # type: ignore[arg-type]


def test_rejection_is_never_a_silent_coercion() -> None:
    """Every refusal raises; nothing is quietly turned into a nearby value."""
    for bad in (0.1, True, Decimal("1")):
        with pytest.raises(NumericPolicyError):
            decimal_from(bad)  # type: ignore[arg-type]

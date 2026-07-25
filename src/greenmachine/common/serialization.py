"""Canonical serialization: one byte-exact encoding per object graph.

Two equal object graphs must produce byte-identical output on any machine, any
platform, any process — that is what makes a content hash a stable identity and a
determinism test meaningful (ENGINEERING_GUIDELINES D3, D7; ADR-0002).

The encoder is a **whitelist**. Every supported type is listed explicitly and
everything else is refused loudly. There is no ``default=`` hook and no ``repr``
fallback, because a fallback is how a float, a set, or an unmodelled object
quietly acquires a representation that differs between runs.

Refused on purpose:

* ``float`` — a binary float has already lost the Decimal guarantee (ADR-0002).
* ``set`` / ``frozenset`` — iteration order is not part of the value.
* naive ``datetime`` — ambiguous about the instant it names.

``Decimal`` is emitted as a canonical base-10 **string**, never a JSON number:
JSON numbers are read back as binary floats, which would destroy the value.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Final, TypeAlias

from .errors import DataInputError

__all__ = [
    "CanonicalizationError",
    "canonical_bytes",
    "canonical_decimal",
    "canonical_json",
    "parse_canonical_decimal",
]

# A JSON-safe value: what the encoder produces before it is dumped. Written as a
# string alias so the recursion resolves without PEP 695 syntax, which would
# raise the project's Python floor from the declared 3.11 to 3.12.
JsonValue: TypeAlias = "bool | int | str | list[JsonValue] | dict[str, JsonValue] | None"

# Canonical decimal form: optional sign, no leading zeros (except a bare "0"), no
# exponent, and no trailing zero in the fraction. "-0" is never canonical.
_CANONICAL_DECIMAL: Final = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$")


class CanonicalizationError(DataInputError, TypeError):
    """An object graph cannot be canonically serialized.

    Reparented under :class:`~greenmachine.common.errors.DataInputError` by
    GM-009. ``TypeError`` is retained because the usual cause is an unsupported
    type, and callers already catching it keep working.
    """


def canonical_decimal(value: Decimal) -> str:
    """Render a ``Decimal`` as its one canonical exact base-10 string.

    Equal values share a representation: ``Decimal("1")``, ``Decimal("1.0")``,
    ``Decimal("1.00")`` and ``Decimal("1E+0")`` all render as ``"1"``. Negative
    zero renders as ``"0"``. Exponent notation is expanded to plain digits.

    The value is **never rounded**. ``format(value, "f")`` expands the exact
    coefficient and exponent and ignores context precision, so a 40-digit value
    survives intact under a precision-28 context. ``Decimal.normalize()`` is
    deliberately *not* used here: it applies the active context and would round
    the number merely to format it.

    Raises:
        CanonicalizationError: if the value is not a finite ``Decimal``.
    """
    if not isinstance(value, Decimal):
        raise CanonicalizationError(
            f"canonical_decimal() expects a Decimal, got {type(value).__name__}"
        )
    if value.is_nan() or value.is_infinite():
        raise CanonicalizationError(f"cannot canonicalize a non-finite Decimal: {value!r}")

    # Collapses -0, 0E+5, 0.000 and every other spelling of zero to one form.
    if value == 0:
        return "0"

    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def parse_canonical_decimal(text: str) -> Decimal:
    """Inverse of :func:`canonical_decimal`; exact round trip.

    Accepts only strings already in canonical form, so a non-canonical spelling
    cannot enter through the back door and produce a value whose re-serialization
    differs from the bytes it was read from.

    Raises:
        CanonicalizationError: if the text is not canonical.
    """
    if not isinstance(text, str):
        raise CanonicalizationError(
            f"parse_canonical_decimal() expects a str, got {type(text).__name__}"
        )
    if text == "-0" or not _CANONICAL_DECIMAL.match(text):
        raise CanonicalizationError(
            f"not a canonical decimal string: {text!r}. Expected plain base-10 with no "
            "exponent, no leading zeros, no trailing fractional zeros, and no '-0'."
        )
    return Decimal(text)


def _encode(value: object, path: str, seen: frozenset[int]) -> JsonValue:
    """Convert one supported value into JSON-safe form, or refuse it by name."""
    # bool before int: bool is an int subclass and must stay a JSON boolean.
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        # Returned verbatim. String content is never normalised, re-cased, or
        # otherwise altered by serialization.
        return value

    if isinstance(value, float):
        raise CanonicalizationError(
            f"{path}: float is never serialized ({value!r}). Carry the value as a "
            "Decimal built from a string (ADR-0002)."
        )
    if isinstance(value, Decimal):
        return canonical_decimal(value)
    if isinstance(value, Enum):
        # By stable member value, not by name and not by repr.
        return _encode(value.value, f"{path}.value", seen)

    # datetime before date: datetime is a date subclass.
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise CanonicalizationError(
                f"{path}: naive datetime is ambiguous and is never serialized ({value!r})"
            )
        # Normalised to UTC, so two spellings of one instant encode identically.
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, set | frozenset):
        raise CanonicalizationError(
            f"{path}: {type(value).__name__} has no defined order, so it has no canonical "
            "form. Use a sorted tuple."
        )

    identity = id(value)
    if identity in seen:
        raise CanonicalizationError(f"{path}: object graph contains a cycle")
    nested = seen | {identity}

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        encoded: dict[str, JsonValue] = {}
        for field in sorted(dataclasses.fields(value), key=lambda f: f.name):
            encoded[field.name] = _encode(
                getattr(value, field.name), f"{path}.{field.name}", nested
            )
        return encoded

    if isinstance(value, Mapping):
        items: dict[str, JsonValue] = {}
        for key in value:
            if not isinstance(key, str):
                raise CanonicalizationError(
                    f"{path}: mapping keys must be str to sort deterministically, got "
                    f"{type(key).__name__}"
                )
            items[key] = _encode(value[key], f"{path}[{key!r}]", nested)
        return {key: items[key] for key in sorted(items)}

    # Exactly list and tuple, not the Sequence ABC: bytes and range are Sequences
    # too, and encoding them as integer arrays would be a silent, surprising
    # representation of a type that was never on the whitelist.
    if isinstance(value, list | tuple):
        return [_encode(item, f"{path}[{index}]", nested) for index, item in enumerate(value)]

    raise CanonicalizationError(
        f"{path}: {type(value).__name__} is not a supported type. Supported: None, bool, "
        "int, str, Decimal, Enum, date, aware datetime, dataclass, tuple, list, and "
        "str-keyed mappings."
    )


def canonical_json(value: object) -> str:
    """Return the canonical JSON text for a supported object graph.

    Mapping keys are sorted, separators are compact and fixed, and no float ever
    appears. Output depends on the value alone — not on locale, platform, dict
    insertion order, or ``PYTHONHASHSEED``.

    Raises:
        CanonicalizationError: for any unsupported type or naive datetime.
    """
    encoded = _encode(value, "<root>", frozenset())
    return json.dumps(
        encoded,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        check_circular=False,
    )


def canonical_bytes(value: object) -> bytes:
    """Return the canonical UTF-8 bytes for a supported object graph.

    This is the input to every content hash and the unit of byte-identity in the
    determinism tests.
    """
    return canonical_json(value).encode("utf-8")

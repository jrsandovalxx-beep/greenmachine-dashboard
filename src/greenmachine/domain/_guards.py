"""Internal construction guards shared by domain value objects and entities.

These are the *only* validation primitives the domain layer uses. Each checks a
single structural invariant and raises :class:`DomainValidationError` naming the
offending field.

Type annotations and ``mypy --strict`` cover ``src/``, but domain objects are also
built from ingestion adapters and deserialized records, where a wrong type arrives
at runtime. So the guards check types at construction rather than trusting the
annotation: a bad argument must fail as a named ``DomainValidationError``, never as
an incidental ``AttributeError``, ``TypeError``, or unhashable-object error.

Guards that establish a type return the narrowed value, so a caller can chain a
further check without re-testing or asserting.

Nothing here encodes a baseball rule. There are no metric domains, thresholds, or
sample minimums — only the structural coherence that makes an object well-formed.

Module is private (leading underscore); nothing here is part of the public
domain vocabulary.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TypeVar

from .enums import ComponentId, MeasurementId
from .errors import DomainValidationError

_UTC_OFFSET = timedelta(0)

# One lowercase 64-character SHA-256 digest and nothing else. The domain
# validates the shape of a stored hash; it never computes one (that stays in
# ``common``), so a domain reference to a config_hash or input_hash cannot be a
# free-form string.
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")

# A stable machine identifier: lowercase, starts with a letter, then letters,
# digits, and underscores. The one spelling a reason code may take, so it cannot
# drift into free prose (matches the configuration override-reason grammar).
_STABLE_CODE = re.compile(r"[a-z][a-z0-9_]*")

T = TypeVar("T")


def ensure_instance(value: object, expected: type[T], field: str) -> T:
    """Reject ``value`` unless it is an instance of ``expected``; return it narrowed."""
    if not isinstance(value, expected):
        raise DomainValidationError(
            f"{field} must be {expected.__name__}, got {type(value).__name__}"
        )
    return value


def ensure_optional_instance(value: object, expected: type[T], field: str) -> T | None:
    """Reject ``value`` unless it is ``None`` or an instance of ``expected``."""
    if value is None:
        return None
    return ensure_instance(value, expected, field)


def ensure_bool(value: object, field: str) -> bool:
    """Reject ``value`` unless it is exactly a ``bool``."""
    if not isinstance(value, bool):
        raise DomainValidationError(f"{field} must be bool, got {type(value).__name__}")
    return value


def ensure_tuple_of(value: object, member: type[T], field: str) -> tuple[T, ...]:
    """Reject ``value`` unless it is a ``tuple`` whose members are all ``member``.

    A ``list`` is refused rather than silently converted: the domain is hashable by
    construction, and quietly normalising a mutable sequence would hide the defect
    that produced it.
    """
    if not isinstance(value, tuple):
        raise DomainValidationError(
            f"{field} must be a tuple (an immutable sequence), got {type(value).__name__}"
        )
    for index, item in enumerate(value):
        if not isinstance(item, member):
            raise DomainValidationError(
                f"{field}[{index}] must be {member.__name__}, got {type(item).__name__}"
            )
    return value


def ensure_non_empty_text(value: object, field: str) -> str:
    """Reject ``value`` unless it is a string with at least one non-blank char."""
    if not isinstance(value, str):
        raise DomainValidationError(f"{field} must be a string, got {type(value).__name__}")
    if not value.strip():
        raise DomainValidationError(f"{field} must be a non-empty, non-blank string")
    return value


def ensure_sha256_hex(value: object, field: str) -> str:
    """Reject ``value`` unless it is exactly 64 lowercase hexadecimal characters.

    Validates the shape of a stored SHA-256 digest — uppercase, wrong length,
    whitespace, and non-hex are all refused — without ever computing one.
    """
    if not isinstance(value, str):
        raise DomainValidationError(f"{field} must be a string, got {type(value).__name__}")
    if _SHA256_HEX.fullmatch(value) is None:
        raise DomainValidationError(
            f"{field} must be exactly 64 lowercase hexadecimal characters "
            f"(a SHA-256 digest), got {value!r}"
        )
    return value


def ensure_stable_code(value: object, field: str) -> str:
    """Reject ``value`` unless it is a non-blank lowercase stable identifier.

    ``[a-z][a-z0-9_]*`` — a machine code, not free prose, so a stored reason can
    be matched and compared rather than reworded.
    """
    if not isinstance(value, str):
        raise DomainValidationError(f"{field} must be a string, got {type(value).__name__}")
    if _STABLE_CODE.fullmatch(value) is None:
        raise DomainValidationError(
            f"{field} must be a stable code (lowercase, starting with a letter, then letters, "
            f"digits, or underscores), got {value!r}"
        )
    return value


def ensure_aware_datetime(value: object, field: str) -> datetime:
    """Reject ``value`` unless it is a timezone-aware :class:`datetime`.

    Naive datetimes are ambiguous about the instant they name, which is a
    determinism hazard, so the domain refuses them at the boundary.
    """
    if not isinstance(value, datetime):
        raise DomainValidationError(f"{field} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError(f"{field} must be timezone-aware, got a naive datetime")
    return value


def ensure_utc(value: object, field: str) -> datetime:
    """Reject ``value`` unless it is timezone-aware and at UTC offset ``00:00``."""
    moment = ensure_aware_datetime(value, field)
    if moment.utcoffset() != _UTC_OFFSET:
        raise DomainValidationError(
            f"{field} must be stored in UTC (offset 00:00), got offset {moment.utcoffset()}"
        )
    return moment


def ensure_finite_decimal(value: object, field: str) -> Decimal:
    """Reject anything that is not a finite :class:`~decimal.Decimal`.

    A ``float`` argument is rejected explicitly: values entering scoring are
    ``Decimal`` and must be built from strings or ints, never from a binary float
    (ADR-0002). ``NaN`` and infinities are refused because no NaN-carrying value
    may cross into the core.
    """
    if not isinstance(value, Decimal):
        raise DomainValidationError(
            f"{field} must be a Decimal built from a string or int, got {type(value).__name__}"
        )
    if value.is_nan() or value.is_infinite():
        raise DomainValidationError(f"{field} must be a finite Decimal, got {value!r}")
    return value


def ensure_non_negative_decimal(value: object, field: str) -> Decimal:
    """Reject ``value`` unless it is a finite ``Decimal`` that is ``>= 0``."""
    number = ensure_finite_decimal(value, field)
    if number < 0:
        raise DomainValidationError(f"{field} must be >= 0, got {number}")
    return number


def ensure_non_negative_int(value: object, field: str) -> int:
    """Reject ``value`` unless it is a non-negative ``int`` (``bool`` excluded)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise DomainValidationError(f"{field} must be an int, got {type(value).__name__}")
    if value < 0:
        raise DomainValidationError(f"{field} must be >= 0, got {value}")
    return value


def ensure_ordered(start: object, end: object, start_field: str, end_field: str) -> None:
    """Reject the pair unless ``start <= end`` (both must be aware datetimes)."""
    first = ensure_aware_datetime(start, start_field)
    last = ensure_aware_datetime(end, end_field)
    if first > last:
        raise DomainValidationError(
            f"{start_field} ({first.isoformat()}) must be <= {end_field} ({last.isoformat()})"
        )


def ensure_no_duplicates(values: Sequence[object], field: str) -> None:
    """Reject ``values`` if any entry appears more than once."""
    seen: list[object] = []
    for item in values:
        if item in seen:
            raise DomainValidationError(f"{field} contains a duplicate entry: {item!r}")
        seen.append(item)


def ensure_measurement_matches_component(
    component_id: object, measurement_id: object, owner: str
) -> None:
    """Reject a component/measurement pairing the model does not define.

    ``attack_angle_quality`` is the only component with distinguishable
    measurements, and exactly one must satisfy it (``MODEL_SPEC.md`` §9.1). Every
    other component has a single implicit measurement identical to itself, carried
    as ``measurement_id=None``. That ``None`` has exactly one meaning — "this
    component has no separate measurement variant" — and never stands for missing
    data, which is its own type.

    This is a structural pairing rule, not scoring: it decides whether the record
    is well-formed, not what it is worth.
    """
    component = ensure_instance(component_id, ComponentId, f"{owner}.component_id")
    measurement = ensure_optional_instance(measurement_id, MeasurementId, f"{owner}.measurement_id")

    if component is ComponentId.ATTACK_ANGLE_QUALITY:
        if measurement is None:
            raise DomainValidationError(
                f"{owner}.measurement_id must be a MeasurementId when component_id is "
                f"'attack_angle_quality', got None"
            )
    elif measurement is not None:
        raise DomainValidationError(
            f"{owner}.measurement_id must be None for component_id "
            f"'{component.value}', got '{measurement.value}'"
        )

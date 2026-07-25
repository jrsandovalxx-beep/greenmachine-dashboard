"""Numeric policy: Decimal construction, the project-local context, intervals.

Implements ADR-0002 (Accepted) and ``MODEL_SPEC.md`` §4. Nothing here knows a
baseball rule: no metric domain, no bucket edge, no grade cutoff. Callers supply
every bound.

Three rules carry most of the weight:

* A ``Decimal`` is built only from a **string** or an **int**, never from a binary
  float. A value that has been through ``float`` has already lost the guarantee.
* All arithmetic runs under a **project-local** context (precision 28,
  ``ROUND_HALF_EVEN``) that neither reads nor mutates the global context.
* Scoring intervals are half-open ``[lower, upper)``; externally defined
  inclusive ranges use a **separate, separately implemented** helper. The two are
  deliberately not unified — see :func:`in_inclusive_range`.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)

from .errors import DataInputError

__all__ = [
    "PRECISION",
    "ROUNDING",
    "NumericPolicyError",
    "add",
    "decimal_from",
    "divide",
    "in_inclusive_range",
    "in_scoring_interval",
    "multiply",
    "numeric_context",
    "percentage",
    "project_context",
    "resolve_scoring_interval",
    "subtract",
]


class NumericPolicyError(DataInputError, ValueError):
    """A value violated the numeric policy of ADR-0002.

    Reparented under :class:`~greenmachine.common.errors.DataInputError` by
    GM-009: the fault is always in a value handed in. ``ValueError`` is retained
    so callers already catching it keep working, and so a rejected argument
    still reads as a value error by Python convention.
    """


PRECISION = 28
ROUNDING = ROUND_HALF_EVEN

# The single source of the project's arithmetic settings. Kept private and only
# ever handed out as a copy, so no caller can reach in and change the settings
# every other caller relies on.
_CONTEXT_TEMPLATE = Context(
    prec=PRECISION,
    rounding=ROUNDING,
    Emin=-999_999,
    Emax=999_999,
    capitals=1,
    clamp=0,
    traps=[InvalidOperation, DivisionByZero, Overflow],
)


def numeric_context() -> Context:
    """Return a **copy** of the project arithmetic context.

    A copy, not the template: mutating the returned context affects only the
    caller's copy, never the settings the rest of the system computes under.
    """
    return _CONTEXT_TEMPLATE.copy()


@contextmanager
def project_context() -> Iterator[Context]:
    """Run a block under the project-local context, restoring the caller's after.

    Wraps :func:`decimal.localcontext`, so the global context is saved on entry
    and restored on exit even if the block raises. A hostile or merely different
    global context (another library setting ``prec=3``) cannot affect arithmetic
    inside this block, and arithmetic inside cannot leak out.
    """
    with localcontext(_CONTEXT_TEMPLATE.copy()) as ctx:
        yield ctx


def decimal_from(value: str | int) -> Decimal:
    """Build a ``Decimal`` from a string or an int, and from nothing else.

    Rejects ``float`` (ADR-0002: never construct a Decimal from a binary float),
    ``bool`` (``True`` is an ``int`` subclass but is not a number here), an
    already-built ``Decimal`` (so the single construction path stays honest), and
    any string that is malformed, ``NaN``, or infinite.

    Raises:
        NumericPolicyError: for any rejected input.
    """
    # The signature keeps callers honest at type-check time. The checks below run
    # against a deliberately widened alias so they stay *live* at runtime: a
    # narrowed `str | int` would make the float and Decimal branches statically
    # unreachable, and the whole point is to reject what an untyped caller — an
    # adapter, a deserializer — actually passes.
    candidate: object = value

    if isinstance(candidate, bool):
        raise NumericPolicyError(
            f"bool is not a numeric value; got {candidate!r}. Pass an int or a string."
        )
    if isinstance(candidate, float):
        raise NumericPolicyError(
            f"a Decimal must never be built from a binary float; got {candidate!r}. "
            "Carry the value as a string instead (ADR-0002)."
        )
    if isinstance(candidate, Decimal):
        raise NumericPolicyError(
            "value is already a Decimal; decimal_from builds one from a string or "
            "int, so passing a Decimal hides where it was constructed"
        )
    if isinstance(candidate, int):
        return Decimal(candidate)
    if not isinstance(candidate, str):
        raise NumericPolicyError(
            f"a Decimal is built only from str or int; got {type(candidate).__name__}"
        )

    text = candidate.strip()
    if not text:
        raise NumericPolicyError("cannot build a Decimal from an empty string")
    try:
        with project_context():
            result = Decimal(text)
    except InvalidOperation as exc:
        raise NumericPolicyError(f"malformed decimal string: {value!r}") from exc

    if result.is_nan():
        raise NumericPolicyError(f"NaN is not a permitted value; got {value!r}")
    if result.is_infinite():
        raise NumericPolicyError(f"infinity is not a permitted value; got {value!r}")
    return result


def _require_finite(value: Decimal, field: str) -> Decimal:
    """Reject anything that is not a finite ``Decimal``."""
    if not isinstance(value, Decimal):
        raise NumericPolicyError(f"{field} must be a Decimal, got {type(value).__name__}")
    if value.is_nan() or value.is_infinite():
        raise NumericPolicyError(f"{field} must be finite, got {value!r}")
    return value


def add(*values: Decimal) -> Decimal:
    """Sum values under the project context. No rounding is applied afterwards."""
    for index, value in enumerate(values):
        _require_finite(value, f"add()[{index}]")
    with project_context():
        total = Decimal(0)
        for value in values:
            total = total + value
        return total


def subtract(left: Decimal, right: Decimal) -> Decimal:
    """Subtract under the project context."""
    _require_finite(left, "subtract() left")
    _require_finite(right, "subtract() right")
    with project_context():
        return left - right


def multiply(left: Decimal, right: Decimal) -> Decimal:
    """Multiply under the project context."""
    _require_finite(left, "multiply() left")
    _require_finite(right, "multiply() right")
    with project_context():
        return left * right


def divide(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Divide under the project context.

    The result is **not quantized**: derived ratios keep full context precision
    and are never rounded before they reach a comparison (``MODEL_SPEC.md`` §4).

    Raises:
        NumericPolicyError: if the denominator is zero.
    """
    _require_finite(numerator, "divide() numerator")
    _require_finite(denominator, "divide() denominator")
    if denominator == 0:
        raise NumericPolicyError("cannot divide by zero")
    with project_context():
        return numerator / denominator


def percentage(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Return ``numerator / denominator * 100`` under the project context.

    Generic arithmetic, not a metric: the caller decides what the two operands
    mean. The result is not quantized.
    """
    _require_finite(numerator, "percentage() numerator")
    _require_finite(denominator, "percentage() denominator")
    if denominator == 0:
        raise NumericPolicyError("cannot compute a percentage with a zero denominator")
    with project_context():
        return numerator / denominator * Decimal(100)


def in_scoring_interval(
    value: Decimal, lower: Decimal, upper: Decimal, *, terminal: bool = False
) -> bool:
    """Half-open scoring-interval membership: ``[lower, upper)``.

    A value exactly equal to ``upper`` is **not** in this interval — it belongs to
    the next one. The exception is the terminal interval, which is **closed** at
    the domain maximum the caller supplies (``MODEL_SPEC.md`` §4.1).

    This is the convention for GreenMachine's own scoring buckets and grade
    cutoffs. Ranges defined by an outside source use :func:`in_inclusive_range`,
    which is a deliberately separate implementation.

    Raises:
        NumericPolicyError: for non-finite inputs or unordered bounds.
    """
    _require_finite(value, "in_scoring_interval() value")
    _require_finite(lower, "in_scoring_interval() lower")
    _require_finite(upper, "in_scoring_interval() upper")
    if not isinstance(terminal, bool):
        raise NumericPolicyError(
            f"in_scoring_interval() terminal must be bool, got {type(terminal).__name__}"
        )
    if lower >= upper:
        raise NumericPolicyError(
            f"in_scoring_interval() requires lower < upper, got lower={lower} upper={upper}"
        )

    if value < lower:
        return False
    if terminal:
        # The terminal interval is closed at the domain maximum.
        return value <= upper
    return value < upper


def resolve_scoring_interval(value: Decimal, boundaries: Sequence[Decimal]) -> int:
    """Index of the half-open interval containing ``value``, over supplied bounds.

    ``boundaries`` is a strictly increasing sequence describing ``len - 1``
    adjacent intervals spanning ``[boundaries[0], boundaries[-1]]``. Every
    interval is ``[lower, upper)`` except the last, which is closed at
    ``boundaries[-1]``. So each in-domain value resolves to exactly one interval.

    The bounds are entirely the caller's: no threshold, cutoff, or component
    definition lives here.

    Raises:
        NumericPolicyError: for bad bounds or a value outside the domain.
    """
    _require_finite(value, "resolve_scoring_interval() value")
    if len(boundaries) < 2:
        raise NumericPolicyError(
            f"resolve_scoring_interval() needs at least two boundaries to describe "
            f"one interval, got {len(boundaries)}"
        )
    for index, bound in enumerate(boundaries):
        _require_finite(bound, f"resolve_scoring_interval() boundaries[{index}]")
    for index in range(len(boundaries) - 1):
        if boundaries[index] >= boundaries[index + 1]:
            raise NumericPolicyError(
                f"resolve_scoring_interval() boundaries must strictly increase, but "
                f"boundaries[{index}]={boundaries[index]} >= "
                f"boundaries[{index + 1}]={boundaries[index + 1]}"
            )

    domain_min = boundaries[0]
    domain_max = boundaries[-1]
    if value < domain_min or value > domain_max:
        raise NumericPolicyError(
            f"resolve_scoring_interval() value {value} is outside the declared domain "
            f"[{domain_min}, {domain_max}]"
        )

    last = len(boundaries) - 2
    for index in range(last + 1):
        if in_scoring_interval(
            value, boundaries[index], boundaries[index + 1], terminal=index == last
        ):
            return index
    raise NumericPolicyError(  # pragma: no cover - unreachable while bounds are ordered
        f"resolve_scoring_interval() failed to place in-domain value {value}"
    )


def in_inclusive_range(value: Decimal, lower: Decimal, upper: Decimal) -> bool:
    """Inclusive membership: ``lower <= value <= upper``. **Both ends included.**

    For ranges defined by an outside source rather than by GreenMachine — the
    motivating case is Baseball Savant's Ideal Attack Angle predicate, which is
    inclusive at both 5 and 20 (``MODEL_SPEC.md`` §9.2).

    Deliberately a **separate implementation** from
    :func:`in_scoring_interval`, and deliberately not written in terms of it.
    ADR-0002 accepts the duplication: unifying them is precisely the bug, because
    one convention would silently corrupt the other. At a shared upper bound the
    two disagree, and a test asserts that they do.

    This helper decides membership only. It computes no attack angle and knows no
    degrees.

    Raises:
        NumericPolicyError: for non-finite inputs or unordered bounds.
    """
    _require_finite(value, "in_inclusive_range() value")
    _require_finite(lower, "in_inclusive_range() lower")
    _require_finite(upper, "in_inclusive_range() upper")
    if lower > upper:
        raise NumericPolicyError(
            f"in_inclusive_range() requires lower <= upper, got lower={lower} upper={upper}"
        )

    # Written as a single closed comparison, which is exactly what "inclusive at
    # both ends" means. in_scoring_interval() reaches its answer through a
    # different, half-open comparison; neither delegates to the other.
    return lower <= value <= upper

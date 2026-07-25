"""Pure result value objects assembled by the scoring core in a later sprint.

These are **containers, not calculators**. They record the outcome of a scoring
step but perform no bucket resolution, no summation, and no comparison — that
logic is Sprint 2. Defining the vocabulary now lets GM-006 compose a
``GradeResult`` from named nouns the Product Owner can read.

Deliberately *not* validated here: that a category's points equal the sum of its
components, or that points respect a ``max_points`` allocation. Those are scoring
invariants checked by the core against configuration, not construction rules of a
plain data record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ._guards import (
    ensure_bool,
    ensure_finite_decimal,
    ensure_instance,
    ensure_measurement_matches_component,
    ensure_non_empty_text,
    ensure_non_negative_decimal,
    ensure_optional_instance,
    ensure_tuple_of,
)
from .enums import Category, ComponentId, MeasurementId, ValidationInputId
from .errors import DomainValidationError

__all__ = ["BucketHit", "CategoryScore", "ComponentScore", "ValidationFinding"]


@dataclass(frozen=True, slots=True)
class BucketHit:
    """Which scoring bucket a value resolved to, and the points it awarded.

    Under the approved representation the terminal bucket is exactly the one with
    no ``upper_bound``: it is closed at the domain maximum (``MODEL_SPEC.md``
    §4.1). ``is_terminal`` and ``upper_bound is None`` therefore mean the same
    thing, and a record where they disagree is contradictory and rejected.

    This records a resolution outcome; it does not perform the resolution.
    """

    lower_bound: Decimal
    upper_bound: Decimal | None
    is_terminal: bool
    points_awarded: Decimal

    def __post_init__(self) -> None:
        lower = ensure_finite_decimal(self.lower_bound, "BucketHit.lower_bound")
        is_terminal = ensure_bool(self.is_terminal, "BucketHit.is_terminal")
        ensure_non_negative_decimal(self.points_awarded, "BucketHit.points_awarded")

        if self.upper_bound is None:
            if not is_terminal:
                raise DomainValidationError(
                    "BucketHit.is_terminal must be True when upper_bound is None; "
                    "only the terminal bucket is closed at the domain maximum"
                )
            return

        upper = ensure_finite_decimal(self.upper_bound, "BucketHit.upper_bound")
        if is_terminal:
            raise DomainValidationError(
                f"BucketHit.is_terminal must be False when upper_bound is set "
                f"(got {upper}); the terminal bucket has no upper bound"
            )
        if lower >= upper:
            raise DomainValidationError(
                f"BucketHit.lower_bound ({lower}) must be < upper_bound ({upper})"
            )


@dataclass(frozen=True, slots=True)
class ComponentScore:
    """The points a single component earned, with the measurement that satisfied it.

    ``measurement_id`` follows the same rule as on an observation:
    ``attack_angle_quality`` requires exactly one measurement, every other
    component requires ``None``. ``bucket_hit`` is absent for binary components
    that declare a predicate rather than buckets.
    """

    component_id: ComponentId
    measurement_id: MeasurementId | None
    points_awarded: Decimal
    bucket_hit: BucketHit | None = None

    def __post_init__(self) -> None:
        ensure_measurement_matches_component(
            self.component_id, self.measurement_id, "ComponentScore"
        )
        ensure_non_negative_decimal(self.points_awarded, "ComponentScore.points_awarded")
        ensure_optional_instance(self.bucket_hit, BucketHit, "ComponentScore.bucket_hit")


@dataclass(frozen=True, slots=True)
class CategoryScore:
    """The points a category earned, with the component scores it is composed of.

    The total is stored, not recomputed here: aggregation is the scoring core's
    job (``MODEL_SPEC.md`` §3).
    """

    category: Category
    points_awarded: Decimal
    component_scores: tuple[ComponentScore, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        ensure_instance(self.category, Category, "CategoryScore.category")
        ensure_non_negative_decimal(self.points_awarded, "CategoryScore.points_awarded")
        ensure_tuple_of(self.component_scores, ComponentScore, "CategoryScore.component_scores")


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    """One advisory Validation Layer finding (``MODEL_SPEC.md`` §17).

    Structured and auditable, it sits beside the score and never changes it. It
    references a :class:`ValidationInputId` and, where relevant, the component it
    concerns (e.g. an ``INSUFFICIENT`` sample warning).
    """

    input_id: ValidationInputId
    message: str
    component_id: ComponentId | None = None

    def __post_init__(self) -> None:
        ensure_instance(self.input_id, ValidationInputId, "ValidationFinding.input_id")
        ensure_non_empty_text(self.message, "ValidationFinding.message")
        ensure_optional_instance(self.component_id, ComponentId, "ValidationFinding.component_id")

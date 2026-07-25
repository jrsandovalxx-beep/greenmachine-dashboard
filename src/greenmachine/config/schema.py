"""Immutable, strictly validated configuration models.

"Rules as data" is the architectural thesis (ARCHITECTURE.md §4.2): changing a
threshold must never require changing Python. That only holds if the data is
trustworthy, so every model here is frozen, forbids unknown keys, and has no
silent default for anything that affects behaviour.

Three rules shape the whole schema:

* **Nothing mutable escapes.** Sequences are ``tuple``; no ``dict``, ``list``,
  or ``set`` appears in a public field. The parsed YAML mapping is never stored.
* **Scoring numerics are quoted strings.** A YAML float has already been through
  binary floating point and lost the guarantee (ADR-0002), so a float is
  rejected rather than coerced. Counts are strict integers, and ``bool`` is not
  an integer here.
* **Allocations are profile-invariant.** Category maximums, component
  ``max_points``, grade cutoffs, the strong-category fraction, and signal rules
  live in one shared structure. Nothing under a ``WindowProfile`` can restate
  them, because those models forbid the keys entirely.

This module defines structure only. It resolves no bucket, grades nothing, and
evaluates no signal.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, StrictInt

from greenmachine.common.numeric import NumericPolicyError, decimal_from
from greenmachine.domain import (
    Category,
    ComponentId,
    Grade,
    MeasurementId,
    MissingReason,
    SampleType,
    Signal,
    WindowProfile,
)

__all__ = [
    "AllocationConfig",
    "BinaryScoring",
    "BucketConfig",
    "BucketedScoring",
    "CategoryAllocation",
    "ComparisonOperator",
    "ComponentConfig",
    "ComponentProfileConfig",
    "Direction",
    "FuzzyScoringPolicy",
    "GradeCutoff",
    "GreenMachineConfig",
    "MissingDataPolicy",
    "MissingDataRule",
    "PredicateComparison",
    "QualificationPredicate",
    "ScoringMethod",
    "SignalClause",
    "SignalCondition",
    "SignalRule",
]


# --------------------------------------------------------------------------
# Numeric field types
# --------------------------------------------------------------------------


def _decimal_from_quoted_string(value: object) -> Decimal:
    """Accept only a quoted YAML string, parsed under the GM-005 policy.

    A YAML float never reaches ``Decimal``: ``0.1`` in YAML is already a binary
    float by the time the parser hands it over, so the exact value it was
    written as is gone. Quoting is the author's declaration that the digits are
    the value (ADR-0002).
    """
    if isinstance(value, bool):
        raise ValueError("must be a quoted decimal string, got a boolean")
    if isinstance(value, float):
        raise ValueError(
            f"must be a quoted decimal string, got a YAML float ({value!r}). "
            "Quote it so the exact digits survive."
        )
    if isinstance(value, int):
        raise ValueError(
            f"must be a quoted decimal string, got a YAML integer ({value!r}). "
            "Quote it so scoring numerics all arrive the same way."
        )
    if isinstance(value, Decimal):
        raise ValueError(
            "must be a quoted decimal string, got a Decimal; configuration is "
            "parsed from text, never handed pre-built numbers"
        )
    if not isinstance(value, str):
        raise ValueError(f"must be a quoted decimal string, got {type(value).__name__}")
    try:
        return decimal_from(value)
    except NumericPolicyError as exc:
        raise ValueError(str(exc)) from exc


def _strict_count(value: object) -> int:
    """Accept only a real YAML integer; a bool is a flag, never a count."""
    if isinstance(value, bool):
        raise ValueError("must be an integer, got a boolean")
    if not isinstance(value, int):
        raise ValueError(f"must be an integer, got {type(value).__name__}")
    return value


ConfigDecimal = Annotated[Decimal, BeforeValidator(_decimal_from_quoted_string)]
"""A scoring numeric: quoted in YAML, exact as a Decimal."""

CountInt = Annotated[StrictInt, BeforeValidator(_strict_count), Field(ge=0)]
"""A non-negative count. Strict: no bool, no float, no numeric string."""


class _Frozen(BaseModel):
    """Base for every configuration model: frozen, no unknown keys.

    Strictness is applied **per field** rather than globally. Pydantic's global
    ``strict=True`` would also refuse the two conversions YAML legitimately
    needs — a sequence into a ``tuple``, and a member's value into its enum —
    which would force every model to re-implement them. The strictness that
    matters is expressed where it belongs instead:

    * scoring numerics through :data:`ConfigDecimal`, which accepts a quoted
      string and nothing else;
    * counts through :data:`CountInt`, which rejects ``bool``, ``float``, and
      numeric strings;
    * flags through ``StrictBool``, which rejects ``"true"``.

    ``extra="forbid"`` and ``frozen=True`` are unaffected by lax mode, and
    Pydantic v2 does not coerce ``int`` into ``str``, so no field silently
    widens.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        arbitrary_types_allowed=False,
        use_enum_values=False,
        validate_default=True,
    )


# --------------------------------------------------------------------------
# Configuration-local vocabulary
# --------------------------------------------------------------------------


class ScoringMethod(Enum):
    """The two approved scoring methods (MODEL_SPEC §5).

    Config-local: the method is a property of how a component is *configured*,
    not part of the domain vocabulary the Product Owner reads.
    """

    BUCKETED = "bucketed"
    BINARY = "binary"


class Direction(Enum):
    """Which way is better for a component's values."""

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


MissingDataPolicy = Literal["not_evaluable", "record_missing"]
"""What a component does when its value is unavailable.

``not_evaluable`` — the component is required, so its absence can make the whole
evaluation ``NOT_EVALUABLE``. ``record_missing`` — the absence is recorded and
the evaluation continues. The final production vocabulary is not fixed by the
approved documents; this is the smallest typed pair the fixtures need.
"""

ComparisonOperator = Literal["at_least", "greater_than", "at_most", "less_than", "equal_to"]
"""Comparisons a binary qualification predicate may express. Data, not code."""


class MissingDataRule(_Frozen):
    """What to do when a component has no value, and which reasons are expected.

    Required on every component: MODEL_SPEC §8.3 forbids a silent default, and a
    component with no declared missing-data behaviour is exactly how a zero
    becomes a grade.
    """

    policy: MissingDataPolicy
    reasons: tuple[MissingReason, ...] = Field(min_length=1)


class FuzzyScoringPolicy(_Frozen):
    """Fuzzy scoring is disabled and stays disabled (MODEL_SPEC §5.2).

    Present as an explicit, required declaration rather than an absence, so a
    future attempt to enable it is a visible configuration change that fails
    validation rather than a quiet omission.
    """

    enabled: StrictBool


# --------------------------------------------------------------------------
# Allocations — one shared, profile-invariant structure
# --------------------------------------------------------------------------


class CategoryAllocation(_Frozen):
    """One category's maximum and the components that make it up.

    Membership lives here rather than on the component so that the category's
    composition is stated once, in the same place as the number it must sum to.
    """

    category: Category
    max_points: ConfigDecimal
    components: tuple[ComponentId, ...] = Field(min_length=1)


class GradeCutoff(_Frozen):
    """One grade's score interval.

    Half-open ``[lower, upper)`` except the terminal grade, which is closed at
    the domain maximum (ADR-0002). ``terminal`` is declared rather than inferred
    so the closed interval is visible in the file.
    """

    grade: Grade
    lower: ConfigDecimal
    upper: ConfigDecimal
    terminal: StrictBool


class SignalCondition(_Frozen):
    """One typed, declarative condition. Never executed here."""


class GradeInCondition(SignalCondition):
    """True when the grade is one of the listed grades."""

    type: Literal["grade_in"]
    grades: tuple[Grade, ...] = Field(min_length=1)


class TotalScoreCondition(SignalCondition):
    """True when the total score compares as stated against ``value``."""

    type: Literal["total_score"]
    operator: ComparisonOperator
    value: ConfigDecimal


class CategoryScoreCondition(SignalCondition):
    """True when one category's score compares as stated against ``value``."""

    type: Literal["category_score"]
    category: Category
    operator: ComparisonOperator
    value: ConfigDecimal


class StrongCategoryCountCondition(SignalCondition):
    """True when the number of strong categories compares against ``count``."""

    type: Literal["strong_category_count"]
    operator: ComparisonOperator
    count: CountInt


class AlwaysCondition(SignalCondition):
    """The fallback clause. Always true; only valid on the last rule."""

    type: Literal["always"]


AnySignalCondition = Annotated[
    GradeInCondition
    | TotalScoreCondition
    | CategoryScoreCondition
    | StrongCategoryCountCondition
    | AlwaysCondition,
    Field(discriminator="type"),
]


class SignalClause(_Frozen):
    """One alternative: every condition in ``all_of`` must hold."""

    all_of: tuple[AnySignalCondition, ...] = Field(min_length=1)


class SignalRule(_Frozen):
    """One prioritised rule. ``any_of`` holds the alternative clauses.

    MODEL_SPEC §16 resolves rules in strict priority order and the first match
    wins; this records the rule, and nothing here evaluates it.
    """

    priority: CountInt
    signal: Signal
    any_of: tuple[SignalClause, ...] = Field(min_length=1)
    override_reason: str | None = None


class AllocationConfig(_Frozen):
    """The one shared allocation structure (MODEL_SPEC §2.1).

    Everything here is profile-invariant by construction: no ``WindowProfile``
    appears anywhere beneath it, and the per-profile models forbid these keys,
    so a per-profile allocation cannot be expressed at all.
    """

    strong_category_fraction: ConfigDecimal
    total_max_points: ConfigDecimal
    categories: tuple[CategoryAllocation, ...] = Field(min_length=1)
    grade_cutoffs: tuple[GradeCutoff, ...] = Field(min_length=1)
    signal_rules: tuple[SignalRule, ...] = Field(min_length=1)


# --------------------------------------------------------------------------
# Scoring definitions
# --------------------------------------------------------------------------


class BucketConfig(_Frozen):
    """One scoring bucket: ``[lower, upper)`` and the points it awards."""

    lower: ConfigDecimal
    upper: ConfigDecimal
    points: ConfigDecimal


class BucketedScoring(_Frozen):
    """A continuous domain divided into ordered buckets.

    Declares no predicate: the binary-only fields are absent from this model, so
    mixing the two shapes is a schema error rather than a semantic one.
    """

    method: Literal["bucketed"]
    domain_min: ConfigDecimal
    domain_max: ConfigDecimal
    measurement_id: MeasurementId | None = None
    buckets: tuple[BucketConfig, ...] = Field(min_length=1)


class PredicateComparison(_Frozen):
    """One comparison of a named input against a Decimal operand.

    ``input_name`` is an opaque identifier the feature layer resolves later. It
    is data: nothing here imports a callable, evaluates an expression, or knows
    what the input means.
    """

    input_name: str = Field(min_length=1)
    operator: ComparisonOperator
    value: ConfigDecimal


class QualificationPredicate(_Frozen):
    """A binary component's qualification test.

    Exactly one of ``all_of`` or ``any_of`` — deliberately one level deep, which
    is enough for the approved binary components and keeps the structure
    obviously non-executable.
    """

    all_of: tuple[PredicateComparison, ...] | None = None
    any_of: tuple[PredicateComparison, ...] | None = None


class BinaryScoring(_Frozen):
    """A genuine yes/no condition and the points a qualifying value earns.

    Declares no domain and no buckets: MODEL_SPEC §5 requires that a binary
    component is *not* forced to describe continuous ranges, and those fields do
    not exist on this model.
    """

    method: Literal["binary"]
    predicate: QualificationPredicate
    qualified_points: ConfigDecimal


AnyScoring = Annotated[BucketedScoring | BinaryScoring, Field(discriminator="method")]


class ComponentProfileConfig(_Frozen):
    """Everything that may legitimately differ between window profiles.

    Buckets and minimum samples only (MODEL_SPEC §6.3). ``max_points`` and the
    grade cutoffs are absent by design, and ``extra="forbid"`` makes adding them
    here a load failure.
    """

    window_profile: WindowProfile
    minimum_sample_required: CountInt
    scoring: tuple[AnyScoring, ...] = Field(min_length=1)


class ComponentConfig(_Frozen):
    """One scored component, with its profile-specific scoring definitions."""

    component_id: ComponentId
    scoring_method: ScoringMethod
    direction: Direction
    max_points: ConfigDecimal
    sample_type: SampleType
    missing_data: MissingDataRule
    applicable_profiles: tuple[WindowProfile, ...] = Field(min_length=1)
    profiles: tuple[ComponentProfileConfig, ...] = Field(min_length=1)


# --------------------------------------------------------------------------
# Root
# --------------------------------------------------------------------------


class GreenMachineConfig(_Frozen):
    """A complete model configuration.

    ``model_configuration_version`` is a plain declared label. Resolving it to a
    stored version and deriving a semantic ``config_hash`` is GM-004 and is
    deliberately absent here.
    """

    schema_version: StrictInt
    model_configuration_version: str = Field(min_length=1)
    specification_version: str = Field(min_length=1)
    fuzzy_scoring: FuzzyScoringPolicy
    allocations: AllocationConfig
    components: tuple[ComponentConfig, ...] = Field(min_length=1)

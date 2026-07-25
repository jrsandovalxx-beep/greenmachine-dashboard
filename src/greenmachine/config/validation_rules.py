"""Semantic validation: every invariant in ``MODEL_SPEC.md`` §19, at load time.

A violation here is a **load failure, never a warning**. Overlapping buckets, a
gap in the grade table, or allocations that do not sum produce a plausible wrong
grade rather than an obvious crash — which is precisely the failure mode this
project exists to prevent, so the configuration is refused before it can grade
anything.

Every failure names the file and the exact key path that caused it.

This module validates structure. It resolves no bucket for a value, assigns no
grade, and evaluates no signal; where it needs to prove that an interval set
covers its domain exactly once, it uses the generic GM-005 helpers rather than
reimplementing the convention.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal, DecimalException

from greenmachine.common.numeric import (
    NumericPolicyError,
    add,
    decimal_from,
    divide,
    resolve_scoring_interval,
)
from greenmachine.domain import Category, ComponentId, Grade, MeasurementId, Signal

from .errors import ConfigSemanticError, context_for, key_path_text
from .schema import (
    AllocationConfig,
    BinaryScoring,
    BucketedScoring,
    ComponentConfig,
    Direction,
    GreenMachineConfig,
    ScoringMethod,
    SignalRule,
)

__all__ = ["TOTAL_MAX_POINTS", "validate_semantics"]

# Structural constants from the specification, not tunable thresholds.
# MODEL_SPEC §2 fixes the total at 12 points and §14 fixes the score domain at
# [0, 12]; §19 invariant 5 requires category maximums to sum exactly to it.
TOTAL_MAX_POINTS = decimal_from("12")
SCORE_DOMAIN_MIN = decimal_from("0")

# The approved evaluation order (MODEL_SPEC §16, Q27). AVOID is evaluated first.
SIGNAL_PRIORITY_ORDER = (Signal.AVOID, Signal.STRONG_BET, Signal.LEAN, Signal.PASS)

# The Grade vocabulary in ascending score order (MODEL_SPEC §14). This is the
# meaning of the grades, not a threshold: whatever numbers a configuration
# chooses, the lowest interval is D and the highest is S.
GRADE_SCORE_ORDER = (Grade.D, Grade.C, Grade.B, Grade.A, Grade.S)

# The measurements that must both be configured for attack_angle_quality (§9.1).
ATTACK_ANGLE_MEASUREMENTS = (
    MeasurementId.IDEAL_ATTACK_ANGLE_PCT,
    MeasurementId.ATTACK_ANGLE_THRESHOLD_PROXY,
)

# A stable, machine-usable identifier: lowercase, starts with a letter, then
# letters/digits/underscores. An override reason code has to survive being
# grepped for and compared, so free text is not enough.
STABLE_CODE = re.compile(r"^[a-z][a-z0-9_]*$")


def _decimal_step(numerator: str, denominator: str) -> Decimal:
    """A small structural Decimal computed under the project context."""
    return divide(decimal_from(numerator), decimal_from(denominator))


def _fail(
    message: str,
    file_path: str | None,
    key_path: tuple[str, ...],
    *,
    metric: str | None = None,
    window_profile: str | None = None,
) -> ConfigSemanticError:
    """Build a semantic error that names where the problem is."""
    return ConfigSemanticError(
        f"{key_path_text(key_path)}: {message}",
        context_for(file_path, key_path, metric=metric, window_profile=window_profile),
    )


def _duplicates(values: Iterable[object]) -> list[str]:
    counts = Counter(values)
    return sorted(str(value) for value, count in counts.items() if count > 1)


def _arith(
    compute: Callable[[], Decimal],
    file_path: str | None,
    key_path: tuple[str, ...],
    *,
    metric: str | None = None,
    window_profile: str | None = None,
) -> Decimal:
    """Run Decimal arithmetic on configuration values, translating any failure.

    All arithmetic goes through the GM-005 primitives, so it runs under the
    project-local context and never depends on ``decimal.getcontext()`` (ADR-0002).
    An extreme finite value can still overflow *that* context; when it does, the
    raw ``NumericPolicyError`` or ``decimal`` exception is turned into a
    :class:`ConfigSemanticError` that names the file and key path, so no
    implementation exception escapes the public API.
    """
    try:
        return compute()
    except (NumericPolicyError, DecimalException) as exc:
        raise _fail(
            f"decimal arithmetic on configuration values failed: {exc}",
            file_path,
            key_path,
            metric=metric,
            window_profile=window_profile,
        ) from exc


def _arith_list(
    compute: Callable[[], list[Decimal]],
    file_path: str | None,
    key_path: tuple[str, ...],
    *,
    metric: str | None = None,
    window_profile: str | None = None,
) -> list[Decimal]:
    """Like :func:`_arith`, but for a computation that returns a list of Decimals."""
    try:
        return compute()
    except (NumericPolicyError, DecimalException) as exc:
        raise _fail(
            f"decimal arithmetic on configuration values failed: {exc}",
            file_path,
            key_path,
            metric=metric,
            window_profile=window_profile,
        ) from exc


def _sum(
    values: Sequence[Decimal],
    file_path: str | None,
    key_path: tuple[str, ...],
) -> Decimal:
    """Total ``values`` under the project context, translating any failure."""
    return _arith(lambda: add(*values), file_path, key_path)


def validate_semantics(config: GreenMachineConfig, file_path: str | None) -> None:
    """Run every semantic invariant. Raises on the first violation found.

    Raises:
        ConfigSemanticError: naming the file and key path of the violation.
    """
    _validate_fuzzy_disabled(config, file_path)
    _validate_allocations(config.allocations, config.components, file_path)
    _validate_grade_cutoffs(config.allocations, file_path)
    _validate_signal_rules(config.allocations, file_path)
    _validate_components(config, file_path)


# --------------------------------------------------------------------------
# Fuzzy scoring
# --------------------------------------------------------------------------


def _validate_fuzzy_disabled(config: GreenMachineConfig, file_path: str | None) -> None:
    """MODEL_SPEC §5.2: fuzzy scoring is disabled and not implemented."""
    if config.fuzzy_scoring.enabled:
        raise _fail(
            "fuzzy scoring is not implemented and must be explicitly disabled",
            file_path,
            ("fuzzy_scoring", "enabled"),
        )


# --------------------------------------------------------------------------
# Allocations (MODEL_SPEC §19 invariants 4, 5, 6, 14)
# --------------------------------------------------------------------------


def _validate_allocations(
    allocations: AllocationConfig,
    components: Sequence[ComponentConfig],
    file_path: str | None,
) -> None:
    base = ("allocations",)

    categories = allocations.categories
    declared = [entry.category for entry in categories]
    if repeated := _duplicates(declared):
        raise _fail(
            f"category declared more than once: {repeated}", file_path, (*base, "categories")
        )
    if missing := sorted(c.value for c in Category if c not in set(declared)):
        raise _fail(f"category missing: {missing}", file_path, (*base, "categories"))

    # Every component belongs to exactly one category, and every component that
    # exists is placed (invariant 14: no dangling reference, no orphan).
    membership: list[ComponentId] = []
    for entry in categories:
        membership.extend(entry.components)
    if repeated := _duplicates(membership):
        raise _fail(
            f"component appears in more than one category: {repeated}",
            file_path,
            (*base, "categories"),
        )

    configured = [component.component_id for component in components]
    if repeated := _duplicates(configured):
        raise _fail(f"component configured more than once: {repeated}", file_path, ("components",))

    known = set(configured)
    for index, entry in enumerate(categories):
        for position, component_id in enumerate(entry.components):
            if component_id not in known:
                raise _fail(
                    f"category '{entry.category.value}' references undefined component "
                    f"'{component_id.value}'",
                    file_path,
                    (*base, "categories", str(index), "components", str(position)),
                )

    if orphans := sorted(c.value for c in known - set(membership)):
        raise _fail(
            f"component configured but not placed in any category: {orphans}",
            file_path,
            ("components",),
        )

    if incomplete := sorted(c.value for c in ComponentId if c not in known):
        raise _fail(
            f"a complete configuration must define every scored component; missing: {incomplete}",
            file_path,
            ("components",),
        )

    by_id = {component.component_id: component for component in components}

    # Checked before the sums: "this maximum must be greater than 0" is a far
    # more actionable message than the arithmetic mismatch it would otherwise
    # surface as.
    for index, entry in enumerate(categories):
        if entry.max_points <= 0:
            raise _fail(
                f"category maximum must be greater than 0, got {entry.max_points}",
                file_path,
                (*base, "categories", str(index), "max_points"),
            )
    for index, component in enumerate(components):
        if component.max_points <= 0:
            raise _fail(
                f"max_points must be greater than 0, got {component.max_points}",
                file_path,
                ("components", str(index), "max_points"),
                metric=component.component_id.value,
            )

    # Invariant 4: component max_points sum exactly to the category maximum.
    for index, entry in enumerate(categories):
        where = (*base, "categories", str(index), "max_points")
        total = _sum([by_id[cid].max_points for cid in entry.components], file_path, where)
        if total != entry.max_points:
            raise _fail(
                f"component max_points sum to {total}, but category "
                f"'{entry.category.value}' declares {entry.max_points}",
                file_path,
                where,
            )

    # Invariant 5: category maximums sum exactly to the declared total.
    if allocations.total_max_points != TOTAL_MAX_POINTS:
        raise _fail(
            f"total_max_points must be {TOTAL_MAX_POINTS} (MODEL_SPEC §2), got "
            f"{allocations.total_max_points}",
            file_path,
            (*base, "total_max_points"),
        )
    category_total = _sum(
        [entry.max_points for entry in categories], file_path, (*base, "categories")
    )
    if category_total != allocations.total_max_points:
        raise _fail(
            f"category maximums sum to {category_total}, but total_max_points is "
            f"{allocations.total_max_points}",
            file_path,
            (*base, "categories"),
        )

    if allocations.strong_category_fraction <= 0 or allocations.strong_category_fraction > 1:
        raise _fail(
            "strong_category_fraction must be greater than 0 and at most 1, got "
            f"{allocations.strong_category_fraction}",
            file_path,
            (*base, "strong_category_fraction"),
        )


# --------------------------------------------------------------------------
# Grade cutoffs (MODEL_SPEC §14, §19 invariant 13)
# --------------------------------------------------------------------------


def _validate_grade_cutoffs(allocations: AllocationConfig, file_path: str | None) -> None:
    base = ("allocations", "grade_cutoffs")
    cutoffs = allocations.grade_cutoffs

    grades = [cutoff.grade for cutoff in cutoffs]
    if repeated := _duplicates(grades):
        raise _fail(f"grade declared more than once: {repeated}", file_path, base)
    if missing := sorted(g.value for g in Grade if g not in set(grades)):
        raise _fail(f"grade missing from the cutoff table: {missing}", file_path, base)

    ordered = sorted(cutoffs, key=lambda cutoff: cutoff.lower)
    if list(ordered) != list(cutoffs):
        raise _fail(
            "grade cutoffs must be declared in ascending order of their lower bound",
            file_path,
            base,
        )

    # The Grade vocabulary carries meaning: sorted by score, the sequence must be
    # D, C, B, A, S. This rejects, e.g., S in the lowest interval and D in the
    # highest — a table that tiles [0, 12] correctly but labels it backwards.
    score_ordered_grades = tuple(cutoff.grade for cutoff in ordered)
    if score_ordered_grades != GRADE_SCORE_ORDER:
        raise _fail(
            "grade cutoffs must run "
            f"{[g.value for g in GRADE_SCORE_ORDER]} in ascending score order, got "
            f"{[g.value for g in score_ordered_grades]}",
            file_path,
            base,
        )

    for index, cutoff in enumerate(cutoffs):
        if cutoff.lower >= cutoff.upper:
            raise _fail(
                f"grade '{cutoff.grade.value}' lower ({cutoff.lower}) must be < upper "
                f"({cutoff.upper})",
                file_path,
                (*base, str(index)),
            )

    if cutoffs[0].lower != SCORE_DOMAIN_MIN:
        raise _fail(
            f"the first grade cutoff must start at {SCORE_DOMAIN_MIN}, got {cutoffs[0].lower}",
            file_path,
            (*base, "0", "lower"),
        )
    if cutoffs[-1].upper != TOTAL_MAX_POINTS:
        raise _fail(
            f"the final grade cutoff must end at {TOTAL_MAX_POINTS}, got {cutoffs[-1].upper}",
            file_path,
            (*base, str(len(cutoffs) - 1), "upper"),
        )

    for index in range(len(cutoffs) - 1):
        if cutoffs[index].upper != cutoffs[index + 1].lower:
            raise _fail(
                f"grade cutoffs must meet exactly: '{cutoffs[index].grade.value}' ends at "
                f"{cutoffs[index].upper} but '{cutoffs[index + 1].grade.value}' starts at "
                f"{cutoffs[index + 1].lower}",
                file_path,
                (*base, str(index + 1), "lower"),
            )

    terminal = [index for index, cutoff in enumerate(cutoffs) if cutoff.terminal]
    if terminal != [len(cutoffs) - 1]:
        raise _fail(
            "exactly one grade cutoff may be terminal, and it must be the last one",
            file_path,
            base,
        )

    _assert_covers_domain(
        [cutoff.lower for cutoff in cutoffs] + [cutoffs[-1].upper],
        file_path,
        base,
        "grade cutoffs",
    )


# --------------------------------------------------------------------------
# Signal rules (MODEL_SPEC §16, §19 invariant 17)
# --------------------------------------------------------------------------


def _validate_signal_rules(allocations: AllocationConfig, file_path: str | None) -> None:
    base = ("allocations", "signal_rules")
    rules = allocations.signal_rules

    signals = [rule.signal for rule in rules]
    if repeated := _duplicates(signals):
        raise _fail(f"signal declared more than once: {repeated}", file_path, base)
    if missing := sorted(s.value for s in Signal if s not in set(signals)):
        raise _fail(f"signal missing a rule: {missing}", file_path, base)

    priorities = [rule.priority for rule in rules]
    if repeated := _duplicates(priorities):
        raise _fail(f"priority used more than once: {repeated}", file_path, base)
    expected = list(range(1, len(rules) + 1))
    if sorted(priorities) != expected:
        raise _fail(
            f"priorities must be contiguous starting at 1; expected {expected}, got "
            f"{sorted(priorities)}",
            file_path,
            base,
        )

    by_priority = sorted(rules, key=lambda rule: rule.priority)
    resolved_order = tuple(rule.signal for rule in by_priority)
    if resolved_order != SIGNAL_PRIORITY_ORDER:
        raise _fail(
            "signal priority order must be "
            f"{[s.value for s in SIGNAL_PRIORITY_ORDER]}, got "
            f"{[s.value for s in resolved_order]}",
            file_path,
            base,
        )

    category_maxima = {entry.category: entry.max_points for entry in allocations.categories}

    for rule in by_priority:
        index = rules.index(rule)
        _validate_signal_rule(rule, index, category_maxima, len(category_maxima), file_path, base)

    _validate_fallback_placement(rules, by_priority, file_path, base)


def _validate_signal_rule(
    rule: SignalRule,
    index: int,
    category_maxima: dict[Category, Decimal],
    category_count: int,
    file_path: str | None,
    base: tuple[str, ...],
) -> None:
    location = (*base, str(index))

    # fullmatch, not match: with `$` alone, ``re.match`` accepts a trailing
    # newline (``"code\n"``), which is not a stable identifier. fullmatch requires
    # the entire string — no leading/trailing whitespace, newline, or tab.
    if rule.override_reason is not None and not STABLE_CODE.fullmatch(rule.override_reason):
        raise _fail(
            "override_reason must be a stable identifier matching "
            f"{STABLE_CODE.pattern} across the whole value (lowercase, starting with a "
            f"letter, no surrounding whitespace), got {rule.override_reason!r}",
            file_path,
            (*location, "override_reason"),
        )

    for clause_index, clause in enumerate(rule.any_of):
        for condition_index, condition in enumerate(clause.all_of):
            where = (*location, "any_of", str(clause_index), "all_of", str(condition_index))

            if condition.type == "total_score":
                if not SCORE_DOMAIN_MIN <= condition.value <= TOTAL_MAX_POINTS:
                    raise _fail(
                        f"total-score threshold {condition.value} is outside the score domain "
                        f"[{SCORE_DOMAIN_MIN}, {TOTAL_MAX_POINTS}]",
                        file_path,
                        (*where, "value"),
                    )
            elif condition.type == "category_score":
                maximum = category_maxima.get(condition.category)
                if maximum is None:
                    raise _fail(
                        f"condition references undefined category '{condition.category.value}'",
                        file_path,
                        (*where, "category"),
                    )
                if not SCORE_DOMAIN_MIN <= condition.value <= maximum:
                    raise _fail(
                        f"category threshold {condition.value} is outside "
                        f"'{condition.category.value}' domain [{SCORE_DOMAIN_MIN}, {maximum}]",
                        file_path,
                        (*where, "value"),
                    )
            elif condition.type == "strong_category_count" and condition.count > category_count:
                raise _fail(
                    f"strong-category count {condition.count} exceeds the "
                    f"{category_count} configured categories",
                    file_path,
                    (*where, "count"),
                )


def _always_count(rule: SignalRule) -> int:
    """How many ``always`` conditions the rule contains, across all clauses."""
    return sum(
        1 for clause in rule.any_of for condition in clause.all_of if condition.type == "always"
    )


def _validate_fallback_placement(
    rules: Sequence[SignalRule],
    by_priority: Sequence[SignalRule],
    file_path: str | None,
    base: tuple[str, ...],
) -> None:
    """The final rule is an unconditional fallback, and nothing else uses ``always``.

    ``always`` is the only condition that is true no matter the score, so it may
    appear exactly once, alone, in exactly the lowest-priority rule. Anywhere
    else — combined with another condition, in a rule that also has alternative
    clauses, duplicated, or on AVOID / STRONG_BET / LEAN — it would make a signal
    fire in cases that are not actually the fallback.
    """
    final = by_priority[-1]

    # No rule other than the final one may contain `always` at all.
    for rule in by_priority[:-1]:
        if _always_count(rule) > 0:
            raise _fail(
                f"only the final fallback rule may use the 'always' condition, but "
                f"'{rule.signal.value}' (priority {rule.priority}) contains it",
                file_path,
                (*base, str(rules.index(rule))),
            )

    # The final rule must be *exactly* one unconditional clause.
    location = (*base, str(rules.index(final)))
    valid_shape = (
        len(final.any_of) == 1
        and len(final.any_of[0].all_of) == 1
        and final.any_of[0].all_of[0].type == "always"
    )
    if not valid_shape:
        raise _fail(
            f"the final fallback rule ('{final.signal.value}') must be exactly one clause of one "
            "'always' condition, with no other clauses or conditions, so every evaluated result "
            "resolves to a signal",
            file_path,
            location,
        )


# --------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------


def _validate_components(config: GreenMachineConfig, file_path: str | None) -> None:
    for index, component in enumerate(config.components):
        base = ("components", str(index))
        metric = component.component_id.value

        profiles = [profile.window_profile for profile in component.profiles]
        if repeated := _duplicates(profiles):
            raise _fail(
                f"window profile defined more than once: {repeated}",
                file_path,
                (*base, "profiles"),
                metric=metric,
            )
        if repeated := _duplicates(component.applicable_profiles):
            raise _fail(
                f"applicable profile listed more than once: {repeated}",
                file_path,
                (*base, "applicable_profiles"),
                metric=metric,
            )
        if set(profiles) != set(component.applicable_profiles):
            declared = sorted(p.value for p in component.applicable_profiles)
            defined = sorted(p.value for p in profiles)
            raise _fail(
                f"profile definitions {defined} do not match applicable_profiles {declared}",
                file_path,
                (*base, "profiles"),
                metric=metric,
            )

        for profile_index, profile in enumerate(component.profiles):
            _validate_profile(
                component, profile_index, profile, file_path, (*base, "profiles"), metric
            )


def _validate_profile(
    component: ComponentConfig,
    profile_index: int,
    profile: object,
    file_path: str | None,
    base: tuple[str, ...],
    metric: str,
) -> None:
    from .schema import ComponentProfileConfig  # local import keeps the module graph flat

    assert isinstance(profile, ComponentProfileConfig)
    location = (*base, str(profile_index))
    where = profile.window_profile.value

    is_attack_angle = component.component_id is ComponentId.ATTACK_ANGLE_QUALITY
    measurements = [
        definition.measurement_id
        for definition in profile.scoring
        if isinstance(definition, BucketedScoring)
    ]

    for definition in profile.scoring:
        expected_method = (
            ScoringMethod.BUCKETED
            if isinstance(definition, BucketedScoring)
            else ScoringMethod.BINARY
        )
        if component.scoring_method is not expected_method:
            raise _fail(
                f"component declares scoring_method '{component.scoring_method.value}' but this "
                f"profile defines a '{expected_method.value}' definition",
                file_path,
                (*location, "scoring"),
                metric=metric,
                window_profile=where,
            )

    if is_attack_angle:
        if len(profile.scoring) != len(ATTACK_ANGLE_MEASUREMENTS):
            raise _fail(
                "attack_angle_quality must define exactly one bucket set per measurement "
                f"({len(ATTACK_ANGLE_MEASUREMENTS)} expected), got {len(profile.scoring)}",
                file_path,
                (*location, "scoring"),
                metric=metric,
                window_profile=where,
            )
        if repeated := _duplicates(m for m in measurements if m is not None):
            raise _fail(
                f"measurement defined more than once: {repeated}",
                file_path,
                (*location, "scoring"),
                metric=metric,
                window_profile=where,
            )
        if set(measurements) != set(ATTACK_ANGLE_MEASUREMENTS):
            defined = sorted(m.value for m in measurements if m is not None)
            raise _fail(
                "attack_angle_quality requires a bucket set for both approved measurements "
                f"{[m.value for m in ATTACK_ANGLE_MEASUREMENTS]}, got {defined}",
                file_path,
                (*location, "scoring"),
                metric=metric,
                window_profile=where,
            )
    else:
        if len(profile.scoring) != 1:
            raise _fail(
                f"a component with one implicit measurement must define exactly one scoring "
                f"definition per profile, got {len(profile.scoring)}",
                file_path,
                (*location, "scoring"),
                metric=metric,
                window_profile=where,
            )
        if any(measurement is not None for measurement in measurements):
            named = sorted(m.value for m in measurements if m is not None)
            raise _fail(
                f"only attack_angle_quality may name a measurement; got {named}",
                file_path,
                (*location, "scoring", "0", "measurement_id"),
                metric=metric,
                window_profile=where,
            )

    for definition_index, definition in enumerate(profile.scoring):
        target = (*location, "scoring", str(definition_index))
        if isinstance(definition, BucketedScoring):
            _validate_buckets(component, definition, file_path, target, metric, where)
        else:
            _validate_binary(component, definition, file_path, target, metric, where)


def _validate_buckets(
    component: ComponentConfig,
    scoring: BucketedScoring,
    file_path: str | None,
    base: tuple[str, ...],
    metric: str,
    window_profile: str,
) -> None:
    buckets = scoring.buckets

    if scoring.domain_min >= scoring.domain_max:
        raise _fail(
            f"domain_min ({scoring.domain_min}) must be < domain_max ({scoring.domain_max})",
            file_path,
            (*base, "domain_min"),
            metric=metric,
            window_profile=window_profile,
        )

    for index, bucket in enumerate(buckets):
        where = (*base, "buckets", str(index))
        if bucket.lower >= bucket.upper:
            raise _fail(
                f"bucket lower ({bucket.lower}) must be < upper ({bucket.upper})",
                file_path,
                (*where, "lower"),
                metric=metric,
                window_profile=window_profile,
            )
        if bucket.points < 0:
            raise _fail(
                f"bucket points must be >= 0, got {bucket.points}",
                file_path,
                (*where, "points"),
                metric=metric,
                window_profile=window_profile,
            )
        if bucket.points > component.max_points:
            raise _fail(
                f"bucket points {bucket.points} exceed the component max_points "
                f"{component.max_points}",
                file_path,
                (*where, "points"),
                metric=metric,
                window_profile=window_profile,
            )

    if buckets[0].lower != scoring.domain_min:
        raise _fail(
            f"the first bucket must start at domain_min ({scoring.domain_min}), got "
            f"{buckets[0].lower}",
            file_path,
            (*base, "buckets", "0", "lower"),
            metric=metric,
            window_profile=window_profile,
        )
    if buckets[-1].upper != scoring.domain_max:
        raise _fail(
            f"the final bucket must end at domain_max ({scoring.domain_max}), got "
            f"{buckets[-1].upper}",
            file_path,
            (*base, "buckets", str(len(buckets) - 1), "upper"),
            metric=metric,
            window_profile=window_profile,
        )

    for index in range(len(buckets) - 1):
        if buckets[index].upper != buckets[index + 1].lower:
            raise _fail(
                f"buckets must meet exactly with no gap or overlap: bucket {index} ends at "
                f"{buckets[index].upper} but bucket {index + 1} starts at "
                f"{buckets[index + 1].lower}",
                file_path,
                (*base, "buckets", str(index + 1), "lower"),
                metric=metric,
                window_profile=window_profile,
            )

    _assert_covers_domain(
        [bucket.lower for bucket in buckets] + [buckets[-1].upper],
        file_path,
        (*base, "buckets"),
        "buckets",
        metric=metric,
        window_profile=window_profile,
    )

    points = [bucket.points for bucket in buckets]
    if component.direction is Direction.HIGHER_IS_BETTER:
        for index in range(len(points) - 1):
            if points[index] > points[index + 1]:
                raise _fail(
                    f"higher_is_better points must never decrease as values increase, but "
                    f"bucket {index} awards {points[index]} and bucket {index + 1} awards "
                    f"{points[index + 1]}",
                    file_path,
                    (*base, "buckets", str(index + 1), "points"),
                    metric=metric,
                    window_profile=window_profile,
                )
        strongest, strongest_index = points[-1], len(points) - 1
    else:
        for index in range(len(points) - 1):
            if points[index] < points[index + 1]:
                raise _fail(
                    f"lower_is_better points must never increase as values increase, but "
                    f"bucket {index} awards {points[index]} and bucket {index + 1} awards "
                    f"{points[index + 1]}",
                    file_path,
                    (*base, "buckets", str(index + 1), "points"),
                    metric=metric,
                    window_profile=window_profile,
                )
        strongest, strongest_index = points[0], 0

    if strongest != component.max_points:
        raise _fail(
            f"the strongest qualifying bucket must award the component max_points "
            f"({component.max_points}), got {strongest}",
            file_path,
            (*base, "buckets", str(strongest_index), "points"),
            metric=metric,
            window_profile=window_profile,
        )


def _validate_binary(
    component: ComponentConfig,
    scoring: BinaryScoring,
    file_path: str | None,
    base: tuple[str, ...],
    metric: str,
    window_profile: str,
) -> None:
    predicate = scoring.predicate
    supplied = [name for name in ("all_of", "any_of") if getattr(predicate, name) is not None]
    if len(supplied) != 1:
        raise _fail(
            f"a qualification predicate must declare exactly one of 'all_of' or 'any_of', "
            f"got {supplied or 'neither'}",
            file_path,
            (*base, "predicate"),
            metric=metric,
            window_profile=window_profile,
        )

    clauses = predicate.all_of if predicate.all_of is not None else predicate.any_of
    if not clauses:
        raise _fail(
            "a qualification predicate must contain at least one comparison",
            file_path,
            (*base, "predicate"),
            metric=metric,
            window_profile=window_profile,
        )

    if scoring.qualified_points < 0:
        raise _fail(
            f"qualified_points must be >= 0, got {scoring.qualified_points}",
            file_path,
            (*base, "qualified_points"),
            metric=metric,
            window_profile=window_profile,
        )
    if scoring.qualified_points != component.max_points:
        raise _fail(
            f"a qualifying binary component is its strongest outcome, so qualified_points must "
            f"equal the component max_points ({component.max_points}), got "
            f"{scoring.qualified_points}",
            file_path,
            (*base, "qualified_points"),
            metric=metric,
            window_profile=window_profile,
        )


# --------------------------------------------------------------------------
# Interval coverage, proven with the GM-005 helpers
# --------------------------------------------------------------------------


def _assert_covers_domain(
    boundaries: Sequence[Decimal],
    file_path: str | None,
    key_path: tuple[str, ...],
    label: str,
    *,
    metric: str | None = None,
    window_profile: str | None = None,
) -> None:
    """Prove the interval set is total over its domain, using the shared helper.

    Structural only: this establishes that every in-domain value belongs to
    exactly one interval. It never resolves a real metric value, and it does not
    reimplement the half-open convention — ``resolve_scoring_interval`` owns it.
    All probe arithmetic runs through the GM-005 primitives, so it does not depend
    on the caller's global Decimal context (ADR-0002).
    """
    two = decimal_from("2")

    def build_probes() -> list[Decimal]:
        step = _decimal_step("1", "1000")
        probes: list[Decimal] = []
        for index, boundary in enumerate(boundaries):
            probes.append(boundary)
            if index + 1 < len(boundaries):
                midpoint = divide(add(boundary, boundaries[index + 1]), two)
                probes.append(midpoint)
                probes.append(min(add(boundary, step), midpoint))
        return probes

    probes = _arith_list(
        build_probes, file_path, key_path, metric=metric, window_profile=window_profile
    )

    for probe in probes:
        if probe < boundaries[0] or probe > boundaries[-1]:
            continue
        try:
            resolve_scoring_interval(probe, list(boundaries))
        except NumericPolicyError as exc:
            raise _fail(
                f"{label} do not cover their domain exactly once: {exc}",
                file_path,
                key_path,
                metric=metric,
                window_profile=window_profile,
            ) from exc

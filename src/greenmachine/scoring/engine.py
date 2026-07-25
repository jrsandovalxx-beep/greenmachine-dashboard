"""The deterministic GreenMachine grading engine (GM-041).

Pure function of ``(frozen InputSnapshot, loaded GreenMachineConfig)`` and
nothing else: no clock, no randomness, no network, no provider knowledge, no
hidden weighting. The same snapshot under the same configuration always
produces the byte-identical result, and every awarded or withheld point
explains itself in the ordered audit derivation — observed value, bucket
bounds, points, reason, rule reference, and any fallback the ingestion layer
recorded.

Execution follows ``MODEL_SPEC.md``:

* §5.1 bucketed scoring — half-open ``[lower, upper)`` buckets over a declared
  domain, the terminal bucket closed at ``domain_max`` (§4.1), the highest
  qualifying bucket winning, points never cumulative;
* §5 binary scoring — a qualification predicate over the reserved input name
  ``observed_value`` (the component's own observed Decimal); any other input
  name fails closed until a future ruling defines its source;
* §5.2 fuzzy scoring — the loaded policy is honored by refusing to run
  anything: it is disabled for MVP, and an enabled policy fails closed rather
  than silently ignoring it;
* §8 missing data — a configured ``not_evaluable`` absence makes the whole
  evaluation :class:`NotEvaluableGradeResult`; ``record_missing`` awards an
  explicit zero with the reason on the record; an unanticipated missing
  reason is an error, never a shrug;
* §8.2 samples — an insufficient present sample is still scored and raises
  exactly one advisory ``SAMPLE_WARNINGS`` finding (the frozen result
  contract enforces it);
* §3 aggregation — plain exact-Decimal sums, no rounding anywhere;
* §14 grades from the configured half-open cutoffs, terminal inclusive.

The engine's entire output is Total Score, Tier, Component Breakdown, Audit
Trail, Warnings, and Fallbacks. GM-041 removed the betting-classification
engine: GreenMachine separates evaluation from decision-making, and any
wagering, fantasy, or DFS decision belongs entirely to the user.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from greenmachine.common.errors import ErrorContext
from greenmachine.config import (
    BinaryScoring,
    BucketedScoring,
    ComponentConfig,
    ComponentProfileConfig,
    GreenMachineConfig,
    QualificationPredicate,
)
from greenmachine.domain import (
    AuditEntry,
    BucketHit,
    Category,
    CategoryScore,
    ComponentId,
    ComponentScore,
    EvaluatedGradeResult,
    Grade,
    InputSnapshot,
    MetricObservation,
    MissingObservation,
    NotEvaluableGradeResult,
    SampleStatus,
    UnavailableRequiredInput,
    ValidationFinding,
    ValidationInputId,
)

from .errors import ScoringConfigError, ScoringInputError

__all__ = ["OBSERVED_VALUE_INPUT_NAME", "score_snapshot"]

# The one input name a binary qualification predicate can resolve today: the
# component's own observed value. Anything else is a future Product Owner
# vocabulary decision and fails closed rather than guessing a source.
OBSERVED_VALUE_INPUT_NAME = "observed_value"

_ZERO = Decimal("0")


@dataclass
class _Audit:
    """Ordered audit assembly: one strictly increasing sequence, no gaps."""

    entries: list[AuditEntry] = field(default_factory=list)

    def add(
        self,
        stage: str,
        rule_reference: str,
        input_summary: str,
        output_summary: str,
        explanation: str,
        component_id: ComponentId | None = None,
        category: Category | None = None,
    ) -> None:
        self.entries.append(
            AuditEntry(
                sequence=len(self.entries) + 1,
                stage=stage,
                rule_reference=rule_reference,
                input_summary=input_summary,
                output_summary=output_summary,
                explanation=explanation,
                component_id=component_id,
                category=category,
            )
        )


@dataclass(frozen=True, slots=True)
class _ComponentOutcome:
    """One configured component's resolution: a score, or a required absence."""

    component_id: ComponentId
    score: ComponentScore | None
    unavailable: UnavailableRequiredInput | None


def _rule_ref(config: GreenMachineConfig, *parts: str) -> str:
    return "/".join((config.model_configuration_version, *parts))


def _plain(value: Decimal) -> str:
    return format(value, "f")


# --------------------------------------------------------------------------
# Present-observation resolution
# --------------------------------------------------------------------------


def _present_for_component(
    snapshot: InputSnapshot, component: ComponentConfig
) -> MetricObservation | None:
    matches = [
        observation
        for observation in snapshot.present_observations
        if observation.component_id is component.component_id
    ]
    if len(matches) > 1:
        raise ScoringInputError(
            f"component '{component.component_id.value}' has "
            f"{len(matches)} present observations; the measurements are mutually "
            f"exclusive and exactly one may satisfy a component per evaluation "
            f"(MODEL_SPEC §9.1)",
            ErrorContext(subject=component.component_id.value),
        )
    return matches[0] if matches else None


def _missing_for_component(
    snapshot: InputSnapshot, component: ComponentConfig
) -> MissingObservation | None:
    matches = [
        observation
        for observation in snapshot.missing_observations
        if observation.component_id is component.component_id
    ]
    return matches[0] if matches else None


def _profile_config(component: ComponentConfig, snapshot: InputSnapshot) -> ComponentProfileConfig:
    for profile_config in component.profiles:
        if profile_config.window_profile is snapshot.window_profile:
            return profile_config
    raise ScoringConfigError(
        f"component '{component.component_id.value}' declares profile "
        f"'{snapshot.window_profile.value}' applicable but configures no scoring "
        f"for it",
        ErrorContext(subject=component.component_id.value),
    )


def _scoring_block(
    component: ComponentConfig,
    profile_config: ComponentProfileConfig,
    observation: MetricObservation,
) -> BucketedScoring | BinaryScoring:
    for block in profile_config.scoring:
        block_measurement = getattr(block, "measurement_id", None)
        if block_measurement is observation.measurement_id:
            return block
    measurement = (
        observation.measurement_id.value if observation.measurement_id is not None else "none"
    )
    raise ScoringConfigError(
        f"component '{component.component_id.value}' has no scoring block for "
        f"measurement '{measurement}' under profile "
        f"'{profile_config.window_profile.value}'; measurement-specific buckets may "
        f"never substitute for one another (MODEL_SPEC §9.1)",
        ErrorContext(subject=component.component_id.value),
    )


# --------------------------------------------------------------------------
# Bucketed resolution (§5.1, edge behavior §4.1)
# --------------------------------------------------------------------------


def _resolve_bucket(
    component: ComponentConfig,
    scoring: BucketedScoring,
    observed: Decimal,
) -> tuple[BucketHit, Decimal, str]:
    """The unique bucket containing ``observed``: ``[lower, upper)``, terminal
    closed at ``domain_max``. Returns the hit, its points, and a bounds text."""
    if observed < scoring.domain_min or observed > scoring.domain_max:
        raise ScoringInputError(
            f"component '{component.component_id.value}' observed value "
            f"{_plain(observed)} lies outside the declared scoring domain "
            f"[{_plain(scoring.domain_min)}, {_plain(scoring.domain_max)}]",
            ErrorContext(subject=component.component_id.value),
        )
    last_index = len(scoring.buckets) - 1
    for index, bucket in enumerate(scoring.buckets):
        terminal = index == last_index
        if terminal:
            if bucket.lower <= observed <= bucket.upper:
                hit = BucketHit(
                    lower_bound=bucket.lower,
                    upper_bound=None,
                    is_terminal=True,
                    points_awarded=bucket.points,
                )
                bounds = f"[{_plain(bucket.lower)}, {_plain(bucket.upper)}] (terminal)"
                return hit, bucket.points, bounds
        elif bucket.lower <= observed < bucket.upper:
            hit = BucketHit(
                lower_bound=bucket.lower,
                upper_bound=bucket.upper,
                is_terminal=False,
                points_awarded=bucket.points,
            )
            bounds = f"[{_plain(bucket.lower)}, {_plain(bucket.upper)})"
            return hit, bucket.points, bounds
    raise ScoringConfigError(  # pragma: no cover - §19 exhaustiveness forbids this
        f"no bucket of component '{component.component_id.value}' contains "
        f"{_plain(observed)} despite domain containment; the configuration bucket "
        f"set is not exhaustive",
        ErrorContext(subject=component.component_id.value),
    )


# --------------------------------------------------------------------------
# Binary resolution (§5)
# --------------------------------------------------------------------------

_OPERATORS: dict[str, Callable[[Decimal, Decimal], bool]] = {
    "at_least": lambda observed, value: observed >= value,
    "greater_than": lambda observed, value: observed > value,
    "at_most": lambda observed, value: observed <= value,
    "less_than": lambda observed, value: observed < value,
    "equal_to": lambda observed, value: observed == value,
}


def _predicate_holds(
    component: ComponentConfig,
    predicate: QualificationPredicate,
    observed: Decimal,
) -> tuple[bool, str]:
    def compare(comparison_input: str, operator: str, value: Decimal) -> bool:
        if comparison_input != OBSERVED_VALUE_INPUT_NAME:
            raise ScoringConfigError(
                f"component '{component.component_id.value}' binary predicate "
                f"references input '{comparison_input}'; the engine can resolve only "
                f"'{OBSERVED_VALUE_INPUT_NAME}' today, and no input source is guessed",
                ErrorContext(subject=component.component_id.value),
            )
        return _OPERATORS[operator](observed, value)

    if predicate.all_of is not None:
        checks = [
            (comparison, compare(comparison.input_name, comparison.operator, comparison.value))
            for comparison in predicate.all_of
        ]
        holds = all(result for _, result in checks)
        joiner = " AND "
    else:
        assert predicate.any_of is not None  # schema guarantees exactly one arm
        checks = [
            (comparison, compare(comparison.input_name, comparison.operator, comparison.value))
            for comparison in predicate.any_of
        ]
        holds = any(result for _, result in checks)
        joiner = " OR "
    description = joiner.join(
        f"{comparison.input_name} {comparison.operator} {_plain(comparison.value)}"
        f"={'true' if result else 'false'}"
        for comparison, result in checks
    )
    return holds, description


# --------------------------------------------------------------------------
# Snapshot / configuration coherence
# --------------------------------------------------------------------------


def _coherence_failure(
    component: ComponentConfig,
    field: str,
    snapshot_value: object,
    configured_value: object,
) -> ScoringInputError:
    """The one shaped message for every snapshot/configuration disagreement."""
    return ScoringInputError(
        f"component '{component.component_id.value}': snapshot {field} "
        f"{snapshot_value!r} disagrees with the configured {field} "
        f"{configured_value!r}; the engine scores a snapshot only under a "
        f"configuration that describes it, and never recalculates, mutates, or "
        f"replaces snapshot metadata",
        ErrorContext(subject=component.component_id.value),
    )


def _require_present_coherence(
    component: ComponentConfig,
    profile_config: ComponentProfileConfig,
    observation: MetricObservation,
) -> None:
    """Fail closed unless the observation's metadata matches the configuration.

    ``sample_status`` was decided by the ingestion layer against the minimum
    stored **on the observation**. Scoring under a configuration that declares a
    different minimum would make every warning and audit line disagree with the
    status the snapshot actually carries, so the disagreement is refused rather
    than reconciled.
    """
    if observation.sample_type is not component.sample_type:
        raise _coherence_failure(
            component,
            "sample_type",
            observation.sample_type.value,
            component.sample_type.value,
        )
    if observation.minimum_sample_required != profile_config.minimum_sample_required:
        raise _coherence_failure(
            component,
            "minimum_sample_required",
            observation.minimum_sample_required,
            profile_config.minimum_sample_required,
        )


def _require_missing_coherence(component: ComponentConfig, observation: MissingObservation) -> None:
    """A missing observation carries no minimum, so only the sample type binds."""
    if observation.sample_type is not component.sample_type:
        raise _coherence_failure(
            component,
            "sample_type",
            observation.sample_type.value,
            component.sample_type.value,
        )


# --------------------------------------------------------------------------
# Component execution
# --------------------------------------------------------------------------


def _score_present(
    config: GreenMachineConfig,
    component: ComponentConfig,
    profile_config: ComponentProfileConfig,
    observation: MetricObservation,
    audit: _Audit,
) -> ComponentScore:
    reference = _rule_ref(
        config,
        "components",
        component.component_id.value,
        profile_config.window_profile.value,
    )
    if observation.fallback_used is not None:
        ineligible = ", ".join(
            f"{record.method.value}"
            for record in observation.fallback_used.higher_priority_ineligible
        )
        audit.add(
            stage="fallback_provenance",
            rule_reference=reference,
            input_summary=(
                f"acquisition method '{observation.acquisition_method.value}' was a "
                f"recorded fallback"
            ),
            output_summary=f"higher-priority methods ineligible: {ineligible}",
            explanation=(
                "the ingestion layer selected event derivation over an approved "
                "higher-priority route; the fallback record travels with the score "
                "(MODEL_SPEC §11.2: eligibility outranks priority)"
            ),
            component_id=component.component_id,
        )

    block = _scoring_block(component, profile_config, observation)
    if isinstance(block, BucketedScoring):
        hit, points, bounds = _resolve_bucket(component, block, observation.raw_value)
        audit.add(
            stage="bucket_resolution",
            rule_reference=reference,
            input_summary=(
                f"observed {_plain(observation.raw_value)} {observation.unit} "
                f"(sample {observation.sample_count} {observation.sample_type.value}, "
                f"minimum configured {profile_config.minimum_sample_required}, "
                f"status {observation.sample_status.value}, direction "
                f"{component.direction.value})"
            ),
            output_summary=(
                f"bucket {bounds} awarded {_plain(points)} of {_plain(component.max_points)} points"
            ),
            explanation=(
                "highest qualifying half-open bucket wins; points are not cumulative "
                "and never rounded (MODEL_SPEC §5.1, §4.1)"
            ),
            component_id=component.component_id,
        )
        return ComponentScore(
            component_id=component.component_id,
            measurement_id=observation.measurement_id,
            points_awarded=points,
            bucket_hit=hit,
        )

    holds, description = _predicate_holds(component, block.predicate, observation.raw_value)
    points = block.qualified_points if holds else _ZERO
    audit.add(
        stage="binary_qualification",
        rule_reference=reference,
        input_summary=(
            f"observed {_plain(observation.raw_value)} {observation.unit}; predicate: {description}"
        ),
        output_summary=(
            f"{'qualified' if holds else 'not qualified'}: awarded {_plain(points)} of "
            f"{_plain(component.max_points)} points"
        ),
        explanation=(
            "binary components award their configured points exactly when the "
            "qualification predicate holds (MODEL_SPEC §5)"
        ),
        component_id=component.component_id,
    )
    return ComponentScore(
        component_id=component.component_id,
        measurement_id=observation.measurement_id,
        points_awarded=points,
        bucket_hit=None,
    )


def _handle_missing(
    config: GreenMachineConfig,
    component: ComponentConfig,
    observation: MissingObservation,
    audit: _Audit,
) -> _ComponentOutcome:
    rule = component.missing_data
    reference = _rule_ref(config, "components", component.component_id.value, "missing_data")
    if observation.missing_reason not in rule.reasons:
        raise ScoringInputError(
            f"component '{component.component_id.value}' is missing with reason "
            f"'{observation.missing_reason.value}', which the configuration's "
            f"missing-data rule does not anticipate (configured: "
            f"{sorted(reason.value for reason in rule.reasons)})",
            ErrorContext(subject=component.component_id.value),
        )
    if rule.policy == "not_evaluable":
        audit.add(
            stage="missing_required_input",
            rule_reference=reference,
            input_summary=(
                f"missing with reason '{observation.missing_reason.value}' "
                f"(source available: "
                f"{str(observation.data_coverage.source_available).lower()})"
            ),
            output_summary="required input unavailable: evaluation is NOT_EVALUABLE",
            explanation=(
                "the configured missing-data policy for this component is "
                "'not_evaluable'; no substitute value is ever invented (MODEL_SPEC §8)"
            ),
            component_id=component.component_id,
        )
        return _ComponentOutcome(
            component_id=component.component_id,
            score=None,
            unavailable=UnavailableRequiredInput(
                component_id=observation.component_id,
                measurement_id=observation.measurement_id,
                missing_reason=observation.missing_reason,
                missing_observation=observation,
                attempted_methods=(),
            ),
        )
    audit.add(
        stage="missing_recorded_zero",
        rule_reference=reference,
        input_summary=(f"missing with reason '{observation.missing_reason.value}'"),
        output_summary=(
            f"recorded 0 of {_plain(component.max_points)} points with the missing "
            f"reason on the record"
        ),
        explanation=(
            "the configured missing-data policy for this component is "
            "'record_missing': the absence is visible and awards nothing "
            "(MODEL_SPEC §8)"
        ),
        component_id=component.component_id,
    )
    return _ComponentOutcome(
        component_id=component.component_id,
        score=ComponentScore(
            component_id=observation.component_id,
            measurement_id=observation.measurement_id,
            points_awarded=_ZERO,
            bucket_hit=None,
        ),
        unavailable=None,
    )


# --------------------------------------------------------------------------
# Aggregation and grade
# --------------------------------------------------------------------------


def _category_scores(
    config: GreenMachineConfig,
    scores_by_component: dict[ComponentId, ComponentScore],
    audit: _Audit,
) -> tuple[CategoryScore, ...]:
    category_scores: list[CategoryScore] = []
    for allocation in config.allocations.categories:
        members = tuple(
            scores_by_component[component_id]
            for component_id in allocation.components
            if component_id in scores_by_component
        )
        if not members:
            raise ScoringInputError(
                f"category '{allocation.category.value}' has no scored component under "
                f"this profile; an evaluated grade cannot carry an empty category",
                ErrorContext(subject=allocation.category.value),
            )
        total = _ZERO
        for member in members:
            total = total + member.points_awarded
        rendered = " + ".join(_plain(member.points_awarded) for member in members)
        audit.add(
            stage="category_aggregation",
            rule_reference=_rule_ref(config, "allocations", allocation.category.value),
            input_summary=f"component points: {rendered}",
            output_summary=(f"category total {_plain(total)} of {_plain(allocation.max_points)}"),
            explanation="plain exact-Decimal sum; no rounding, rescaling, or averaging "
            "(MODEL_SPEC §3)",
            category=allocation.category,
        )
        category_scores.append(
            CategoryScore(
                category=allocation.category,
                points_awarded=total,
                component_scores=members,
            )
        )
    return tuple(category_scores)


def _grade_for(config: GreenMachineConfig, total: Decimal, audit: _Audit) -> Grade:
    for cutoff in config.allocations.grade_cutoffs:
        contains = (
            cutoff.lower <= total <= cutoff.upper
            if cutoff.terminal
            else cutoff.lower <= total < cutoff.upper
        )
        if contains:
            bracket = "]" if cutoff.terminal else ")"
            audit.add(
                stage="grade_assignment",
                rule_reference=_rule_ref(config, "allocations", "grade_cutoffs"),
                input_summary=f"total score {_plain(total)}",
                output_summary=(
                    f"grade {cutoff.grade.value} from cutoff "
                    f"[{_plain(cutoff.lower)}, {_plain(cutoff.upper)}{bracket}"
                ),
                explanation=(
                    "grades come from the configured half-open cutoffs before any "
                    "presentation rounding; the terminal cutoff is inclusive "
                    "(MODEL_SPEC §4.1, §14)"
                ),
            )
            return cutoff.grade
    raise ScoringConfigError(  # pragma: no cover - §19 exhaustiveness forbids this
        f"no grade cutoff contains total {_plain(total)}"
    )


# --------------------------------------------------------------------------
# Warnings (frozen contract: one advisory finding per insufficient component)
# --------------------------------------------------------------------------


def _sample_warning_findings(snapshot: InputSnapshot) -> tuple[ValidationFinding, ...]:
    insufficient: list[ComponentId] = []
    for observation in snapshot.present_observations:
        if (
            observation.sample_status is SampleStatus.INSUFFICIENT
            and observation.component_id not in insufficient
        ):
            insufficient.append(observation.component_id)
    return tuple(
        ValidationFinding(
            input_id=ValidationInputId.SAMPLE_WARNINGS,
            message=(
                f"advisory: component '{component.value}' was scored from an "
                f"insufficient sample; the label never gates scoring (MODEL_SPEC §8.2)"
            ),
            component_id=component,
        )
        for component in insufficient
    )


# --------------------------------------------------------------------------
# The engine
# --------------------------------------------------------------------------


def score_snapshot(
    snapshot: InputSnapshot, config: GreenMachineConfig
) -> EvaluatedGradeResult | NotEvaluableGradeResult:
    """Deterministically grade one frozen snapshot under one configuration."""
    if not isinstance(snapshot, InputSnapshot):
        raise ScoringInputError(
            f"score_snapshot expects an InputSnapshot, got {type(snapshot).__name__}"
        )
    if not isinstance(config, GreenMachineConfig):
        raise ScoringInputError(
            f"score_snapshot expects a GreenMachineConfig, got {type(config).__name__}"
        )
    if config.fuzzy_scoring.enabled:
        raise ScoringConfigError(
            "fuzzy scoring is enabled in this configuration; it is not implemented "
            "for MVP and the engine refuses to silently ignore it (MODEL_SPEC §5.2)"
        )

    audit = _Audit()
    audit.add(
        stage="validation",
        rule_reference=_rule_ref(config, "schema_version", str(config.schema_version)),
        input_summary=(
            f"snapshot {snapshot.snapshot_id.value} under profile "
            f"'{snapshot.window_profile.value}': "
            f"{len(snapshot.present_observations)} present, "
            f"{len(snapshot.missing_observations)} missing observation(s)"
        ),
        output_summary=(
            f"configuration '{config.model_configuration_version}' "
            f"(spec {config.specification_version}) accepted for grading"
        ),
        explanation=(
            "structure and MODEL_SPEC §19 semantics were enforced at configuration "
            "load; the engine now resolves each configured component against the "
            "frozen snapshot"
        ),
    )

    configured_components: set[ComponentId] = set()
    outcomes: list[_ComponentOutcome] = []
    for component in config.components:
        configured_components.add(component.component_id)
        if snapshot.window_profile not in component.applicable_profiles:
            audit.add(
                stage="profile_applicability",
                rule_reference=_rule_ref(
                    config, "components", component.component_id.value, "applicable_profiles"
                ),
                input_summary=(f"profile '{snapshot.window_profile.value}' is not applicable"),
                output_summary="component skipped for this profile",
                explanation=("a component scores only under its configured applicable profiles"),
                component_id=component.component_id,
            )
            continue
        present = _present_for_component(snapshot, component)
        if present is not None:
            profile_config = _profile_config(component, snapshot)
            _require_present_coherence(component, profile_config, present)
            score = _score_present(config, component, profile_config, present, audit)
            outcomes.append(
                _ComponentOutcome(
                    component_id=component.component_id, score=score, unavailable=None
                )
            )
            continue
        missing = _missing_for_component(snapshot, component)
        if missing is None:
            raise ScoringInputError(
                f"configured component '{component.component_id.value}' has neither a "
                f"present nor a missing observation on the snapshot; the snapshot and "
                f"configuration disagree and nothing is guessed",
                ErrorContext(subject=component.component_id.value),
            )
        _require_missing_coherence(component, missing)
        outcomes.append(_handle_missing(config, component, missing, audit))

    unconfigured = [
        observation.component_id.value
        for observation in snapshot.present_observations
        if observation.component_id not in configured_components
    ]
    if unconfigured:
        audit.add(
            stage="unscored_observations",
            rule_reference=_rule_ref(config, "components"),
            input_summary=(
                f"present observation(s) with no configured component: {sorted(unconfigured)}"
            ),
            output_summary="left unscored; no configuration means no points",
            explanation=(
                "the configuration is the sole authority over what scores; an "
                "unconfigured observation is recorded, never silently graded"
            ),
        )

    unavailable = tuple(
        outcome.unavailable for outcome in outcomes if outcome.unavailable is not None
    )
    if unavailable:
        names = ", ".join(sorted(entry.component_id.value for entry in unavailable))
        audit.add(
            stage="evaluability_verdict",
            rule_reference=_rule_ref(config, "components", "missing_data"),
            input_summary=f"required input(s) unavailable: {names}",
            output_summary="NOT_EVALUABLE (no score or grade exists)",
            explanation=(
                "NOT_EVALUABLE is a distinct terminal state, never a low grade (MODEL_SPEC §15)"
            ),
        )
        return NotEvaluableGradeResult(
            window_profile=snapshot.window_profile,
            present_observations=snapshot.present_observations,
            missing_observations=snapshot.missing_observations,
            validation_findings=_sample_warning_findings(snapshot),
            audit_derivation=tuple(audit.entries),
            unavailable_required_inputs=unavailable,
        )

    scores_by_component = {
        outcome.component_id: outcome.score for outcome in outcomes if outcome.score is not None
    }
    category_scores = _category_scores(config, scores_by_component, audit)

    total = _ZERO
    for category_score in category_scores:
        total = total + category_score.points_awarded
    audit.add(
        stage="total_aggregation",
        rule_reference=_rule_ref(config, "allocations", "total_max_points"),
        input_summary=" + ".join(
            f"{score.category.value}={_plain(score.points_awarded)}" for score in category_scores
        ),
        output_summary=(f"total {_plain(total)} of {_plain(config.allocations.total_max_points)}"),
        explanation="plain exact-Decimal sum of category totals (MODEL_SPEC §3)",
    )

    grade = _grade_for(config, total, audit)

    return EvaluatedGradeResult(
        window_profile=snapshot.window_profile,
        present_observations=snapshot.present_observations,
        missing_observations=snapshot.missing_observations,
        validation_findings=_sample_warning_findings(snapshot),
        audit_derivation=tuple(audit.entries),
        component_scores=tuple(
            scores_by_component[component_id] for component_id in scores_by_component
        ),
        category_scores=category_scores,
        total_score=total,
        grade=grade,
    )

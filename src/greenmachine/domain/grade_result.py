"""The pure grading output, as two structurally distinct variants.

ADR-0004 makes ``GradeResult`` the deterministic output of ``(frozen input,
configuration)`` and nothing else: it carries **no timestamp, no identity, no
version, no hash, and no outcome**. Orchestration metadata lives on the
:class:`~greenmachine.domain.envelope.EvaluationEnvelope`; the game outcome lives
in a separate :class:`~greenmachine.domain.outcome.OutcomeRecord` (ADR-0006).

The two terminal states of ``MODEL_SPEC.md`` §15 are *different types*, not one
type with half its fields optional:

* :class:`EvaluatedGradeResult` — a complete grade: component and category
  scores, a total, and a grade.
* :class:`NotEvaluableGradeResult` — no score or grade at all; instead, the
  required inputs that were unavailable and why.

GM-041 removed the betting-classification fields (``signal`` and
``signal_reason``) from this contract. GreenMachine separates evaluation from
decision-making: the platform's responsibility ends at a transparent,
deterministic, auditable evaluation, and any wagering, fantasy, or DFS
decision belongs entirely to the user.

The variant *is* the :class:`EvaluationStatus`; a caller cannot select a status
that contradicts the fields, and an evaluated result missing a required field or
a not-evaluable result carrying a score is unconstructable. These records
validate structure only — no summation, no comparison against configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise

from ._guards import (
    ensure_instance,
    ensure_measurement_matches_component,
    ensure_no_duplicates,
    ensure_non_empty_text,
    ensure_non_negative_decimal,
    ensure_non_negative_int,
    ensure_optional_instance,
    ensure_tuple_of,
)
from .enums import (
    Category,
    ComponentId,
    EvaluationStatus,
    Grade,
    MeasurementId,
    MissingReason,
    SampleStatus,
    ValidationInputId,
    WindowProfile,
)
from .errors import DomainValidationError
from .observations import MetricObservation, MissingObservation
from .results import CategoryScore, ComponentScore, ValidationFinding
from .values import MethodIneligibility

__all__ = [
    "AuditEntry",
    "EvaluatedGradeResult",
    "GradeResult",
    "NotEvaluableGradeResult",
    "UnavailableRequiredInput",
]


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One ordered, data-only step in how a result was derived.

    Records a decision already made elsewhere — it executes no rule and performs
    no scoring. ``sequence`` fixes the order, ``stage`` names the step,
    ``rule_reference`` cites the stable configuration/rule it applied, and the two
    summaries plus the explanation make it human-readable. ``component_id`` and
    ``category`` are present only where the step concerns one.
    """

    sequence: int
    stage: str
    rule_reference: str
    input_summary: str
    output_summary: str
    explanation: str
    component_id: ComponentId | None = None
    category: Category | None = None

    def __post_init__(self) -> None:
        ensure_non_negative_int(self.sequence, "AuditEntry.sequence")
        ensure_non_empty_text(self.stage, "AuditEntry.stage")
        ensure_non_empty_text(self.rule_reference, "AuditEntry.rule_reference")
        ensure_non_empty_text(self.input_summary, "AuditEntry.input_summary")
        ensure_non_empty_text(self.output_summary, "AuditEntry.output_summary")
        ensure_non_empty_text(self.explanation, "AuditEntry.explanation")
        ensure_optional_instance(self.component_id, ComponentId, "AuditEntry.component_id")
        ensure_optional_instance(self.category, Category, "AuditEntry.category")


@dataclass(frozen=True, slots=True)
class UnavailableRequiredInput:
    """One required input that was unavailable, making an evaluation not-evaluable.

    Retains the component/measurement it concerns, the :class:`MissingReason`, the
    :class:`MissingObservation` that recorded the absence, and every acquisition
    method that was attempted and found ineligible before the evaluation gave up.

    A :class:`~greenmachine.domain.values.MethodIneligibility` records a *failed
    attempt*; it is deliberately not a
    :class:`~greenmachine.domain.values.FallbackRecord`, which describes a
    *selected* fallback — and here no method was ultimately selected.
    """

    component_id: ComponentId
    measurement_id: MeasurementId | None
    missing_reason: MissingReason
    missing_observation: MissingObservation
    attempted_methods: tuple[MethodIneligibility, ...]

    def __post_init__(self) -> None:
        ensure_measurement_matches_component(
            self.component_id, self.measurement_id, "UnavailableRequiredInput"
        )
        reason = ensure_instance(
            self.missing_reason, MissingReason, "UnavailableRequiredInput.missing_reason"
        )
        observation = ensure_instance(
            self.missing_observation,
            MissingObservation,
            "UnavailableRequiredInput.missing_observation",
        )
        attempted = ensure_tuple_of(
            self.attempted_methods,
            MethodIneligibility,
            "UnavailableRequiredInput.attempted_methods",
        )
        ensure_no_duplicates(
            [entry.method for entry in attempted],
            "UnavailableRequiredInput.attempted_methods",
        )

        if observation.component_id is not self.component_id:
            raise DomainValidationError(
                "UnavailableRequiredInput.missing_observation.component_id must equal "
                f"component_id ('{self.component_id.value}')"
            )
        if observation.measurement_id is not self.measurement_id:
            raise DomainValidationError(
                "UnavailableRequiredInput.missing_observation.measurement_id must equal "
                "measurement_id"
            )
        if observation.missing_reason is not reason:
            raise DomainValidationError(
                "UnavailableRequiredInput.missing_observation.missing_reason must equal "
                f"missing_reason ('{reason.value}')"
            )


@dataclass(frozen=True, slots=True)
class GradeResult:
    """Common, pure content shared by the two result variants.

    Abstract: construct :class:`EvaluatedGradeResult` or
    :class:`NotEvaluableGradeResult`. Carries the profile, the present and missing
    observations, the advisory validation findings, and the ordered audit
    derivation — and, by construction, nothing that would make it impure (no time,
    no id, no version, no hash, no outcome).
    """

    window_profile: WindowProfile
    present_observations: tuple[MetricObservation, ...]
    missing_observations: tuple[MissingObservation, ...]
    validation_findings: tuple[ValidationFinding, ...]
    audit_derivation: tuple[AuditEntry, ...]

    def __post_init__(self) -> None:
        if type(self) is GradeResult:
            raise DomainValidationError(
                "GradeResult is abstract; construct an EvaluatedGradeResult or a "
                "NotEvaluableGradeResult"
            )
        self._validate_common()

    def _validate_common(self) -> None:
        profile = ensure_instance(self.window_profile, WindowProfile, "GradeResult.window_profile")
        present = ensure_tuple_of(
            self.present_observations, MetricObservation, "GradeResult.present_observations"
        )
        missing = ensure_tuple_of(
            self.missing_observations, MissingObservation, "GradeResult.missing_observations"
        )
        ensure_tuple_of(
            self.validation_findings, ValidationFinding, "GradeResult.validation_findings"
        )
        audit = ensure_tuple_of(self.audit_derivation, AuditEntry, "GradeResult.audit_derivation")

        for present_observation in present:
            if present_observation.window_profile is not profile:
                raise DomainValidationError(
                    f"GradeResult present observation has window_profile "
                    f"'{present_observation.window_profile.value}', but the result's profile is "
                    f"'{profile.value}'; a result carries exactly one profile"
                )
        for missing_observation in missing:
            if missing_observation.window_profile is not profile:
                raise DomainValidationError(
                    f"GradeResult missing observation has window_profile "
                    f"'{missing_observation.window_profile.value}', but the result's profile is "
                    f"'{profile.value}'; a result carries exactly one profile"
                )

        keys = [(o.component_id, o.measurement_id) for o in present]
        keys += [(o.component_id, o.measurement_id) for o in missing]
        ensure_no_duplicates(keys, "GradeResult observation (component_id, measurement_id) keys")

        # The complete ordered derivation is part of the contract: a result that
        # cannot say how it was derived is not a result. One entry suffices.
        if not audit:
            raise DomainValidationError(
                "GradeResult.audit_derivation must contain at least one AuditEntry; the "
                "complete ordered derivation is part of the result contract"
            )
        sequences = [entry.sequence for entry in audit]
        for earlier, later in pairwise(sequences):
            if later <= earlier:
                raise DomainValidationError(
                    f"GradeResult.audit_derivation sequences must strictly increase, got "
                    f"{earlier} then {later}"
                )

    @property
    def status(self) -> EvaluationStatus:
        raise NotImplementedError  # pragma: no cover - overridden by every variant


@dataclass(frozen=True, slots=True)
class EvaluatedGradeResult(GradeResult):
    """A complete grade. Its status is always ``EVALUATED``.

    Requires every evaluated field: the component and category scores, the total,
    and the grade. An insufficient present sample must carry exactly one advisory
    ``SAMPLE_WARNINGS`` finding for its component — advisory only, never altering
    score or grade.
    """

    component_scores: tuple[ComponentScore, ...]
    category_scores: tuple[CategoryScore, ...]
    total_score: Decimal
    grade: Grade

    def __post_init__(self) -> None:
        self._validate_common()
        component_scores = ensure_tuple_of(
            self.component_scores, ComponentScore, "EvaluatedGradeResult.component_scores"
        )
        category_scores = ensure_tuple_of(
            self.category_scores, CategoryScore, "EvaluatedGradeResult.category_scores"
        )
        # A complete evaluated grade cannot be empty of the scores that produced
        # it. How many there must be is configuration, checked by the scoring
        # engine — the structural floor here is simply "at least one".
        if not component_scores:
            raise DomainValidationError(
                "EvaluatedGradeResult.component_scores must contain at least one "
                "ComponentScore; an evaluated grade cannot be scoreless"
            )
        if not category_scores:
            raise DomainValidationError(
                "EvaluatedGradeResult.category_scores must contain at least one "
                "CategoryScore; an evaluated grade cannot be categoryless"
            )
        ensure_non_negative_decimal(self.total_score, "EvaluatedGradeResult.total_score")
        ensure_instance(self.grade, Grade, "EvaluatedGradeResult.grade")

        ensure_no_duplicates(
            [score.category for score in category_scores],
            "EvaluatedGradeResult.category_scores categories",
        )
        ensure_no_duplicates(
            [(score.component_id, score.measurement_id) for score in component_scores],
            "EvaluatedGradeResult.component_scores (component_id, measurement_id) keys",
        )
        self._validate_score_observation_coherence(component_scores, category_scores)
        self._validate_sample_warnings()

    def _validate_score_observation_coherence(
        self,
        component_scores: tuple[ComponentScore, ...],
        category_scores: tuple[CategoryScore, ...],
    ) -> None:
        """Consistency between the two stored score representations and the inputs.

        Every top-level score must concern an observed component (present *or*
        typed-missing — a configured missing-data policy may award for a missing
        observation, but never for a component absent from the result). The
        category copies must then partition the top-level scores exactly: no
        duplicate within a category, no component in two categories, no category
        copy differing from its top-level score, and no top-level score left out.
        No points are summed and no configuration is consulted here.
        """
        observed_keys = {
            (observation.component_id, observation.measurement_id)
            for observation in self.present_observations
        }
        observed_keys |= {
            (observation.component_id, observation.measurement_id)
            for observation in self.missing_observations
        }

        top_by_key: dict[tuple[ComponentId, MeasurementId | None], ComponentScore] = {}
        for score in component_scores:
            key = (score.component_id, score.measurement_id)
            if key not in observed_keys:
                raise DomainValidationError(
                    f"EvaluatedGradeResult.component_scores contains a score for component "
                    f"'{score.component_id.value}', which has no present or missing "
                    f"observation on the result"
                )
            top_by_key[key] = score

        placed: list[tuple[ComponentId, MeasurementId | None]] = []
        for index, category_score in enumerate(category_scores):
            if not category_score.component_scores:
                raise DomainValidationError(
                    f"EvaluatedGradeResult.category_scores[{index}].component_scores must "
                    f"contain at least one ComponentScore; an empty category is not part "
                    f"of a complete evaluated grade"
                )
            ensure_no_duplicates(
                [(s.component_id, s.measurement_id) for s in category_score.component_scores],
                f"EvaluatedGradeResult.category_scores[{index}].component_scores keys",
            )
            for member in category_score.component_scores:
                key = (member.component_id, member.measurement_id)
                top = top_by_key.get(key)
                if top is None:
                    raise DomainValidationError(
                        f"EvaluatedGradeResult.category_scores[{index}] contains component "
                        f"'{member.component_id.value}', which is not among the top-level "
                        f"component_scores"
                    )
                if member != top:
                    raise DomainValidationError(
                        f"EvaluatedGradeResult.category_scores[{index}] component "
                        f"'{member.component_id.value}' differs from the top-level "
                        f"component score"
                    )
                if key in placed:
                    raise DomainValidationError(
                        f"EvaluatedGradeResult component '{member.component_id.value}' "
                        f"appears in more than one category"
                    )
                placed.append(key)

        unplaced = [key for key in top_by_key if key not in placed]
        if unplaced:
            names = sorted(component.value for component, _ in unplaced)
            raise DomainValidationError(
                f"EvaluatedGradeResult top-level component score(s) missing from every "
                f"category: {names}"
            )

    def _validate_sample_warnings(self) -> None:
        insufficient = {
            observation.component_id
            for observation in self.present_observations
            if observation.sample_status is SampleStatus.INSUFFICIENT
        }
        warned: list[ComponentId] = []
        for finding in self.validation_findings:
            if finding.input_id is not ValidationInputId.SAMPLE_WARNINGS:
                continue
            component = finding.component_id
            if component is None:
                raise DomainValidationError(
                    "a SAMPLE_WARNINGS finding must reference the affected component_id"
                )
            if component not in insufficient:
                raise DomainValidationError(
                    f"SAMPLE_WARNINGS finding references component '{component.value}', which "
                    f"has no insufficient present sample"
                )
            if component in warned:
                raise DomainValidationError(
                    f"duplicate SAMPLE_WARNINGS finding for component '{component.value}'"
                )
            warned.append(component)

        unwarned = insufficient - set(warned)
        if unwarned:
            raise DomainValidationError(
                "every insufficient present sample requires one SAMPLE_WARNINGS finding; "
                f"missing for: {sorted(component.value for component in unwarned)}"
            )

    @property
    def status(self) -> EvaluationStatus:
        return EvaluationStatus.EVALUATED


@dataclass(frozen=True, slots=True)
class NotEvaluableGradeResult(GradeResult):
    """A not-evaluable outcome. Its status is always ``NOT_EVALUABLE``.

    Carries no total score and no grade — those fields do not
    exist on this type. Instead it requires at least one
    :class:`UnavailableRequiredInput` explaining what was missing and why.
    """

    unavailable_required_inputs: tuple[UnavailableRequiredInput, ...]

    def __post_init__(self) -> None:
        self._validate_common()
        inputs = ensure_tuple_of(
            self.unavailable_required_inputs,
            UnavailableRequiredInput,
            "NotEvaluableGradeResult.unavailable_required_inputs",
        )
        if not inputs:
            raise DomainValidationError(
                "NotEvaluableGradeResult requires at least one unavailable required input; a "
                "not-evaluable result must say what was missing"
            )

        # A required failure must cite an observation this result actually holds.
        # A missing observation may exist without being required (an optional
        # component's absence need not fail the evaluation), but a required record
        # can never introduce an observation absent from the result — and no key
        # may be reported required twice.
        ensure_no_duplicates(
            [(entry.component_id, entry.measurement_id) for entry in inputs],
            "NotEvaluableGradeResult.unavailable_required_inputs (component_id, "
            "measurement_id) keys",
        )
        for index, entry in enumerate(inputs):
            if entry.missing_observation not in self.missing_observations:
                raise DomainValidationError(
                    f"NotEvaluableGradeResult.unavailable_required_inputs[{index}]."
                    f"missing_observation for component '{entry.component_id.value}' is not "
                    f"among the result's missing_observations"
                )

    @property
    def status(self) -> EvaluationStatus:
        return EvaluationStatus.NOT_EVALUABLE

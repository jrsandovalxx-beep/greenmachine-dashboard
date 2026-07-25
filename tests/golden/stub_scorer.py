"""TEST-ONLY stub scorer for the GM-008 golden harness. Not a scoring engine.

This module exists so the golden harness can be proven end to end before the
Sprint-2 scoring engine exists. It lives under ``tests/`` and must never enter
``src/``. It performs **no scoring of any kind**: no bucket resolution, no
threshold comparison, no category aggregation, no grade derivation, no
signal-rule evaluation, and it consults no configuration. It reads no clock, no
filesystem, no network, no environment, and no randomness.

What it does instead: it assembles a structurally valid, deliberately synthetic
:class:`~greenmachine.domain.EvaluatedGradeResult` (or, when a snapshot carries
no present observations, a
:class:`~greenmachine.domain.NotEvaluableGradeResult`) directly from the
supplied snapshot, using fixed constants selected **only** by
:class:`~greenmachine.domain.WindowProfile` — solely to prove that the two
profiles are genuinely separate execution paths. It never inspects a metric
value to decide points, grade, or signal. Every number it emits is an obviously
synthetic fixture value, never a production threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from greenmachine.domain import (
    AuditEntry,
    Category,
    CategoryScore,
    ComponentId,
    ComponentScore,
    EvaluatedGradeResult,
    Grade,
    InputSnapshot,
    NotEvaluableGradeResult,
    SampleStatus,
    Signal,
    UnavailableRequiredInput,
    ValidationFinding,
    ValidationInputId,
    WindowProfile,
)

__all__ = ["score_snapshot"]


@dataclass(frozen=True, slots=True)
class _StubProfileConstants:
    """Fixed synthetic outputs for one profile. Chosen to be visibly fake."""

    component_points: Decimal
    category: Category
    category_points: Decimal
    total_score: Decimal
    grade: Grade
    signal: Signal
    signal_reason: str


# Two deliberately different constant sets prove RECENT_7D and LONG_TERM_2Y are
# distinct execution paths. Decimals are constructed from strings (ADR-0002).
_PROFILE_CONSTANTS: dict[WindowProfile, _StubProfileConstants] = {
    WindowProfile.RECENT_7D: _StubProfileConstants(
        component_points=Decimal("0.111"),
        category=Category.POWER_PROFILE,
        category_points=Decimal("1.111"),
        total_score=Decimal("1.111"),
        grade=Grade.C,
        signal=Signal.PASS,
        signal_reason="synthetic_stub_recent_pass",
    ),
    WindowProfile.LONG_TERM_2Y: _StubProfileConstants(
        component_points=Decimal("0.222"),
        category=Category.FORM,
        category_points=Decimal("2.222"),
        total_score=Decimal("2.222"),
        grade=Grade.B,
        signal=Signal.LEAN,
        signal_reason="synthetic_stub_long_term_lean",
    ),
}

_STUB_EXPLANATION = (
    "GM-008 test-only stub scorer: fixed synthetic values selected by window profile; "
    "no bucket resolution, no aggregation, no grading or signal rules were executed"
)


def score_snapshot(
    snapshot: InputSnapshot, config_version_identifier: str, /
) -> EvaluatedGradeResult | NotEvaluableGradeResult:
    """Produce a synthetic, structurally valid GradeResult for a golden case.

    The supplied snapshot's profile and observations are preserved verbatim.
    A snapshot with at least one present observation yields an
    ``EvaluatedGradeResult`` built from fixed profile-keyed constants; a
    snapshot with only missing observations yields a ``NotEvaluableGradeResult``
    citing every missing observation. The configuration version reference is
    used only as a stable audit ``rule_reference`` value.
    """
    if not isinstance(snapshot, InputSnapshot):
        raise TypeError(f"score_snapshot expects an InputSnapshot, got {type(snapshot).__name__}")
    if not isinstance(config_version_identifier, str) or not config_version_identifier.strip():
        raise ValueError("config_version_identifier must be a non-blank string")

    constants = _PROFILE_CONSTANTS[snapshot.window_profile]
    if snapshot.present_observations:
        return _evaluated(snapshot, config_version_identifier, constants)
    return _not_evaluable(snapshot, config_version_identifier)


def _evaluated(
    snapshot: InputSnapshot,
    config_version_identifier: str,
    constants: _StubProfileConstants,
) -> EvaluatedGradeResult:
    component_scores = tuple(
        ComponentScore(
            component_id=observation.component_id,
            measurement_id=observation.measurement_id,
            points_awarded=constants.component_points,
            bucket_hit=None,
        )
        for observation in snapshot.present_observations
    )
    # One synthetic category holding every component score: the stub proves the
    # record shape, not any component-to-category mapping (that is Sprint-2
    # configuration). The category points are a fixed constant, never a sum.
    category_scores = (
        CategoryScore(
            category=constants.category,
            points_awarded=constants.category_points,
            component_scores=component_scores,
        ),
    )
    # Exactly one advisory warning per distinct insufficient *component*, in
    # deterministic first-occurrence order: the frozen GradeResult contract
    # requires one SAMPLE_WARNINGS finding per component, and a coherent
    # snapshot may hold two insufficient attack_angle_quality observations
    # (one per measurement) that must collapse to a single warning.
    insufficient_components: list[ComponentId] = []
    for observation in snapshot.present_observations:
        if (
            observation.sample_status is SampleStatus.INSUFFICIENT
            and observation.component_id not in insufficient_components
        ):
            insufficient_components.append(observation.component_id)
    validation_findings = tuple(
        ValidationFinding(
            input_id=ValidationInputId.SAMPLE_WARNINGS,
            message=(
                f"synthetic stub advisory: insufficient sample for component '{component.value}'"
            ),
            component_id=component,
        )
        for component in insufficient_components
    )
    audit_derivation = (
        AuditEntry(
            sequence=1,
            stage="stub_scoring",
            rule_reference=config_version_identifier,
            input_summary=(
                f"{len(snapshot.present_observations)} present observation(s) under profile "
                f"'{snapshot.window_profile.value}'"
            ),
            output_summary=(f"fixed synthetic points {constants.component_points} per component"),
            explanation=_STUB_EXPLANATION,
        ),
        AuditEntry(
            sequence=2,
            stage="stub_result",
            rule_reference=config_version_identifier,
            input_summary=f"fixed synthetic total {constants.total_score}",
            output_summary=(
                f"grade {constants.grade.value}, signal {constants.signal.value} "
                f"({constants.signal_reason})"
            ),
            explanation=_STUB_EXPLANATION,
        ),
    )
    return EvaluatedGradeResult(
        window_profile=snapshot.window_profile,
        present_observations=snapshot.present_observations,
        missing_observations=snapshot.missing_observations,
        validation_findings=validation_findings,
        audit_derivation=audit_derivation,
        component_scores=component_scores,
        category_scores=category_scores,
        total_score=constants.total_score,
        grade=constants.grade,
        signal=constants.signal,
        signal_reason=constants.signal_reason,
    )


def _not_evaluable(
    snapshot: InputSnapshot, config_version_identifier: str
) -> NotEvaluableGradeResult:
    if not snapshot.missing_observations:
        raise ValueError(
            "the stub scorer requires at least one observation on the snapshot; a snapshot "
            "with neither present nor missing observations is not a coherent golden fixture"
        )
    unavailable = tuple(
        UnavailableRequiredInput(
            component_id=observation.component_id,
            measurement_id=observation.measurement_id,
            missing_reason=observation.missing_reason,
            missing_observation=observation,
            attempted_methods=(),
        )
        for observation in snapshot.missing_observations
    )
    audit_derivation = (
        AuditEntry(
            sequence=1,
            stage="stub_evaluability_check",
            rule_reference=config_version_identifier,
            input_summary=(
                f"0 present and {len(snapshot.missing_observations)} missing observation(s) "
                f"under profile '{snapshot.window_profile.value}'"
            ),
            output_summary="NOT_EVALUABLE",
            explanation=_STUB_EXPLANATION,
        ),
    )
    return NotEvaluableGradeResult(
        window_profile=snapshot.window_profile,
        present_observations=snapshot.present_observations,
        missing_observations=snapshot.missing_observations,
        validation_findings=(),
        audit_derivation=audit_derivation,
        unavailable_required_inputs=unavailable,
    )

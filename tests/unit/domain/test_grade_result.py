"""GradeResult: two structural variants, purity, and the sample-warning rule."""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from decimal import Decimal

import pytest
import synthetic_records as sr

from greenmachine.domain import (
    ComponentId,
    ComponentScore,
    DomainValidationError,
    EvaluatedGradeResult,
    EvaluationStatus,
    GradeResult,
    MissingReason,
    SampleType,
    UnavailableRequiredInput,
    ValidationFinding,
    ValidationInputId,
    WindowProfile,
)

EVALUATED = sr.evaluated_grade_result()
NOT_EVAL = sr.not_evaluable_grade_result()

_EVALUATED_ONLY_FIELDS = (
    "component_scores",
    "category_scores",
    "total_score",
    "grade",
)
# Nothing that would make the result impure or hindsight-bearing (ADR-0004/0006).
_FORBIDDEN_FIELDS = (
    "evaluated_at",
    "as_of",
    "evaluation_id",
    "snapshot_id",
    "input_hash",
    "config_hash",
    "schema_version",
    "code_version",
    "outcome",
    "hit_at_least_one_home_run",
)


def test_the_variant_determines_the_status() -> None:
    assert EVALUATED.status is EvaluationStatus.EVALUATED
    assert NOT_EVAL.status is EvaluationStatus.NOT_EVALUABLE


def test_the_base_grade_result_is_abstract() -> None:
    with pytest.raises(DomainValidationError, match=r"abstract"):
        GradeResult(
            window_profile=WindowProfile.RECENT_7D,
            present_observations=(),
            missing_observations=(),
            validation_findings=(),
            audit_derivation=(),
        )


def test_an_evaluated_result_requires_every_evaluated_field() -> None:
    with pytest.raises(TypeError):
        EvaluatedGradeResult(  # type: ignore[call-arg]
            window_profile=WindowProfile.RECENT_7D,
            present_observations=(),
            missing_observations=(),
            validation_findings=(),
            audit_derivation=(),
        )


def test_a_not_evaluable_result_has_no_score_or_grade_fields() -> None:
    for field in _EVALUATED_ONLY_FIELDS:
        assert not hasattr(NOT_EVAL, field), f"NotEvaluable must not carry {field}"


def test_a_not_evaluable_result_requires_at_least_one_unavailable_input() -> None:
    with pytest.raises(DomainValidationError, match=r"unavailable"):
        dataclasses.replace(NOT_EVAL, unavailable_required_inputs=())


def test_a_float_total_score_is_rejected() -> None:
    with pytest.raises(DomainValidationError):
        dataclasses.replace(EVALUATED, total_score=2.2)  # type: ignore[arg-type]


def test_an_insufficient_observation_requires_a_sample_warning() -> None:
    without_warning = tuple(
        finding
        for finding in EVALUATED.validation_findings
        if finding.input_id is not ValidationInputId.SAMPLE_WARNINGS
    )
    with pytest.raises(DomainValidationError, match=r"SAMPLE_WARNINGS"):
        dataclasses.replace(EVALUATED, validation_findings=without_warning)


def test_a_duplicate_sample_warning_is_rejected() -> None:
    warning = next(
        finding
        for finding in EVALUATED.validation_findings
        if finding.input_id is ValidationInputId.SAMPLE_WARNINGS
    )
    with pytest.raises(DomainValidationError, match=r"duplicate"):
        dataclasses.replace(
            EVALUATED, validation_findings=(*EVALUATED.validation_findings, warning)
        )


def test_a_sample_warning_for_a_sufficient_component_is_rejected() -> None:
    spurious = ValidationFinding(
        input_id=ValidationInputId.SAMPLE_WARNINGS,
        message="exit_velocity was not insufficient",
        component_id=ComponentId.EXIT_VELOCITY,
    )
    with pytest.raises(DomainValidationError, match=r"no insufficient"):
        dataclasses.replace(
            EVALUATED, validation_findings=(*EVALUATED.validation_findings, spurious)
        )


def test_a_sample_warning_without_a_component_is_rejected() -> None:
    anonymous = ValidationFinding(
        input_id=ValidationInputId.SAMPLE_WARNINGS, message="which component?"
    )
    with pytest.raises(DomainValidationError, match=r"must reference"):
        dataclasses.replace(EVALUATED, validation_findings=(anonymous,))


def test_a_profile_mismatch_between_result_and_observations_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"profile"):
        dataclasses.replace(EVALUATED, window_profile=WindowProfile.LONG_TERM_2Y)


def test_out_of_order_audit_entries_are_rejected() -> None:
    reversed_audit = tuple(reversed(EVALUATED.audit_derivation))
    with pytest.raises(DomainValidationError, match=r"strictly increase"):
        dataclasses.replace(EVALUATED, audit_derivation=reversed_audit)


@pytest.mark.parametrize("field", _FORBIDDEN_FIELDS)
def test_a_grade_result_carries_no_time_identity_version_hash_or_outcome(field: str) -> None:
    assert not hasattr(EVALUATED, field)
    assert not hasattr(NOT_EVAL, field)


# --------------------------------------------------------------------------
# r1 §3: score / observation coherence on the evaluated variant
# --------------------------------------------------------------------------


def test_a_coherent_evaluated_result_remains_valid() -> None:
    assert sr.evaluated_grade_result() == EVALUATED


def test_a_score_for_an_unobserved_component_is_rejected() -> None:
    park_score = ComponentScore(
        component_id=ComponentId.PARK, measurement_id=None, points_awarded=Decimal("0.1")
    )
    with pytest.raises(DomainValidationError, match=r"no present or missing observation"):
        dataclasses.replace(EVALUATED, component_scores=(*EVALUATED.component_scores, park_score))


def test_a_duplicate_component_inside_one_category_is_rejected() -> None:
    power, environment = EVALUATED.category_scores
    weather = environment.component_scores[0]
    doubled = dataclasses.replace(environment, component_scores=(weather, weather))
    with pytest.raises(DomainValidationError, match=r"category_scores\[1\].*duplicate"):
        dataclasses.replace(EVALUATED, category_scores=(power, doubled))


def test_a_component_repeated_across_two_categories_is_rejected() -> None:
    power, environment = EVALUATED.category_scores
    weather = environment.component_scores[0]
    power_with_weather = dataclasses.replace(
        power, component_scores=(*power.component_scores, weather)
    )
    with pytest.raises(DomainValidationError, match=r"more than one category"):
        dataclasses.replace(EVALUATED, category_scores=(power_with_weather, environment))


def test_a_category_copy_differing_from_the_top_level_score_is_rejected() -> None:
    power, environment = EVALUATED.category_scores
    drifted_weather = dataclasses.replace(
        environment.component_scores[0], points_awarded=Decimal("0.7")
    )
    drifted = dataclasses.replace(environment, component_scores=(drifted_weather,))
    with pytest.raises(DomainValidationError, match=r"differs from the top-level"):
        dataclasses.replace(EVALUATED, category_scores=(power, drifted))


def test_a_category_component_absent_from_the_top_level_is_rejected() -> None:
    power, environment = EVALUATED.category_scores
    park_score = ComponentScore(
        component_id=ComponentId.PARK, measurement_id=None, points_awarded=Decimal("0.1")
    )
    smuggled = dataclasses.replace(
        environment, component_scores=(*environment.component_scores, park_score)
    )
    with pytest.raises(DomainValidationError, match=r"not among the top-level"):
        dataclasses.replace(EVALUATED, category_scores=(power, smuggled))


def test_a_top_level_score_omitted_from_every_category_is_rejected() -> None:
    # Drop the environment category entirely: its weather score stays top-level
    # but is now placed in no category. (An *emptied* category is itself
    # rejected earlier by the r2 nonempty rule, tested separately below.)
    power, _environment = EVALUATED.category_scores
    with pytest.raises(DomainValidationError, match=r"missing from every category"):
        dataclasses.replace(EVALUATED, category_scores=(power,))


# --------------------------------------------------------------------------
# r1 §4: required-input coherence on the not-evaluable variant
# --------------------------------------------------------------------------


def test_an_unavailable_record_for_an_unrelated_component_is_rejected() -> None:
    park_missing = sr.missing_observation(
        ComponentId.PARK, MissingReason.SOURCE_UNAVAILABLE, SampleType.GAMES
    )
    unrelated = UnavailableRequiredInput(
        component_id=ComponentId.PARK,
        measurement_id=None,
        missing_reason=MissingReason.SOURCE_UNAVAILABLE,
        missing_observation=park_missing,
        attempted_methods=(),
    )
    with pytest.raises(DomainValidationError, match=r"not among the result's missing"):
        dataclasses.replace(
            NOT_EVAL,
            unavailable_required_inputs=(*NOT_EVAL.unavailable_required_inputs, unrelated),
        )


def test_an_unavailable_record_with_a_different_observation_context_is_rejected() -> None:
    original = NOT_EVAL.unavailable_required_inputs[0]
    drifted_observation = dataclasses.replace(
        original.missing_observation, window_start=sr.WINDOW_START - timedelta(days=1)
    )
    drifted = dataclasses.replace(original, missing_observation=drifted_observation)
    with pytest.raises(DomainValidationError, match=r"not among the result's missing"):
        dataclasses.replace(NOT_EVAL, unavailable_required_inputs=(drifted,))


def test_a_duplicate_unavailable_required_input_key_is_rejected() -> None:
    original = NOT_EVAL.unavailable_required_inputs[0]
    twin = dataclasses.replace(original, attempted_methods=())
    with pytest.raises(DomainValidationError, match=r"duplicate"):
        dataclasses.replace(NOT_EVAL, unavailable_required_inputs=(original, twin))


def test_a_valid_subset_of_missing_observations_is_accepted() -> None:
    """An optional missing component need not make the evaluation not-evaluable."""
    extra_missing = sr.missing_bat_speed()
    subset = dataclasses.replace(
        NOT_EVAL,
        missing_observations=(*NOT_EVAL.missing_observations, extra_missing),
    )

    assert len(subset.missing_observations) == 2
    assert len(subset.unavailable_required_inputs) == 1


# --------------------------------------------------------------------------
# r2 §1: an evaluated grade cannot be structurally empty
# --------------------------------------------------------------------------


def test_empty_top_level_component_scores_are_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"component_scores must contain at least one"):
        dataclasses.replace(EVALUATED, component_scores=())


def test_empty_category_scores_are_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"category_scores must contain at least one"):
        dataclasses.replace(EVALUATED, category_scores=())


def test_both_empty_score_collections_are_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"must contain at least one"):
        dataclasses.replace(EVALUATED, component_scores=(), category_scores=())


def test_a_category_with_empty_component_scores_is_rejected() -> None:
    power, environment = EVALUATED.category_scores
    emptied = dataclasses.replace(environment, component_scores=())
    with pytest.raises(
        DomainValidationError,
        match=r"category_scores\[1\]\.component_scores must contain at least one",
    ):
        dataclasses.replace(EVALUATED, category_scores=(power, emptied))


def test_the_coherent_evaluated_fixture_remains_accepted() -> None:
    rebuilt = sr.evaluated_grade_result()
    assert rebuilt == EVALUATED
    assert len(rebuilt.component_scores) == 3
    assert all(category.component_scores for category in rebuilt.category_scores)


# --------------------------------------------------------------------------
# r2 §2: the audit derivation cannot be empty
# --------------------------------------------------------------------------


def test_an_evaluated_result_with_an_empty_audit_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"audit_derivation must contain at least one"):
        dataclasses.replace(EVALUATED, audit_derivation=())


def test_a_not_evaluable_result_with_an_empty_audit_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"audit_derivation must contain at least one"):
        dataclasses.replace(NOT_EVAL, audit_derivation=())


def test_a_single_entry_audit_is_accepted() -> None:
    single = dataclasses.replace(EVALUATED, audit_derivation=EVALUATED.audit_derivation[:1])
    assert len(single.audit_derivation) == 1


def test_the_existing_multi_entry_audit_remains_accepted() -> None:
    assert len(EVALUATED.audit_derivation) == 2

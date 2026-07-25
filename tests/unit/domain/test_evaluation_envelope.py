"""EvaluationEnvelope: supplied time, validated metadata, no clock, no outcome."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest
import synthetic_records as sr

from greenmachine.common.clock import FixedClock
from greenmachine.domain import (
    DomainValidationError,
    EvaluatedGradeResult,
    EvaluationId,
    ProvenanceEntry,
    SourceCaptureId,
    WindowProfile,
)
from greenmachine.evaluation import serialize_record

ENVELOPE = sr.evaluation_envelope()


def test_the_supplied_utc_evaluated_at_is_preserved_exactly() -> None:
    assert ENVELOPE.evaluated_at == sr.EVALUATED_AT
    assert ENVELOPE.evaluated_at.utcoffset() == timedelta(0)


def test_a_naive_evaluated_at_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"aware"):
        dataclasses.replace(ENVELOPE, evaluated_at=datetime(2026, 7, 15, 22, 5))


def test_a_non_utc_evaluated_at_is_rejected() -> None:
    eastern = sr.EVALUATED_AT.astimezone(timezone(timedelta(hours=-4)))
    with pytest.raises(DomainValidationError, match=r"UTC"):
        dataclasses.replace(ENVELOPE, evaluated_at=eastern)


def test_a_fixed_clock_produces_repeatable_envelope_bytes() -> None:
    """With the injected instant held constant, the envelope is byte-identical."""
    clock = FixedClock(sr.EVALUATED_AT)
    first = dataclasses.replace(ENVELOPE, evaluated_at=clock.now())
    second = dataclasses.replace(ENVELOPE, evaluated_at=clock.now())

    assert serialize_record(first) == serialize_record(second)


def test_a_different_evaluated_at_changes_the_envelope_bytes() -> None:
    later = dataclasses.replace(ENVELOPE, evaluated_at=sr.EVALUATED_AT + timedelta(minutes=1))
    assert serialize_record(later) != serialize_record(ENVELOPE)


def test_a_profile_mismatch_with_the_grade_result_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"window_profile"):
        dataclasses.replace(ENVELOPE, window_profile=WindowProfile.LONG_TERM_2Y)


def test_self_supersession_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"supersede itself"):
        dataclasses.replace(ENVELOPE, supersedes=ENVELOPE.evaluation_id)


def test_supersession_of_another_evaluation_is_allowed() -> None:
    superseding = dataclasses.replace(ENVELOPE, supersedes=EvaluationId("SYNTHETIC-EVAL-0000"))
    assert superseding.supersedes == EvaluationId("SYNTHETIC-EVAL-0000")


@pytest.mark.parametrize("bad", [True, False, 0, -1, "1"])
def test_schema_version_must_be_a_strict_positive_int(bad: object) -> None:
    with pytest.raises(DomainValidationError):
        dataclasses.replace(ENVELOPE, schema_version=bad)  # type: ignore[arg-type]


def test_slate_date_must_be_a_date_not_a_datetime() -> None:
    with pytest.raises(DomainValidationError, match=r"not a datetime"):
        dataclasses.replace(ENVELOPE, slate_date=sr.SCHEDULED_START_UTC)


@pytest.mark.parametrize(
    "field",
    ["code_version", "model_configuration_version", "product_specification_version"],
)
def test_version_strings_must_be_nonblank(field: str) -> None:
    with pytest.raises(DomainValidationError):
        dataclasses.replace(ENVELOPE, **{field: "   "})


def test_a_raw_string_hash_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"Sha256Digest"):
        dataclasses.replace(ENVELOPE, config_hash="a" * 64)  # type: ignore[arg-type]


def test_provenance_naming_an_unobserved_component_is_rejected() -> None:
    stray = ProvenanceEntry(
        provider_id=sr.ProviderId.BASEBALL_SAVANT,
        acquisition_method=sr.AcquisitionMethod.DIRECT_AGGREGATE,
        source_as_of=sr.SOURCE_AS_OF,
        retrieved_at=sr.RETRIEVED_AT,
        component_id=sr.ComponentId.PARK,  # not observed on the result
    )
    with pytest.raises(DomainValidationError, match=r"no matching present observation"):
        dataclasses.replace(ENVELOPE, provenance=(*ENVELOPE.provenance, stray))


# --------------------------------------------------------------------------
# r1 §5: source-capture coherence
# --------------------------------------------------------------------------


def test_a_mismatched_envelope_source_capture_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"source_capture_id"):
        dataclasses.replace(ENVELOPE, source_capture_id=SourceCaptureId("ANOTHER-CAPTURE"))


def test_a_result_with_mixed_source_captures_is_rejected() -> None:
    result = sr.evaluated_grade_result()
    first, second, third = result.present_observations
    drifted = dataclasses.replace(second, source_capture_id=SourceCaptureId("DRIFTED-CAPTURE"))
    mixed = dataclasses.replace(result, present_observations=(first, drifted, third))

    with pytest.raises(DomainValidationError, match=r"source_capture_id"):
        dataclasses.replace(ENVELOPE, grade_result=mixed)


# --------------------------------------------------------------------------
# r1 §6: exact provenance coherence and evaluated_at bounds
# --------------------------------------------------------------------------


def _exit_entry(**overrides: object) -> ProvenanceEntry:
    """A provenance entry that exactly matches the exit-velocity observation."""
    values: dict[str, object] = {
        "provider_id": sr.ProviderId.BASEBALL_SAVANT,
        "acquisition_method": sr.AcquisitionMethod.DIRECT_AGGREGATE,
        "source_as_of": sr.SOURCE_AS_OF,
        "retrieved_at": sr.RETRIEVED_AT,
        "component_id": sr.ComponentId.EXIT_VELOCITY,
        "measurement_id": None,
    }
    values.update(overrides)
    return ProvenanceEntry(**values)  # type: ignore[arg-type]


def test_exactly_matching_provenance_is_accepted() -> None:
    accepted = dataclasses.replace(ENVELOPE, provenance=(_exit_entry(),))
    assert accepted.provenance[0].component_id is sr.ComponentId.EXIT_VELOCITY


def test_a_mismatched_provider_is_rejected() -> None:
    """ProviderId has one approved member, so a mismatch cannot be built through
    the public constructor; the field is forged post-construction (bypassing the
    frozen dataclass) purely to prove the guard fires when a second provider
    eventually lands."""
    from enum import Enum

    forged_provider = Enum("ForgedProviderId", {"OTHER": "other"})
    entry = _exit_entry()
    object.__setattr__(entry, "provider_id", forged_provider.OTHER)

    with pytest.raises(DomainValidationError, match=r"provider_id"):
        dataclasses.replace(ENVELOPE, provenance=(entry,))


def test_a_mismatched_acquisition_method_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"acquisition_method"):
        dataclasses.replace(
            ENVELOPE,
            provenance=(_exit_entry(acquisition_method=sr.AcquisitionMethod.STRUCTURED_EXTRACT),),
        )


def test_a_mismatched_source_as_of_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"source_as_of.*must equal"):
        dataclasses.replace(
            ENVELOPE,
            provenance=(_exit_entry(source_as_of=sr.SOURCE_AS_OF - timedelta(hours=1)),),
        )


def test_a_mismatched_retrieved_at_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"retrieved_at.*must equal"):
        dataclasses.replace(
            ENVELOPE,
            provenance=(_exit_entry(retrieved_at=sr.RETRIEVED_AT - timedelta(minutes=5)),),
        )


def test_provenance_for_a_missing_only_component_is_rejected() -> None:
    """A missing observation has no selected method, only MethodIneligibility."""
    with pytest.raises(DomainValidationError, match=r"no matching present observation"):
        dataclasses.replace(
            ENVELOPE, provenance=(_exit_entry(component_id=sr.ComponentId.BAT_SPEED),)
        )


def test_duplicate_provenance_entries_are_rejected() -> None:
    entry = _exit_entry()
    with pytest.raises(DomainValidationError, match=r"duplicate"):
        dataclasses.replace(ENVELOPE, provenance=(entry, entry))


def test_an_evaluated_at_before_retrieval_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"retrieved_at.*must be <= evaluated_at"):
        dataclasses.replace(ENVELOPE, evaluated_at=sr.SOURCE_AS_OF)


def test_an_evaluated_at_before_the_observation_as_of_is_rejected() -> None:
    just_before_as_of = sr.AS_OF - timedelta(minutes=15)
    with pytest.raises(DomainValidationError, match=r"\]\.as_of.*must be <= evaluated_at"):
        dataclasses.replace(ENVELOPE, evaluated_at=just_before_as_of)


# --------------------------------------------------------------------------
# r1 §7: only the two approved result variants
# --------------------------------------------------------------------------


class _SyntheticThirdVariant(EvaluatedGradeResult):
    """A structurally valid but unapproved result subclass."""


def test_an_unapproved_grade_result_subclass_is_rejected() -> None:
    field_values = {
        field.name: getattr(ENVELOPE.grade_result, field.name)
        for field in dataclasses.fields(EvaluatedGradeResult)
    }
    third = _SyntheticThirdVariant(**field_values)

    with pytest.raises(DomainValidationError, match=r"exactly an EvaluatedGradeResult"):
        dataclasses.replace(ENVELOPE, grade_result=third)


def test_the_envelope_has_no_outcome_field_and_no_mutation() -> None:
    fields = {field.name for field in dataclasses.fields(ENVELOPE)}
    assert not (fields & {"outcome", "outcome_record", "hit_at_least_one_home_run"})
    with pytest.raises(dataclasses.FrozenInstanceError):
        ENVELOPE.code_version = "9.9.9"  # type: ignore[misc]


def test_evaluated_at_is_supplied_not_generated() -> None:
    """It is a required field with no default or factory, so nothing mints it.

    The architecture suite additionally proves the envelope module reads no clock.
    """
    fields = {field.name: field for field in dataclasses.fields(ENVELOPE)}
    evaluated_at = fields["evaluated_at"]

    assert evaluated_at.default is dataclasses.MISSING
    assert evaluated_at.default_factory is dataclasses.MISSING

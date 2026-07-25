"""Canonical record serialization: lossless round-trips, loud on anything wrong."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
import synthetic_records as sr

from greenmachine.domain import (
    EvaluatedGradeResult,
    EvaluationEnvelope,
    InputSnapshot,
    NotEvaluableGradeResult,
    OutcomeRecord,
    Sha256Digest,
)
from greenmachine.evaluation import (
    EvaluationSerializationError,
    Record,
    RecordIntegrityError,
    UnsupportedRecordSchemaVersionError,
    deserialize_envelope,
    deserialize_record,
    deserialize_snapshot,
    serialize_record,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "evaluations"

BUILDERS = {
    "input_snapshot": sr.input_snapshot,
    "evaluated_grade_result": sr.evaluated_grade_result,
    "not_evaluable_grade_result": sr.not_evaluable_grade_result,
    "evaluation_envelope": sr.evaluation_envelope,
    "outcome_record": sr.outcome_record,
}
CLASSES = {
    "input_snapshot": InputSnapshot,
    "evaluated_grade_result": EvaluatedGradeResult,
    "not_evaluable_grade_result": NotEvaluableGradeResult,
    "evaluation_envelope": EvaluationEnvelope,
    "outcome_record": OutcomeRecord,
}


def _records() -> list[Record]:
    return [builder() for builder in BUILDERS.values()]


def _wrapper(record: Record) -> dict[str, object]:
    return json.loads(serialize_record(record))


def _bytes(wrapper: dict[str, object]) -> bytes:
    return json.dumps(wrapper).encode("utf-8")


# --------------------------------------------------------------------------
# Round-trip and stability
# --------------------------------------------------------------------------


@pytest.mark.parametrize("record", _records(), ids=list(BUILDERS))
def test_every_record_round_trips_exactly(record: Record) -> None:
    assert deserialize_record(serialize_record(record)) == record


@pytest.mark.parametrize("record", _records(), ids=list(BUILDERS))
def test_serialization_is_byte_stable(record: Record) -> None:
    assert serialize_record(record) == serialize_record(record)


def test_equal_results_produce_identical_bytes() -> None:
    assert serialize_record(sr.evaluated_grade_result()) == serialize_record(
        sr.evaluated_grade_result()
    )


@pytest.mark.parametrize("name", list(BUILDERS), ids=list(BUILDERS))
def test_a_hand_authored_fixture_produces_the_expected_object(name: str) -> None:
    data = (FIXTURES / f"{name}.json").read_bytes()

    record = deserialize_record(data)

    assert isinstance(record, CLASSES[name])
    assert record == BUILDERS[name]()


# --------------------------------------------------------------------------
# Loud failures
# --------------------------------------------------------------------------


def test_an_unknown_schema_version_is_rejected() -> None:
    wrapper = _wrapper(sr.outcome_record())
    wrapper["schema_version"] = 2
    with pytest.raises(UnsupportedRecordSchemaVersionError) as caught:
        deserialize_record(_bytes(wrapper))
    assert "outcome_record" in str(caught.value)
    assert "2" in str(caught.value)


def test_an_unknown_record_type_is_rejected() -> None:
    wrapper = _wrapper(sr.outcome_record())
    wrapper["record_type"] = "mystery_record"
    with pytest.raises(EvaluationSerializationError, match=r"unknown record type"):
        deserialize_record(_bytes(wrapper))


def test_an_unknown_field_is_rejected() -> None:
    wrapper = _wrapper(sr.outcome_record())
    payload = wrapper["payload"]
    assert isinstance(payload, dict)
    payload["surprise"] = 1
    with pytest.raises(EvaluationSerializationError, match=r"unknown field"):
        deserialize_record(_bytes(wrapper))


def test_a_missing_field_is_rejected() -> None:
    wrapper = _wrapper(sr.outcome_record())
    payload = wrapper["payload"]
    assert isinstance(payload, dict)
    del payload["game_id"]
    with pytest.raises(EvaluationSerializationError, match=r"missing required field"):
        deserialize_record(_bytes(wrapper))


def test_malformed_json_is_translated() -> None:
    with pytest.raises(EvaluationSerializationError, match=r"valid JSON"):
        deserialize_record(b"{ not json ]")


def test_non_bytes_input_is_rejected() -> None:
    with pytest.raises(EvaluationSerializationError, match=r"must be bytes"):
        deserialize_record("a string")  # type: ignore[arg-type]


def test_a_float_is_refused_during_decoding() -> None:
    wrapper = _wrapper(sr.evaluated_grade_result())
    payload = wrapper["payload"]
    assert isinstance(payload, dict)
    payload["total_score"] = 2.2  # a JSON float where a Decimal string belongs
    with pytest.raises(EvaluationSerializationError, match=r"floating-point"):
        deserialize_record(_bytes(wrapper))


def test_any_float_anywhere_is_refused() -> None:
    wrapper = _wrapper(sr.outcome_record())
    wrapper["schema_version"] = 1.0
    with pytest.raises(EvaluationSerializationError, match=r"floating-point"):
        deserialize_record(_bytes(wrapper))


def test_an_int_for_a_bool_is_rejected() -> None:
    wrapper = _wrapper(sr.outcome_record())
    payload = wrapper["payload"]
    assert isinstance(payload, dict)
    payload["hit_at_least_one_home_run"] = 1
    with pytest.raises(EvaluationSerializationError, match=r"boolean"):
        deserialize_record(_bytes(wrapper))


def test_a_stored_snapshot_hash_mismatch_is_rejected() -> None:
    wrapper = _wrapper(sr.input_snapshot())
    payload = wrapper["payload"]
    assert isinstance(payload, dict)
    payload["input_hash"] = {"value": "b" * 64}
    with pytest.raises(RecordIntegrityError, match=r"input_hash"):
        deserialize_record(_bytes(wrapper))


def test_a_stored_snapshot_id_mismatch_is_rejected() -> None:
    wrapper = _wrapper(sr.input_snapshot())
    payload = wrapper["payload"]
    assert isinstance(payload, dict)
    payload["snapshot_id"] = {"value": "TAMPERED-SNAPSHOT-ID"}
    with pytest.raises(RecordIntegrityError, match=r"snapshot_id"):
        deserialize_record(_bytes(wrapper))


def test_an_envelope_wrapper_schema_mismatch_is_rejected() -> None:
    wrapper = _wrapper(sr.evaluation_envelope())
    payload = wrapper["payload"]
    assert isinstance(payload, dict)
    # The wrapper stays at the supported version 1; only the embedded one differs.
    assert wrapper["schema_version"] == 1
    payload["schema_version"] = 7
    with pytest.raises(RecordIntegrityError, match=r"schema_version"):
        deserialize_record(_bytes(wrapper))


def test_the_typed_deserializers_reject_the_wrong_record_type() -> None:
    outcome_bytes = serialize_record(sr.outcome_record())
    with pytest.raises(EvaluationSerializationError, match=r"expected"):
        deserialize_snapshot(outcome_bytes)
    with pytest.raises(EvaluationSerializationError, match=r"expected"):
        deserialize_envelope(outcome_bytes)


def test_serializing_a_non_record_is_rejected() -> None:
    with pytest.raises(EvaluationSerializationError, match=r"cannot serialize"):
        serialize_record(object())  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# r1 §2: the serializer verifies snapshot identity before writing bytes
# --------------------------------------------------------------------------


def test_the_serializer_rejects_a_tampered_snapshot() -> None:
    tampered = sr.rebuild_snapshot(sr.input_snapshot(), input_hash=Sha256Digest("b" * 64))
    with pytest.raises(RecordIntegrityError, match=r"input_hash"):
        serialize_record(tampered)


def test_a_factory_snapshot_still_serializes_and_decodes() -> None:
    snapshot = sr.input_snapshot()
    assert deserialize_snapshot(serialize_record(snapshot)) == snapshot


# --------------------------------------------------------------------------
# r1 §7: only the two approved result variants serialize
# --------------------------------------------------------------------------


class _SyntheticThirdVariant(EvaluatedGradeResult):
    """A structurally valid but unapproved result subclass."""


def test_an_unapproved_result_subclass_cannot_be_serialized() -> None:
    field_values = {
        field.name: getattr(sr.evaluated_grade_result(), field.name)
        for field in dataclasses.fields(EvaluatedGradeResult)
    }
    third = _SyntheticThirdVariant(**field_values)

    with pytest.raises(EvaluationSerializationError, match=r"cannot serialize"):
        serialize_record(third)


# --------------------------------------------------------------------------
# r1 §8: an unsupported schema version is refused at write time
# --------------------------------------------------------------------------


def test_an_unsupported_envelope_schema_version_is_not_serialized() -> None:
    stale = dataclasses.replace(sr.evaluation_envelope(), schema_version=99)

    with pytest.raises(UnsupportedRecordSchemaVersionError) as caught:
        serialize_record(stale)

    message = str(caught.value)
    assert "evaluation_envelope" in message
    assert "99" in message
    assert "[1]" in message  # the supported versions are named


def test_a_supported_envelope_still_serializes() -> None:
    envelope = sr.evaluation_envelope()
    assert deserialize_envelope(serialize_record(envelope)) == envelope

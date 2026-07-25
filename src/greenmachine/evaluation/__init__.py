"""Orchestration boundary: content-derived identity and record serialization.

This layer sits above ``domain`` and reuses ``common`` determinism primitives; it
never imports ``config`` or the grading core. GM-006 populates it with the
domain/evaluation boundary that gives an :class:`~greenmachine.domain.InputSnapshot`
its content-derived identity, and with the lossless canonical serialization of
every GM-006 record. Supplying ``evaluated_at`` from an injected clock, and
composing configuration and the grading core into an envelope, arrive with later
tickets.
"""

from __future__ import annotations

from .errors import (
    EvaluationError,
    EvaluationSerializationError,
    RecordIntegrityError,
    UnsupportedRecordSchemaVersionError,
)
from .serialization import (
    RECORD_SCHEMA_VERSION,
    Record,
    deserialize_envelope,
    deserialize_evaluated_result,
    deserialize_not_evaluable_result,
    deserialize_outcome,
    deserialize_record,
    deserialize_snapshot,
    freeze_input_snapshot,
    serialize_record,
    verify_snapshot_identity,
)

__all__ = [
    "RECORD_SCHEMA_VERSION",
    "EvaluationError",
    "EvaluationSerializationError",
    "Record",
    "RecordIntegrityError",
    "UnsupportedRecordSchemaVersionError",
    "deserialize_envelope",
    "deserialize_evaluated_result",
    "deserialize_not_evaluable_result",
    "deserialize_outcome",
    "deserialize_record",
    "deserialize_snapshot",
    "freeze_input_snapshot",
    "serialize_record",
    "verify_snapshot_identity",
]

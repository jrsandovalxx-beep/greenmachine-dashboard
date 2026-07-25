"""Typed failures for the evaluation layer's record serialization and integrity.

Rooted at :class:`~greenmachine.common.errors.GreenMachineError` (ADR-0007) via
:class:`EvaluationError`, so a caller may catch the whole family and be certain no
raw ``KeyError``, ``TypeError``, ``ValueError``, ``JSONDecodeError``, or Decimal
error escapes a public deserialize operation.

Two distinct failure modes:

* :class:`EvaluationSerializationError` — the bytes could not be decoded into the
  record they claim to be: malformed JSON, an unknown record type, an unknown or
  missing field, a wrong runtime type, or (its subclass
  :class:`UnsupportedRecordSchemaVersionError`) a schema version this build does
  not support.
* :class:`RecordIntegrityError` — the record decoded cleanly but is internally
  inconsistent: a stored snapshot whose recomputed identity does not match, or an
  envelope whose wrapper and embedded schema versions disagree.
"""

from __future__ import annotations

from greenmachine.common.errors import GreenMachineError

__all__ = [
    "EvaluationError",
    "EvaluationSerializationError",
    "RecordIntegrityError",
    "UnsupportedRecordSchemaVersionError",
]


class EvaluationError(GreenMachineError):
    """Root of every error the evaluation layer raises deliberately."""


class EvaluationSerializationError(EvaluationError):
    """A stored record could not be serialized to or decoded from canonical bytes.

    Raised for malformed JSON, an unknown record type, an unknown or missing
    field, a wrong runtime type, or a floating-point number where an exact Decimal
    string belongs. The original parse failure is preserved as ``__cause__``.
    """


class UnsupportedRecordSchemaVersionError(EvaluationSerializationError):
    """A record declares a schema version this build does not support.

    Carries the record type, the observed version, and the supported versions, so
    an unknown or newer version fails loudly rather than being read as the current
    one.
    """


class RecordIntegrityError(EvaluationError):
    """A record decoded cleanly but is internally inconsistent.

    A stored snapshot whose recomputed ``input_hash`` or ``snapshot_id`` does not
    match what it carries, or an envelope whose wrapper schema version disagrees
    with the embedded one. The record is never silently repaired.
    """

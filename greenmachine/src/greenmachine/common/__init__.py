"""Shared determinism primitives: numeric policy, clock port, canonical bytes, ids.

Standard library only. No I/O, no environment, no randomness, no third-party
dependency, and no import of any other GreenMachine package — these primitives sit
underneath everything else, so anything they depended on would become a dependency
of the whole system.

Delivered by GM-005 (ADR-0002, ``MODEL_SPEC.md`` §4) and GM-009 (ADR-0007). The
error taxonomy rooted at :class:`GreenMachineError` and the structured logging
baseline live here; every determinism primitive's error now sits under that root.

``logging`` is deliberately **not** re-exported: it is imported explicitly by the
composition root, so nothing acquires a logging dependency by importing this
package.
"""

from __future__ import annotations

from .clock import Clock, ClockError, FixedClock, SystemClock
from .errors import (
    ConfigurationError,
    DataInputError,
    DomainInvariantError,
    ErrorContext,
    GreenMachineError,
    IngestionError,
    PersistenceError,
    ProviderSchemaChangeError,
)
from .ids import DIGEST_ALGORITHM, IdentifierError, content_digest, deterministic_id
from .numeric import (
    PRECISION,
    ROUNDING,
    NumericPolicyError,
    add,
    decimal_from,
    divide,
    in_inclusive_range,
    in_scoring_interval,
    multiply,
    numeric_context,
    percentage,
    project_context,
    resolve_scoring_interval,
    subtract,
)
from .serialization import (
    CanonicalizationError,
    canonical_bytes,
    canonical_decimal,
    canonical_json,
    parse_canonical_decimal,
)

__all__ = [
    "DIGEST_ALGORITHM",
    "PRECISION",
    "ROUNDING",
    "CanonicalizationError",
    "Clock",
    "ClockError",
    "ConfigurationError",
    "DataInputError",
    "DomainInvariantError",
    "ErrorContext",
    "FixedClock",
    "GreenMachineError",
    "IdentifierError",
    "IngestionError",
    "NumericPolicyError",
    "PersistenceError",
    "ProviderSchemaChangeError",
    "SystemClock",
    "add",
    "canonical_bytes",
    "canonical_decimal",
    "canonical_json",
    "content_digest",
    "decimal_from",
    "deterministic_id",
    "divide",
    "in_inclusive_range",
    "in_scoring_interval",
    "multiply",
    "numeric_context",
    "parse_canonical_decimal",
    "percentage",
    "project_context",
    "resolve_scoring_interval",
    "subtract",
]

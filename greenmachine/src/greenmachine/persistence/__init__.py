"""Persistence: append-only repository ports and deterministic adapters.

ARCHITECTURE §4.8 — storage interfaces make history replacement impossible.
Three completely separate repositories (input snapshots, evaluation envelopes,
outcome revisions) expose exactly ``append``, ``get``, and ``query``; nothing
can update, delete, or overwrite a stored record, and every correction is a new
record linked through ``supersedes``.

Outcome corrections follow the frozen Product Owner ruling: the minimal domain
:class:`~greenmachine.domain.OutcomeRecord` is untouched, and history lives in
the persistence-only :class:`OutcomeRevision` wrapper with its content-derived
:class:`OutcomeRevisionId` (ADR-0006).

GM-007 delivers the ports, the in-memory reference adapters, and the reusable
repository contract suite. Durable storage arrives with a later ticket.
"""

from __future__ import annotations

from .errors import (
    BranchingSupersessionError,
    ConflictingRecordError,
    DuplicateRecordError,
    InvalidSupersessionError,
    MalformedOutcomeRevisionIdError,
    MalformedRepositoryInputError,
    MissingSupersededParentError,
    OutcomeRevisionIdentityError,
    SupersessionError,
)
from .in_memory import (
    InMemoryEvaluationRepository,
    InMemoryOutcomeRepository,
    InMemorySnapshotRepository,
)
from .ports import (
    EvaluationQuery,
    EvaluationRepository,
    OutcomeQuery,
    OutcomeRepository,
    OutcomeRevision,
    OutcomeRevisionId,
    SnapshotQuery,
    SnapshotRepository,
    create_outcome_revision,
)

__all__ = [
    "BranchingSupersessionError",
    "ConflictingRecordError",
    "DuplicateRecordError",
    "EvaluationQuery",
    "EvaluationRepository",
    "InMemoryEvaluationRepository",
    "InMemoryOutcomeRepository",
    "InMemorySnapshotRepository",
    "InvalidSupersessionError",
    "MalformedOutcomeRevisionIdError",
    "MalformedRepositoryInputError",
    "MissingSupersededParentError",
    "OutcomeQuery",
    "OutcomeRepository",
    "OutcomeRevision",
    "OutcomeRevisionId",
    "OutcomeRevisionIdentityError",
    "SnapshotQuery",
    "SnapshotRepository",
    "SupersessionError",
    "create_outcome_revision",
]

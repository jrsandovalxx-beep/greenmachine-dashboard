"""Deterministic in-memory adapters for the three append-only repositories.

Reference implementations of the ports — instance-local, with no module-level
singleton, no environment read, no filesystem, no database, no clock, and no
randomness. Each adapter necessarily mutates internally by appending, but it
exposes no operation capable of changing or removing a record already stored:
``append`` refuses an existing identity, ``get`` and ``query`` only read, and
the backing collections are never exposed.

Query results are explicitly sorted by documented stable keys ending in the
record's unique identity, so the order never depends on insertion order,
dictionary order, or ``PYTHONHASHSEED``. Outcome ordering uses the supersession
*depth derived from the stored chain* — root first — never append order.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from greenmachine.domain import (
    EvaluationEnvelope,
    EvaluationId,
    InputSnapshot,
    OutcomeRecord,
    SnapshotId,
)

from .errors import (
    BranchingSupersessionError,
    ConflictingRecordError,
    DuplicateRecordError,
    InvalidSupersessionError,
    MalformedRepositoryInputError,
    MissingSupersededParentError,
    context_for,
)
from .ports import (
    EvaluationQuery,
    OutcomeQuery,
    OutcomeRevision,
    OutcomeRevisionId,
    SnapshotQuery,
)

if TYPE_CHECKING:
    from .ports import EvaluationRepository, OutcomeRepository, SnapshotRepository

__all__ = [
    "InMemoryEvaluationRepository",
    "InMemoryOutcomeRepository",
    "InMemorySnapshotRepository",
]


def _reject_input(
    message: str, *, expected: str, observed: object
) -> MalformedRepositoryInputError:
    return MalformedRepositoryInputError(
        message, context_for(expected=expected, observed=type(observed).__name__)
    )


def _check_new_identity(existing: object, incoming: object, identity: str, kind: str) -> None:
    """Refuse to store over an existing identity — loudly, never idempotently."""
    if existing is None:
        return
    if existing == incoming:
        raise DuplicateRecordError(
            f"{kind} {identity!r} is already stored; append-only history is never appended twice",
            context_for(subject=identity),
        )
    raise ConflictingRecordError(
        f"{kind} identity {identity!r} is already used by a different stored record",
        context_for(subject=identity),
    )


class InMemorySnapshotRepository:
    """Instance-local append-only store of frozen input snapshots."""

    def __init__(self) -> None:
        self._records: dict[SnapshotId, InputSnapshot] = {}

    def append(self, snapshot: InputSnapshot) -> None:
        if not isinstance(snapshot, InputSnapshot):
            raise _reject_input(
                f"SnapshotRepository.append stores an InputSnapshot, got {type(snapshot).__name__}",
                expected="InputSnapshot",
                observed=snapshot,
            )
        _check_new_identity(
            self._records.get(snapshot.snapshot_id),
            snapshot,
            snapshot.snapshot_id.value,
            "snapshot",
        )
        self._records[snapshot.snapshot_id] = snapshot

    def get(self, snapshot_id: SnapshotId) -> InputSnapshot | None:
        if not isinstance(snapshot_id, SnapshotId):
            raise _reject_input(
                f"SnapshotRepository.get takes a SnapshotId, got {type(snapshot_id).__name__}",
                expected="SnapshotId",
                observed=snapshot_id,
            )
        return self._records.get(snapshot_id)

    def query(self, query: SnapshotQuery) -> tuple[InputSnapshot, ...]:
        if not isinstance(query, SnapshotQuery):
            raise _reject_input(
                f"SnapshotRepository.query takes a SnapshotQuery, got {type(query).__name__}",
                expected="SnapshotQuery",
                observed=query,
            )
        matches = [s for s in self._records.values() if _snapshot_matches(s, query)]
        return tuple(sorted(matches, key=_snapshot_sort_key))


def _snapshot_matches(snapshot: InputSnapshot, query: SnapshotQuery) -> bool:
    if query.slate_date is not None and snapshot.game_context.slate_date != query.slate_date:
        return False
    if query.game_id is not None and snapshot.game_context.game_id != query.game_id:
        return False
    if query.batter_id is not None and snapshot.batter.player_id != query.batter_id:
        return False
    if (
        query.expected_starting_pitcher_id is not None
        and snapshot.expected_starting_pitcher.player_id != query.expected_starting_pitcher_id
    ):
        return False
    if query.window_profile is not None and snapshot.window_profile is not query.window_profile:
        return False
    return not (
        query.source_capture_id is not None
        and snapshot.source_capture_id != query.source_capture_id
    )


def _snapshot_sort_key(snapshot: InputSnapshot) -> tuple[date, str, str, str, str, str]:
    """Documented stable order; ``snapshot_id`` is the final unique tie-breaker."""
    return (
        snapshot.game_context.slate_date,
        snapshot.game_context.game_id.value,
        snapshot.batter.player_id.value,
        snapshot.expected_starting_pitcher.player_id.value,
        snapshot.window_profile.value,
        snapshot.snapshot_id.value,
    )


class InMemoryEvaluationRepository:
    """Instance-local append-only store of envelopes with linear supersession."""

    def __init__(self) -> None:
        self._records: dict[EvaluationId, EvaluationEnvelope] = {}
        # parent id -> the single direct child that superseded it.
        self._superseded_by: dict[EvaluationId, EvaluationId] = {}

    def append(self, envelope: EvaluationEnvelope) -> None:
        if not isinstance(envelope, EvaluationEnvelope):
            raise _reject_input(
                f"EvaluationRepository.append stores an EvaluationEnvelope, got "
                f"{type(envelope).__name__}",
                expected="EvaluationEnvelope",
                observed=envelope,
            )
        _check_new_identity(
            self._records.get(envelope.evaluation_id),
            envelope,
            envelope.evaluation_id.value,
            "evaluation",
        )
        supersedes = envelope.supersedes
        if supersedes is not None:
            # Requiring the parent to preexist also makes cycles impossible.
            parent = self._records.get(supersedes)
            if parent is None:
                raise MissingSupersededParentError(
                    f"evaluation {envelope.evaluation_id.value!r} supersedes "
                    f"{supersedes.value!r}, which is not stored",
                    context_for(subject=envelope.evaluation_id.value, observed=supersedes.value),
                )
            # A correction corrects the same evaluation unit: one game, one
            # batter, one window profile (Q2/ADR-0005). The pitcher, snapshot,
            # capture, versions, hashes, slate_date, and result may all
            # legitimately change in a corrected evaluation, so they are
            # deliberately not compared.
            if parent.game_id != envelope.game_id:
                raise InvalidSupersessionError(
                    f"an evaluation correction must concern the same game: parent has "
                    f"{parent.game_id.value!r}, child {envelope.evaluation_id.value!r} has "
                    f"{envelope.game_id.value!r}",
                    context_for(
                        subject=envelope.evaluation_id.value,
                        expected=parent.game_id.value,
                        observed=envelope.game_id.value,
                    ),
                )
            if parent.batter_id != envelope.batter_id:
                raise InvalidSupersessionError(
                    f"an evaluation correction must concern the same batter: parent has "
                    f"{parent.batter_id.value!r}, child {envelope.evaluation_id.value!r} has "
                    f"{envelope.batter_id.value!r}",
                    context_for(
                        subject=envelope.evaluation_id.value,
                        expected=parent.batter_id.value,
                        observed=envelope.batter_id.value,
                    ),
                )
            if parent.window_profile is not envelope.window_profile:
                raise InvalidSupersessionError(
                    f"an evaluation correction must concern the same window profile: parent "
                    f"has {parent.window_profile.value!r}, child "
                    f"{envelope.evaluation_id.value!r} has "
                    f"{envelope.window_profile.value!r}",
                    context_for(
                        subject=envelope.evaluation_id.value,
                        expected=parent.window_profile.value,
                        observed=envelope.window_profile.value,
                        window_profile=envelope.window_profile.value,
                    ),
                )
            existing_child = self._superseded_by.get(supersedes)
            if existing_child is not None:
                raise BranchingSupersessionError(
                    f"evaluation {supersedes.value!r} is already superseded by "
                    f"{existing_child.value!r}; correction chains are linear",
                    context_for(subject=supersedes.value, observed=existing_child.value),
                )
        # All checks passed: store atomically (a failed append changed nothing).
        self._records[envelope.evaluation_id] = envelope
        if supersedes is not None:
            self._superseded_by[supersedes] = envelope.evaluation_id

    def get(self, evaluation_id: EvaluationId) -> EvaluationEnvelope | None:
        if not isinstance(evaluation_id, EvaluationId):
            raise _reject_input(
                f"EvaluationRepository.get takes an EvaluationId, got "
                f"{type(evaluation_id).__name__}",
                expected="EvaluationId",
                observed=evaluation_id,
            )
        return self._records.get(evaluation_id)

    def query(self, query: EvaluationQuery) -> tuple[EvaluationEnvelope, ...]:
        if not isinstance(query, EvaluationQuery):
            raise _reject_input(
                f"EvaluationRepository.query takes an EvaluationQuery, got {type(query).__name__}",
                expected="EvaluationQuery",
                observed=query,
            )
        matches = [e for e in self._records.values() if _evaluation_matches(e, query)]
        return tuple(sorted(matches, key=_evaluation_sort_key))


def _evaluation_matches(envelope: EvaluationEnvelope, query: EvaluationQuery) -> bool:
    if query.slate_date is not None and envelope.slate_date != query.slate_date:
        return False
    if query.game_id is not None and envelope.game_id != query.game_id:
        return False
    if query.batter_id is not None and envelope.batter_id != query.batter_id:
        return False
    if (
        query.expected_starting_pitcher_id is not None
        and envelope.expected_starting_pitcher_id != query.expected_starting_pitcher_id
    ):
        return False
    if (
        query.model_configuration_version is not None
        and envelope.model_configuration_version != query.model_configuration_version
    ):
        return False
    if query.window_profile is not None and envelope.window_profile is not query.window_profile:
        return False
    return not (
        query.source_capture_id is not None
        and envelope.source_capture_id != query.source_capture_id
    )


def _evaluation_sort_key(
    envelope: EvaluationEnvelope,
) -> tuple[date, str, str, str, str, datetime, str]:
    """Documented stable order; ``evaluation_id`` is the final unique tie-breaker."""
    return (
        envelope.slate_date,
        envelope.game_id.value,
        envelope.batter_id.value,
        envelope.expected_starting_pitcher_id.value,
        envelope.window_profile.value,
        envelope.evaluated_at,
        envelope.evaluation_id.value,
    )


class InMemoryOutcomeRepository:
    """Instance-local append-only store of outcome revisions (ADR-0006).

    Accepts only :class:`OutcomeRevision`; a bare ``OutcomeRecord`` is refused
    with a pointer to :func:`~greenmachine.persistence.create_outcome_revision`.
    """

    def __init__(self) -> None:
        self._records: dict[OutcomeRevisionId, OutcomeRevision] = {}
        # parent id -> the single direct child revision that corrected it.
        self._superseded_by: dict[OutcomeRevisionId, OutcomeRevisionId] = {}

    def append(self, revision: OutcomeRevision) -> None:
        # Widened so both guards stay live at runtime for an untyped caller.
        candidate: object = revision
        if isinstance(candidate, OutcomeRecord):
            raise MalformedRepositoryInputError(
                "OutcomeRepository stores OutcomeRevision records, not bare "
                "OutcomeRecords; wrap the outcome with create_outcome_revision",
                context_for(expected="OutcomeRevision", observed="OutcomeRecord"),
            )
        if not isinstance(candidate, OutcomeRevision):
            raise _reject_input(
                f"OutcomeRepository.append stores an OutcomeRevision, got "
                f"{type(candidate).__name__}",
                expected="OutcomeRevision",
                observed=candidate,
            )
        revision = candidate
        _check_new_identity(
            self._records.get(revision.outcome_revision_id),
            revision,
            revision.outcome_revision_id.value,
            "outcome revision",
        )
        supersedes = revision.supersedes
        if supersedes is not None:
            parent = self._records.get(supersedes)
            if parent is None:
                raise MissingSupersededParentError(
                    f"outcome revision {revision.outcome_revision_id.value!r} supersedes "
                    f"{supersedes.value!r}, which is not stored",
                    context_for(
                        subject=revision.outcome_revision_id.value,
                        observed=supersedes.value,
                    ),
                )
            if parent.outcome.game_id != revision.outcome.game_id:
                raise InvalidSupersessionError(
                    f"an outcome correction must concern the same game: parent has "
                    f"{parent.outcome.game_id.value!r}, child has "
                    f"{revision.outcome.game_id.value!r}",
                    context_for(
                        subject=revision.outcome_revision_id.value,
                        expected=parent.outcome.game_id.value,
                        observed=revision.outcome.game_id.value,
                    ),
                )
            if parent.outcome.batter_id != revision.outcome.batter_id:
                raise InvalidSupersessionError(
                    f"an outcome correction must concern the same batter: parent has "
                    f"{parent.outcome.batter_id.value!r}, child has "
                    f"{revision.outcome.batter_id.value!r}",
                    context_for(
                        subject=revision.outcome_revision_id.value,
                        expected=parent.outcome.batter_id.value,
                        observed=revision.outcome.batter_id.value,
                    ),
                )
            existing_child = self._superseded_by.get(supersedes)
            if existing_child is not None:
                raise BranchingSupersessionError(
                    f"outcome revision {supersedes.value!r} is already superseded by "
                    f"{existing_child.value!r}; correction chains are linear",
                    context_for(subject=supersedes.value, observed=existing_child.value),
                )
        # All checks passed: store atomically (a failed append changed nothing).
        self._records[revision.outcome_revision_id] = revision
        if supersedes is not None:
            self._superseded_by[supersedes] = revision.outcome_revision_id

    def get(self, revision_id: OutcomeRevisionId) -> OutcomeRevision | None:
        if not isinstance(revision_id, OutcomeRevisionId):
            raise _reject_input(
                f"OutcomeRepository.get takes an OutcomeRevisionId, got "
                f"{type(revision_id).__name__}",
                expected="OutcomeRevisionId",
                observed=revision_id,
            )
        return self._records.get(revision_id)

    def query(self, query: OutcomeQuery) -> tuple[OutcomeRevision, ...]:
        if not isinstance(query, OutcomeQuery):
            raise _reject_input(
                f"OutcomeRepository.query takes an OutcomeQuery, got {type(query).__name__}",
                expected="OutcomeQuery",
                observed=query,
            )
        matches = [r for r in self._records.values() if _outcome_matches(r, query)]
        return tuple(sorted(matches, key=self._outcome_sort_key))

    def _chain_depth(self, revision: OutcomeRevision) -> int:
        """Supersession depth derived from the stored chain — never append order.

        Every parent is guaranteed to exist (append enforces it), and chains are
        finite because a parent must preexist its child, so this walk terminates.
        """
        depth = 0
        current = revision
        while current.supersedes is not None:
            current = self._records[current.supersedes]
            depth += 1
        return depth

    def _outcome_sort_key(self, revision: OutcomeRevision) -> tuple[str, str, int, str]:
        """Documented stable order: subject, then root-first chain depth, then id."""
        return (
            revision.outcome.game_id.value,
            revision.outcome.batter_id.value,
            self._chain_depth(revision),
            revision.outcome_revision_id.value,
        )


def _outcome_matches(revision: OutcomeRevision, query: OutcomeQuery) -> bool:
    if query.game_id is not None and revision.outcome.game_id != query.game_id:
        return False
    if query.batter_id is not None and revision.outcome.batter_id != query.batter_id:
        return False
    if (
        query.outcome_revision_id is not None
        and revision.outcome_revision_id != query.outcome_revision_id
    ):
        return False
    return not (query.supersedes is not None and revision.supersedes != query.supersedes)


if TYPE_CHECKING:
    # Static proof that each adapter satisfies its port protocol.
    _snapshot_port: SnapshotRepository = InMemorySnapshotRepository()
    _evaluation_port: EvaluationRepository = InMemoryEvaluationRepository()
    _outcome_port: OutcomeRepository = InMemoryOutcomeRepository()

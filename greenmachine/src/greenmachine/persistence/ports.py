"""Append-only repository ports, query contracts, and the outcome revision.

ARCHITECTURE §4.8: storage interfaces make history replacement impossible. Three
completely separate, strongly typed repositories — snapshots, evaluation
envelopes, outcome revisions — each exposing exactly ``append``, ``get``, and
``query``. There is no update, delete, upsert, or replace anywhere; a changed
fact is a *new* record (a new content-derived snapshot, a superseding
evaluation, a superseding outcome revision), and every old record stays
readable.

This module also carries the Product Owner ruling on outcome corrections:
:class:`~greenmachine.domain.OutcomeRecord` stays the minimal frozen domain
contract (game, batter, one boolean), and correction history lives in the
**persistence-only** :class:`OutcomeRevision` wrapper, whose
:class:`OutcomeRevisionId` is deterministically derived from the outcome content
and the superseded revision — GM-005's
:func:`~greenmachine.common.ids.deterministic_id`, no clock, no randomness, no
repository state.

Queries are small frozen objects of optional exact-match fields combined with
AND; an all-unset query selects everything, in the adapter's documented
deterministic order. No expression language, no arbitrary predicates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from greenmachine.common.ids import deterministic_id
from greenmachine.domain import (
    EvaluationEnvelope,
    EvaluationId,
    GameId,
    InputSnapshot,
    OutcomeRecord,
    PlayerId,
    SnapshotId,
    SourceCaptureId,
    WindowProfile,
)

from .errors import (
    InvalidSupersessionError,
    MalformedOutcomeRevisionIdError,
    MalformedRepositoryInputError,
    OutcomeRevisionIdentityError,
    context_for,
)

__all__ = [
    "EvaluationQuery",
    "EvaluationRepository",
    "OutcomeQuery",
    "OutcomeRepository",
    "OutcomeRevision",
    "OutcomeRevisionId",
    "SnapshotQuery",
    "SnapshotRepository",
    "create_outcome_revision",
]

# The single documented namespace binding an outcome revision id to its content.
# deterministic_id() renders "<namespace>-<sha256 hex>", giving the exact
# required identifier form: "outcome-revision-<64 lowercase hex characters>".
_OUTCOME_REVISION_NAMESPACE = "outcome-revision"
_OUTCOME_REVISION_PREFIX = f"{_OUTCOME_REVISION_NAMESPACE}-"
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


# --------------------------------------------------------------------------
# Outcome revision identity (Product Owner ruling)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OutcomeRevisionId:
    """Identity of one stored outcome revision. Persistence-only.

    Exactly ``outcome-revision-`` followed by 64 lowercase hexadecimal
    characters. Frozen, hashable, and validated at construction; a malformed
    value raises :class:`MalformedOutcomeRevisionIdError`, never a raw
    ``ValueError`` or ``TypeError``. Construction validates only — deriving an
    identity from content is :func:`create_outcome_revision`'s job.
    """

    value: str

    def __post_init__(self) -> None:
        candidate: object = self.value
        if not isinstance(candidate, str):
            raise MalformedOutcomeRevisionIdError(
                f"OutcomeRevisionId.value must be a string, got {type(candidate).__name__}",
                context_for(),
            )
        digest = candidate.removeprefix(_OUTCOME_REVISION_PREFIX)
        if digest == candidate or _SHA256_HEX.fullmatch(digest) is None:
            raise MalformedOutcomeRevisionIdError(
                f"OutcomeRevisionId.value must be "
                f"'{_OUTCOME_REVISION_PREFIX}<64 lowercase hex characters>', got "
                f"{candidate!r}",
                context_for(observed=candidate),
            )

    def __str__(self) -> str:
        return self.value


def _revision_identity_payload(
    outcome: OutcomeRecord, supersedes: OutcomeRevisionId | None
) -> dict[str, object]:
    """The stable identity projection: exactly the ruling's four facts.

    The superseded identifier (or ``None``) and the three ``OutcomeRecord``
    fields, as primitive values. Including ``supersedes`` chain-hashes the
    lineage: a revision's identity commits to its predecessor, so re-asserting
    an earlier boolean still yields a distinct id, and a revision can never
    contain its own identity.
    """
    return {
        "supersedes": None if supersedes is None else supersedes.value,
        "game_id": outcome.game_id.value,
        "batter_id": outcome.batter_id.value,
        "hit_at_least_one_home_run": outcome.hit_at_least_one_home_run,
    }


def _require_outcome_record(outcome: object) -> OutcomeRecord:
    if not isinstance(outcome, OutcomeRecord):
        raise MalformedRepositoryInputError(
            f"an outcome revision wraps an OutcomeRecord, got {type(outcome).__name__}",
            context_for(expected="OutcomeRecord", observed=type(outcome).__name__),
        )
    return outcome


def _require_optional_revision_id(value: object, field: str) -> OutcomeRevisionId | None:
    if value is None:
        return None
    if not isinstance(value, OutcomeRevisionId):
        raise MalformedRepositoryInputError(
            f"{field} must be an OutcomeRevisionId or None, got {type(value).__name__}",
            context_for(key_path=(field,)),
        )
    return value


@dataclass(frozen=True, slots=True)
class OutcomeRevision:
    """One append-only outcome correction record. Persistence-only.

    Wraps the frozen minimal :class:`~greenmachine.domain.OutcomeRecord` with a
    content-derived identity and an optional supersession link — and nothing
    else: no timestamp, no provider detail, no version, no wager, odds, or ROI.
    The domain outcome contract is untouched (Product Owner ruling; ADR-0006).

    Construction validates every field and the identity coherence:
    ``outcome_revision_id`` must equal the identity derived from ``outcome`` and
    ``supersedes``. A mismatched caller-supplied identity is rejected, never
    silently rewritten. Use :func:`create_outcome_revision`.
    """

    outcome_revision_id: OutcomeRevisionId
    supersedes: OutcomeRevisionId | None
    outcome: OutcomeRecord

    def __post_init__(self) -> None:
        revision_id: object = self.outcome_revision_id
        if not isinstance(revision_id, OutcomeRevisionId):
            raise MalformedRepositoryInputError(
                f"OutcomeRevision.outcome_revision_id must be an OutcomeRevisionId, got "
                f"{type(revision_id).__name__}",
                context_for(key_path=("outcome_revision_id",)),
            )
        supersedes = _require_optional_revision_id(self.supersedes, "OutcomeRevision.supersedes")
        outcome = _require_outcome_record(self.outcome)

        if supersedes is not None and supersedes == revision_id:
            raise InvalidSupersessionError(
                f"OutcomeRevision {revision_id.value!r} cannot supersede itself",
                context_for(subject=revision_id.value),
            )

        expected = deterministic_id(
            _OUTCOME_REVISION_NAMESPACE, _revision_identity_payload(outcome, supersedes)
        )
        if revision_id.value != expected:
            raise OutcomeRevisionIdentityError(
                "OutcomeRevision.outcome_revision_id does not match the identity derived "
                "from its outcome and supersedes; use create_outcome_revision",
                context_for(
                    subject=revision_id.value, expected=expected, observed=revision_id.value
                ),
            )


def create_outcome_revision(
    outcome: OutcomeRecord, *, supersedes: OutcomeRevisionId | None = None
) -> OutcomeRevision:
    """Create an :class:`OutcomeRevision` with its content-derived identity.

    The supported construction path: it validates the inputs, derives the
    deterministic identity with GM-005's ``deterministic_id`` under the
    ``outcome-revision`` namespace, and returns a coherent frozen revision. The
    same outcome and ``supersedes`` always produce the same identity, in any
    process under any ``PYTHONHASHSEED``; changing either changes it. No clock,
    filesystem, environment, or global state is read.
    """
    validated_outcome = _require_outcome_record(outcome)
    validated_supersedes = _require_optional_revision_id(supersedes, "supersedes")
    revision_id = OutcomeRevisionId(
        deterministic_id(
            _OUTCOME_REVISION_NAMESPACE,
            _revision_identity_payload(validated_outcome, validated_supersedes),
        )
    )
    return OutcomeRevision(
        outcome_revision_id=revision_id,
        supersedes=validated_supersedes,
        outcome=validated_outcome,
    )


# --------------------------------------------------------------------------
# Query contracts
# --------------------------------------------------------------------------


def _require_optional_instance(value: object, expected: type, field: str) -> None:
    if value is None or isinstance(value, expected):
        return
    raise MalformedRepositoryInputError(
        f"{field} must be {expected.__name__} or None, got {type(value).__name__}",
        context_for(key_path=(field,)),
    )


def _require_optional_date(value: object, field: str) -> None:
    if value is None:
        return
    # ``datetime`` is a ``date`` subclass; a slate date is a plain date only.
    if isinstance(value, datetime) or not isinstance(value, date):
        raise MalformedRepositoryInputError(
            f"{field} must be a datetime.date or None, got {type(value).__name__}",
            context_for(key_path=(field,)),
        )


def _require_optional_version(value: object, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise MalformedRepositoryInputError(
            f"{field} must be a string or None, got {type(value).__name__}",
            context_for(key_path=(field,)),
        )
    if not value.strip():
        raise MalformedRepositoryInputError(
            f"{field} must be a non-blank version string",
            context_for(key_path=(field,)),
        )


@dataclass(frozen=True, slots=True)
class SnapshotQuery:
    """Exact-match filters over stored input snapshots, combined with AND.

    Every field is optional; an all-unset query selects every snapshot. Frozen
    and hashable, validated at construction.
    """

    slate_date: date | None = None
    game_id: GameId | None = None
    batter_id: PlayerId | None = None
    expected_starting_pitcher_id: PlayerId | None = None
    window_profile: WindowProfile | None = None
    source_capture_id: SourceCaptureId | None = None

    def __post_init__(self) -> None:
        _require_optional_date(self.slate_date, "SnapshotQuery.slate_date")
        _require_optional_instance(self.game_id, GameId, "SnapshotQuery.game_id")
        _require_optional_instance(self.batter_id, PlayerId, "SnapshotQuery.batter_id")
        _require_optional_instance(
            self.expected_starting_pitcher_id,
            PlayerId,
            "SnapshotQuery.expected_starting_pitcher_id",
        )
        _require_optional_instance(
            self.window_profile, WindowProfile, "SnapshotQuery.window_profile"
        )
        _require_optional_instance(
            self.source_capture_id, SourceCaptureId, "SnapshotQuery.source_capture_id"
        )


@dataclass(frozen=True, slots=True)
class EvaluationQuery:
    """Exact-match filters over stored evaluation envelopes, combined with AND."""

    slate_date: date | None = None
    game_id: GameId | None = None
    batter_id: PlayerId | None = None
    expected_starting_pitcher_id: PlayerId | None = None
    model_configuration_version: str | None = None
    window_profile: WindowProfile | None = None
    source_capture_id: SourceCaptureId | None = None

    def __post_init__(self) -> None:
        _require_optional_date(self.slate_date, "EvaluationQuery.slate_date")
        _require_optional_instance(self.game_id, GameId, "EvaluationQuery.game_id")
        _require_optional_instance(self.batter_id, PlayerId, "EvaluationQuery.batter_id")
        _require_optional_instance(
            self.expected_starting_pitcher_id,
            PlayerId,
            "EvaluationQuery.expected_starting_pitcher_id",
        )
        _require_optional_version(
            self.model_configuration_version, "EvaluationQuery.model_configuration_version"
        )
        _require_optional_instance(
            self.window_profile, WindowProfile, "EvaluationQuery.window_profile"
        )
        _require_optional_instance(
            self.source_capture_id, SourceCaptureId, "EvaluationQuery.source_capture_id"
        )


@dataclass(frozen=True, slots=True)
class OutcomeQuery:
    """Exact-match filters over stored outcome revisions, combined with AND.

    ``None`` always means *unset* (no filter); a root-only filter
    ("supersedes is None") is deliberately not expressible in this grammar.
    """

    game_id: GameId | None = None
    batter_id: PlayerId | None = None
    outcome_revision_id: OutcomeRevisionId | None = None
    supersedes: OutcomeRevisionId | None = None

    def __post_init__(self) -> None:
        _require_optional_instance(self.game_id, GameId, "OutcomeQuery.game_id")
        _require_optional_instance(self.batter_id, PlayerId, "OutcomeQuery.batter_id")
        _require_optional_instance(
            self.outcome_revision_id, OutcomeRevisionId, "OutcomeQuery.outcome_revision_id"
        )
        _require_optional_instance(self.supersedes, OutcomeRevisionId, "OutcomeQuery.supersedes")


# --------------------------------------------------------------------------
# Repository ports: append, get, query — and nothing else
# --------------------------------------------------------------------------


@runtime_checkable
class SnapshotRepository(Protocol):
    """Append-only storage for frozen input snapshots.

    A snapshot has no supersession: a changed input is a new content-derived
    identity, and both snapshots stay independently stored and queryable.
    """

    def append(self, snapshot: InputSnapshot) -> None:
        """Store a new snapshot. An existing identity is a typed conflict."""
        ...

    def get(self, snapshot_id: SnapshotId) -> InputSnapshot | None:
        """Return the stored snapshot, or ``None`` when the id is unknown."""
        ...

    def query(self, query: SnapshotQuery) -> tuple[InputSnapshot, ...]:
        """Return matching snapshots as a new tuple, in deterministic order."""
        ...


@runtime_checkable
class EvaluationRepository(Protocol):
    """Append-only storage for evaluation envelopes with linear supersession."""

    def append(self, envelope: EvaluationEnvelope) -> None:
        """Store a new envelope; supersession must point at one existing parent."""
        ...

    def get(self, evaluation_id: EvaluationId) -> EvaluationEnvelope | None:
        """Return the stored envelope, or ``None`` when the id is unknown."""
        ...

    def query(self, query: EvaluationQuery) -> tuple[EvaluationEnvelope, ...]:
        """Return matching envelopes as a new tuple, in deterministic order."""
        ...


@runtime_checkable
class OutcomeRepository(Protocol):
    """Append-only storage for outcome revisions with linear correction chains.

    Accepts only :class:`OutcomeRevision` — never a bare
    :class:`~greenmachine.domain.OutcomeRecord` (ADR-0006).
    """

    def append(self, revision: OutcomeRevision) -> None:
        """Store a new revision; a correction must extend an existing chain."""
        ...

    def get(self, revision_id: OutcomeRevisionId) -> OutcomeRevision | None:
        """Return the stored revision, or ``None`` when the id is unknown."""
        ...

    def query(self, query: OutcomeQuery) -> tuple[OutcomeRevision, ...]:
        """Return matching revisions as a new tuple, in deterministic order."""
        ...

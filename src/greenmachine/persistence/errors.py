"""Typed persistence failures, rooted at the project taxonomy (ADR-0007).

Every error here subclasses :class:`~greenmachine.common.errors.PersistenceError`,
so a caller may catch the whole storage family — or one precise case — without
parsing messages. The distinctions mirror what a caller can actually react to:

* :class:`MalformedRepositoryInputError` — the argument itself is wrong: a bad
  record type, a wrong identifier wrapper, an invalid query object or field, a
  malformed :class:`~greenmachine.persistence.ports.OutcomeRevisionId`
  (:class:`MalformedOutcomeRevisionIdError`), or a revision whose stored identity
  does not describe its content (:class:`OutcomeRevisionIdentityError`).
* :class:`DuplicateRecordError` — an identity was appended twice. Its subclass
  :class:`ConflictingRecordError` is the stronger case: the same identity reused
  by a *different* record. Append is never silently idempotent.
* :class:`SupersessionError` — a correction chain rule was violated: the named
  parent does not exist (:class:`MissingSupersededParentError`), the supersession
  itself is invalid, e.g. a subject mismatch (:class:`InvalidSupersessionError`),
  or a second child tried to fork one parent
  (:class:`BranchingSupersessionError`).

All errors carry :class:`~greenmachine.common.errors.ErrorContext`. No raw
``KeyError``, ``AttributeError``, ``TypeError``, or ``ValueError`` escapes a
public repository API.
"""

from __future__ import annotations

from greenmachine.common.errors import ErrorContext, PersistenceError

__all__ = [
    "BranchingSupersessionError",
    "ConflictingRecordError",
    "DuplicateRecordError",
    "InvalidSupersessionError",
    "MalformedOutcomeRevisionIdError",
    "MalformedRepositoryInputError",
    "MissingSupersededParentError",
    "OutcomeRevisionIdentityError",
    "SupersessionError",
]


class MalformedRepositoryInputError(PersistenceError):
    """A public repository argument was structurally wrong.

    The wrong record type on ``append``, the wrong identifier wrapper on
    ``get``, the wrong query object or an invalid query field on ``query`` —
    the argument itself is the problem, not the repository's contents.
    """


class MalformedOutcomeRevisionIdError(MalformedRepositoryInputError):
    """A value offered as an ``OutcomeRevisionId`` is not one valid identifier.

    The exact form is ``outcome-revision-`` followed by 64 lowercase hexadecimal
    characters; anything else — uppercase, wrong length, whitespace, a malformed
    prefix, a non-string — fails here rather than being stored.
    """


class OutcomeRevisionIdentityError(MalformedRepositoryInputError):
    """An ``OutcomeRevision`` claims an identity its content does not produce.

    The revision id is content-derived; a caller-supplied mismatch is rejected,
    never silently rewritten.
    """


class DuplicateRecordError(PersistenceError):
    """A record identity was appended more than once.

    History is append-only and append is never idempotent: even re-appending the
    identical record is refused, and the original stays exactly as stored.
    """


class ConflictingRecordError(DuplicateRecordError):
    """An existing identity was reused by a *different* record.

    The stronger form of a duplicate: accepting it would silently replace
    history. A subclass of :class:`DuplicateRecordError`, so catching the base
    still catches the conflict while the type distinguishes the two cases.
    """


class SupersessionError(PersistenceError):
    """A correction chain rule was violated during an append."""


class MissingSupersededParentError(SupersessionError):
    """A record claims to supersede a parent the repository does not hold.

    Requiring the parent to preexist is also what makes cycles impossible.
    """


class InvalidSupersessionError(SupersessionError):
    """The supersession itself is not a valid correction.

    Self-supersession, or an outcome correction whose parent concerns a
    different game or batter — a correction must correct the same subject.
    """


class BranchingSupersessionError(SupersessionError):
    """A second record tried to supersede an already-superseded parent.

    Correction chains are linear: one parent, at most one direct child. A fork
    would leave two competing "current" records, so it is refused.
    """


def context_for(
    *,
    subject: str | None = None,
    expected: str | None = None,
    observed: str | None = None,
    window_profile: str | None = None,
    key_path: tuple[str, ...] = (),
) -> ErrorContext:
    """Build the structured context every persistence error carries."""
    return ErrorContext(
        subject=subject,
        expected=expected,
        observed=observed,
        window_profile=window_profile,
        key_path=key_path,
    )

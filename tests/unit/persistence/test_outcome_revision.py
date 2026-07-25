"""OutcomeRevision and its content-derived identity (Product Owner ruling)."""

from __future__ import annotations

import dataclasses

import pytest
import synthetic_records as sr

from greenmachine.domain import GameId, OutcomeRecord, PlayerId
from greenmachine.persistence import (
    InvalidSupersessionError,
    MalformedOutcomeRevisionIdError,
    MalformedRepositoryInputError,
    OutcomeRevision,
    OutcomeRevisionId,
    OutcomeRevisionIdentityError,
    create_outcome_revision,
)

OUTCOME = sr.outcome_record()
PREFIX = "outcome-revision-"


def corrected_outcome() -> OutcomeRecord:
    return OutcomeRecord(
        game_id=OUTCOME.game_id,
        batter_id=OUTCOME.batter_id,
        hit_at_least_one_home_run=False,
    )


# --------------------------------------------------------------------------
# Identity derivation
# --------------------------------------------------------------------------


def test_the_identity_has_the_exact_required_form() -> None:
    revision = create_outcome_revision(OUTCOME)
    value = revision.outcome_revision_id.value

    assert value.startswith(PREFIX)
    digest = value.removeprefix(PREFIX)
    assert len(digest) == 64
    assert all(character in "0123456789abcdef" for character in digest)


def test_the_same_content_produces_the_same_identity() -> None:
    assert create_outcome_revision(OUTCOME) == create_outcome_revision(sr.outcome_record())


def test_an_outcome_change_changes_the_identity() -> None:
    assert (
        create_outcome_revision(OUTCOME).outcome_revision_id
        != create_outcome_revision(corrected_outcome()).outcome_revision_id
    )


def test_a_supersedes_change_changes_the_identity() -> None:
    root = create_outcome_revision(OUTCOME)
    chained = create_outcome_revision(OUTCOME, supersedes=root.outcome_revision_id)

    assert chained.outcome_revision_id != root.outcome_revision_id


def test_reasserting_an_earlier_value_still_yields_a_distinct_identity() -> None:
    """true -> false -> true: the chain hash keeps every revision distinct."""
    root = create_outcome_revision(OUTCOME)
    corrected = create_outcome_revision(corrected_outcome(), supersedes=root.outcome_revision_id)
    reasserted = create_outcome_revision(OUTCOME, supersedes=corrected.outcome_revision_id)

    identities = {
        root.outcome_revision_id,
        corrected.outcome_revision_id,
        reasserted.outcome_revision_id,
    }
    assert len(identities) == 3


# --------------------------------------------------------------------------
# OutcomeRevisionId validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        PREFIX + "A" * 64,  # uppercase digest
        PREFIX + "a" * 63,  # too short
        PREFIX + "a" * 65,  # too long
        PREFIX + "a" * 63 + "g",  # non-hex
        PREFIX + " " + "a" * 63,  # whitespace
        "outcome_revision-" + "a" * 64,  # malformed prefix
        "a" * 64,  # missing prefix
        "",  # empty
    ],
)
def test_a_malformed_identifier_is_rejected(bad: str) -> None:
    with pytest.raises(MalformedOutcomeRevisionIdError):
        OutcomeRevisionId(bad)


@pytest.mark.parametrize("bad", [123, None, b"outcome-revision-" + b"a" * 64, ["x"]])
def test_a_non_string_identifier_is_rejected(bad: object) -> None:
    with pytest.raises(MalformedOutcomeRevisionIdError):
        OutcomeRevisionId(bad)  # type: ignore[arg-type]


def test_a_valid_identifier_is_frozen_and_hashable() -> None:
    identifier = OutcomeRevisionId(PREFIX + "a" * 64)

    assert hash(identifier) == hash(OutcomeRevisionId(PREFIX + "a" * 64))
    assert str(identifier) == PREFIX + "a" * 64
    with pytest.raises(dataclasses.FrozenInstanceError):
        identifier.value = "x"  # type: ignore[misc]


# --------------------------------------------------------------------------
# OutcomeRevision coherence
# --------------------------------------------------------------------------


def test_the_revision_is_frozen_hashable_and_minimal() -> None:
    revision = create_outcome_revision(OUTCOME)

    assert isinstance(hash(revision), int)
    with pytest.raises(dataclasses.FrozenInstanceError):
        revision.outcome = corrected_outcome()  # type: ignore[misc]

    field_names = {field.name for field in dataclasses.fields(OutcomeRevision)}
    assert field_names == {"outcome_revision_id", "supersedes", "outcome"}


@pytest.mark.parametrize(
    "forbidden",
    ["timestamp", "created_at", "provider_id", "code_version", "wager", "odds", "roi"],
)
def test_the_revision_carries_no_forbidden_concern(forbidden: str) -> None:
    assert not hasattr(create_outcome_revision(OUTCOME), forbidden)


def test_a_mismatched_identity_is_rejected_not_rewritten() -> None:
    wrong = OutcomeRevisionId(PREFIX + "a" * 64)
    with pytest.raises(OutcomeRevisionIdentityError) as caught:
        OutcomeRevision(outcome_revision_id=wrong, supersedes=None, outcome=OUTCOME)

    assert caught.value.context.expected != caught.value.context.observed


def test_self_supersession_is_rejected() -> None:
    identifier = OutcomeRevisionId(PREFIX + "b" * 64)
    with pytest.raises(InvalidSupersessionError, match=r"supersede itself"):
        OutcomeRevision(outcome_revision_id=identifier, supersedes=identifier, outcome=OUTCOME)


def test_the_factory_rejects_a_non_outcome() -> None:
    with pytest.raises(MalformedRepositoryInputError, match=r"OutcomeRecord"):
        create_outcome_revision("not an outcome")  # type: ignore[arg-type]


def test_the_factory_rejects_a_malformed_supersedes() -> None:
    with pytest.raises(MalformedRepositoryInputError, match=r"supersedes"):
        create_outcome_revision(OUTCOME, supersedes="a raw string")  # type: ignore[arg-type]


def test_the_revision_rejects_a_non_outcome_payload() -> None:
    root = create_outcome_revision(OUTCOME)
    with pytest.raises(MalformedRepositoryInputError):
        OutcomeRevision(
            outcome_revision_id=root.outcome_revision_id,
            supersedes=None,
            outcome="not an outcome",  # type: ignore[arg-type]
        )


# --------------------------------------------------------------------------
# The frozen domain contract is untouched
# --------------------------------------------------------------------------


def test_outcome_record_remains_exactly_the_minimal_contract() -> None:
    field_names = {field.name for field in dataclasses.fields(OutcomeRecord)}
    assert field_names == {"game_id", "batter_id", "hit_at_least_one_home_run"}
    assert not hasattr(OUTCOME, "supersedes")
    assert not hasattr(OUTCOME, "outcome_revision_id")


def test_outcome_revision_is_not_part_of_the_domain() -> None:
    import greenmachine.domain as domain

    assert not hasattr(domain, "OutcomeRevision")
    assert not hasattr(domain, "OutcomeRevisionId")
    assert GameId is not None and PlayerId is not None  # domain vocabulary intact

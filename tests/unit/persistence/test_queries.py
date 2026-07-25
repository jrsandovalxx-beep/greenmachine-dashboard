"""Query objects: frozen, hashable, and strict about their field types."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest
import synthetic_records as sr

from greenmachine.domain import GameId, PlayerId, SourceCaptureId, WindowProfile
from greenmachine.persistence import (
    EvaluationQuery,
    MalformedRepositoryInputError,
    OutcomeQuery,
    OutcomeRevisionId,
    SnapshotQuery,
)

QUERY_TYPES = [SnapshotQuery, EvaluationQuery, OutcomeQuery]


@pytest.mark.parametrize("query_type", QUERY_TYPES, ids=lambda t: t.__name__)
def test_an_all_unset_query_is_valid_frozen_and_hashable(query_type: type) -> None:
    query = query_type()

    assert hash(query) == hash(query_type())
    first_field = dataclasses.fields(query)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(query, first_field, None)


def test_a_fully_populated_snapshot_query_is_valid() -> None:
    query = SnapshotQuery(
        slate_date=sr.SLATE_DATE,
        game_id=GameId("SYNTHETIC-GAME-0001"),
        batter_id=PlayerId("SYNTHETIC-BATTER-0001"),
        expected_starting_pitcher_id=PlayerId("SYNTHETIC-PITCHER-0009"),
        window_profile=WindowProfile.RECENT_7D,
        source_capture_id=SourceCaptureId("SYNTHETIC-CAPTURE-0001"),
    )
    assert query.slate_date == sr.SLATE_DATE


@pytest.mark.parametrize("query_type", [SnapshotQuery, EvaluationQuery], ids=lambda t: t.__name__)
def test_a_datetime_is_rejected_for_the_slate_date(query_type: type) -> None:
    """datetime subclasses date; a slate filter must be a plain date."""
    with pytest.raises(MalformedRepositoryInputError, match=r"slate_date"):
        query_type(slate_date=datetime(2026, 7, 15, tzinfo=UTC))


@pytest.mark.parametrize("query_type", [SnapshotQuery, EvaluationQuery], ids=lambda t: t.__name__)
def test_a_raw_string_game_id_is_rejected(query_type: type) -> None:
    with pytest.raises(MalformedRepositoryInputError, match=r"game_id"):
        query_type(game_id="SYNTHETIC-GAME-0001")


def test_a_bool_is_rejected_where_an_identifier_belongs() -> None:
    with pytest.raises(MalformedRepositoryInputError, match=r"batter_id"):
        SnapshotQuery(batter_id=True)  # type: ignore[arg-type]


def test_a_raw_string_profile_is_rejected() -> None:
    with pytest.raises(MalformedRepositoryInputError, match=r"window_profile"):
        SnapshotQuery(window_profile="RECENT_7D")  # type: ignore[arg-type]


def test_a_blank_configuration_version_is_rejected() -> None:
    with pytest.raises(MalformedRepositoryInputError, match=r"non-blank"):
        EvaluationQuery(model_configuration_version="   ")


def test_a_bool_configuration_version_is_rejected() -> None:
    with pytest.raises(MalformedRepositoryInputError, match=r"model_configuration_version"):
        EvaluationQuery(model_configuration_version=True)  # type: ignore[arg-type]


def test_a_raw_string_revision_id_filter_is_rejected() -> None:
    with pytest.raises(MalformedRepositoryInputError, match=r"outcome_revision_id"):
        OutcomeQuery(outcome_revision_id="outcome-revision-" + "a" * 64)  # type: ignore[arg-type]


def test_a_raw_string_supersedes_filter_is_rejected() -> None:
    with pytest.raises(MalformedRepositoryInputError, match=r"supersedes"):
        OutcomeQuery(supersedes="outcome-revision-" + "a" * 64)  # type: ignore[arg-type]


def test_a_valid_outcome_query_accepts_revision_identifiers() -> None:
    identifier = OutcomeRevisionId("outcome-revision-" + "a" * 64)
    query = OutcomeQuery(outcome_revision_id=identifier, supersedes=identifier)
    assert query.outcome_revision_id == identifier

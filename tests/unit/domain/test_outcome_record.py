"""OutcomeRecord: a minimal, separate contract that cannot touch an evaluation."""

from __future__ import annotations

import dataclasses

import pytest
import synthetic_records as sr

from greenmachine.domain import (
    DomainValidationError,
    EvaluatedGradeResult,
    EvaluationEnvelope,
    GameId,
    InputSnapshot,
    NotEvaluableGradeResult,
    OutcomeRecord,
    PlayerId,
)

OUTCOME = sr.outcome_record()


def test_the_home_run_flag_must_be_a_strict_bool() -> None:
    for bad in (1, 0, "true", None):
        with pytest.raises(DomainValidationError):
            OutcomeRecord(
                game_id=GameId("SYNTHETIC-GAME-0001"),
                batter_id=PlayerId("SYNTHETIC-BATTER-0001"),
                hit_at_least_one_home_run=bad,  # type: ignore[arg-type]
            )


def test_it_is_immutable_and_hashable() -> None:
    assert isinstance(hash(OUTCOME), int)
    assert sr.outcome_record() == OUTCOME
    with pytest.raises(dataclasses.FrozenInstanceError):
        OUTCOME.hit_at_least_one_home_run = False  # type: ignore[misc]


def test_it_contains_only_the_approved_identity_and_outcome_fields() -> None:
    fields = {field.name for field in dataclasses.fields(OUTCOME)}
    assert fields == {"game_id", "batter_id", "hit_at_least_one_home_run"}


@pytest.mark.parametrize(
    "contract", [InputSnapshot, EvaluatedGradeResult, NotEvaluableGradeResult, EvaluationEnvelope]
)
def test_no_evaluation_contract_can_hold_an_outcome(contract: type) -> None:
    field_names = {field.name for field in dataclasses.fields(contract)}
    field_types = " ".join(str(field.type) for field in dataclasses.fields(contract))

    assert not (field_names & {"outcome", "outcome_record", "hit_at_least_one_home_run"})
    assert "OutcomeRecord" not in field_types

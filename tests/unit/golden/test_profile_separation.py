"""Profile separation across the committed golden tree (ADR-0005, W1-W4).

The two evaluated cases are two independently frozen snapshots from one
synthetic source capture: same collection operation, distinct profiles,
distinct identities, distinct expected results — and neither ever borrows from
the other.
"""

from __future__ import annotations

from tests.golden.runner import CASES_ROOT, discover_cases, run_case
from tests.golden.stub_scorer import score_snapshot

from greenmachine.domain import (
    EvaluatedGradeResult,
    NotEvaluableGradeResult,
    WindowProfile,
)
from greenmachine.evaluation import serialize_record

CASES = {case.case_id: case for case in discover_cases(CASES_ROOT)}
RECENT = CASES["synthetic-recent-evaluated"]
LONG_TERM = CASES["synthetic-long-term-evaluated"]
NOT_EVALUABLE = CASES["synthetic-recent-not-evaluable"]


def test_the_two_evaluated_cases_share_exactly_one_source_capture() -> None:
    assert RECENT.snapshot.source_capture_id == LONG_TERM.snapshot.source_capture_id
    assert RECENT.snapshot.source_capture_id.value == "SYNTHETIC-CAPTURE-0001"


def test_profiles_differ() -> None:
    assert RECENT.window_profile is WindowProfile.RECENT_7D
    assert LONG_TERM.window_profile is WindowProfile.LONG_TERM_2Y


def test_snapshot_ids_differ() -> None:
    assert RECENT.snapshot.snapshot_id != LONG_TERM.snapshot.snapshot_id


def test_input_hashes_differ() -> None:
    assert RECENT.snapshot.input_hash != LONG_TERM.snapshot.input_hash


def test_window_bounds_differ() -> None:
    assert RECENT.snapshot.window_start != LONG_TERM.snapshot.window_start


def test_expected_results_differ() -> None:
    assert RECENT.expected_result != LONG_TERM.expected_result
    assert serialize_record(RECENT.expected_result) != serialize_record(LONG_TERM.expected_result)


def test_both_cases_pass_independently() -> None:
    assert run_case(RECENT, score_snapshot).passed
    assert run_case(LONG_TERM, score_snapshot).passed


def test_neither_case_contains_an_observation_from_the_other_profile() -> None:
    """No silent cross-window fallback: every observation carries its own profile."""
    for case in (RECENT, LONG_TERM, NOT_EVALUABLE):
        for observation in case.snapshot.present_observations:
            assert observation.window_profile is case.window_profile
        for observation in case.snapshot.missing_observations:
            assert observation.window_profile is case.window_profile
        for observation in case.expected_result.present_observations:
            assert observation.window_profile is case.window_profile
        for observation in case.expected_result.missing_observations:
            assert observation.window_profile is case.window_profile


def test_expected_variants_cover_both_terminal_states() -> None:
    assert isinstance(RECENT.expected_result, EvaluatedGradeResult)
    assert isinstance(LONG_TERM.expected_result, EvaluatedGradeResult)
    assert isinstance(NOT_EVALUABLE.expected_result, NotEvaluableGradeResult)


def test_the_not_evaluable_case_is_a_separate_capture() -> None:
    assert NOT_EVALUABLE.snapshot.source_capture_id.value == "SYNTHETIC-CAPTURE-0002"
    assert NOT_EVALUABLE.snapshot.present_observations == ()


def test_every_committed_identifier_is_visibly_synthetic() -> None:
    for case in CASES.values():
        snapshot = case.snapshot
        assert "SYNTHETIC" in snapshot.game_context.game_id.value
        assert "SYNTHETIC" in snapshot.batter.player_id.value
        assert "Synthetic" in snapshot.batter.full_name
        assert "SYNTHETIC" in snapshot.expected_starting_pitcher.player_id.value
        assert "Synthetic" in snapshot.game_context.venue.name
        assert "SYNTHETIC" in snapshot.source_capture_id.value
        assert case.config_version_identifier == "synthetic-fixture-0"

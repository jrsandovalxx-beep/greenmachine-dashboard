"""The committed golden suite: every case under ``tests/golden/cases`` must pass.

Runs each discovered case against the injected test-only stub scorer. Any drift
between a committed snapshot, the scorer, and the committed expected result
fails with a readable field-level diff — the suite never repairs a golden file;
regeneration is only ever the explicit ``scripts/update_goldens.py``.
"""

from __future__ import annotations

import pytest
from tests.golden.runner import CASES_ROOT, GoldenCase, assert_case_passes, discover_cases
from tests.golden.stub_scorer import score_snapshot

CASES = discover_cases(CASES_ROOT)


def test_the_committed_golden_tree_is_not_empty() -> None:
    """Anti-vacuity: the parametrized suite below must actually cover cases."""
    assert len(CASES) >= 2


def test_both_window_profiles_are_covered() -> None:
    profiles = {case.window_profile.value for case in CASES}
    assert profiles == {"RECENT_7D", "LONG_TERM_2Y"}


def test_discovery_is_ordered_by_case_id() -> None:
    identifiers = [case.case_id for case in CASES]
    assert identifiers == sorted(identifiers)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_golden_case(case: GoldenCase) -> None:
    assert_case_passes(case, score_snapshot)

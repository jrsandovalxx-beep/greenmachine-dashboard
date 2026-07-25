"""Persistence identity and query order are stable across processes and seeds.

The ``OutcomeRevisionId`` derivation and every repository query order must not
depend on ``PYTHONHASHSEED``, dict/set iteration, or append order, so both are
recomputed in fresh interpreters under deliberately different seeds — and with
the appends permuted — and compared. No Hypothesis (GM-008 owns that setup).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "evaluations"
INTEGRATION = Path(__file__).resolve().parents[1] / "integration"

_PROBE = f"""
import sys
sys.path.insert(0, {str(FIXTURES)!r})
sys.path.insert(0, {str(INTEGRATION)!r})
import synthetic_records as sr
from repository_contracts import make_envelope, make_revision, make_snapshot
from greenmachine.persistence import (
    EvaluationQuery, InMemoryEvaluationRepository, InMemoryOutcomeRepository,
    InMemorySnapshotRepository, OutcomeQuery, SnapshotQuery,
)

root = make_revision(homered=True)
child = make_revision(homered=False, supersedes=root.outcome_revision_id)
print(root.outcome_revision_id.value)
print(child.outcome_revision_id.value)

snapshots = InMemorySnapshotRepository()
for record in (make_snapshot(game="SYNTHETIC-GAME-0002"), make_snapshot(),
               make_snapshot(batter="SYNTHETIC-BATTER-0002")):
    snapshots.append(record)
print("|".join(s.snapshot_id.value for s in snapshots.query(SnapshotQuery())))

evaluations = InMemoryEvaluationRepository()
for record in (
    make_envelope(evaluation_id="SYNTHETIC-EVAL-1003", minutes_offset=5),
    make_envelope(),
    make_envelope(evaluation_id="SYNTHETIC-EVAL-1002", game="SYNTHETIC-GAME-0002"),
):
    evaluations.append(record)
print("|".join(e.evaluation_id.value for e in evaluations.query(EvaluationQuery())))

outcomes = InMemoryOutcomeRepository()
for record in (make_revision(game="SYNTHETIC-GAME-0002"), root, child):
    outcomes.append(record)
print("|".join(r.outcome_revision_id.value for r in outcomes.query(OutcomeQuery())))
"""

SEEDS = ("0", "1", "12345", "99999")


def run_probe(seed: str) -> tuple[str, ...]:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = seed
    from tests.network_guard.guarded_child import guarded_python_command

    completed = subprocess.run(
        guarded_python_command("-c", _PROBE),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return tuple(completed.stdout.strip().splitlines())


@pytest.fixture(scope="module")
def probe_runs() -> list[tuple[str, ...]]:
    return [run_probe(seed) for seed in SEEDS]


def test_revision_identity_and_query_order_are_identical_across_processes(
    probe_runs: list[tuple[str, ...]],
) -> None:
    assert len(set(probe_runs)) == 1, f"output diverged across processes: {probe_runs}"


def test_python_hash_seed_does_not_influence_output(
    probe_runs: list[tuple[str, ...]],
) -> None:
    # Four different seeds were used; nothing about the output moved.
    assert len({run for run in probe_runs}) == 1


def test_the_subprocess_and_this_process_agree(probe_runs: list[tuple[str, ...]]) -> None:
    import synthetic_records as sr  # noqa: F401 - path check for the local run

    sys.path.insert(0, str(INTEGRATION))
    from repository_contracts import make_revision

    root = make_revision(homered=True)
    child = make_revision(homered=False, supersedes=root.outcome_revision_id)

    assert probe_runs[0][0] == root.outcome_revision_id.value
    assert probe_runs[0][1] == child.outcome_revision_id.value


@pytest.mark.parametrize("repeat", range(3))
def test_repeated_cross_seed_runs_stay_stable(repeat: int) -> None:
    assert run_probe("0") == run_probe("54321")

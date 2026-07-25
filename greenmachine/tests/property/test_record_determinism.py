"""Record serialization and snapshot identity are stable across processes.

Canonical bytes and content-derived identity must not depend on ``PYTHONHASHSEED``
or dict ordering, so they are recomputed in fresh interpreters under deliberately
different seeds and compared. No Hypothesis — deterministic parameterisation and
subprocesses only (GM-008 owns property-test framework setup).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest
import synthetic_records as sr

from greenmachine.evaluation import serialize_record

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "evaluations"

_PROBE = f"""
import sys, hashlib
sys.path.insert(0, {str(FIXTURES)!r})
import synthetic_records as sr
from greenmachine.evaluation import serialize_record

snapshot = sr.input_snapshot()
print(snapshot.snapshot_id.value)
print(snapshot.input_hash.value)
print(hashlib.sha256(serialize_record(snapshot)).hexdigest())
print(hashlib.sha256(serialize_record(sr.evaluated_grade_result())).hexdigest())
print(hashlib.sha256(serialize_record(sr.not_evaluable_grade_result())).hexdigest())
print(hashlib.sha256(serialize_record(sr.evaluation_envelope())).hexdigest())
print(hashlib.sha256(serialize_record(sr.outcome_record())).hexdigest())
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


def test_identity_and_serialized_digests_are_identical_across_processes(
    probe_runs: list[tuple[str, ...]],
) -> None:
    assert len(set(probe_runs)) == 1, f"output diverged across processes: {probe_runs}"


def test_python_hash_seed_does_not_influence_output(
    probe_runs: list[tuple[str, ...]],
) -> None:
    # Four different seeds were used; nothing about the digests moved.
    assert len({run for run in probe_runs}) == 1


def test_the_subprocess_and_this_process_agree(probe_runs: list[tuple[str, ...]]) -> None:
    snapshot = sr.input_snapshot()
    in_process = (
        snapshot.snapshot_id.value,
        snapshot.input_hash.value,
        hashlib.sha256(serialize_record(snapshot)).hexdigest(),
        hashlib.sha256(serialize_record(sr.evaluated_grade_result())).hexdigest(),
        hashlib.sha256(serialize_record(sr.not_evaluable_grade_result())).hexdigest(),
        hashlib.sha256(serialize_record(sr.evaluation_envelope())).hexdigest(),
        hashlib.sha256(serialize_record(sr.outcome_record())).hexdigest(),
    )

    assert probe_runs[0] == in_process


@pytest.mark.parametrize("repeat", range(3))
def test_repeated_runs_stay_stable(repeat: int) -> None:
    assert run_probe("0") == run_probe("54321")

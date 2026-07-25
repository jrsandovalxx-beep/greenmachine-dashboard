"""Discovery order and golden results are identical across PYTHONHASHSEED values.

Python's per-process string-hash randomization is the classic source of
accidental ordering nondeterminism. Each subprocess below discovers the
committed cases, runs them against the stub, and prints a transcript; every
seed must produce byte-identical output.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# Deliberately spread seeds; the full five-seed matrix from the GM-008
# validation plan is exercised here on every run.
HASH_SEEDS = ("0", "1", "7", "123", "424242")

_TRANSCRIPT_PROGRAM = """
import hashlib
import sys

sys.path.insert(0, {repo_root!r})
sys.path.insert(0, {fixtures!r})

from greenmachine.evaluation import serialize_record
from tests.golden.runner import CASES_ROOT, discover_cases, run_cases
from tests.golden.stub_scorer import score_snapshot

cases = discover_cases(CASES_ROOT)
runs = run_cases(cases, score_snapshot)
for case, run in zip(cases, runs, strict=True):
    expected_digest = hashlib.sha256(serialize_record(case.expected_result)).hexdigest()
    actual_digest = hashlib.sha256(serialize_record(score_snapshot(
        case.snapshot, case.config_version_identifier))).hexdigest()
    print(case.case_id, case.window_profile.value, expected_digest, actual_digest,
          "passed" if run.passed else "failed")
"""


def transcript(hash_seed: str) -> str:
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = hash_seed
    program = _TRANSCRIPT_PROGRAM.format(
        repo_root=str(REPO_ROOT),
        fixtures=str(REPO_ROOT / "tests" / "fixtures" / "evaluations"),
    )
    from tests.network_guard.guarded_child import guarded_python_command

    completed = subprocess.run(
        guarded_python_command("-c", program),
        capture_output=True,
        text=True,
        env=environment,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def test_discovery_order_and_results_are_identical_across_hash_seeds() -> None:
    transcripts = {seed: transcript(seed) for seed in HASH_SEEDS}

    reference = transcripts[HASH_SEEDS[0]]
    assert "passed" in reference and "failed" not in reference
    lines = reference.strip().splitlines()
    assert [line.split()[0] for line in lines] == sorted(line.split()[0] for line in lines)
    for seed in HASH_SEEDS[1:]:
        assert transcripts[seed] == reference, f"PYTHONHASHSEED={seed} diverged"

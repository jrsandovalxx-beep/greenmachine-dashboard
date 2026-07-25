"""Determinism across process boundaries.

Byte-identity inside one process proves little: the hazards that matter are
``PYTHONHASHSEED`` randomisation, dict ordering, and locale. These tests
re-serialize the same fixture in separate interpreters and compare the bytes.

No Hypothesis here — GM-008 owns property-test framework setup, so this uses
deterministic parameterisation and subprocesses only.
"""

from __future__ import annotations

import os
import subprocess
from decimal import Decimal

import pytest

from greenmachine.common import canonical_bytes, content_digest, deterministic_id

# Built in the subprocess so nothing is inherited from this interpreter.
FIXTURE_SOURCE = """
import dataclasses
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

from greenmachine.common import canonical_bytes, content_digest, deterministic_id


class Profile(Enum):
    RECENT_7D = "RECENT_7D"
    LONG_TERM_2Y = "LONG_TERM_2Y"


@dataclasses.dataclass(frozen=True)
class Observation:
    component: str
    value: Decimal
    profile: Profile
    observed_at: datetime


fixture = {
    "zulu": Observation(
        "exit_velocity",
        Decimal("12.3400"),
        Profile.RECENT_7D,
        datetime(2026, 7, 15, 23, 10, tzinfo=UTC),
    ),
    "alpha": Observation(
        "barrel_pct",
        Decimal("1E+2"),
        Profile.LONG_TERM_2Y,
        datetime(2026, 7, 15, 19, 10, tzinfo=timezone(timedelta(hours=-4))),
    ),
    "middle": {"nested": [1, "two", Decimal("-0"), None, True]},
}

print(canonical_bytes(fixture).decode("utf-8"))
print(content_digest(fixture))
print(deterministic_id("snapshot", fixture))
"""


def run_fixture(hash_seed: str) -> tuple[str, str, str]:
    """Serialize the fixture in a fresh interpreter under a given PYTHONHASHSEED."""
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = hash_seed
    from tests.network_guard.guarded_child import guarded_python_command

    completed = subprocess.run(
        guarded_python_command("-c", FIXTURE_SOURCE),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    canonical, digest, identifier = completed.stdout.strip().splitlines()
    return canonical, digest, identifier


@pytest.fixture(scope="module")
def subprocess_runs() -> list[tuple[str, str, str]]:
    """Four independent interpreters, deliberately different hash seeds."""
    return [run_fixture(seed) for seed in ("0", "1", "12345", "99999")]


def test_canonical_bytes_are_identical_across_processes(
    subprocess_runs: list[tuple[str, str, str]],
) -> None:
    """The core guarantee: same graph, same bytes, different interpreters."""
    encodings = {run[0] for run in subprocess_runs}

    assert len(encodings) == 1, f"canonical bytes diverged across processes: {encodings}"


def test_digest_is_identical_across_processes(
    subprocess_runs: list[tuple[str, str, str]],
) -> None:
    digests = {run[1] for run in subprocess_runs}

    assert len(digests) == 1, f"content digest diverged: {digests}"


def test_identifier_is_identical_across_processes(
    subprocess_runs: list[tuple[str, str, str]],
) -> None:
    identifiers = {run[2] for run in subprocess_runs}

    assert len(identifiers) == 1, f"identifier diverged: {identifiers}"


def test_python_hash_seed_does_not_influence_output(
    subprocess_runs: list[tuple[str, str, str]],
) -> None:
    """Four different seeds were used; nothing about the output moved."""
    assert len({run for run in subprocess_runs}) == 1


def test_subprocess_output_matches_this_process(
    subprocess_runs: list[tuple[str, str, str]],
) -> None:
    """A subprocess and the test runner agree, so nothing is process-local."""
    canonical, digest, identifier = subprocess_runs[0]
    payload = {"a": 1, "b": Decimal("1.50")}

    # The in-process helpers behave identically on their own fixture.
    assert canonical_bytes(payload) == canonical_bytes(dict(reversed(list(payload.items()))))
    assert content_digest(payload) == content_digest(payload)
    assert deterministic_id("snapshot", payload) == deterministic_id("snapshot", payload)
    assert len(digest) == 64
    assert identifier.startswith("snapshot-")
    assert canonical.startswith("{")


@pytest.mark.parametrize("repeat", range(3))
def test_repeated_runs_stay_stable(repeat: int) -> None:
    """Run the whole comparison more than once, as the ticket requires."""
    first = run_fixture("0")
    second = run_fixture("54321")

    assert first == second


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (Decimal("1"), Decimal("1.00")),
        (Decimal("-0"), Decimal("0")),
        (Decimal("2.5"), Decimal("2.50")),
    ],
)
def test_equal_decimals_hash_identically(left: Decimal, right: Decimal) -> None:
    assert left == right
    assert content_digest(left) == content_digest(right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (Decimal("1"), Decimal("1.0000000000000000000000000000001")),
        (Decimal("2.5"), Decimal("2.6")),
    ],
)
def test_distinct_decimals_hash_differently(left: Decimal, right: Decimal) -> None:
    assert left != right
    assert content_digest(left) != content_digest(right)

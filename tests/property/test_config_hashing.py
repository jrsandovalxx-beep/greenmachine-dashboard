"""The semantic ``config_hash`` is stable across processes and hash seeds.

Byte-identity inside one interpreter proves little: the real hazards are
``PYTHONHASHSEED`` randomisation and dict ordering. These tests recompute the
hash of the same configuration in separate interpreters, under deliberately
different seeds, and confirm nothing about the digest moves — and that a
semantically equivalent but textually different file lands on the same digest in
a fresh process too.

No Hypothesis here — GM-008 owns property-test framework setup, so this uses
deterministic parameterisation and subprocesses only.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from greenmachine.config import config_hash, load_config_text, source_digest

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "config"
    / "valid"
    / "complete_synthetic.yaml"
)

# Recomputes the identity in a fresh interpreter from a file path, so nothing is
# inherited from this process.
_PROBE = (
    "import sys\n"
    "from greenmachine.config import load_config_text, config_hash, source_digest\n"
    "text = open(sys.argv[1], encoding='utf-8').read()\n"
    "print(config_hash(load_config_text(text)).value)\n"
    "print(source_digest(text))\n"
)

SEEDS = ("0", "1", "12345", "99999")


def run_probe(path: Path, seed: str) -> tuple[str, str]:
    """Return ``(config_hash, source_digest)`` computed in a fresh interpreter."""
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = seed
    from tests.network_guard.guarded_child import guarded_python_command

    completed = subprocess.run(
        guarded_python_command("-c", _PROBE, str(path)),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    config_digest, src_digest = completed.stdout.strip().splitlines()
    return config_digest, src_digest


@pytest.fixture(scope="module")
def probe_runs() -> list[tuple[str, str]]:
    """The fixture hashed in four independent interpreters, different seeds each."""
    return [run_probe(FIXTURE, seed) for seed in SEEDS]


def test_config_hash_is_identical_across_processes(probe_runs: list[tuple[str, str]]) -> None:
    digests = {config_digest for config_digest, _ in probe_runs}

    assert len(digests) == 1, f"config_hash diverged across processes: {digests}"


def test_python_hash_seed_does_not_influence_config_hash(
    probe_runs: list[tuple[str, str]],
) -> None:
    """Four different seeds were used; the digest did not move for any of them."""
    assert len({run for run in probe_runs}) == 1


def test_source_digest_is_identical_across_processes(probe_runs: list[tuple[str, str]]) -> None:
    fingerprints = {src_digest for _, src_digest in probe_runs}

    assert len(fingerprints) == 1, f"source_digest diverged across processes: {fingerprints}"


def test_the_subprocess_and_this_process_agree(probe_runs: list[tuple[str, str]]) -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    in_process = (config_hash(load_config_text(text)).value, source_digest(text))

    assert probe_runs[0] == in_process


@pytest.mark.parametrize("repeat", range(3))
def test_repeated_cross_seed_runs_stay_stable(repeat: int) -> None:
    """Run the whole comparison more than once, as the ticket requires."""
    assert run_probe(FIXTURE, "0") == run_probe(FIXTURE, "54321")


def test_an_equivalent_variant_hashes_the_same_in_a_fresh_process(tmp_path: Path) -> None:
    """Comments added and newlines switched to CRLF: a different file, same rules."""
    original = FIXTURE.read_text(encoding="utf-8")
    variant_text = original.replace(
        "schema_version: 1", "# an added banner comment\nschema_version: 1  # inline note"
    ).replace("\n", "\r\n")
    variant = tmp_path / "variant.yaml"
    variant.write_bytes(variant_text.encode("utf-8"))

    canonical_hash = run_probe(FIXTURE, "0")[0]
    variant_hash = run_probe(variant, "7")[0]

    assert variant_hash == canonical_hash

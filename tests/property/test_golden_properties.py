"""Property tests for the GM-008 golden harness, under the deterministic CI profile.

Covers the diff engine's reflexivity and sensitivity, discovery-order
independence from directory creation order, repeated-run stability, malformed
manifest rejection — and asserts the deterministic Hypothesis configuration
itself. Strategies generate abstract canonical structures; no baseball
threshold appears here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from tests.golden.runner import (
    CASES_ROOT,
    GoldenCaseError,
    canonical_structure_differences,
    discover_cases,
    run_case,
)
from tests.golden.stub_scorer import score_snapshot

REPO_ROOT = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------
# The deterministic Hypothesis configuration is itself under test
# --------------------------------------------------------------------------


FIXED_SEED = 20260724


def test_ci_profile_is_registered_with_deterministic_settings() -> None:
    profile = settings.get_profile("greenmachine-ci")
    # derandomize stays False deliberately: Hypothesis prefers derandomization
    # over a forced seed, and the configured mechanism is the explicit fixed
    # seed 20260724 supplied via --hypothesis-seed in pyproject addopts.
    assert profile.derandomize is False, "the explicit fixed seed must drive generation"
    assert profile.database is None, "examples must be generated in memory only"
    assert profile.deadline is None, "no wall-clock dependence in pass/fail decisions"
    assert profile.max_examples == 50
    # Pinned explicitly, and pinned EMPTY. Hypothesis fills an unspecified
    # setting from the active built-in profile, and on a hosted runner that
    # profile suppresses HealthCheck.too_slow -- so leaving this unset made the
    # effective value depend on the environment. The explicit empty tuple blocks
    # that inheritance and states the accepted ADR-0008 policy: GreenMachine
    # suppresses no health check anywhere. This must stay an equality against
    # one tuple; accepting either shape would re-admit the environment
    # dependence it exists to rule out.
    assert tuple(profile.suppress_health_check) == (), (
        "every Hypothesis health check stays active, in every environment"
    )


def test_exploratory_override_profile_is_registered_but_not_default() -> None:
    profile = settings.get_profile("greenmachine-exploratory")
    assert profile.derandomize is False
    assert profile.database is None


def test_active_settings_match_the_loaded_profile(loaded_hypothesis_profile: str) -> None:
    active = settings()
    loaded = settings.get_profile(loaded_hypothesis_profile)
    assert active.derandomize == loaded.derandomize
    assert active.database == loaded.database
    assert active.deadline == loaded.deadline
    assert active.max_examples == loaded.max_examples


def test_repository_default_seed_is_20260724() -> None:
    """pyproject addopts configures Hypothesis's pytest seed option explicitly."""
    import tomllib

    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    addopts = pyproject["tool"]["pytest"]["ini_options"]["addopts"]
    assert f"--hypothesis-seed={FIXED_SEED}" in addopts


def test_fixed_seed_20260724_is_active(configured_hypothesis_seed: str | None) -> None:
    """The seed option reached Hypothesis: global_force_seed is 20260724."""
    if configured_hypothesis_seed != str(FIXED_SEED):
        pytest.skip(
            f"deliberate --hypothesis-seed override active "
            f"({configured_hypothesis_seed!r}); the CI default is {FIXED_SEED}"
        )
    from hypothesis import core

    assert core.global_force_seed == FIXED_SEED


_SEED_PROBE_PROGRAM = (
    "import hashlib\n"
    "from hypothesis import core, given, settings, strategies as st\n"
    "settings.register_profile('probe', derandomize=False, database=None,\n"
    "                          deadline=None, max_examples=25)\n"
    "settings.load_profile('probe')\n"
    "core.global_force_seed = {seed}\n"
    "drawn = []\n"
    "@given(st.integers(), st.text())\n"
    "def probe(number, text):\n"
    "    drawn.append((number, text))\n"
    "probe()\n"
    "print(hashlib.sha256(repr(drawn).encode('utf-8')).hexdigest())\n"
)


def _seed_probe(seed: int) -> str:
    """One fresh process drawing an example stream under the given forced seed."""
    from tests.network_guard.guarded_child import guarded_python_command

    completed = subprocess.run(
        guarded_python_command("-c", _SEED_PROBE_PROGRAM.format(seed=seed)),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def test_fixed_seed_examples_are_stable_across_subprocesses() -> None:
    """Two fresh processes under seed 20260724 draw identical example streams,
    and a different seed draws a different stream — the seed genuinely drives
    generation through the same mechanism the pytest plugin uses."""
    first = _seed_probe(FIXED_SEED)
    second = _seed_probe(FIXED_SEED)
    other = _seed_probe(999)

    assert first == second
    assert first != other


# --------------------------------------------------------------------------
# Strategies: abstract canonical JSON structures (no baseball values)
# --------------------------------------------------------------------------

scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**6), max_value=10**6),
    st.text(max_size=12),
)

structures = st.recursive(
    scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(min_size=1, max_size=8), children, max_size=4),
    ),
    max_leaves=20,
)


def first_leaf_path(structure: object) -> list[object] | None:
    """Deterministic walk (sorted keys, ascending indexes) to the first scalar leaf."""
    if isinstance(structure, dict):
        for key in sorted(structure):
            path = first_leaf_path(structure[key])
            if path is not None:
                return [key, *path]
        return None
    if isinstance(structure, list):
        for index, item in enumerate(structure):
            path = first_leaf_path(item)
            if path is not None:
                return [index, *path]
        return None
    return []


def replace_leaf(structure: object, path: list[object]) -> object:
    """Return a copy of ``structure`` with the leaf at ``path`` changed."""
    if not path:
        return "synthetic-mutated-leaf" if structure != "synthetic-mutated-leaf" else 0
    head, *rest = path
    if isinstance(structure, dict):
        copied = dict(structure)
        copied[head] = replace_leaf(copied[head], rest)  # type: ignore[index]
        return copied
    assert isinstance(structure, list)
    copied_list = list(structure)
    copied_list[head] = replace_leaf(copied_list[head], rest)  # type: ignore[index]
    return copied_list


# --------------------------------------------------------------------------
# Diff-engine properties
# --------------------------------------------------------------------------


@given(structure=structures)
def test_a_canonical_structure_has_no_diff_against_itself(structure: object) -> None:
    assert canonical_structure_differences(structure, structure) == ()


@given(structure=structures)
def test_a_changed_leaf_produces_at_least_one_deterministic_field_path(
    structure: object,
) -> None:
    path = first_leaf_path(structure)
    assume(path is not None)
    assert path is not None
    mutated = replace_leaf(structure, path)

    first = canonical_structure_differences(structure, mutated)
    second = canonical_structure_differences(structure, mutated)

    assert len(first) >= 1
    assert first == second, "diffing must be deterministic"
    assert all(isinstance(difference.path, str) for difference in first)


@given(structure=structures, other=structures)
def test_diffing_is_deterministic_for_arbitrary_pairs(structure: object, other: object) -> None:
    first = canonical_structure_differences(structure, other)
    second = canonical_structure_differences(structure, other)
    assert first == second
    if structure == other:
        assert first == ()


# --------------------------------------------------------------------------
# Discovery-order and repeated-run properties
# --------------------------------------------------------------------------

_CASE_IDS = (
    "synthetic-order-alpha",
    "synthetic-order-bravo",
    "synthetic-order-charlie",
)
_TEMPLATE_CASE = CASES_ROOT / "synthetic-recent-evaluated"


def _write_reordered_tree(root: Path, creation_order: tuple[str, ...]) -> None:
    for position, case_id in enumerate(creation_order):
        # Directory names deliberately disagree with case ids so ordering by
        # name and ordering by id are distinguishable.
        directory = root / f"dir-{position}-{case_id}"
        directory.mkdir()
        shutil.copyfile(_TEMPLATE_CASE / "input_snapshot.json", directory / "input_snapshot.json")
        shutil.copyfile(
            _TEMPLATE_CASE / "expected_grade_result.json",
            directory / "expected_grade_result.json",
        )
        manifest = {
            "case_id": case_id,
            "config_version_identifier": "synthetic-fixture-0",
            "window_profile": "RECENT_7D",
            "snapshot_file": "input_snapshot.json",
            "expected_file": "expected_grade_result.json",
        }
        (directory / "case.json").write_bytes(json.dumps(manifest).encode("utf-8"))


@settings(max_examples=6)
@given(creation_order=st.permutations(_CASE_IDS))
def test_discovery_order_is_independent_of_directory_creation_order(
    creation_order: tuple[str, ...],
) -> None:
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "cases"
        root.mkdir()
        _write_reordered_tree(root, tuple(creation_order))
        cases = discover_cases(root)
        assert [case.case_id for case in cases] == sorted(_CASE_IDS)


@settings(max_examples=6)
@given(selector=st.integers(min_value=0, max_value=2))
def test_repeated_deterministic_runs_produce_the_same_result(selector: int) -> None:
    cases = discover_cases(CASES_ROOT)
    case = cases[selector % len(cases)]
    first = run_case(case, score_snapshot)
    second = run_case(case, score_snapshot)
    assert first == second
    assert first.passed


# --------------------------------------------------------------------------
# Malformed manifest values fail with the focused case error
# --------------------------------------------------------------------------

_VALID_PROFILES = frozenset({"RECENT_7D", "LONG_TERM_2Y"})

invalid_profiles = st.text(min_size=1, max_size=16).filter(lambda text: text not in _VALID_PROFILES)
blank_texts = st.text(alphabet=" \t\n", max_size=6)


def _write_manifest_case(root: Path, manifest: dict[str, object]) -> Path:
    directory = root / "manifest-case"
    directory.mkdir(parents=True)
    shutil.copyfile(_TEMPLATE_CASE / "input_snapshot.json", directory / "input_snapshot.json")
    shutil.copyfile(
        _TEMPLATE_CASE / "expected_grade_result.json",
        directory / "expected_grade_result.json",
    )
    (directory / "case.json").write_bytes(json.dumps(manifest).encode("utf-8"))
    return directory


@settings(max_examples=15)
@given(profile=invalid_profiles)
def test_malformed_profile_values_fail_with_a_focused_case_error(profile: str) -> None:
    from tests.golden.runner import load_case

    manifest: dict[str, object] = {
        "case_id": "synthetic-malformed",
        "config_version_identifier": "synthetic-fixture-0",
        "window_profile": profile,
        "snapshot_file": "input_snapshot.json",
        "expected_file": "expected_grade_result.json",
    }
    with tempfile.TemporaryDirectory() as scratch:
        directory = _write_manifest_case(Path(scratch), manifest)
        try:
            load_case(directory)
        except GoldenCaseError as error:
            assert "window_profile" in str(error)
        else:
            raise AssertionError(f"profile {profile!r} should have been rejected")


@settings(max_examples=15)
@given(case_id=blank_texts)
def test_blank_case_ids_fail_with_a_focused_case_error(case_id: str) -> None:
    from tests.golden.runner import load_case

    manifest: dict[str, object] = {
        "case_id": case_id,
        "config_version_identifier": "synthetic-fixture-0",
        "window_profile": "RECENT_7D",
        "snapshot_file": "input_snapshot.json",
        "expected_file": "expected_grade_result.json",
    }
    with tempfile.TemporaryDirectory() as scratch:
        directory = _write_manifest_case(Path(scratch), manifest)
        try:
            load_case(directory)
        except GoldenCaseError as error:
            assert "case_id" in str(error)
        else:
            raise AssertionError("a blank case_id should have been rejected")

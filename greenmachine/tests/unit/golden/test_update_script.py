"""``scripts/update_goldens.py`` — exercised only against temporary copied trees.

Every scenario copies the committed golden cases into ``tmp_path`` first; the
repository's committed cases are never touched. The alternate scorer below is
importable by the script subprocess via its explicit ``module:function`` path.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from tests.golden.runner import CASES_ROOT
from tests.golden.stub_scorer import score_snapshot
from tests.network_guard.guarded_child import guarded_python_command

from greenmachine.domain import EvaluatedGradeResult, InputSnapshot, NotEvaluableGradeResult

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "update_goldens.py"

STUB_PATH = "tests.golden.stub_scorer:score_snapshot"
ALTERNATE_PATH = "tests.unit.golden.test_update_script:alternate_scorer"
BROKEN_PATH = "tests.unit.golden.test_update_script:broken_scorer"

RECENT = "synthetic-recent-evaluated"
LONG_TERM = "synthetic-long-term-evaluated"
NOT_EVALUABLE = "synthetic-recent-not-evaluable"


def alternate_scorer(
    snapshot: InputSnapshot, config_version_identifier: str, /
) -> EvaluatedGradeResult | NotEvaluableGradeResult:
    """A second deterministic test scorer whose evaluated output differs from the stub."""
    result = score_snapshot(snapshot, config_version_identifier)
    if isinstance(result, EvaluatedGradeResult):
        return replace(result, total_score=Decimal("7.777"))
    return result


def broken_scorer(snapshot: InputSnapshot, config_version_identifier: str, /) -> object:
    """Returns an unsupported type; the script must refuse to write it."""
    return None


def copy_cases(tmp_path: Path) -> Path:
    root = tmp_path / "cases"
    shutil.copytree(CASES_ROOT, root)
    return root


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def run_script(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the script in a guarded subprocess, from an unrelated working directory."""
    return subprocess.run(
        guarded_python_command(str(SCRIPT), *arguments),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=120,
    )


# --------------------------------------------------------------------------
# Targeted updates
# --------------------------------------------------------------------------


def test_only_the_targeted_expected_file_changes(tmp_path: Path) -> None:
    root = copy_cases(tmp_path)
    before = tree_bytes(root)

    completed = run_script(
        RECENT, "--scorer", ALTERNATE_PATH, "--cases-root", str(root), cwd=tmp_path
    )

    assert completed.returncode == 0, completed.stderr
    assert f"updated {RECENT}" in completed.stdout
    after = tree_bytes(root)
    changed = {name for name in before if before[name] != after[name]}
    assert changed == {f"{RECENT}/expected_grade_result.json"}
    assert set(before) == set(after)  # no file created or removed
    assert b"7.777" in after[f"{RECENT}/expected_grade_result.json"]


def test_case_json_and_snapshot_remain_byte_identical(tmp_path: Path) -> None:
    root = copy_cases(tmp_path)
    before = tree_bytes(root)

    completed = run_script(
        RECENT, "--scorer", ALTERNATE_PATH, "--cases-root", str(root), cwd=tmp_path
    )

    assert completed.returncode == 0, completed.stderr
    after = tree_bytes(root)
    assert after[f"{RECENT}/case.json"] == before[f"{RECENT}/case.json"]
    assert after[f"{RECENT}/input_snapshot.json"] == before[f"{RECENT}/input_snapshot.json"]
    for case_id in (LONG_TERM, NOT_EVALUABLE):
        for name in ("case.json", "input_snapshot.json", "expected_grade_result.json"):
            assert after[f"{case_id}/{name}"] == before[f"{case_id}/{name}"]


def test_multiple_targets_update_together(tmp_path: Path) -> None:
    root = copy_cases(tmp_path)
    before = tree_bytes(root)

    completed = run_script(
        RECENT, LONG_TERM, "--scorer", ALTERNATE_PATH, "--cases-root", str(root), cwd=tmp_path
    )

    assert completed.returncode == 0, completed.stderr
    after = tree_bytes(root)
    changed = {name for name in before if before[name] != after[name]}
    assert changed == {
        f"{RECENT}/expected_grade_result.json",
        f"{LONG_TERM}/expected_grade_result.json",
    }


def test_repeated_update_with_the_same_scorer_is_byte_identical(tmp_path: Path) -> None:
    root = copy_cases(tmp_path)

    first = run_script(RECENT, "--scorer", ALTERNATE_PATH, "--cases-root", str(root), cwd=tmp_path)
    assert first.returncode == 0, first.stderr
    after_first = tree_bytes(root)

    second = run_script(RECENT, "--scorer", ALTERNATE_PATH, "--cases-root", str(root), cwd=tmp_path)
    assert second.returncode == 0, second.stderr
    assert f"unchanged {RECENT}" in second.stdout
    assert tree_bytes(root) == after_first


def test_stub_scorer_reproduces_the_committed_goldens_exactly(tmp_path: Path) -> None:
    """The committed expected files are precisely the stub's output."""
    root = copy_cases(tmp_path)
    before = tree_bytes(root)

    completed = run_script(
        RECENT,
        LONG_TERM,
        NOT_EVALUABLE,
        "--scorer",
        STUB_PATH,
        "--cases-root",
        str(root),
        cwd=tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.count("unchanged") == 3
    assert tree_bytes(root) == before


# --------------------------------------------------------------------------
# Refusals, all without modifying any file
# --------------------------------------------------------------------------


def test_unknown_target_fails_without_modifying_any_file(tmp_path: Path) -> None:
    root = copy_cases(tmp_path)
    before = tree_bytes(root)

    completed = run_script(
        "no-such-case", "--scorer", ALTERNATE_PATH, "--cases-root", str(root), cwd=tmp_path
    )

    assert completed.returncode != 0
    assert "no-such-case" in completed.stderr
    assert tree_bytes(root) == before


def test_mixed_known_and_unknown_targets_write_nothing(tmp_path: Path) -> None:
    root = copy_cases(tmp_path)
    before = tree_bytes(root)

    completed = run_script(
        RECENT,
        "no-such-case",
        "--scorer",
        ALTERNATE_PATH,
        "--cases-root",
        str(root),
        cwd=tmp_path,
    )

    assert completed.returncode != 0
    assert tree_bytes(root) == before


def test_duplicate_requested_ids_are_rejected(tmp_path: Path) -> None:
    root = copy_cases(tmp_path)
    before = tree_bytes(root)

    completed = run_script(
        RECENT, RECENT, "--scorer", ALTERNATE_PATH, "--cases-root", str(root), cwd=tmp_path
    )

    assert completed.returncode != 0
    assert "duplicate" in completed.stderr
    assert tree_bytes(root) == before


def test_invalid_scorer_module_fails_without_modifying_any_file(tmp_path: Path) -> None:
    root = copy_cases(tmp_path)
    before = tree_bytes(root)

    completed = run_script(
        RECENT, "--scorer", "no.such.module:scorer", "--cases-root", str(root), cwd=tmp_path
    )

    assert completed.returncode != 0
    assert "could not be imported" in completed.stderr
    assert tree_bytes(root) == before


def test_invalid_scorer_attribute_fails_without_modifying_any_file(tmp_path: Path) -> None:
    root = copy_cases(tmp_path)
    before = tree_bytes(root)

    completed = run_script(
        RECENT,
        "--scorer",
        "tests.golden.stub_scorer:no_such_function",
        "--cases-root",
        str(root),
        cwd=tmp_path,
    )

    assert completed.returncode != 0
    assert "does not exist" in completed.stderr
    assert tree_bytes(root) == before


def test_malformed_scorer_specification_is_rejected(tmp_path: Path) -> None:
    root = copy_cases(tmp_path)
    before = tree_bytes(root)

    completed = run_script(
        RECENT, "--scorer", "not-an-import-path", "--cases-root", str(root), cwd=tmp_path
    )

    assert completed.returncode != 0
    assert "module:function" in completed.stderr
    assert tree_bytes(root) == before


def test_scorer_returning_an_unsupported_type_writes_nothing(tmp_path: Path) -> None:
    root = copy_cases(tmp_path)
    before = tree_bytes(root)

    completed = run_script(RECENT, "--scorer", BROKEN_PATH, "--cases-root", str(root), cwd=tmp_path)

    assert completed.returncode != 0
    assert "must return exactly" in completed.stderr
    assert tree_bytes(root) == before


def test_missing_target_arguments_are_rejected(tmp_path: Path) -> None:
    """There is no implicit update-every-case default."""
    root = copy_cases(tmp_path)
    before = tree_bytes(root)

    completed = run_script("--scorer", ALTERNATE_PATH, "--cases-root", str(root), cwd=tmp_path)

    assert completed.returncode != 0
    assert tree_bytes(root) == before


# --------------------------------------------------------------------------
# Normal pytest execution never updates a golden
# --------------------------------------------------------------------------


def test_running_the_golden_suite_never_updates_a_committed_golden(tmp_path: Path) -> None:
    before = tree_bytes(CASES_ROOT)

    completed = subprocess.run(
        guarded_python_command("-m", "pytest", "tests/golden", "-q", "-p", "no:cacheprovider"),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=300,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert tree_bytes(CASES_ROOT) == before

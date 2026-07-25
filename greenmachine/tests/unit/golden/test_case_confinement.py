"""Case-root confinement: a discovered golden case never escapes its root.

Symlink scenarios are exercised where the platform permits creating directory
symlinks (on Windows this needs Developer Mode or elevation); everywhere else
the containment helper is tested directly, which is the same code path
discovery and the update script rely on.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from tests.golden.runner import (
    CASES_ROOT,
    GoldenCaseError,
    contained_case_directory,
    discover_cases,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
UPDATE_SCRIPT = REPO_ROOT / "scripts" / "update_goldens.py"

RECENT_CASE_ID = "synthetic-recent-evaluated"


def _try_directory_symlink(link: Path, target: Path) -> bool:
    """Create a directory symlink, reporting whether the platform allows it."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        return False
    return True


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# --------------------------------------------------------------------------
# The containment helper, tested directly (platform-independent)
# --------------------------------------------------------------------------


def test_contained_ordinary_directory_is_accepted(tmp_path: Path) -> None:
    root = tmp_path / "cases"
    inside = root / "ordinary-case"
    inside.mkdir(parents=True)

    resolved = contained_case_directory(inside, root)

    assert resolved == inside.resolve()
    assert resolved.is_relative_to(root.resolve())


def test_directory_outside_the_root_is_rejected_with_a_focused_error(
    tmp_path: Path,
) -> None:
    """An escape raises GoldenCaseError — never a raw ValueError or OSError."""
    root = tmp_path / "cases"
    root.mkdir()
    outside = tmp_path / "elsewhere" / "escaped-case"
    outside.mkdir(parents=True)

    with pytest.raises(GoldenCaseError, match="not inside the case root") as failure:
        contained_case_directory(outside, root)
    assert not isinstance(failure.value, ValueError)
    assert "escaped-case" in str(failure.value)


def test_the_root_itself_is_not_a_case_directory(tmp_path: Path) -> None:
    root = tmp_path / "cases"
    root.mkdir()
    with pytest.raises(GoldenCaseError, match="not inside the case root"):
        contained_case_directory(root, root)


def test_non_path_arguments_are_rejected() -> None:
    with pytest.raises(GoldenCaseError, match="expects Paths"):
        contained_case_directory("not-a-path", CASES_ROOT)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Symlink integration (platform-conditional)
# --------------------------------------------------------------------------


def test_external_case_directory_symlink_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "cases"
    root.mkdir()
    shutil.copytree(CASES_ROOT / RECENT_CASE_ID, root / RECENT_CASE_ID)

    external_target = tmp_path / "outside" / "external-case"
    shutil.copytree(CASES_ROOT / RECENT_CASE_ID, external_target)
    link = root / "linked-case"
    if not _try_directory_symlink(link, external_target):
        pytest.skip("directory symlinks are unavailable on this platform")

    with pytest.raises(GoldenCaseError, match="symlink"):
        discover_cases(root)


def test_inside_root_symlink_is_also_rejected(tmp_path: Path) -> None:
    """Even a symlink resolving inside the root is refused: cases are regular dirs."""
    root = tmp_path / "cases"
    root.mkdir()
    real_case = root / RECENT_CASE_ID
    shutil.copytree(CASES_ROOT / RECENT_CASE_ID, real_case)
    link = root / "alias-case"
    if not _try_directory_symlink(link, real_case):
        pytest.skip("directory symlinks are unavailable on this platform")

    with pytest.raises(GoldenCaseError, match="symlink"):
        discover_cases(root)


def test_update_request_against_an_escaped_case_writes_nothing(tmp_path: Path) -> None:
    """The update script refuses an escaped tree, exits nonzero, changes no file."""
    root = tmp_path / "cases"
    root.mkdir()
    shutil.copytree(CASES_ROOT / RECENT_CASE_ID, root / RECENT_CASE_ID)
    external_target = tmp_path / "outside" / "external-case"
    shutil.copytree(CASES_ROOT / "synthetic-long-term-evaluated", external_target)
    link = root / "linked-case"
    if not _try_directory_symlink(link, external_target):
        pytest.skip("directory symlinks are unavailable on this platform")

    before_root = tree_bytes(root)
    before_external = tree_bytes(external_target)

    from tests.network_guard.guarded_child import guarded_python_command

    completed = subprocess.run(
        guarded_python_command(
            str(UPDATE_SCRIPT),
            RECENT_CASE_ID,
            "--scorer",
            "tests.golden.stub_scorer:score_snapshot",
            "--cases-root",
            str(root),
        ),
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=120,
    )

    assert completed.returncode != 0
    assert "symlink" in completed.stderr
    assert "Traceback" not in completed.stderr  # focused error, not a raw traceback
    assert tree_bytes(root) == before_root
    assert tree_bytes(external_target) == before_external


def test_update_boundary_rejects_an_escaped_case_on_every_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The script's own containment check fires even if discovery were bypassed.

    Platform-independent counterpart to the symlink test above: a GoldenCase
    whose directory lies outside the requested root is injected past discovery,
    and the update boundary must refuse it with a focused GoldenUpdateError —
    exiting nonzero and writing nothing.
    """
    from scripts.update_goldens import main
    from tests.golden import runner
    from tests.golden.runner import load_case

    external = tmp_path / "outside" / RECENT_CASE_ID
    shutil.copytree(CASES_ROOT / RECENT_CASE_ID, external)
    escaped_case = load_case(external)

    empty_root = tmp_path / "cases"
    empty_root.mkdir()

    monkeypatch.setattr(runner, "discover_cases", lambda root: (escaped_case,))
    before = tree_bytes(external)

    exit_code = main(
        [
            RECENT_CASE_ID,
            "--scorer",
            "tests.golden.stub_scorer:score_snapshot",
            "--cases-root",
            str(empty_root),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "not inside the case root" in captured.err
    assert "refusing to plan or write" in captured.err
    assert tree_bytes(external) == before


# --------------------------------------------------------------------------
# Normal discovery is unaffected
# --------------------------------------------------------------------------


def test_all_committed_cases_still_discover_normally() -> None:
    cases = discover_cases(CASES_ROOT)
    assert [case.case_id for case in cases] == [
        "synthetic-long-term-evaluated",
        "synthetic-recent-evaluated",
        "synthetic-recent-not-evaluable",
    ]
    resolved_root = CASES_ROOT.resolve()
    for case in cases:
        assert case.directory.is_relative_to(resolved_root)

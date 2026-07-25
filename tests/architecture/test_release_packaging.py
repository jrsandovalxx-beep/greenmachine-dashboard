"""Release-archive packaging contracts, tested against the real file plan.

The release builder is repo-owned (``scripts/build_release_archive.py``) so
its plan is importable here: every archive destination passes the **same**
path validator that bundle publication uses, and the exclusion rules (no
stale handoff, no failed-capture bundles, no caches/venvs/logs/databases/
editor files, no machine-local content) are proven on the plan itself.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_BUILDER_PATH = REPO_ROOT / "scripts" / "build_release_archive.py"

_spec = importlib.util.spec_from_file_location("build_release_archive", _BUILDER_PATH)
assert _spec is not None and _spec.loader is not None
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)

PLAN = builder.release_file_plan()
ARCNAMES = [arcname for arcname, _ in PLAN]


def test_the_plan_is_nonempty_and_covers_the_release() -> None:
    """Anti-vacuity: the rules below must be judging the real release."""
    assert len(PLAN) > 150
    for required in (
        "greenmachine/pyproject.toml",
        "greenmachine/src/greenmachine/ingestion/orchestration.py",
        "greenmachine/evidence/gm020_vertical_slice/prospective_run/manifest.json",
        "greenmachine/scripts/run_gm020_vertical_slice.py",
    ):
        assert required in ARCNAMES, required


def test_every_archive_path_passes_the_publication_path_validator() -> None:
    """The exact validator capture publication uses: no escapes, no absolute
    paths, no duplicates or normalized collisions."""
    from greenmachine.ingestion.archive import validate_bundle_paths

    validate_bundle_paths(ARCNAMES)


def test_no_stale_handoff_ships() -> None:
    assert not any("GREENMACHINE_HANDOFF" in arcname for arcname in ARCNAMES)


def test_no_failed_capture_bundle_ships() -> None:
    assert not any(
        "failed_run" in arcname or "failed_attempt" in arcname.lower() for arcname in ARCNAMES
    )


def test_no_cache_venv_log_database_or_editor_file_ships() -> None:
    banned_fragments = (
        "/.venv/",
        "/__pycache__/",
        "/.mypy_cache/",
        "/.pytest_cache/",
        "/.ruff_cache/",
        "/.hypothesis/",
        "/.idea/",
        "/.vscode/",
        "/.git/",
        "/cleanvenv/",
        "egg-info",
    )
    banned_suffixes = (".zip", ".pyc", ".log", ".db", ".sqlite", ".sqlite3", ".swp", ".tmp")
    banned_names = (".coverage", ".DS_Store", "Thumbs.db")
    for arcname in ARCNAMES:
        assert not any(fragment in arcname for fragment in banned_fragments), arcname
        assert not arcname.lower().endswith(banned_suffixes), arcname
        assert not arcname.endswith(banned_names), arcname


def test_no_machine_local_content_ships() -> None:
    violations = builder.validate_plan(PLAN)
    assert violations == []


def test_the_shipped_version_is_exactly_0_2_0() -> None:
    import greenmachine

    assert greenmachine.__version__ == "0.2.0"
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.2.0"' in pyproject

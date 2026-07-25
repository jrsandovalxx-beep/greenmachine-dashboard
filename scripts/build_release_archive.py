"""Build a GreenMachine release archive with a validated, deterministic plan.

Repo-owned so the packaging rules are themselves under test: the file plan
(exclusions, arcnames, forbidden-content scan) is importable, and every
archive destination passes the **same** bundle-relative path validator that
capture publication uses (`greenmachine.ingestion.archive.validate_bundle_paths`)
— no escaped, absolute, or colliding archive path can exist.

Excluded from every release archive:

* virtual environments, caches, coverage databases, logs, editor/IDE files
* previously built archives
* ``GREENMACHINE_HANDOFF.md`` — a stale working-session handoff,
  intentionally excluded from approved archives (never edited, never shipped)
* any transient failed-capture bundle (the sanitized incident document is the
  durable record)

Usage::

    python scripts/build_release_archive.py --output greenmachine-gm-020-r2.zip
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_PREFIX = "greenmachine"

EXCLUDED_DIRECTORIES = frozenset(
    {
        ".venv",
        "cleanvenv",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".hypothesis",
        "__pycache__",
        ".claude",
        ".idea",
        ".vscode",
        "greenmachine.egg-info",
    }
)
EXCLUDED_SUFFIXES = frozenset(
    {".zip", ".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3", ".swp", ".tmp"}
)
EXCLUDED_NAMES = frozenset({".coverage", ".DS_Store", "GREENMACHINE_HANDOFF.md", "Thumbs.db"})

# Anything matching these must never appear in a release archive: machine-local
# paths, usernames, or secret-shaped content. Assembled from fragments so this
# script (which ships in the archive) cannot match its own marker list.
FORBIDDEN_CONTENT_MARKERS = tuple(
    left + right
    for left, right in (
        (b"Jr", b"san"),
        (b"C:\\", b"Users"),
        (b"App", b"Data"),
        (b"api", b"_key"),
        (b"secret", b"_key"),
    )
)


def is_included(path: Path) -> bool:
    relative_parts = path.relative_to(REPO_ROOT).parts
    if set(relative_parts) & EXCLUDED_DIRECTORIES:
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if path.name in EXCLUDED_NAMES or path.name.startswith(".coverage."):
        return False
    if path.name.startswith("manual_review_"):
        return False  # temporary manual-review exports never ship
    is_failed_capture = "failed_run" in relative_parts or "failed_attempt" in path.name.lower()
    return not is_failed_capture


def release_file_plan() -> tuple[tuple[str, Path], ...]:
    """The complete deterministic (arcname, source) plan for a release archive."""
    files = sorted(path for path in REPO_ROOT.rglob("*") if path.is_file() and is_included(path))
    return tuple(
        (f"{ARCHIVE_PREFIX}/" + path.relative_to(REPO_ROOT).as_posix(), path) for path in files
    )


def validate_plan(plan: Sequence[tuple[str, Path]]) -> list[str]:
    """Path-validate every arcname with the publication validator and scan
    every file for forbidden content. Returns violations (empty = clean)."""
    from greenmachine.ingestion.archive import validate_bundle_paths

    validate_bundle_paths([arcname for arcname, _ in plan])

    violations: list[str] = []
    for arcname, source in plan:
        body = source.read_bytes()
        for marker in FORBIDDEN_CONTENT_MARKERS:
            if marker in body:
                violations.append(f"forbidden content {marker!r} in {arcname}")
    return violations


def main(argv: Sequence[str] | None = None) -> int:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    parser = argparse.ArgumentParser(prog="build_release_archive.py")
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)

    plan = release_file_plan()
    violations = validate_plan(plan)
    if violations:
        for violation in violations:
            print(violation, file=sys.stderr)
        return 1

    output: Path = arguments.output
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for arcname, source in plan:
            archive.write(source, arcname)
    print(f"wrote {output.name}: {len(plan)} files, {output.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Deliberately regenerate targeted golden expected results (GM-008, ADR-0008).

This is the **only** golden write path in the repository. The pytest suite
never rewrites a golden file — drift always fails the build — and regeneration
happens only when a developer runs this script with explicit targets::

    python scripts/update_goldens.py CASE_ID [CASE_ID ...] \\
        --scorer tests.golden.stub_scorer:score_snapshot

There is no "update everything" default: every case id must be named, the
scorer must be named as an explicit ``module:function`` import path (never
selected from the environment), and only each targeted case's expected result
file is rewritten — ``case.json`` and ``input_snapshot.json`` are never
touched. Output bytes come from the canonical GM-006 ``serialize_record``
encoder, so a regenerated file carries no timestamp, no current date, and no
machine-specific content: rerunning with the same scorer is byte-identical.

Failures (unknown case id, duplicate targets, invalid scorer path, a scorer
result that is not exactly an approved GradeResult variant) exit nonzero, and
all targets are validated and scored **before** any file is written.

``--cases-root`` exists so tests can exercise this script against a temporary
copy of the golden tree; it defaults to the committed ``tests/golden/cases/``.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _ensure_import_path() -> None:
    """Make ``tests.golden.runner`` importable when run as a script."""
    entry = str(_REPO_ROOT)
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="update_goldens.py",
        description=(
            "Deliberately regenerate the expected result file of explicitly targeted "
            "golden cases. Never rewrites case.json, input_snapshot.json, or an "
            "untargeted case."
        ),
    )
    parser.add_argument(
        "case_ids",
        nargs="+",
        metavar="CASE_ID",
        help="explicit golden case id(s) to regenerate; there is no update-all default",
    )
    parser.add_argument(
        "--scorer",
        required=True,
        metavar="MODULE:FUNCTION",
        help=(
            "explicit import path of the scorer callable, e.g. "
            "tests.golden.stub_scorer:score_snapshot"
        ),
    )
    parser.add_argument(
        "--cases-root",
        type=Path,
        default=None,
        metavar="PATH",
        help="golden case root to operate on (defaults to the committed tests/golden/cases)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    _ensure_import_path()
    from tests.golden.runner import GoldenCaseError, GoldenUpdateError

    arguments = _parse_arguments(argv)
    try:
        messages = _update(arguments)
    except (GoldenCaseError, GoldenUpdateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for message in messages:
        print(message)
    return 0


def _update(arguments: argparse.Namespace) -> list[str]:
    from tests.golden.runner import (
        CASES_ROOT,
        GoldenCase,
        GoldenUpdateError,
        discover_cases,
        score_case,
    )

    from greenmachine.evaluation import serialize_record

    requested: list[str] = list(arguments.case_ids)
    duplicates = sorted({case_id for case_id in requested if requested.count(case_id) > 1})
    if duplicates:
        raise GoldenUpdateError(f"duplicate case id(s) requested: {duplicates}")

    root: Path = arguments.cases_root if arguments.cases_root is not None else CASES_ROOT
    cases = discover_cases(root)
    by_id: dict[str, GoldenCase] = {case.case_id: case for case in cases}

    unknown = sorted(set(requested) - set(by_id))
    if unknown:
        raise GoldenUpdateError(f"unknown case id(s): {unknown}; available: {sorted(by_id)}")

    scorer = _import_scorer(arguments.scorer)

    # Phase 1 — score and serialize every target. Nothing is written until
    # every targeted case has produced a valid canonical result, so a failure
    # on any target modifies no file at all. Containment is re-validated at
    # this write boundary (belt and braces over discovery): a case directory
    # outside the resolved root is refused before anything is planned.
    resolved_root = root.resolve()
    planned: list[tuple[GoldenCase, bytes]] = []
    for case_id in sorted(requested):
        case = by_id[case_id]
        if not case.directory.is_relative_to(resolved_root):
            raise GoldenUpdateError(
                f"case '{case.case_id}' directory {case.directory} is not inside the case "
                f"root {resolved_root}; refusing to plan or write outside the root"
            )
        result = score_case(case, scorer)
        planned.append((case, serialize_record(result)))

    # Phase 2 — write only each targeted case's expected result file, and only
    # when its bytes actually change.
    messages: list[str] = []
    for case, data in planned:
        target = case.directory / case.expected_filename
        relative = target.relative_to(root.resolve()).as_posix()
        if target.read_bytes() == data:
            messages.append(f"unchanged {case.case_id}: {relative}")
            continue
        _atomic_replace(target, data)
        messages.append(f"updated {case.case_id}: {relative}")
    return messages


def _import_scorer(specification: str) -> object:
    """Import ``module:function`` explicitly, with focused failures."""
    import importlib

    from tests.golden.runner import GoldenUpdateError

    module_name, separator, attribute_path = specification.partition(":")
    if not separator or not module_name.strip() or not attribute_path.strip():
        raise GoldenUpdateError(
            f"--scorer must be an explicit 'module:function' import path, got {specification!r}"
        )
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise GoldenUpdateError(
            f"--scorer module {module_name!r} could not be imported: {exc}"
        ) from exc
    target: object = module
    for part in attribute_path.split("."):
        try:
            target = getattr(target, part)
        except AttributeError as exc:
            raise GoldenUpdateError(
                f"--scorer attribute {attribute_path!r} does not exist in module {module_name!r}"
            ) from exc
    if not callable(target):
        raise GoldenUpdateError(
            f"--scorer {specification!r} resolved to a non-callable {type(target).__name__}"
        )
    return target


def _atomic_replace(target: Path, data: bytes) -> None:
    """Write via a sibling temporary file and atomic rename."""
    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f"{target.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


if __name__ == "__main__":
    sys.exit(main())

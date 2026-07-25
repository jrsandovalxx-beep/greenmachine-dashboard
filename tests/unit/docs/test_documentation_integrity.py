"""GM-010 documentation and repository-closeout contract tests.

Keeps the documentation honest after the Sprint 1 closeout: every relative
markdown link resolves, the ADR index and the ADR files agree, ticket-referenced
open questions exist in the register, the reconciled documents carry no stale
Sprint 1 status, and the placeholder packages remain placeholder-only — so a
claim that "no scoring engine or production ingestion exists" cannot silently
rot.

`GREENMACHINE_HANDOFF.md` is deliberately outside the stale-status scan: it is
a frozen historical handoff document that GM-010 is prohibited from editing.
The enum/GLOSSARY drift rule is enforced separately (and has been since GM-002)
by ``tests/unit/domain/test_glossary_drift.py``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS = REPO_ROOT / "docs"
ADR_DIR = DOCS / "adr"
SRC_PACKAGE = REPO_ROOT / "src" / "greenmachine"

# The markdown files GM-010 owns the accuracy of. The frozen handoff is
# excluded by ruling; everything else with prose status is covered.
RECONCILED_DOCUMENTS = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "CHANGELOG.md",
    DOCS / "SPRINT_1_PLAN.md",
    DOCS / "ARCHITECTURE.md",
    DOCS / "SPRINT_1_CLOSEOUT.md",
    ADR_DIR / "README.md",
)


def markdown_files() -> list[Path]:
    """Every markdown file whose links must resolve.

    The frozen handoff is included here — link resolution is a mechanical
    check, not an edit — but excluded from the stale-status rules below.
    """
    files = sorted(DOCS.rglob("*.md"))
    files.extend(sorted(REPO_ROOT.glob("*.md")))
    files.append(REPO_ROOT / "tests" / "README.md")
    return files


_LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")


def relative_link_targets(path: Path) -> list[tuple[str, Path]]:
    """Every relative markdown link in ``path``, resolved against its folder."""
    targets: list[tuple[str, Path]] = []
    for raw_target in _LINK_PATTERN.findall(path.read_text(encoding="utf-8")):
        if raw_target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        file_part = raw_target.split("#", 1)[0]
        if not file_part:
            continue
        targets.append((raw_target, (path.parent / file_part)))
    return targets


@pytest.mark.parametrize(
    "path", markdown_files(), ids=lambda p: p.relative_to(REPO_ROOT).as_posix()
)
def test_every_relative_markdown_link_resolves(path: Path) -> None:
    broken = [raw for raw, resolved in relative_link_targets(path) if not resolved.exists()]
    assert broken == [], f"{path.name} has broken relative link(s): {broken}"


# --------------------------------------------------------------------------
# ADR integrity
# --------------------------------------------------------------------------

_REQUIRED_ADR_SECTIONS = ("## Context", "## Decision", "## Consequences")
_VALID_STATUS_PATTERN = re.compile(
    r"^\*\*Status:\*\* (Proposed|Accepted|Rejected|Superseded by ADR-\d{4})$", re.MULTILINE
)


def adr_files() -> list[Path]:
    return sorted(entry for entry in ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"))


def test_the_adr_set_is_exactly_0001_through_0008() -> None:
    numbers = sorted(path.name[:4] for path in adr_files())
    assert numbers == [f"{n:04d}" for n in range(1, 9)]


@pytest.mark.parametrize("path", adr_files(), ids=lambda p: p.name)
def test_every_adr_has_required_sections_and_a_valid_status(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for section in _REQUIRED_ADR_SECTIONS:
        assert section in text, f"{path.name} is missing the '{section}' section"
    assert _VALID_STATUS_PATTERN.search(text), f"{path.name} has no valid Status line"


def test_every_accepted_adr_is_marked_accepted() -> None:
    """Sprint 1 closed with all eight ADRs Accepted; none proposed or superseded."""
    for path in adr_files():
        text = path.read_text(encoding="utf-8")
        assert "**Status:** Accepted" in text, f"{path.name} is not Accepted"


def test_the_adr_index_lists_exactly_the_adr_files() -> None:
    index = (ADR_DIR / "README.md").read_text(encoding="utf-8")
    linked = set(re.findall(r"\]\((\d{4}-[^)]+\.md)\)", index))
    on_disk = {path.name for path in adr_files()}
    assert linked == on_disk


# --------------------------------------------------------------------------
# Open-question referential integrity
# --------------------------------------------------------------------------


def test_every_open_question_referenced_by_the_sprint_plan_exists() -> None:
    register = (DOCS / "OPEN_QUESTIONS.md").read_text(encoding="utf-8")
    registered = set(re.findall(r"### (Q\d+)\b", register))
    referenced = set(
        re.findall(r"\b(Q\d+)\b", (DOCS / "SPRINT_1_PLAN.md").read_text(encoding="utf-8"))
    )
    missing = sorted(referenced - registered, key=lambda q: int(q[1:]))
    assert missing == [], f"sprint plan references unregistered question(s): {missing}"


# --------------------------------------------------------------------------
# Stale Sprint 1 status must not return to the reconciled documents
# --------------------------------------------------------------------------

_STALE_PHRASES = (
    "Implementation continues with **GM-002 only**",
    "Implementation continues with GM-002",
    "GM-002 was not started",
    "GM-008 has not started",
    "no executable code yet",
    "Implementation has not started",
    "docs/adr/0005-golden-testing-strategy.md",
    # GM-010-r1: the repository-wide no-threshold claim was too broad — the
    # accurate boundary is "not implemented in src/ and no production
    # model-configuration version published" (MODEL_SPEC legitimately contains
    # specification rules and defaults).
    "exists anywhere in the repository",
    # GM-010-r1: overbroad network claim — only Python children launched via
    # the guarded bootstrap are covered, not arbitrary subprocesses.
    "(parent and child processes)",
    # GM-010-r1: the automatic 0.2.0 promise was never an approved versioning
    # decision; future version changes require an explicit ruling.
    "accompanies the next code-changing ticket",
    "lands with the next code-changing ticket",
    "deferred to the next code-changing ticket",
)


@pytest.mark.parametrize(
    "path", RECONCILED_DOCUMENTS, ids=lambda p: p.relative_to(REPO_ROOT).as_posix()
)
def test_no_reconciled_document_carries_stale_sprint_status(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    found = [phrase for phrase in _STALE_PHRASES if phrase in text]
    assert found == [], f"{path.name} contains stale Sprint 1 status: {found}"


def test_the_sprint_plan_and_architecture_declare_sprint_1_complete() -> None:
    plan = (DOCS / "SPRINT_1_PLAN.md").read_text(encoding="utf-8")
    architecture = (DOCS / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "SPRINT 1 COMPLETE" in plan
    assert "Sprint 1 is complete" in architecture
    assert "GM-020" in architecture  # the next milestone is named


# --------------------------------------------------------------------------
# GM-010-r1 precision markers
# --------------------------------------------------------------------------


def _normalized(path: Path) -> str:
    """Document text with all whitespace collapsed, so markdown line wraps
    cannot split a semantic marker phrase."""
    return " ".join(path.read_text(encoding="utf-8").split())


_BOUNDARY_DOCUMENTS = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "CHANGELOG.md",
    DOCS / "SPRINT_1_CLOSEOUT.md",
)


@pytest.mark.parametrize(
    "path", _BOUNDARY_DOCUMENTS, ids=lambda p: p.relative_to(REPO_ROOT).as_posix()
)
def test_boundary_documents_state_the_precise_implementation_boundary(path: Path) -> None:
    """The docs distinguish MODEL_SPEC rules from production config and src code."""
    text = _normalized(path)
    assert "model-configuration version has been published" in text
    assert "implemented in `src/`" in text
    assert "approved specification rules" in text


_SEQUENCE_DOCUMENTS = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "CHANGELOG.md",
    DOCS / "SPRINT_1_PLAN.md",
    DOCS / "ARCHITECTURE.md",
    DOCS / "SPRINT_1_CLOSEOUT.md",
)


@pytest.mark.parametrize(
    "path", _SEQUENCE_DOCUMENTS, ids=lambda p: p.relative_to(REPO_ROOT).as_posix()
)
def test_gm020_is_consistently_the_next_vertical_slice_milestone(path: Path) -> None:
    text = _normalized(path)
    assert "GM-020" in text
    assert "vertical slice" in text


def test_the_roadmap_places_the_ingestion_slice_before_the_grading_core() -> None:
    """The approved sequence supersedes the old grading-core-first phase order."""
    readme = _normalized(REPO_ROOT / "README.md")
    assert "approved post-Sprint-1 sequence" in readme
    assert readme.index("approved post-Sprint-1 sequence") < readme.index("Phase 3 — Grading core")
    for path in (DOCS / "ARCHITECTURE.md", DOCS / "SPRINT_1_CLOSEOUT.md"):
        assert "post-Sprint-1 sequence" in _normalized(path), path.name


def test_network_wording_names_the_parent_process_and_the_guarded_bootstrap() -> None:
    readme = _normalized(REPO_ROOT / "README.md")
    assert "parent pytest" in readme
    assert "guarded bootstrap" in readme


def test_no_automatic_version_bump_promise_remains() -> None:
    """0.1.0 stands; future version changes require an explicit per-ticket ruling."""
    for path in (REPO_ROOT / "CHANGELOG.md", DOCS / "SPRINT_1_PLAN.md"):
        text = _normalized(path)
        assert "not applied" in text, path.name
        assert "explicit ruling" in text, path.name


def test_the_closeout_records_the_exact_test_totals() -> None:
    closeout = _normalized(DOCS / "SPRINT_1_CLOSEOUT.md")
    assert "2,818 passed, 4 skipped" in closeout
    assert "2,817 passed, 4 skipped" in closeout
    assert "GREENMACHINE_HANDOFF.md" in closeout  # the one-test difference is explained


# --------------------------------------------------------------------------
# GM-020-r1 packaging contracts
# --------------------------------------------------------------------------


def test_the_readme_current_code_version_matches_the_package() -> None:
    """The README's active-current claims agree with the installed version."""
    import greenmachine

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert f"**Code version:** {greenmachine.__version__}" in readme
    assert f"| Code | {greenmachine.__version__} |" in readme


def test_no_failed_capture_raw_bundle_ships_in_evidence() -> None:
    """Failed-attempt raw bytes never ship: the behavior is covered by tests,
    and the incident record is a concise sanitized document instead."""
    evidence = REPO_ROOT / "evidence"
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in evidence.rglob("*")
        if "failed_run" in path.parts or "failed_attempt" in path.name.lower()
    ]
    assert offenders == []


# --------------------------------------------------------------------------
# The placeholder packages must stay placeholder-only
# --------------------------------------------------------------------------

# GM-020 implemented `ingestion`; GM-030 implemented `reporting` (the
# manual-review dashboard layer); GM-041 implemented `scoring`, whose purity is
# guarded by tests/architecture/test_scoring_boundaries.py instead. The
# remaining three stay placeholder-only until their tickets land (the
# Validation Layer is Sprint 2+). `validation` was an unguarded placeholder
# until GM-040 closed the gap.
PLACEHOLDER_PACKAGES = ("features", "validation", "cli")


def _is_docstring_only(path: Path) -> bool:
    module = ast.parse(path.read_text(encoding="utf-8"))
    if not module.body:
        return False
    first, *rest = module.body
    is_docstring = isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
    return is_docstring and rest == []


@pytest.mark.parametrize("package", PLACEHOLDER_PACKAGES)
def test_placeholder_packages_contain_no_behavior(package: str) -> None:
    """No unticketed implementation exists — structurally.

    Each deferred package holds only a docstring-only ``__init__`` module. Any
    function, class, or assignment appearing here means production
    implementation started without a ticket.
    """
    package_dir = SRC_PACKAGE / package
    files = sorted(package_dir.rglob("*.py"))
    expected = {package_dir / "__init__.py"}
    assert set(files) == expected, f"{package} gained unexpected module(s)"
    for path in files:
        assert _is_docstring_only(path), f"{path} is no longer docstring-only"

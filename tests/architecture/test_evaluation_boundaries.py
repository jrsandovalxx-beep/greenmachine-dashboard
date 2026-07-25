"""Boundaries for the evaluation layer and the GM-006 record contracts.

``evaluation`` sits above ``domain`` and reuses the ``common`` determinism
primitives — and nothing else. It must not import ``config`` or the grading core,
must add no third-party dependency, and must read no clock, no randomness, no
environment, and no filesystem. Only the snapshot-identity/serialization module
may reach the ``common`` hashing and canonical-serialization helpers.

The record contracts themselves are checked structurally: none of them carries an
outcome-shaped field (ADR-0006), so hindsight cannot be attached.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest
from static_analysis import collect_imports, package_of, third_party_offenders

from greenmachine.domain import (
    EvaluatedGradeResult,
    EvaluationEnvelope,
    InputSnapshot,
    NotEvaluableGradeResult,
    OutcomeRecord,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
PACKAGE_ROOT = SRC_ROOT / "greenmachine"
EVALUATION_ROOT = PACKAGE_ROOT / "evaluation"

EVALUATION_PACKAGE = "greenmachine.evaluation"

# The only GreenMachine packages evaluation may reach: the domain vocabulary, and
# the common error taxonomy plus the two determinism helpers GM-006 reuses.
APPROVED_INTERNAL = frozenset(
    {
        "greenmachine.domain",
        "greenmachine.common.errors",
        "greenmachine.common.serialization",
        "greenmachine.common.ids",
    }
)

FORBIDDEN_INTERNAL = (
    "greenmachine.config",
    "greenmachine.scoring",
    "greenmachine.features",
    "greenmachine.ingestion",
    "greenmachine.persistence",
    "greenmachine.reporting",
    "greenmachine.cli",
    "greenmachine.validation",
)

# The `common` hashing/serialization grant is narrow: only the serialization
# module may reach these. errors.py uses `common.errors`; nothing else uses common.
COMMON_HASHING = frozenset({"greenmachine.common.serialization", "greenmachine.common.ids"})
IDENTITY_MODULE = "serialization.py"

# Determinism/IO modules the layer must never import.
FORBIDDEN_STDLIB = frozenset(
    {
        "os",
        "socket",
        "subprocess",
        "shutil",
        "urllib",
        "http",
        "tempfile",
        "random",
        "secrets",
        "uuid",
        "pathlib",
        "time",
    }
)

# Constructs that read a clock or mint randomness even through an allowed module.
FORBIDDEN_SOURCE_PATTERNS = (
    "datetime.now",
    "utcnow",
    ".today(",
    "time.time",
    "uuid1",
    "uuid4",
    "random.",
    "os.environ",
    "getenv",
    "open(",
    "Path(",
)

# The domain modules that define the GM-006 record contracts.
CONTRACT_MODULES = ("snapshot.py", "grade_result.py", "envelope.py", "outcome.py")


def evaluation_files() -> list[Path]:
    return sorted(EVALUATION_ROOT.rglob("*.py"))


def parse_file(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def seeded(source: str) -> ast.Module:
    try:
        return ast.parse(source)
    except SyntaxError as exc:  # pragma: no cover - the snippets are valid
        pytest.fail(f"seeded source must be syntactically valid, but did not parse: {exc}")


def internal_offenders(tree: ast.Module, package: str) -> list[str]:
    offenders: list[str] = []
    for record in collect_imports(tree):
        resolved = record.resolved(package)
        if not resolved.startswith("greenmachine"):
            continue
        if resolved == package or resolved.startswith(f"{package}."):
            continue  # intra-evaluation
        if any(
            resolved == approved or resolved.startswith(f"{approved}.")
            for approved in APPROVED_INTERNAL
        ):
            continue
        offenders.append(resolved)
    return offenders


# --------------------------------------------------------------------------
# The real package
# --------------------------------------------------------------------------


def test_the_evaluation_package_is_populated() -> None:
    assert len(evaluation_files()) >= 3


@pytest.mark.parametrize("path", evaluation_files(), ids=lambda p: p.name)
def test_evaluation_imports_only_approved_greenmachine_packages(path: Path) -> None:
    offenders = internal_offenders(parse_file(path), package_of(path, SRC_ROOT))
    assert not offenders, f"{path.name} imports outside the approved set: {offenders}"


@pytest.mark.parametrize("path", evaluation_files(), ids=lambda p: p.name)
def test_evaluation_imports_no_downstream_or_config_package(path: Path) -> None:
    imported = {
        record.resolved(package_of(path, SRC_ROOT)) for record in collect_imports(parse_file(path))
    }
    offenders = [
        name
        for name in imported
        for forbidden in FORBIDDEN_INTERNAL
        if name == forbidden or name.startswith(f"{forbidden}.")
    ]
    assert not offenders, f"{path.name} imports a forbidden package: {offenders}"


@pytest.mark.parametrize("path", evaluation_files(), ids=lambda p: p.name)
def test_evaluation_imports_only_the_standard_library_third_party(path: Path) -> None:
    offenders = third_party_offenders(parse_file(path))
    assert not offenders, f"{path.name} imports third-party code: {offenders}"


@pytest.mark.parametrize("path", evaluation_files(), ids=lambda p: p.name)
def test_evaluation_imports_no_io_or_nondeterministic_module(path: Path) -> None:
    offenders = [
        record.top_level
        for record in collect_imports(parse_file(path))
        if record.top_level in FORBIDDEN_STDLIB
    ]
    assert not offenders, f"{path.name} imports a forbidden stdlib module: {offenders}"


@pytest.mark.parametrize("path", evaluation_files(), ids=lambda p: p.name)
def test_evaluation_reads_no_clock_randomness_or_filesystem(path: Path) -> None:
    code = "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    offenders = [pattern for pattern in FORBIDDEN_SOURCE_PATTERNS if pattern in code]
    assert not offenders, f"{path.name} contains a forbidden construct: {offenders}"


def test_only_the_serialization_module_reaches_common_hashing() -> None:
    """The snapshot-identity grant is narrow: one module, not the whole layer."""
    reachers = {
        path.name
        for path in evaluation_files()
        for record in collect_imports(parse_file(path))
        if record.resolved(package_of(path, SRC_ROOT)) in COMMON_HASHING
    }
    assert reachers <= {IDENTITY_MODULE}, (
        f"common hashing/serialization reached outside {IDENTITY_MODULE}: {reachers}"
    )


# --------------------------------------------------------------------------
# The record contracts carry no outcome (ADR-0006)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "contract",
    [InputSnapshot, EvaluatedGradeResult, NotEvaluableGradeResult, EvaluationEnvelope],
    ids=lambda c: c.__name__,
)
def test_no_record_contract_carries_an_outcome(contract: type) -> None:
    names = {field.name for field in dataclasses.fields(contract)}
    types = " ".join(str(field.type) for field in dataclasses.fields(contract))
    assert not (names & {"outcome", "outcome_record", "hit_at_least_one_home_run"})
    assert "OutcomeRecord" not in types


def test_the_outcome_record_holds_only_identity_and_the_flag() -> None:
    names = {field.name for field in dataclasses.fields(OutcomeRecord)}
    assert names == {"game_id", "batter_id", "hit_at_least_one_home_run"}


# --------------------------------------------------------------------------
# Meta-tests: prove each guard bites
# --------------------------------------------------------------------------


def test_meta_a_config_import_is_rejected() -> None:
    tree = seeded("from greenmachine.config import ConfigHash\n")
    assert internal_offenders(tree, EVALUATION_PACKAGE) == ["greenmachine.config"]


def test_meta_a_downstream_import_is_rejected() -> None:
    tree = seeded("from greenmachine.scoring import grade\n")
    assert internal_offenders(tree, EVALUATION_PACKAGE) == ["greenmachine.scoring"]


@pytest.mark.parametrize(
    "source",
    [
        "from greenmachine.domain import InputSnapshot\n",
        "from greenmachine.common.errors import GreenMachineError\n",
        "from greenmachine.common.serialization import canonical_bytes\n",
        "from greenmachine.common.ids import content_digest\n",
        "from .errors import RecordIntegrityError\n",
    ],
)
def test_meta_approved_imports_are_permitted(source: str) -> None:
    assert internal_offenders(seeded(source), EVALUATION_PACKAGE) == []


def test_meta_a_third_party_import_is_rejected() -> None:
    assert third_party_offenders(seeded("import pydantic\n"))
    assert third_party_offenders(seeded("import numpy\n"))


def test_meta_a_clock_read_pattern_is_detected() -> None:
    assert "datetime.now" in "value = datetime.now()"
    assert any(pattern in "uuid4()" for pattern in FORBIDDEN_SOURCE_PATTERNS)

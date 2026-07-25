"""Boundaries for the GM-041 grading engine.

`scoring` was a docstring-only placeholder until GM-041; the guards that kept
it empty are replaced here by guards that keep it *pure*. A `GradeResult` is a
function of `(frozen InputSnapshot, loaded GreenMachineConfig)` and nothing
else, so the package may reach the domain vocabulary, the configuration
contracts, and the common error taxonomy — and nothing else.

Purity is checked the same way the rest of the tree checks it: resolved
imports and canonical call targets, never bare syntax, with meta-tests proving
each guard bites. Floats are excluded twice over (no annotation, no
Decimal-from-float) because a single float would silently end the exact
arithmetic ADR-0002 requires.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from static_analysis import (
    clock_policy_violations,
    collect_imports,
    decimal_from_float_offenders,
    float_annotation_offenders,
    module_qualname,
    package_of,
    random_offenders,
    third_party_offenders,
    uuid_offenders,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
PACKAGE_ROOT = SRC_ROOT / "greenmachine"
SCORING_ROOT = PACKAGE_ROOT / "scoring"

SCORING_PACKAGE = "greenmachine.scoring"

# Everything the engine is permitted to reach: the neutral vocabulary it grades,
# the configuration that carries every threshold, the error root, and the
# numeric policy. Provider vocabulary, persistence, and presentation are all
# downstream or sideways.
#
# `greenmachine.common.numeric` is listed by MODULE, not as `greenmachine.common`
# as a whole: the engine must sum under the project-local Decimal context
# (ADR-0002) rather than the caller's mutable global one, and that is the only
# thing it may reach into `common` for besides the error root. Widening this to
# the whole package would silently admit the clock, serialization, and
# identifier modules — the meta-tests at the bottom of this file prove the
# approved module passes while its siblings stay rejected.
APPROVED_INTERNAL = frozenset(
    {
        "greenmachine.domain",
        "greenmachine.config",
        "greenmachine.common.errors",
        "greenmachine.common.numeric",
    }
)

FORBIDDEN_INTERNAL = (
    "greenmachine.ingestion",
    "greenmachine.persistence",
    "greenmachine.reporting",
    "greenmachine.features",
    "greenmachine.cli",
    "greenmachine.validation",
    "greenmachine.evaluation",
)

# I/O and non-determinism the engine must never import. `pathlib` and `time` are
# standard library and still forbidden: purity, not provenance, is the rule.
FORBIDDEN_STDLIB = frozenset(
    {
        "os",
        "socket",
        "subprocess",
        "shutil",
        "urllib",
        "http",
        "tempfile",
        "sqlite3",
        "random",
        "secrets",
        "uuid",
        "pathlib",
        "time",
        "logging",
    }
)

# Constructs that reach the outside world even through an allowed module.
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


def scoring_files() -> list[Path]:
    return sorted(SCORING_ROOT.rglob("*.py"))


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
            continue  # intra-scoring
        if any(
            resolved == approved or resolved.startswith(f"{approved}.")
            for approved in APPROVED_INTERNAL
        ):
            continue
        offenders.append(resolved)
    return offenders


# --------------------------------------------------------------------------
# The package is implemented, and stays inside its approved reach
# --------------------------------------------------------------------------


def test_the_scoring_package_is_populated() -> None:
    """GM-041 ended the placeholder era: an engine and its error taxonomy."""
    names = {path.name for path in scoring_files()}
    assert {"__init__.py", "engine.py", "errors.py"} <= names


@pytest.mark.parametrize("path", scoring_files(), ids=lambda p: p.name)
def test_scoring_imports_only_approved_greenmachine_packages(path: Path) -> None:
    offenders = internal_offenders(parse_file(path), package_of(path, SRC_ROOT))
    assert not offenders, f"{path.name} imports outside the approved set: {offenders}"


@pytest.mark.parametrize("path", scoring_files(), ids=lambda p: p.name)
def test_scoring_imports_no_sideways_or_downstream_package(path: Path) -> None:
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


# --------------------------------------------------------------------------
# Purity: no third party, no I/O, no clock, no randomness, no float
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", scoring_files(), ids=lambda p: p.name)
def test_scoring_imports_no_third_party_code(path: Path) -> None:
    """Covers pandas by construction (ADR: pandas stays outside grading — its
    float coercion and index magic would break ADR-0002 determinism)."""
    offenders = third_party_offenders(parse_file(path))
    assert not offenders, f"{path.name} imports third-party code: {offenders}"


@pytest.mark.parametrize("path", scoring_files(), ids=lambda p: p.name)
def test_scoring_imports_no_io_or_nondeterministic_module(path: Path) -> None:
    offenders = [
        record.top_level
        for record in collect_imports(parse_file(path))
        if record.top_level in FORBIDDEN_STDLIB
    ]
    assert not offenders, f"{path.name} imports a forbidden stdlib module: {offenders}"


@pytest.mark.parametrize("path", scoring_files(), ids=lambda p: p.name)
def test_scoring_reads_no_clock(path: Path) -> None:
    violations = clock_policy_violations(parse_file(path), module_qualname(path, SRC_ROOT))
    assert not violations, f"{path.name} reads wall-clock time: {violations}"


@pytest.mark.parametrize("path", scoring_files(), ids=lambda p: p.name)
def test_scoring_mints_no_randomness(path: Path) -> None:
    tree = parse_file(path)
    assert not random_offenders(tree), f"{path.name} imports a randomness source"
    assert not uuid_offenders(tree), f"{path.name} calls a non-deterministic UUID factory"


@pytest.mark.parametrize("path", scoring_files(), ids=lambda p: p.name)
def test_scoring_never_touches_a_float(path: Path) -> None:
    tree = parse_file(path)
    assert not float_annotation_offenders(tree), f"{path.name} annotates a float"
    assert not decimal_from_float_offenders(tree), f"{path.name} builds a Decimal from a float"


@pytest.mark.parametrize("path", scoring_files(), ids=lambda p: p.name)
def test_scoring_contains_no_escape_hatch_construct(path: Path) -> None:
    code = "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    offenders = [pattern for pattern in FORBIDDEN_SOURCE_PATTERNS if pattern in code]
    assert not offenders, f"{path.name} contains a forbidden construct: {offenders}"


# --------------------------------------------------------------------------
# No threshold may hide in code (development rule 4)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", scoring_files(), ids=lambda p: p.name)
def test_scoring_embeds_no_numeric_threshold(path: Path) -> None:
    """Every number the engine applies comes from the configuration.

    The only Decimal literals allowed in the package are the additive identity
    used to seed exact sums, so a bucket boundary or allocation cannot be
    smuggled in as a constant.
    """
    aliased = {
        alias
        for record in collect_imports(parse_file(path))
        if record.module == "decimal"
        for alias in record.names
    } | {"Decimal"}
    literals = [
        node.args[0].value
        for node in ast.walk(parse_file(path))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in aliased
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]
    offenders = [value for value in literals if value not in ("0",)]
    assert not offenders, f"{path.name} embeds a numeric constant: {offenders}"


# --------------------------------------------------------------------------
# Meta-tests: prove each guard bites
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "from greenmachine.ingestion import run_capture\n",
        "from greenmachine.reporting import load_dashboard\n",
        "from greenmachine.persistence import EvaluationStore\n",
        "from ..ingestion.operator import execute_real_slice\n",
    ],
)
def test_meta_a_forbidden_internal_import_is_rejected(source: str) -> None:
    assert internal_offenders(seeded(source), SCORING_PACKAGE)


@pytest.mark.parametrize(
    "source",
    [
        "from greenmachine.domain import InputSnapshot\n",
        "from greenmachine.config import GreenMachineConfig\n",
        "from greenmachine.common.errors import ErrorContext\n",
        "from greenmachine.common.numeric import add\n",
        "from .errors import ScoringConfigError\n",
    ],
)
def test_meta_approved_imports_are_permitted(source: str) -> None:
    assert internal_offenders(seeded(source), SCORING_PACKAGE) == []


@pytest.mark.parametrize(
    "source",
    [
        "from greenmachine.common.clock import SystemClock\n",
        "from greenmachine.common.serialization import canonical_bytes\n",
        "from greenmachine.common.ids import content_digest\n",
        "import greenmachine.common as common\n",
    ],
)
def test_meta_an_unrelated_common_import_is_still_rejected(source: str) -> None:
    """The numeric allowance is one module, not the whole ``common`` package.

    ``greenmachine.common.numeric`` is approved so the engine can sum under the
    project Decimal context (ADR-0002). Its siblings — the clock above all —
    stay forbidden, so the allowance can never be read as opening ``common``.
    """
    assert internal_offenders(seeded(source), SCORING_PACKAGE)


def test_meta_the_numeric_allowance_is_module_scoped_not_package_scoped() -> None:
    """The allowlist names the module; the bare package is deliberately absent."""
    assert "greenmachine.common.numeric" in APPROVED_INTERNAL
    assert "greenmachine.common" not in APPROVED_INTERNAL


def test_meta_a_pandas_import_is_rejected() -> None:
    assert third_party_offenders(seeded("import pandas as pd\n"))


def test_meta_a_clock_read_is_detected() -> None:
    tree = seeded("from datetime import datetime\n\ndef f():\n    return datetime.now()\n")
    assert clock_policy_violations(tree, SCORING_PACKAGE)


def test_meta_a_float_decimal_is_detected() -> None:
    tree = seeded("from decimal import Decimal as D\n\nvalue = D(0.75)\n")
    assert decimal_from_float_offenders(tree)

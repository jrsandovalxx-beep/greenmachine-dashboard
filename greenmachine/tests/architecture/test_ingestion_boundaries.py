"""Architecture guards for the GM-020 ingestion slice.

Focused rules: dependency direction (domain/common never import ingestion;
ingestion never imports scoring/reporting/cli/features), provider vocabulary
confinement, composition-root discipline for the concrete transport and
``SystemClock``, no hidden sample-minimum default, no float in
behavior-affecting ingestion code, and no out-of-scope feature modules. The
src-wide GM-005 determinism guards (no clock reads, no randomness, no
``Decimal(float)``, no broad except) apply to every ingestion file
automatically because they glob ``src/``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from static_analysis import collect_imports, within

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
PACKAGE_ROOT = SRC_ROOT / "greenmachine"
INGESTION_ROOT = PACKAGE_ROOT / "ingestion"


def parse_file(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def ingestion_files() -> list[Path]:
    return sorted(INGESTION_ROOT.rglob("*.py"))


def test_the_ingestion_package_is_populated() -> None:
    """Anti-vacuity: the scans below must cover the real slice."""
    names = {path.name for path in ingestion_files()}
    assert {"models.py", "orchestration.py", "mapping.py", "manifest.py"} <= names


# --------------------------------------------------------------------------
# Dependency direction
# --------------------------------------------------------------------------

_FORBIDDEN_FOR_INGESTION = (
    "greenmachine.scoring",
    "greenmachine.reporting",
    "greenmachine.cli",
    "greenmachine.features",
    "greenmachine.config",
)


@pytest.mark.parametrize(
    "path",
    sorted((PACKAGE_ROOT / "domain").rglob("*.py"))
    + sorted((PACKAGE_ROOT / "common").rglob("*.py")),
    ids=lambda p: p.parent.name + "/" + p.name,
)
def test_domain_and_common_never_import_ingestion(path: Path) -> None:
    for record in collect_imports(parse_file(path)):
        resolved = record.module if not record.is_relative else ""
        assert "ingestion" not in resolved, f"{path.name} imports {resolved}"


@pytest.mark.parametrize("path", ingestion_files(), ids=lambda p: p.parent.name + "/" + p.name)
def test_ingestion_never_imports_scoring_or_reporting(path: Path) -> None:
    package = "greenmachine.ingestion" + (
        "." + path.parent.name if path.parent != INGESTION_ROOT else ""
    )
    for record in collect_imports(parse_file(path)):
        resolved = record.resolved(package)
        for forbidden in _FORBIDDEN_FOR_INGESTION:
            assert not within(resolved, forbidden), f"{path.name} imports {resolved}"


def test_the_concrete_transport_is_composed_only_at_the_root() -> None:
    """Orchestration and mapping see only the injected transport protocol."""
    for path in ingestion_files():
        if path.name == "transport.py":
            continue
        modules = {record.module for record in collect_imports(parse_file(path))}
        assert not any("transport" in module for module in modules), (
            f"{path.name} imports the concrete transport; only the composition "
            f"root (the runner script) may"
        )


def test_system_clock_is_never_instantiated_inside_src() -> None:
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        for node in ast.walk(parse_file(path)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "SystemClock"
            ):
                raise AssertionError(
                    f"{path.name} instantiates SystemClock; only the composition root (scripts) may"
                )


# --------------------------------------------------------------------------
# Provider vocabulary confinement
# --------------------------------------------------------------------------

_PROVIDER_WIRE_KEYS = frozenset(
    {
        # Baseball Savant CSV columns / query parameters
        "hc_x",
        "hc_y",
        "launch_speed_angle",
        "bb_type",
        "launch_speed",
        "launch_angle",
        "batters_lookup[]",
        "pitchers_lookup[]",
        "hfGT",
        # MLB Stats API JSON keys
        "gamePk",
        "probablePitchers",
        "abstractGameState",
        "detailedState",
        "officialDate",
        "gameType",
    }
)
_PARSER_FILES = {"parser.py", "client.py"}


def _addressing_constants(tree: ast.Module) -> set[str]:
    """String constants used to address data — docstrings excluded.

    Prose that *explains* provider semantics is required by the ticket and
    lives wherever the semantics are implemented. What must not spread is
    payload addressing: reaching into a provider response (or building a
    provider request) by its wire key.
    """
    docstrings = {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node not in docstrings
    }


@pytest.mark.parametrize(
    "path",
    [p for p in ingestion_files() if p.name not in _PARSER_FILES],
    ids=lambda p: p.parent.name + "/" + p.name,
)
def test_provider_wire_keys_stay_inside_parser_and_client_modules(path: Path) -> None:
    leaked = _addressing_constants(parse_file(path)) & _PROVIDER_WIRE_KEYS
    assert leaked == set(), (
        f"{path.parent.name}/{path.name} addresses provider payloads by wire key "
        f"{sorted(leaked)}; only client/parser modules may"
    )


def test_the_parser_modules_really_do_hold_the_wire_keys() -> None:
    """Anti-vacuity: the guard above would be meaningless if nothing matched."""
    held: set[str] = set()
    for path in ingestion_files():
        if path.name in _PARSER_FILES:
            held |= _addressing_constants(parse_file(path)) & _PROVIDER_WIRE_KEYS
    assert {"gamePk", "hc_x", "bb_type", "hfGT"} <= held


def test_no_provider_vocabulary_reaches_the_domain_or_common_layers() -> None:
    """The boundary that matters: domain contracts never learn a provider's names.

    Ingestion-internal records deliberately keep Statcast column names as
    field names so an auditor can trace a value back to its source column;
    that vocabulary stops at the mapping boundary.
    """
    for package in ("domain", "common"):
        for path in sorted((PACKAGE_ROOT / package).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for key in _PROVIDER_WIRE_KEYS:
                assert key not in source, f"{package}/{path.name} mentions {key!r}"


def test_the_savant_request_asks_for_regular_season_rows() -> None:
    """Anti-vacuity for the R-only policy: the request narrows AND mapping re-enforces."""
    client_source = (INGESTION_ROOT / "savant" / "client.py").read_text(encoding="utf-8")
    assert 'hfGT", "R|"' in client_source or "('hfGT', 'R|')" in client_source.replace('"', "'")


# --------------------------------------------------------------------------
# No hidden sample default; no float in behavior-affecting code
# --------------------------------------------------------------------------


def test_no_sample_minimum_policy_is_constructed_inside_src() -> None:
    """No policy with values invented in src exists.

    Two files are exempt because they ARE the injection path, not a default:
    ``models.py`` defines the type, and ``policy.py`` parses caller-supplied
    exact bytes into it (every value still originates outside src).
    """
    exempt = {INGESTION_ROOT / "models.py", INGESTION_ROOT / "policy.py"}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if path in exempt:
            continue
        for node in ast.walk(parse_file(path)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "SampleMinimumPolicy"
            ):
                raise AssertionError(
                    f"{path.name} constructs a SampleMinimumPolicy inside src; the "
                    f"policy must always be injected by the caller"
                )


def _float_offenders(tree: ast.Module) -> list[int]:
    offenders: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            offenders.append(getattr(node, "lineno", 0))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "float"
        ):
            offenders.append(node.lineno)
        annotation = getattr(node, "annotation", None) or getattr(node, "returns", None)
        if annotation is not None:
            offenders.extend(
                sub.lineno
                for sub in ast.walk(annotation)
                if isinstance(sub, ast.Name) and sub.id == "float"
            )
    return offenders


@pytest.mark.parametrize("path", ingestion_files(), ids=lambda p: p.parent.name + "/" + p.name)
def test_no_float_literal_call_or_annotation_in_ingestion(path: Path) -> None:
    assert _float_offenders(parse_file(path)) == []


def test_seeded_float_usage_is_detected() -> None:
    flagged = ast.parse("x = 0.5\n")
    assert _float_offenders(flagged)
    flagged_call = ast.parse("y = float('1.5')\n")
    assert _float_offenders(flagged_call)
    control = ast.parse("from decimal import Decimal\nz = Decimal('1.5')\n")
    assert _float_offenders(control) == []


# --------------------------------------------------------------------------
# Scope discipline: nothing beyond the slice
# --------------------------------------------------------------------------


def test_no_out_of_scope_feature_module_exists() -> None:
    """GM-030 authorized the reporting dashboard modules; weather, park,
    bullpen, and full-slate implementations remain out of scope."""
    names = " ".join(path.name.lower() for path in PACKAGE_ROOT.rglob("*.py"))
    for banned in ("weather", "park", "bullpen", "slate_runner", "scoreboard"):
        assert banned not in names, f"out-of-scope module name containing {banned!r} found"


def test_scoring_features_validation_and_cli_remain_placeholders() -> None:
    """`reporting` is implemented by GM-030; these four still await tickets
    (`validation` was an unguarded placeholder until GM-040)."""
    for package in ("scoring", "features", "validation", "cli"):
        files = sorted((PACKAGE_ROOT / package).rglob("*.py"))
        assert [path.name for path in files] == ["__init__.py"], package


def test_no_database_module_is_imported_by_ingestion() -> None:
    for path in ingestion_files():
        tops = {record.top_level for record in collect_imports(parse_file(path))}
        assert "sqlite3" not in tops, path.name

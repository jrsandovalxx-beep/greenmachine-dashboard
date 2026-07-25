"""Architecture tests: the domain layer's boundaries, enforced mechanically.

ARCHITECTURE 4 and 9 and ENGINEERING_GUIDELINES D1 state that ``domain`` depends
on nothing — no other GreenMachine package, no third-party library, no clock, no
randomness, no filesystem, no environment. Those are the guarantees that make the
grading core replayable, so they are asserted by parsing the source rather than
trusted to review.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from static_analysis import (
    collect_imports,
    cross_package_offenders,
    package_of,
    third_party_offenders,
)

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
DOMAIN_ROOT = SRC_ROOT / "greenmachine" / "domain"

DOMAIN_PACKAGE = "greenmachine.domain"

# GM-009 grants exactly one dependency out of the domain: `domain/errors.py` may
# import `common.errors` so domain failures sit under GreenMachineError. That
# module holds only exception classes and an immutable context — no clock, no
# I/O, no GreenMachine imports of its own — so the domain stays pure. Matched
# exactly: `greenmachine.common` and `greenmachine.common.logging` stay forbidden.
DOMAIN_ERRORS_MODULE = "errors.py"
APPROVED_DOMAIN_IMPORT = frozenset({"greenmachine.common.errors"})


def approved_extras(path: Path) -> frozenset[str]:
    """The narrow exception, granted to one file and no other."""
    return APPROVED_DOMAIN_IMPORT if path.name == DOMAIN_ERRORS_MODULE else frozenset()


# Third-party and I/O-capable modules the deterministic core must never import.
FORBIDDEN_MODULES = frozenset(
    {
        "aiohttp",
        "httpx",
        "numpy",
        "pandas",
        "plotly",
        "pybaseball",
        "pydantic",
        "requests",
        "sqlite3",
        "sqlalchemy",
        "streamlit",
        "urllib",
        "yaml",
    }
)

# Sources of non-determinism: a clock, randomness, the environment, or the network.
NONDETERMINISTIC_MODULES = frozenset({"os", "random", "secrets", "socket", "subprocess", "time"})

# Textual patterns that would break determinism even via an allowed module.
FORBIDDEN_SOURCE_PATTERNS = (
    "datetime.now",
    "datetime.utcnow",
    ".today(",
    "time.time",
    "uuid4",
    "uuid1",
    "os.environ",
    "getenv",
    "random.",
    "open(",
    "Path(",
)


def domain_modules() -> list[Path]:
    return sorted(DOMAIN_ROOT.rglob("*.py"))


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported_modules(tree: ast.Module) -> list[tuple[str, int]]:
    """Absolute module names imported by ``tree``, with line numbers.

    Relative imports are excluded here and handled by
    :func:`static_analysis.cross_package_offenders`, which resolves their level
    against the importing package. The earlier version of this helper flattened
    every relative import to ``""``, which silently exempted
    ``from ..common import x`` — a real escape that never spells its target.
    """
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            found.append((node.module or "", node.lineno))
    return found


def test_domain_package_is_not_empty() -> None:
    """Guards every other test here against silently passing on an empty package."""
    modules = domain_modules()

    assert len(modules) >= 6
    assert (DOMAIN_ROOT / "__init__.py") in modules


@pytest.mark.parametrize("path", domain_modules(), ids=lambda p: p.name)
def test_domain_imports_no_other_greenmachine_package(path: Path) -> None:
    """ARCHITECTURE 4: domain depends on nothing internal.

    Level-1 intra-domain imports are allowed; any import that leaves the package,
    written absolutely *or* relatively, is not.
    """
    package = package_of(path, SRC_ROOT)
    offenders = cross_package_offenders(
        parse(path), package, DOMAIN_PACKAGE, also_allowed=approved_extras(path)
    )

    assert not offenders, (
        f"{path.name} imports outside {DOMAIN_PACKAGE}: {[o.describe(package) for o in offenders]}"
    )


def test_only_domain_errors_uses_the_approved_common_import() -> None:
    """Every other domain module is held to full isolation."""
    for path in domain_modules():
        if path.name == DOMAIN_ERRORS_MODULE:
            continue
        package = package_of(path, SRC_ROOT)
        offenders = cross_package_offenders(parse(path), package, DOMAIN_PACKAGE)

        assert not offenders, f"{path.name} must not import common at all"


def test_domain_errors_actually_uses_the_exception() -> None:
    """Anti-vacuity: the exception exists because the import is really there."""
    errors_module = DOMAIN_ROOT / DOMAIN_ERRORS_MODULE
    imported = {record.module for record in collect_imports(parse(errors_module))}

    assert "greenmachine.common.errors" in imported


def test_domain_errors_imports_nothing_else_from_common() -> None:
    """The grant is one module wide, not one package wide."""
    errors_module = DOMAIN_ROOT / DOMAIN_ERRORS_MODULE
    from_common = {
        record.module
        for record in collect_imports(parse(errors_module))
        if record.module.startswith("greenmachine.common")
    }

    assert from_common == {"greenmachine.common.errors"}


@pytest.mark.parametrize("path", domain_modules(), ids=lambda p: p.name)
def test_domain_imports_no_forbidden_third_party(path: Path) -> None:
    """ARCHITECTURE 9: no pandas, Streamlit, Plotly, SQLite, or network client."""
    offenders = [
        (name, line)
        for name, line in imported_modules(parse(path))
        if name.split(".")[0] in FORBIDDEN_MODULES
    ]

    assert not offenders, f"{path.name} imports a forbidden dependency: {offenders}"


@pytest.mark.parametrize("path", domain_modules(), ids=lambda p: p.name)
def test_domain_imports_only_the_standard_library(path: Path) -> None:
    """Any non-stdlib package, listed or not, is refused.

    The fixed deny list above stays as an explicit statement of the named
    hazards; this catches everything else.
    """
    offenders = third_party_offenders(parse(path))

    assert not offenders, f"{path.name} imports third-party code: {offenders}"


# --------------------------------------------------------------------------
# Meta-tests for the domain boundary rules
# --------------------------------------------------------------------------


def seeded(source: str) -> ast.Module:
    """Parse seeded source, first proving it is syntactically valid."""
    try:
        return ast.parse(source)
    except SyntaxError as exc:  # pragma: no cover - the snippets are valid
        pytest.fail(f"seeded source must be syntactically valid, but did not parse: {exc}")


def test_meta_intra_domain_relative_import_is_allowed() -> None:
    tree = seeded("from .enums import ComponentId\n")

    assert cross_package_offenders(tree, DOMAIN_PACKAGE, DOMAIN_PACKAGE) == []


def test_meta_relative_escape_from_domain_is_rejected() -> None:
    """The bypass a flattened relative import used to hide."""
    tree = seeded("from ..common import decimal_from\n")

    offenders = cross_package_offenders(tree, DOMAIN_PACKAGE, DOMAIN_PACKAGE)

    assert [o.resolved(DOMAIN_PACKAGE) for o in offenders] == ["greenmachine.common"]


def test_meta_absolute_escape_from_domain_is_rejected() -> None:
    tree = seeded("from greenmachine.common import decimal_from\n")

    assert cross_package_offenders(tree, DOMAIN_PACKAGE, DOMAIN_PACKAGE)


def test_meta_a_domain_import_of_config_is_rejected() -> None:
    """ARCHITECTURE ruling (GM-006): the domain never imports config.

    A stored ``config_hash`` is carried as a domain ``Sha256Digest``, not by
    reaching for :class:`~greenmachine.config.ConfigHash`.
    """
    tree = seeded("from greenmachine.config import ConfigHash\n")

    assert [
        o.resolved(DOMAIN_PACKAGE)
        for o in cross_package_offenders(tree, DOMAIN_PACKAGE, DOMAIN_PACKAGE)
    ] == ["greenmachine.config"]


def test_meta_a_relative_domain_import_of_config_is_rejected() -> None:
    tree = seeded("from ..config import ConfigHash\n")

    assert cross_package_offenders(tree, DOMAIN_PACKAGE, DOMAIN_PACKAGE)


def test_meta_domain_third_party_import_is_rejected() -> None:
    assert third_party_offenders(seeded("import scipy\n"))
    assert third_party_offenders(seeded("import pandas\n"))


def test_meta_domain_stdlib_import_is_allowed() -> None:
    source = "from dataclasses import dataclass\nfrom decimal import Decimal\n"

    assert third_party_offenders(seeded(source)) == []
    assert cross_package_offenders(seeded(source), DOMAIN_PACKAGE, DOMAIN_PACKAGE) == []


# --------------------------------------------------------------------------
# Meta-tests for the one approved domain -> common.errors dependency
# --------------------------------------------------------------------------


def test_meta_domain_errors_may_import_common_errors() -> None:
    tree = seeded("from greenmachine.common.errors import DomainInvariantError\n")

    assert (
        cross_package_offenders(
            tree, DOMAIN_PACKAGE, DOMAIN_PACKAGE, also_allowed=APPROVED_DOMAIN_IMPORT
        )
        == []
    )


def test_meta_the_same_import_is_rejected_without_the_grant() -> None:
    """Another domain module writing the identical line is still an escape."""
    tree = seeded("from greenmachine.common.errors import DomainInvariantError\n")

    assert cross_package_offenders(tree, DOMAIN_PACKAGE, DOMAIN_PACKAGE)


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("common.logging", "from greenmachine.common.logging import configure_logger\n"),
        ("common.numeric", "from greenmachine.common.numeric import decimal_from\n"),
        ("common.clock", "from greenmachine.common.clock import SystemClock\n"),
        ("common.serialization", "from greenmachine.common.serialization import canonical_bytes\n"),
        ("common.ids", "from greenmachine.common.ids import content_digest\n"),
        ("the common package itself", "from greenmachine.common import GreenMachineError\n"),
        ("relative common.logging", "from ..common.logging import configure_logger\n"),
    ],
)
def test_meta_the_grant_does_not_extend_to_any_other_common_module(label: str, source: str) -> None:
    """The exception is matched exactly, so nothing else rides along with it."""
    offenders = cross_package_offenders(
        seeded(source), DOMAIN_PACKAGE, DOMAIN_PACKAGE, also_allowed=APPROVED_DOMAIN_IMPORT
    )

    assert offenders, f"{label} must remain forbidden"


def test_meta_the_grant_covers_the_relative_spelling_too() -> None:
    """`from ..common.errors import X` resolves to the same approved module."""
    tree = seeded("from ..common.errors import DomainInvariantError\n")

    assert (
        cross_package_offenders(
            tree, DOMAIN_PACKAGE, DOMAIN_PACKAGE, also_allowed=APPROVED_DOMAIN_IMPORT
        )
        == []
    )


@pytest.mark.parametrize("path", domain_modules(), ids=lambda p: p.name)
def test_domain_imports_no_source_of_nondeterminism(path: Path) -> None:
    """D1/D2: the domain reads no clock, no environment, and no randomness."""
    offenders = [
        (name, line)
        for name, line in imported_modules(parse(path))
        if name.split(".")[0] in NONDETERMINISTIC_MODULES
    ]

    assert not offenders, f"{path.name} imports a non-deterministic module: {offenders}"


@pytest.mark.parametrize("path", domain_modules(), ids=lambda p: p.name)
def test_domain_source_contains_no_nondeterministic_calls(path: Path) -> None:
    """Catches a clock, id generator, or file access reached through an allowed
    module — for example ``datetime.now()`` via the permitted ``datetime`` import."""
    source = path.read_text(encoding="utf-8")
    # A comment naming a construct is not a call to it; everything else counts.
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))

    offenders = [pattern for pattern in FORBIDDEN_SOURCE_PATTERNS if pattern in code]

    assert not offenders, f"{path.name} contains non-deterministic constructs: {offenders}"


@pytest.mark.parametrize("path", domain_modules(), ids=lambda p: p.name)
def test_no_domain_field_entering_scoring_is_typed_float(path: Path) -> None:
    """ADR-0002: values entering scoring are Decimal, never float.

    Asserted statically over every annotation in the package, so a float field can
    never be introduced without this failing.
    """
    tree = parse(path)
    offenders: list[tuple[str, int]] = []

    for node in ast.walk(tree):
        annotation = getattr(node, "annotation", None) or getattr(node, "returns", None)
        if annotation is None:
            continue
        for sub in ast.walk(annotation):
            if isinstance(sub, ast.Name) and sub.id == "float":
                offenders.append((ast.unparse(annotation), sub.lineno))

    assert not offenders, f"{path.name} declares a float-typed annotation: {offenders}"


@pytest.mark.parametrize("path", domain_modules(), ids=lambda p: p.name)
def test_no_decimal_is_constructed_from_a_float(path: Path) -> None:
    """ADR-0002: ``Decimal(0.1)`` is prohibited; construct from strings or ints."""
    tree = parse(path)
    offenders: list[int] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != "Decimal" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, float):
            offenders.append(node.lineno)

    assert not offenders, f"{path.name} constructs a Decimal from a float at {offenders}"


def test_domain_declares_no_baseball_threshold() -> None:
    """No threshold, bucket edge, allocation, or sample minimum lives in src/.

    Every numeric literal in the domain package must be structural (0, 1, or an
    index), never a baseball number — those belong in configuration.
    """
    allowed = {0, 1}
    offenders: list[tuple[str, int, object]] = []

    for path in domain_modules():
        for node in ast.walk(parse(path)):
            if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
                if isinstance(node.value, bool) or node.value in allowed:
                    continue
                offenders.append((path.name, node.lineno, node.value))

    assert not offenders, f"domain contains numeric literals that may be thresholds: {offenders}"

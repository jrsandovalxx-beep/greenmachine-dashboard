"""Static guards for the GM-005 determinism rules, across all of ``src/``.

The rules live in :mod:`static_analysis` as plain functions over an AST plus the
module's identity, so the same code that scans the real tree is pointed at seeded
snippets below with synthetic module names. Each meta-test first asserts the
snippet **parses** — proving the guard fires for the violation and not for a
syntax error — then asserts the guard flags it, with a negative control alongside.

``test_import_boundaries.py`` covers the domain package's boundaries. This file
covers the determinism rules that apply everywhere.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest
from static_analysis import (
    APPROVED_CLOCK_MODULE,
    APPROVED_CLOCK_SCOPE,
    CLOCK_READS,
    clock_policy_violations,
    clock_reads,
    collect_aliases,
    collect_imports,
    cross_package_offenders,
    decimal_from_float_offenders,
    float_annotation_offenders,
    io_module_offenders,
    module_qualname,
    package_of,
    random_offenders,
    resolve_call_target,
    scoped_calls,
    third_party_offenders,
    uuid_offenders,
)

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
PACKAGE_ROOT = SRC_ROOT / "greenmachine"
COMMON_ROOT = PACKAGE_ROOT / "common"

COMMON_PACKAGE = "greenmachine.common"

# Standard-library modules `common` is separately forbidden to import: they are
# not third-party, they are I/O and environment access.
FORBIDDEN_IO = frozenset(
    {"os", "io", "socket", "subprocess", "shutil", "urllib", "http", "pathlib", "tempfile"}
)


def source_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def parse_file(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def seeded(source: str) -> ast.Module:
    """Parse seeded source, first proving it is syntactically valid.

    Without this, a typo in a snippet would make the guard 'fail' for the wrong
    reason and the meta-test would prove nothing.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:  # pragma: no cover - the snippets are valid
        pytest.fail(f"seeded source must be syntactically valid, but did not parse: {exc}")


# --------------------------------------------------------------------------
# The rules applied to the real tree
# --------------------------------------------------------------------------


def test_the_source_tree_is_not_empty() -> None:
    """Guards every scan below against passing on an empty tree."""
    assert len(source_files(PACKAGE_ROOT)) >= 10
    assert len(source_files(COMMON_ROOT)) >= 5


@pytest.mark.parametrize("path", source_files(PACKAGE_ROOT), ids=lambda p: p.name)
def test_no_decimal_is_built_from_a_float(path: Path) -> None:
    """ADR-0002, across all of src/ and through any import alias."""
    assert not decimal_from_float_offenders(parse_file(path))


@pytest.mark.parametrize("path", source_files(COMMON_ROOT), ids=lambda p: p.name)
def test_numeric_primitives_declare_no_float(path: Path) -> None:
    assert not float_annotation_offenders(parse_file(path))


@pytest.mark.parametrize("path", source_files(PACKAGE_ROOT), ids=lambda p: p.name)
def test_only_the_approved_file_and_scope_reads_the_clock(path: Path) -> None:
    """D2: the sole real-time read is SystemClock.now in common/clock.py."""
    module = module_qualname(path, SRC_ROOT)
    violations = clock_policy_violations(parse_file(path), module)

    assert not violations, f"{module}: {violations}"


def test_the_approved_clock_read_actually_exists() -> None:
    """Anti-vacuity: the rule above would pass if the read simply vanished.

    Also proves alias resolution works against the real file, not only against
    the seeded snippets below.
    """
    clock = COMMON_ROOT / "clock.py"
    reads = clock_reads(parse_file(clock))

    assert [scope for scope, _ in reads] == [APPROVED_CLOCK_SCOPE]
    assert module_qualname(clock, SRC_ROOT) == APPROVED_CLOCK_MODULE


@pytest.mark.parametrize("path", source_files(PACKAGE_ROOT), ids=lambda p: p.name)
def test_no_randomness_anywhere_in_src(path: Path) -> None:
    assert not random_offenders(parse_file(path))


@pytest.mark.parametrize("path", source_files(PACKAGE_ROOT), ids=lambda p: p.name)
def test_no_random_uuid_anywhere_in_src(path: Path) -> None:
    """Identifiers are content-derived, never randomly generated."""
    assert not uuid_offenders(parse_file(path))


@pytest.mark.parametrize("path", source_files(COMMON_ROOT), ids=lambda p: p.name)
def test_common_imports_only_the_standard_library(path: Path) -> None:
    """Detected against sys.stdlib_module_names, not a hand-kept deny list."""
    offenders = third_party_offenders(parse_file(path))

    assert not offenders, f"{path.name} imports third-party code: {offenders}"


@pytest.mark.parametrize("path", source_files(COMMON_ROOT), ids=lambda p: p.name)
def test_common_never_escapes_its_own_package(path: Path) -> None:
    """Intra-common imports only, whether written absolutely or relatively."""
    package = package_of(path, SRC_ROOT)
    offenders = cross_package_offenders(parse_file(path), package, COMMON_PACKAGE)

    assert not offenders, (
        f"{path.name} imports outside {COMMON_PACKAGE}: {[o.describe(package) for o in offenders]}"
    )


@pytest.mark.parametrize("path", source_files(COMMON_ROOT), ids=lambda p: p.name)
def test_common_performs_no_io_or_environment_access(path: Path) -> None:
    offenders = io_module_offenders(parse_file(path), FORBIDDEN_IO)

    assert not offenders, f"{path.name} imports an I/O module: {offenders}"


def test_common_contains_no_baseball_vocabulary() -> None:
    """Whole-word matching: ``window_profile`` is a correlation field, not wind.

    A substring check flagged it, which is exactly the false positive that makes
    a guard get deleted rather than fixed.
    """
    baseball = (
        "barrel",
        "exit_velocity",
        "hard_hit",
        "sweet_spot",
        "bat_speed",
        "park_factor",
        "wind",
        "attack_angle_pct",
        "power_profile",
    )
    for path in source_files(COMMON_ROOT):
        text = path.read_text(encoding="utf-8").lower()
        for term in baseball:
            found = re.search(rf"\b{re.escape(term)}\b", text)
            assert found is None, f"{path.name} mentions baseball vocabulary: {term!r}"


@pytest.mark.parametrize("path", source_files(PACKAGE_ROOT), ids=lambda p: p.name)
def test_only_the_logging_module_imports_logging(path: Path) -> None:
    """ADR-0007: the grading core does not log, so it cannot vary its output.

    Exactly one module in the package may import the stdlib ``logging``.
    """
    module = module_qualname(path, SRC_ROOT)
    imports_logging = any(
        record.top_level == "logging" for record in collect_imports(parse_file(path))
    )

    if module == "greenmachine.common.logging":
        assert imports_logging, "the logging module must actually import logging"
    else:
        assert not imports_logging, f"{module} must not log; the core stays observation-free"


def test_the_domain_package_never_imports_logging() -> None:
    domain_root = PACKAGE_ROOT / "domain"

    for path in source_files(domain_root):
        imported = {record.top_level for record in collect_imports(parse_file(path))}
        assert "logging" not in imported, f"{path.name} must not log"


def test_common_declares_no_grade_cutoff_table() -> None:
    """The documented cutoffs must be supplied by callers, not baked in."""
    cutoffs = {4, 6, 8, 10, 12}
    for path in source_files(COMMON_ROOT):
        literals = {
            node.value
            for node in ast.walk(parse_file(path))
            if isinstance(node, ast.Constant)
            and isinstance(node.value, int)
            and not isinstance(node.value, bool)
        }
        present = cutoffs & literals
        assert len(present) < 3, (
            f"{path.name} contains {sorted(present)}, which looks like a cutoff table"
        )


# --------------------------------------------------------------------------
# Meta: relative and cross-package imports
# --------------------------------------------------------------------------


def test_meta_intra_common_relative_import_is_allowed() -> None:
    tree = seeded("from .serialization import canonical_bytes\n")

    assert cross_package_offenders(tree, COMMON_PACKAGE, COMMON_PACKAGE) == []


def test_meta_relative_escape_from_common_is_rejected() -> None:
    """The bypass: `..` never spells 'greenmachine' but leaves the package."""
    tree = seeded("from ..domain import ComponentId\n")

    offenders = cross_package_offenders(tree, COMMON_PACKAGE, COMMON_PACKAGE)

    assert [o.resolved(COMMON_PACKAGE) for o in offenders] == ["greenmachine.domain"]


def test_meta_deep_relative_escape_is_rejected() -> None:
    tree = seeded("from ...greenmachine.scoring import thing\n")

    assert cross_package_offenders(tree, COMMON_PACKAGE, COMMON_PACKAGE)


def test_meta_bare_relative_parent_import_is_rejected() -> None:
    tree = seeded("from .. import domain\n")

    offenders = cross_package_offenders(tree, COMMON_PACKAGE, COMMON_PACKAGE)

    assert [o.resolved(COMMON_PACKAGE) for o in offenders] == ["greenmachine"]


def test_meta_absolute_cross_package_import_is_rejected() -> None:
    tree = seeded("from greenmachine.domain import ComponentId\n")

    assert cross_package_offenders(tree, COMMON_PACKAGE, COMMON_PACKAGE)


def test_meta_absolute_intra_common_import_is_allowed() -> None:
    tree = seeded("from greenmachine.common.numeric import add\n")

    assert cross_package_offenders(tree, COMMON_PACKAGE, COMMON_PACKAGE) == []


def test_meta_stdlib_import_is_not_a_cross_package_offence() -> None:
    tree = seeded("import decimal\nfrom datetime import datetime\n")

    assert cross_package_offenders(tree, COMMON_PACKAGE, COMMON_PACKAGE) == []


# --------------------------------------------------------------------------
# Meta: third-party detection
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "import decimal\n",
        "from decimal import Decimal\n",
        "import pathlib\n",
        "from __future__ import annotations\n",
        "import greenmachine.common.numeric\n",
        "from .serialization import canonical_bytes\n",
    ],
)
def test_meta_permitted_imports_are_not_third_party(source: str) -> None:
    """pathlib is standard library here; the I/O rule forbids it separately."""
    assert third_party_offenders(seeded(source)) == []


@pytest.mark.parametrize(
    "source",
    [
        "import scipy\n",
        "import some_unlisted_vendor_package\n",
        "from scipy import stats\n",
        "import pandas as pd\n",
        "import totally_made_up_module.submodule\n",
    ],
)
def test_meta_third_party_imports_are_rejected(source: str) -> None:
    """Caught by stdlib membership, so an unlisted package needs no deny-list entry."""
    assert third_party_offenders(seeded(source))


def test_meta_third_party_detection_does_not_require_installation() -> None:
    """scipy is not installed here, and the rule still catches it."""
    assert "scipy" not in sys.modules
    assert third_party_offenders(seeded("import scipy\n"))


def test_meta_pathlib_is_stdlib_but_still_forbidden_as_io() -> None:
    tree = seeded("import pathlib\n")

    assert third_party_offenders(tree) == []
    assert io_module_offenders(tree, FORBIDDEN_IO)


# --------------------------------------------------------------------------
# Meta: clock reads, bound to file and scope
# --------------------------------------------------------------------------


APPROVED_CLOCK_SOURCE = (
    "from datetime import UTC, datetime\n"
    "class SystemClock:\n"
    "    def now(self):\n"
    "        return datetime.now(UTC)\n"
)


def test_meta_approved_clock_read_is_permitted_in_the_approved_module() -> None:
    tree = seeded(APPROVED_CLOCK_SOURCE)

    assert clock_policy_violations(tree, APPROVED_CLOCK_MODULE) == []


def test_meta_same_class_and_method_in_another_file_is_rejected() -> None:
    """The bypass: an exemption keyed only on the scope name."""
    tree = seeded(APPROVED_CLOCK_SOURCE)

    assert clock_policy_violations(tree, "greenmachine.scoring.fake")


def test_meta_another_method_in_the_approved_file_is_rejected() -> None:
    source = (
        "from datetime import UTC, datetime\n"
        "class SystemClock:\n"
        "    def now(self):\n"
        "        return datetime.now(UTC)\n"
        "    def sneak(self):\n"
        "        return datetime.now(UTC)\n"
    )
    violations = clock_policy_violations(seeded(source), APPROVED_CLOCK_MODULE)

    assert any("SystemClock.sneak" in v for v in violations)


def test_meta_a_second_read_in_the_approved_scope_is_rejected() -> None:
    source = (
        "from datetime import UTC, datetime\n"
        "class SystemClock:\n"
        "    def now(self):\n"
        "        first = datetime.now(UTC)\n"
        "        return max(first, datetime.now(UTC))\n"
    )
    violations = clock_policy_violations(seeded(source), APPROVED_CLOCK_MODULE)

    assert any("exactly one" in v for v in violations)


def test_meta_module_scope_clock_read_is_rejected() -> None:
    tree = seeded("from datetime import datetime\nNOW = datetime.now()\n")

    assert clock_policy_violations(tree, "greenmachine.common.clock")
    assert clock_reads(tree) == [("<module>", 2)]


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("direct", "from datetime import datetime\nv = datetime.now()\n"),
        ("class alias", "from datetime import datetime as dt\nv = dt.now()\n"),
        ("module alias", "import datetime as dm\nv = dm.datetime.now()\n"),
        ("plain module", "import datetime\nv = datetime.datetime.now()\n"),
        ("utcnow", "from datetime import datetime as dt\nv = dt.utcnow()\n"),
        ("date.today", "from datetime import date\nv = date.today()\n"),
        ("date alias", "from datetime import date as d\nv = d.today()\n"),
        ("date via module", "import datetime as dm\nv = dm.date.today()\n"),
        ("datetime.today", "from datetime import datetime\nv = datetime.today()\n"),
        ("datetime.today alias", "from datetime import datetime as dt\nv = dt.today()\n"),
        ("datetime.today module", "import datetime\nv = datetime.datetime.today()\n"),
        ("datetime.today mod alias", "import datetime as dm\nv = dm.datetime.today()\n"),
        ("time.time", "import time\nv = time.time()\n"),
        ("time alias", "import time as t\nv = t.time()\n"),
    ],
)
def test_meta_clock_reads_are_detected_through_aliases(label: str, source: str) -> None:
    """Every direct syntactic form of a clock read, however it was imported."""
    assert clock_reads(seeded(source)), f"missed the {label} form"


def test_meta_datetime_today_is_rejected_even_in_the_approved_file() -> None:
    """`today()` is not an alternative spelling the approved file may adopt."""
    source = (
        "from datetime import datetime\n"
        "class SystemClock:\n"
        "    def now(self):\n"
        "        return datetime.today()\n"
        "    def other(self):\n"
        "        return datetime.today()\n"
    )
    violations = clock_policy_violations(seeded(source), APPROVED_CLOCK_MODULE)

    assert any("SystemClock.other" in v for v in violations)
    assert any("exactly one" in v for v in violations)


def test_the_approved_read_is_specifically_datetime_now() -> None:
    """Pin the real implementation: it must stay ``datetime.now(UTC)``.

    The policy allows exactly one read in ``SystemClock.now``; this additionally
    fixes *which* read it is, so ``today()`` could not quietly replace it.
    """
    clock = COMMON_ROOT / "clock.py"
    tree = parse_file(clock)
    aliases = collect_aliases(tree)

    targets = [
        resolve_call_target(call.func, aliases)
        for call, _ in scoped_calls(tree)
        if resolve_call_target(call.func, aliases) in CLOCK_READS
    ]

    assert targets == ["datetime.datetime.now"]


def test_meta_an_unrelated_now_method_is_not_a_clock_read() -> None:
    """Negative control: matching on the bare name `now` would false-positive."""
    source = "class Widget:\n    def now(self):\n        return 1\nv = Widget().now()\n"

    assert clock_reads(seeded(source)) == []


# --------------------------------------------------------------------------
# Meta: Decimal-from-float
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("positive literal", "from decimal import Decimal\nv = Decimal(0.1)\n"),
        ("negative literal", "from decimal import Decimal\nv = Decimal(-0.1)\n"),
        ("unary plus", "from decimal import Decimal\nv = Decimal(+0.1)\n"),
        ("float call", "from decimal import Decimal\nv = Decimal(float('1.5'))\n"),
        ("class alias", "from decimal import Decimal as D\nv = D(0.1)\n"),
        ("negative via alias", "from decimal import Decimal as D\nv = D(-2.5)\n"),
        ("module alias", "import decimal as dec\nv = dec.Decimal(0.1)\n"),
        ("plain module", "import decimal\nv = decimal.Decimal(-0.1)\n"),
    ],
)
def test_meta_decimal_from_float_is_detected_through_aliases(label: str, source: str) -> None:
    assert decimal_from_float_offenders(seeded(source)), f"missed the {label} form"


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("string", "from decimal import Decimal\nv = Decimal('0.1')\n"),
        ("int", "from decimal import Decimal\nv = Decimal(1)\n"),
        ("negative int", "from decimal import Decimal\nv = Decimal(-1)\n"),
        ("variable", "from decimal import Decimal\nv = Decimal(raw)\n"),
        ("helper", "from greenmachine.common import decimal_from\nv = decimal_from('0.1')\n"),
        ("aliased string", "from decimal import Decimal as D\nv = D('0.1')\n"),
        ("unrelated call", "v = SomeOther(0.1)\n"),
    ],
)
def test_meta_permitted_decimal_construction_is_not_flagged(label: str, source: str) -> None:
    """Negative controls: no speculative inference, no false positives."""
    assert decimal_from_float_offenders(seeded(source)) == [], f"false positive: {label}"


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("keyword", "from decimal import Decimal\nv = Decimal(value=0.1)\n"),
        ("negative keyword", "from decimal import Decimal\nv = Decimal(value=-0.1)\n"),
        ("aliased keyword", "from decimal import Decimal as D\nv = D(value=0.1)\n"),
        ("module keyword", "import decimal as dec\nv = dec.Decimal(value=0.1)\n"),
        ("keyword float call", "from decimal import Decimal\nv = Decimal(value=float(x))\n"),
    ],
)
def test_meta_decimal_keyword_float_is_detected(label: str, source: str) -> None:
    """The constructor's `value=` keyword carries a float just as a positional does."""
    assert decimal_from_float_offenders(seeded(source)), f"missed the {label} form"


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("direct", "from decimal import Decimal\nv = Decimal.from_float(0.1)\n"),
        ("negative", "from decimal import Decimal\nv = Decimal.from_float(-0.1)\n"),
        ("aliased class", "from decimal import Decimal as D\nv = D.from_float(0.1)\n"),
        ("module alias", "import decimal as dec\nv = dec.Decimal.from_float(0.1)\n"),
        ("plain module", "import decimal\nv = decimal.Decimal.from_float(-0.1)\n"),
        ("keyword", "from decimal import Decimal\nv = Decimal.from_float(f=0.1)\n"),
    ],
)
def test_meta_decimal_from_float_method_is_detected(label: str, source: str) -> None:
    """`Decimal.from_float` converts a binary float by definition."""
    assert decimal_from_float_offenders(seeded(source)), f"missed the {label} form"


@pytest.mark.parametrize(
    ("label", "source"),
    [
        (
            "direct",
            "from decimal import Context\nv = Context().create_decimal_from_float(0.1)\n",
        ),
        (
            "negative",
            "from decimal import Context\nv = Context().create_decimal_from_float(-0.1)\n",
        ),
        (
            "aliased class",
            "from decimal import Context as C\nv = C().create_decimal_from_float(0.1)\n",
        ),
        (
            "module alias",
            "import decimal as dec\nv = dec.Context().create_decimal_from_float(0.1)\n",
        ),
        (
            "plain module",
            "import decimal\nv = decimal.Context().create_decimal_from_float(0.1)\n",
        ),
        (
            "keyword",
            "from decimal import Context\nv = Context().create_decimal_from_float(f=0.1)\n",
        ),
    ],
)
def test_meta_context_create_decimal_from_float_is_detected(label: str, source: str) -> None:
    """The decimal context API is another direct float-to-Decimal route."""
    assert decimal_from_float_offenders(seeded(source)), f"missed the {label} form"


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("unknown from_float", "v = obj.from_float(0.1)\n"),
        ("unknown value keyword", "v = configure(value=0.1)\n"),
        ("unknown create method", "v = thing().create_decimal_from_float(0.1)\n"),
        ("string keyword", "from decimal import Decimal\nv = Decimal(value='0.1')\n"),
        ("int keyword", "from decimal import Decimal\nv = Decimal(value=1)\n"),
        ("from_float variable", "from decimal import Decimal\nv = Decimal.from_float(raw)\n"),
        (
            "context non-float api",
            "from decimal import Context\nv = Context().create_decimal('0.1')\n",
        ),
        ("unrelated kwarg", "from decimal import Decimal\nv = Decimal('1', other=0.1)\n"),
    ],
)
def test_meta_unrelated_float_shaped_calls_are_not_flagged(label: str, source: str) -> None:
    """Negative controls: the guard needs a *tracked* callee, not a familiar name."""
    assert decimal_from_float_offenders(seeded(source)) == [], f"false positive: {label}"


# --------------------------------------------------------------------------
# Meta: UUID
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("module", "import uuid\nv = uuid.uuid4()\n"),
        ("module uuid1", "import uuid\nv = uuid.uuid1()\n"),
        ("module alias", "import uuid as u\nv = u.uuid4()\n"),
        ("from import", "from uuid import uuid4\nv = uuid4()\n"),
        ("from import alias", "from uuid import uuid4 as make_id\nv = make_id()\n"),
        ("uuid1 alias", "from uuid import uuid1 as make_id\nv = make_id()\n"),
    ],
)
def test_meta_random_uuid_is_detected_through_aliases(label: str, source: str) -> None:
    assert uuid_offenders(seeded(source)), f"missed the {label} form"


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("uuid5", "import uuid\nv = uuid.uuid5(uuid.NAMESPACE_DNS, 'x')\n"),
        ("uuid3", "import uuid\nv = uuid.uuid3(uuid.NAMESPACE_DNS, 'x')\n"),
        ("uuid5 alias", "from uuid import uuid5 as derive\nv = derive(ns, 'x')\n"),
        ("unrelated", "v = obj.uuid4_lookalike()\n"),
    ],
)
def test_meta_deterministic_uuid_factories_are_permitted(label: str, source: str) -> None:
    assert uuid_offenders(seeded(source)) == [], f"false positive: {label}"


# --------------------------------------------------------------------------
# Meta: randomness and float annotations
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    ["import random\n", "from random import randint\n", "import secrets\n", "import random as r\n"],
)
def test_meta_random_guard_fires(source: str) -> None:
    assert random_offenders(seeded(source))


def test_meta_float_annotation_guard_fires() -> None:
    assert float_annotation_offenders(seeded("def ratio(x: float) -> float:\n    return x\n"))


def test_meta_decimal_annotation_is_not_flagged() -> None:
    source = "from decimal import Decimal\ndef ratio(x: Decimal) -> Decimal:\n    return x\n"

    assert float_annotation_offenders(seeded(source)) == []

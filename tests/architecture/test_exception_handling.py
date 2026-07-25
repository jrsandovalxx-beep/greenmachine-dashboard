"""No broad exception handling anywhere in ``src/``.

ADR-0007: a swallowed exception produces a grade that looks right and is wrong,
which is the worst outcome for a system whose value is trustworthy explanation.
The prohibition is enforced here by parsing the tree, not left to review
attention or to a Ruff setting that a future ``noqa`` could quietly disable.

The rule resolves import aliases, so renaming ``Exception`` on the way in does
not evade it. Each seeded meta-test asserts its snippet **parses** before the
guard is applied, so a failure can only come from the rule recognising the
violation.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from static_analysis import (
    broad_exception_offenders,
    broad_suppress_offenders,
    handler_offenders,
)

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
PACKAGE_ROOT = SRC_ROOT / "greenmachine"


def source_files() -> list[Path]:
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def parse_file(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def seeded(source: str) -> ast.Module:
    """Parse seeded source, first proving it is syntactically valid."""
    try:
        return ast.parse(source)
    except SyntaxError as exc:  # pragma: no cover - the snippets are valid
        pytest.fail(f"seeded source must be syntactically valid, but did not parse: {exc}")


# --------------------------------------------------------------------------
# The real tree
# --------------------------------------------------------------------------


def test_the_source_tree_is_not_empty() -> None:
    """Guards the scan below against passing on an empty tree."""
    assert len(source_files()) >= 10


@pytest.mark.parametrize("path", source_files(), ids=lambda p: p.name)
def test_no_broad_exception_handling_in_src(path: Path) -> None:
    offenders = broad_exception_offenders(parse_file(path))

    assert not offenders, f"{path.name}: {offenders}"


def test_the_existing_specific_handlers_are_still_present() -> None:
    """Anti-vacuity: the rule would pass on a tree with no handlers at all."""
    handlers = [
        node
        for path in source_files()
        for node in ast.walk(parse_file(path))
        if isinstance(node, ast.ExceptHandler)
    ]

    assert handlers, "expected at least one except handler in src/ to exercise the rule"
    assert all(handler.type is not None for handler in handlers)


def test_an_ellipsis_protocol_body_is_not_mistaken_for_a_swallow() -> None:
    """The no-op rule applies to handler bodies only, never to function bodies.

    ``Clock.now`` is a Protocol stub whose body is a docstring and ``...`` — the
    exact shape the swallow rule rejects inside an ``except``. Flagging it would
    be the false positive that gets a guard deleted.
    """
    clock = SRC_ROOT / "greenmachine" / "common" / "clock.py"
    tree = parse_file(clock)

    stubs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.body
        and isinstance(node.body[-1], ast.Expr)
        and isinstance(node.body[-1].value, ast.Constant)
        and node.body[-1].value.value is Ellipsis
    ]

    assert stubs, "expected a Protocol stub ending in `...` to exercise this case"
    assert broad_exception_offenders(tree) == []


# --------------------------------------------------------------------------
# Meta: forms that must be rejected
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("bare except", "try:\n    f()\nexcept:\n    g()\n"),
        ("Exception", "try:\n    f()\nexcept Exception:\n    g()\n"),
        ("BaseException", "try:\n    f()\nexcept BaseException:\n    g()\n"),
        ("Exception as exc", "try:\n    f()\nexcept Exception as exc:\n    g()\n"),
        (
            "aliased Exception",
            "from builtins import Exception as E\ntry:\n    f()\nexcept E:\n    g()\n",
        ),
        (
            "aliased BaseException",
            "from builtins import BaseException as B\ntry:\n    f()\nexcept B:\n    g()\n",
        ),
        (
            "builtins.Exception",
            "import builtins\ntry:\n    f()\nexcept builtins.Exception:\n    g()\n",
        ),
        (
            "aliased builtins module",
            "import builtins as b\ntry:\n    f()\nexcept b.Exception:\n    g()\n",
        ),
        (
            "tuple containing Exception",
            "try:\n    f()\nexcept (ValueError, Exception):\n    g()\n",
        ),
        (
            "tuple containing BaseException",
            "try:\n    f()\nexcept (KeyError, BaseException):\n    g()\n",
        ),
    ],
)
def test_meta_broad_handlers_are_rejected(label: str, source: str) -> None:
    assert broad_exception_offenders(seeded(source)), f"missed the {label} form"


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("specific with pass", "try:\n    f()\nexcept ValueError:\n    pass\n"),
        ("bare with pass", "try:\n    f()\nexcept:\n    pass\n"),
        ("tuple with pass", "try:\n    f()\nexcept (ValueError, KeyError):\n    pass\n"),
        ("ellipsis alone", "try:\n    f()\nexcept ValueError:\n    ...\n"),
        (
            "docstring then pass",
            'try:\n    f()\nexcept ValueError:\n    "ignore because optional"\n    pass\n',
        ),
        (
            "docstring then ellipsis",
            'try:\n    f()\nexcept ValueError:\n    "ignore because optional"\n    ...\n',
        ),
        ("literal only", 'try:\n    f()\nexcept ValueError:\n    "documented reason"\n'),
        ("number literal only", "try:\n    f()\nexcept ValueError:\n    0\n"),
        ("None literal only", "try:\n    f()\nexcept ValueError:\n    None\n"),
        (
            "two literals then pass",
            'try:\n    f()\nexcept ValueError:\n    "why"\n    "more"\n    pass\n',
        ),
        ("ellipsis then pass", "try:\n    f()\nexcept ValueError:\n    ...\n    pass\n"),
    ],
)
def test_meta_effectively_empty_handlers_are_rejected(label: str, source: str) -> None:
    """A handler that does nothing swallows the failure, however it is spelled.

    A string explaining the decision does not make the failure observable.
    """
    offenders = broad_exception_offenders(seeded(source))

    assert offenders, f"missed the {label} form"
    assert any("swallowed" in reason for _, reason in offenders)


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("re-raise", "try:\n    f()\nexcept ValueError:\n    raise\n"),
        ("recover", "try:\n    f()\nexcept ValueError:\n    recover()\n"),
        ("log", 'try:\n    f()\nexcept ValueError:\n    logger.warning("recovered")\n'),
        (
            "return fallback",
            "def g():\n    try:\n        f()\n    except ValueError:\n        return fallback\n",
        ),
        ("assign then use", "try:\n    f()\nexcept ValueError:\n    x = 1\n"),
        (
            "docstring then real work",
            'try:\n    f()\nexcept ValueError:\n    "why we recover"\n    recover()\n',
        ),
        (
            "continue",
            "for i in x:\n    try:\n        f()\n    except ValueError:\n        continue\n",
        ),
        ("raise from", "try:\n    f()\nexcept ValueError as exc:\n    raise Wrapped from exc\n"),
    ],
)
def test_meta_handlers_that_do_something_are_permitted(label: str, source: str) -> None:
    """The rule rejects clearly empty handlers, not imperfect recovery."""
    assert broad_exception_offenders(seeded(source)) == [], f"false positive: {label}"


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("empty tuple", "try:\n    f()\nexcept ValueError:\n    ()\n"),
        ("empty list", "try:\n    f()\nexcept ValueError:\n    []\n"),
        ("empty dict", "try:\n    f()\nexcept ValueError:\n    {}\n"),
        ("literal set", "try:\n    f()\nexcept ValueError:\n    {1, 2}\n"),
        ("negative number", "try:\n    f()\nexcept ValueError:\n    -1\n"),
        ("positive number", "try:\n    f()\nexcept ValueError:\n    +1\n"),
        (
            "nested literal container",
            'try:\n    f()\nexcept ValueError:\n    [1, ("a", 2), {"k": None}]\n',
        ),
        ("literal dict", 'try:\n    f()\nexcept ValueError:\n    {"why": "optional"}\n'),
        (
            "literal tuple then pass",
            "try:\n    f()\nexcept ValueError:\n    ()\n    pass\n",
        ),
    ],
)
def test_meta_literal_only_handler_expressions_are_rejected(label: str, source: str) -> None:
    """A literal that is evaluated and discarded is still a swallow."""
    offenders = broad_exception_offenders(seeded(source))

    assert offenders, f"missed the {label} form"
    assert any("swallowed" in reason for _, reason in offenders)


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("list with a call", "try:\n    f()\nexcept ValueError:\n    [recover()]\n"),
        ("dict with a call", 'try:\n    f()\nexcept ValueError:\n    {"result": recover()}\n'),
        ("dict with a call key", "try:\n    f()\nexcept ValueError:\n    {key(): 1}\n"),
        ("tuple with a call", "try:\n    f()\nexcept ValueError:\n    (recover(),)\n"),
        ("walrus", "try:\n    f()\nexcept ValueError:\n    (value := recover())\n"),
        ("dict unpacking", "try:\n    f()\nexcept ValueError:\n    {**recover()}\n"),
        ("bare name", "try:\n    f()\nexcept ValueError:\n    sentinel\n"),
        ("attribute access", "try:\n    f()\nexcept ValueError:\n    obj.attr\n"),
        ("subscript", "try:\n    f()\nexcept ValueError:\n    table[key]\n"),
        (
            "literal then real work",
            "try:\n    f()\nexcept ValueError:\n    ()\n    recover()\n",
        ),
    ],
)
def test_meta_executable_handler_expressions_are_permitted(label: str, source: str) -> None:
    """Anything that executes is not a no-op, however literal it looks."""
    assert broad_exception_offenders(seeded(source)) == [], f"false positive: {label}"


def test_meta_a_bare_except_reports_both_reasons() -> None:
    offenders = broad_exception_offenders(seeded("try:\n    f()\nexcept:\n    pass\n"))

    ((_, reason),) = offenders
    assert "bare" in reason
    assert "swallowed" in reason


# --------------------------------------------------------------------------
# Meta: contextlib.suppress
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "source"),
    [
        (
            "direct suppress(Exception)",
            "from contextlib import suppress\nwith suppress(Exception):\n    work()\n",
        ),
        (
            "direct suppress(BaseException)",
            "from contextlib import suppress\nwith suppress(BaseException):\n    work()\n",
        ),
        (
            "aliased suppress",
            "from contextlib import suppress as ignore\nwith ignore(BaseException):\n    work()\n",
        ),
        (
            "module qualified",
            "import contextlib\nwith contextlib.suppress(Exception):\n    work()\n",
        ),
        (
            "aliased module",
            "import contextlib as cl\nwith cl.suppress(ValueError, Exception):\n    work()\n",
        ),
        (
            "broad among specifics",
            "from contextlib import suppress\n"
            "with suppress(ValueError, KeyError, Exception):\n    work()\n",
        ),
        (
            "aliased exception argument",
            "from contextlib import suppress\nfrom builtins import Exception as E\n"
            "with suppress(E):\n    work()\n",
        ),
        (
            "qualified exception argument",
            "import builtins\nfrom contextlib import suppress\n"
            "with builtins.Exception if 0 else suppress(builtins.Exception):\n    work()\n",
        ),
        (
            "assigned rather than used inline",
            "from contextlib import suppress\ncm = suppress(Exception)\n",
        ),
    ],
)
def test_meta_broad_suppression_is_rejected(label: str, source: str) -> None:
    """`with suppress(Exception)` is `except Exception: pass` in nicer clothing."""
    offenders = broad_exception_offenders(seeded(source))

    assert offenders, f"missed the {label} form"
    assert any("suppress" in reason for _, reason in offenders)


@pytest.mark.parametrize(
    ("label", "source"),
    [
        (
            "specific",
            "from contextlib import suppress\nwith suppress(ValueError):\n    work()\n",
        ),
        (
            "several specifics",
            "from contextlib import suppress\nwith suppress(ValueError, KeyError):\n    work()\n",
        ),
        (
            "project type",
            "from contextlib import suppress\n"
            "from greenmachine.common.errors import GreenMachineError\n"
            "with suppress(GreenMachineError):\n    work()\n",
        ),
        (
            "module qualified specific",
            "import contextlib\nwith contextlib.suppress(ValueError):\n    work()\n",
        ),
        (
            "unrelated helper named suppress",
            "from mylib import suppress\nwith suppress(Exception):\n    work()\n",
        ),
        (
            "method named suppress",
            "with obj.suppress(Exception):\n    work()\n",
        ),
        (
            "contextmanager is not suppress",
            "from contextlib import contextmanager\n@contextmanager\ndef f():\n    yield\n",
        ),
    ],
)
def test_meta_specific_or_unrelated_suppression_is_permitted(label: str, source: str) -> None:
    """Resolution, not name matching: an unrelated `suppress` is untouched."""
    assert broad_exception_offenders(seeded(source)) == [], f"false positive: {label}"


@pytest.mark.parametrize(
    ("label", "source"),
    [
        (
            "starred tuple with Exception",
            "from contextlib import suppress\n"
            "with suppress(*(ValueError, Exception)):\n    work()\n",
        ),
        (
            "starred list with BaseException",
            "from contextlib import suppress\nwith suppress(*[BaseException]):\n    work()\n",
        ),
        (
            "starred tuple with an aliased broad exception",
            "from contextlib import suppress\nfrom builtins import Exception as E\n"
            "with suppress(*(ValueError, E)):\n    work()\n",
        ),
        (
            "starred tuple with a qualified broad exception",
            "import builtins\nfrom contextlib import suppress\n"
            "with suppress(*(builtins.Exception,)):\n    work()\n",
        ),
        (
            "starred list, module-qualified suppress",
            "import contextlib\nwith contextlib.suppress(*[Exception]):\n    work()\n",
        ),
    ],
)
def test_meta_starred_literal_broad_suppression_is_rejected(label: str, source: str) -> None:
    """`suppress(*(ValueError, Exception))` is the valid multi-argument spelling."""
    offenders = broad_exception_offenders(seeded(source))

    assert offenders, f"missed the {label} form"
    assert any("suppress" in reason for _, reason in offenders)


@pytest.mark.parametrize(
    ("label", "source"),
    [
        (
            "starred tuple of specifics",
            "from contextlib import suppress\n"
            "with suppress(*(ValueError, KeyError)):\n    work()\n",
        ),
        (
            "starred list of a project type",
            "from contextlib import suppress\n"
            "from greenmachine.common.errors import GreenMachineError\n"
            "with suppress(*[GreenMachineError]):\n    work()\n",
        ),
        (
            "starred variable stays unresolved",
            "from contextlib import suppress\nwith suppress(*specific_exceptions):\n    work()\n",
        ),
        (
            "starred call stays unresolved",
            "from contextlib import suppress\nwith suppress(*chosen()):\n    work()\n",
        ),
        (
            "unrelated suppress with a starred literal",
            "from mylib import suppress\nwith suppress(*(ValueError, Exception)):\n    work()\n",
        ),
    ],
)
def test_meta_starred_specific_or_unresolvable_suppression_is_permitted(
    label: str, source: str
) -> None:
    """A starred variable is reported as a limitation, never guessed at."""
    assert broad_exception_offenders(seeded(source)) == [], f"false positive: {label}"


def test_meta_the_two_swallow_rules_are_reported_separately() -> None:
    """Handler bodies and suppression are distinct findings on distinct lines."""
    source = (
        "from contextlib import suppress\n"
        "try:\n    f()\nexcept ValueError:\n    ...\n"
        "with suppress(Exception):\n    g()\n"
    )
    tree = seeded(source)

    assert len(handler_offenders(tree)) == 1
    assert len(broad_suppress_offenders(tree)) == 1
    assert len(broad_exception_offenders(tree)) == 2


# --------------------------------------------------------------------------
# Meta: forms that must be permitted
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("ValueError", "try:\n    f()\nexcept ValueError:\n    g()\n"),
        ("named binding", "try:\n    f()\nexcept ValueError as exc:\n    raise Wrapped from exc\n"),
        ("tuple of specifics", "try:\n    f()\nexcept (ValueError, KeyError):\n    g()\n"),
        (
            "project root type",
            "from greenmachine.common.errors import GreenMachineError\n"
            "try:\n    f()\nexcept GreenMachineError:\n    g()\n",
        ),
        (
            "project branch",
            "from greenmachine.common.errors import IngestionError\n"
            "try:\n    f()\nexcept IngestionError:\n    g()\n",
        ),
        (
            "stdlib qualified",
            "import decimal\ntry:\n    f()\nexcept decimal.InvalidOperation:\n    g()\n",
        ),
        ("re-raise", "try:\n    f()\nexcept ValueError:\n    raise\n"),
        ("try/finally only", "try:\n    f()\nfinally:\n    g()\n"),
        ("no handler at all", "def f():\n    return 1\n"),
    ],
)
def test_meta_specific_handlers_are_permitted(label: str, source: str) -> None:
    assert broad_exception_offenders(seeded(source)) == [], f"false positive: {label}"


def test_meta_an_unrelated_class_named_exception_is_not_confused() -> None:
    """A project type merely *named* like a builtin is resolved, not string-matched."""
    source = (
        "from mylib import Exception as NotTheBuiltin\n"
        "try:\n    f()\nexcept NotTheBuiltin:\n    g()\n"
    )

    assert broad_exception_offenders(seeded(source)) == []

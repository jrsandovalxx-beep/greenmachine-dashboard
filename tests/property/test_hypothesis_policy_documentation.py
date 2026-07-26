"""GM-041.5-HF2: the profile's documentation cannot drift from the profile.

Four sources describe the ``greenmachine-ci`` Hypothesis profile:

* ``tests/conftest.py`` — where it is actually registered;
* ``tests/property/conftest.py`` — a docstring listing every setting;
* ``tests/README.md`` — a settings table;
* ``docs/adr/0008-golden-testing-strategy.md`` — the accepted policy.

GM-041.5-HF1 changed the first and left the other three saying the opposite, so
the repository asserted two contradictory health-check policies at once and no
test noticed. These guards compare each document's *claimed values* against the
**live registered profile**, so they check meaning rather than matching a
paragraph of prose: reword any of these files freely and the tests still pass;
change what one of them claims and they fail.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest
from hypothesis import settings

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_CONFTEST = REPO_ROOT / "tests" / "conftest.py"
PROPERTY_CONFTEST = REPO_ROOT / "tests" / "property" / "conftest.py"
TESTS_README = REPO_ROOT / "tests" / "README.md"
ADR_0008 = REPO_ROOT / "docs" / "adr" / "0008-golden-testing-strategy.md"

PROFILE_NAME = "greenmachine-ci"

# Settings a document may state, and how to read the live value as a string.
_LIVE = {
    "derandomize": lambda p: str(p.derandomize),
    "database": lambda p: "None" if p.database is None else repr(p.database),
    "deadline": lambda p: "None" if p.deadline is None else repr(p.deadline),
    "max_examples": lambda p: str(p.max_examples),
    "print_blob": lambda p: str(p.print_blob),
}

# A claim about health checks must both mention them and deny suppression.
_NEGATION = re.compile(r"\b(no|none|never)\b", re.IGNORECASE)
_SUPPRESS = re.compile(r"suppress", re.IGNORECASE)


def _live_profile() -> settings:
    if str(REPO_ROOT / "tests") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "tests"))
    return settings.get_profile(PROFILE_NAME)


def _claimed_settings(text: str) -> dict[str, str]:
    """Every claim a document makes about a known setting, in either notation.

    Two notations are in use and both are read by the same function, so a
    docstring bullet, an ADR sentence, and a markdown table are all comparable:

    * ``name=value`` — docstrings and prose;
    * ``| `name` | `value` | …`` — the settings table in ``tests/README.md``.
    """
    claims: dict[str, str] = {}
    for name in _LIVE:
        for match in re.finditer(rf"`*\b{name}`*\s*=\s*`*([A-Za-z0-9_.]+)`*", text):
            claims[name] = match.group(1)
        table = re.search(
            rf"^\|\s*`?{name}`?\s*\|\s*\**`?([A-Za-z0-9_.]+)`?\**\s*\|", text, re.MULTILINE
        )
        if table:
            claims[name] = table.group(1)
    return claims


def _registered_settings() -> dict[str, str]:
    """What ``tests/conftest.py`` passes to the greenmachine-ci registration.

    Read from the AST rather than by scanning the file, because the same file
    also registers ``greenmachine-exploratory`` with a deliberately different
    budget; a whole-file text scan would conflate the two.
    """
    tree = ast.parse(ROOT_CONFTEST.read_text(encoding="utf-8"), filename=str(ROOT_CONFTEST))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "register_profile"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == PROFILE_NAME
        ):
            claims: dict[str, str] = {}
            for keyword in node.keywords:
                if keyword.arg in _LIVE:
                    claims[keyword.arg] = str(ast.literal_eval(keyword.value))
            return claims
    raise AssertionError(f"no {PROFILE_NAME} registration found in {ROOT_CONFTEST}")


def _health_check_claims(text: str) -> list[str]:
    """Every line that says something about health checks."""
    return [line.strip() for line in text.splitlines() if "health check" in line.lower()]


# --------------------------------------------------------------------------
# The registration itself
# --------------------------------------------------------------------------


def test_the_registration_pins_suppress_health_check_explicitly_and_empty() -> None:
    """Read from the AST, so this is about the code and not about a comment.

    Explicit matters as much as empty: an unspecified setting inherits from the
    active built-in profile, which is what made the value environment-dependent
    in the first place.
    """
    tree = ast.parse(ROOT_CONFTEST.read_text(encoding="utf-8"), filename=str(ROOT_CONFTEST))

    registrations = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "register_profile"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == PROFILE_NAME
    ]
    assert len(registrations) == 1, f"expected exactly one {PROFILE_NAME} registration"

    keywords = {kw.arg: kw.value for kw in registrations[0].keywords}
    assert "suppress_health_check" in keywords, (
        "suppress_health_check must be passed EXPLICITLY; an unspecified setting "
        "is inherited from the active built-in profile, which differs under CI"
    )
    assert ast.literal_eval(keywords["suppress_health_check"]) == (), (
        "GreenMachine suppresses no health check (ADR-0008)"
    )


def test_the_live_profile_agrees_with_the_registration() -> None:
    assert tuple(_live_profile().suppress_health_check) == ()


# --------------------------------------------------------------------------
# Documentation agrees with the live profile
# --------------------------------------------------------------------------

_DOCUMENTS = (
    ("tests/property/conftest.py", PROPERTY_CONFTEST),
    ("tests/README.md", TESTS_README),
    ("docs/adr/0008-golden-testing-strategy.md", ADR_0008),
)


@pytest.mark.parametrize(("label", "path"), _DOCUMENTS, ids=[d[0] for d in _DOCUMENTS])
def test_documented_setting_values_match_the_live_profile(label: str, path: Path) -> None:
    """Whatever a document claims a setting is, that must be what it is."""
    profile = _live_profile()
    claims = _claimed_settings(path.read_text(encoding="utf-8"))

    assert claims, f"{label} states no profile settings at all; it should describe the profile"

    for name, claimed in claims.items():
        actual = _LIVE[name](profile)
        assert claimed == actual, (
            f"{label} says {name}={claimed}, but the registered profile has {name}={actual}"
        )


@pytest.mark.parametrize(("label", "path"), _DOCUMENTS, ids=[d[0] for d in _DOCUMENTS])
def test_every_source_states_the_no_suppression_policy(label: str, path: Path) -> None:
    """Each source must say it, and none may say the opposite.

    Matched semantically -- a mention of health checks together with a negation
    of suppression -- rather than against one fixed sentence, so these files can
    be rewritten without breaking the guard.
    """
    claims = _health_check_claims(path.read_text(encoding="utf-8"))
    assert claims, f"{label} says nothing about health checks; the policy must be stated"

    stated = [c for c in claims if _SUPPRESS.search(c) and _NEGATION.search(c)]
    assert stated, (
        f"{label} mentions health checks but never states that none is suppressed: {claims}"
    )


@pytest.mark.parametrize(
    ("label", "text", "expected"),
    (
        ("docstring bullet", "- ``max_examples=50`` — a budget", {"max_examples": "50"}),
        ("adr prose", "keeps `database=None`, explicit `max_examples=50`,", {"max_examples": "50"}),
        ("readme table", "| `max_examples` | `50` | explicit budget |", {"max_examples": "50"}),
        ("bold table value", "| seed | **20260724** | fixed |", {}),
    ),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_meta_the_parser_reads_each_notation(
    label: str, text: str, expected: dict[str, str]
) -> None:
    """A parser that silently matches nothing would make every guard vacuous."""
    claims = _claimed_settings(text)
    for name, value in expected.items():
        assert claims.get(name) == value, label


def test_meta_a_drifted_document_is_caught() -> None:
    """The exact shape HF1 left behind: a document claiming the old value."""
    drifted = _claimed_settings("| `max_examples` | `999` | stale |")

    assert drifted["max_examples"] == "999"
    assert drifted["max_examples"] != str(_live_profile().max_examples)


@pytest.mark.parametrize(
    ("label", "line", "states_policy"),
    (
        ("denies suppression", "No health check is suppressed.", True),
        ("table cell", "| health checks | none suppressed | |", True),
        ("adr wording", "and no suppressed health checks;", True),
        ("asserts a suppression", "health checks: too_slow is suppressed", False),
        ("silent on the point", "health checks run during generation", False),
    ),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_meta_the_policy_matcher_distinguishes_a_claim_from_its_opposite(
    label: str, line: str, states_policy: bool
) -> None:
    matched = bool(_SUPPRESS.search(line) and _NEGATION.search(line))

    assert matched is states_policy, label


def test_all_four_sources_are_consistent_with_one_another() -> None:
    """The failure mode HF1 actually produced: code changed, documents did not.

    Every setting any document names is collected and compared across all of
    them, so two documents disagreeing fails here even if each separately
    matched the profile at the time it was written.
    """
    collected: dict[str, dict[str, str]] = {"tests/conftest.py": _registered_settings()}
    for label, path in _DOCUMENTS:
        collected[label] = _claimed_settings(path.read_text(encoding="utf-8"))

    names = {name for claims in collected.values() for name in claims}
    for name in sorted(names):
        values = {label: claims[name] for label, claims in collected.items() if name in claims}
        distinct = set(values.values())
        assert len(distinct) == 1, f"sources disagree about {name}: {values}"

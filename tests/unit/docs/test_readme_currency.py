"""The canonical root README must describe the delivered system, not a stale one.

Scope is deliberately narrow: **only** the repository-root `README.md`, which is
the canonical entry point a reviewer or contributor reads first. Explicitly
excluded are the CHANGELOG, the Sprint 1 records, revision histories, and the
preserved noncanonical `greenmachine/` duplicate — those are historical
documents and may accurately describe superseded designs, including the removed
v6.3 signal engine.

Two rules. The retired claims below must not return to the canonical README:
GM-041 delivered the grading engine, and every one of these statements was true
of the README before it and false after. And the permanent product principle —
GreenMachine separates evaluation from decision-making and produces no automated
recommendation — must remain stated.

Ordinary English is not banned. "pass" appears legitimately in prose ("a first
pass"), so only the betting-classification token forms are refused.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
README = REPO_ROOT / "README.md"


def readme_text() -> str:
    return README.read_text(encoding="utf-8")


def normalized() -> str:
    """README text with whitespace collapsed, so a line wrap cannot hide a phrase."""
    return " ".join(readme_text().split())


# --------------------------------------------------------------------------
# Retired betting vocabulary
# --------------------------------------------------------------------------

# Token forms only. `LEAN`/`AVOID`/`PASS` are matched as standalone uppercase
# words so ordinary prose ("a first pass", "lean on") is unaffected.
_BANNED_TOKENS = (
    "STRONG_BET",
    "STRONG BET",
    r"\bLEAN\b",
    r"\bAVOID\b",
    r"\bPASS\b",
)


@pytest.mark.parametrize("pattern", _BANNED_TOKENS, ids=lambda p: p.strip("\\b"))
def test_the_readme_advertises_no_betting_classification(pattern: str) -> None:
    found = re.search(pattern, readme_text())
    assert found is None, (
        f"README advertises the retired betting classification {pattern!r}; "
        f"GM-041 removed every betting classification from all scope"
    )


_BANNED_PHRASES = (
    # Betting-signal vocabulary as a current-facing claim.
    "betting signal",
    "signal rule that fired",
    "assigns a grade and a signal",
    "alter a grade or signal",
    "signal engine",
    "Signals:",
    # Stale implementation status.
    "grading engine itself is still not implemented",
    "no runtime scoring engine exists",
    "computes no score",
    # Stale placeholder status for scoring.
    "**Placeholder-only** (docstring packages with no behavior): `scoring`",
    "`scoring`, `features`,\n`cli`",
)


@pytest.mark.parametrize("phrase", _BANNED_PHRASES, ids=lambda p: p[:40])
def test_the_readme_carries_no_stale_current_facing_claim(phrase: str) -> None:
    assert phrase not in readme_text(), (
        f"README contains the stale claim {phrase!r}; it describes a design or "
        f"status that GM-041 superseded"
    )


def test_the_readme_does_not_list_signals_as_an_output() -> None:
    """The v6.3 output line is gone in every spelling."""
    text = normalized()
    for claim in (
        "assigns a grade and a signal",
        "Signals: `STRONG_BET`",
        "then assigns a grade and a signal",
    ):
        assert claim not in text, claim


def test_scoring_is_not_described_as_a_placeholder() -> None:
    """`features` and `cli` may remain placeholders; `scoring` may not."""
    text = normalized()
    placeholder_sentences = [
        sentence
        for sentence in re.split(r"(?<=[.!])\s", text)
        if "laceholder" in sentence and "`scoring`" in sentence
    ]
    offending = [s for s in placeholder_sentences if "no longer a placeholder" not in s]
    assert offending == [], (
        f"README still describes `scoring` as a placeholder: {offending}; GM-041 implements it"
    )


# --------------------------------------------------------------------------
# Required current statements
# --------------------------------------------------------------------------


def test_the_readme_states_the_engine_is_implemented() -> None:
    text = normalized()
    assert "GM-041 implements the deterministic production grading engine" in text


def test_the_readme_states_no_production_configuration_is_approved() -> None:
    text = normalized()
    assert "No production model configuration has been approved yet" in text
    assert "synthetic" in text


def test_the_readme_lists_exactly_the_six_engine_outputs() -> None:
    text = normalized()
    for output in (
        "Total Score",
        "Tier",
        "Component Breakdown",
        "Audit Trail",
        "Warnings",
        "Fallbacks",
    ):
        assert output in text, output


def test_the_readme_states_the_separation_of_evaluation_from_decision_making() -> None:
    """The permanent product principle, in the canonical entry point."""
    text = normalized()
    assert "GreenMachine intentionally separates evaluation from decision-making" in text
    assert "belongs entirely to the user" in text


def test_the_readme_states_no_automated_recommendation_is_produced() -> None:
    text = normalized()
    assert "no automated recommendation" in text
    assert "no decision output" in text


def test_the_readme_records_the_current_ticket_sequence() -> None:
    text = normalized()
    assert "GM-041.5" in text
    assert "Stabilization & UX Review" in text
    assert "GM-042" in text


def test_the_readme_states_the_prototype_does_not_render_the_engine_yet() -> None:
    text = normalized()
    assert "does not yet render the production engine" in text


# --------------------------------------------------------------------------
# Scope: historical documents are deliberately untouched
# --------------------------------------------------------------------------


def test_this_suite_inspects_only_the_canonical_root_readme() -> None:
    """Anti-overreach: the rules above must not be read as repository-wide.

    The CHANGELOG legitimately records the removed v6.3 signal engine, and the
    preserved nested duplicate is noncanonical. Neither is in scope.
    """
    assert README == REPO_ROOT / "README.md"
    changelog = REPO_ROOT / "CHANGELOG.md"
    if changelog.is_file():
        # Anti-vacuity: history really does mention what the README may not, so
        # a repository-wide ban would have been wrong.
        assert "signal" in changelog.read_text(encoding="utf-8").lower()

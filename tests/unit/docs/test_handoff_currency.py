"""The handoff's *current-facing* sections must describe the merged project.

The canonical handoff is one document doing two jobs. Most of it describes the
system as it is now; §16 is a **revision history** in which every entry
accurately records the state at the time it was written. Rev 6 saying "the
Streamlit prototype does not yet render the production engine's evaluation" was
true when rev 6 was written, and rewriting it would falsify the record.

So every assertion here is scoped to a named current-facing section — the
project overview, the milestone table, the roadmap, and the Quick Start expected
result — and the revision history is excluded by construction. There is no
whole-document substring ban: a phrase banned outright would eventually collide
with a legitimate historical sentence, and the guard would then be pressuring
someone to edit the record.

The specific regressions guarded are the ones GM-041.5-HF2 rev 15 corrected:
claiming the engine evaluation is still pending, showing GM-041 or GM-041.5 as
unmerged, mis-sequencing the roadmap, and reporting five Windows platform skips
where there are six.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HANDOFF = REPO_ROOT / "docs" / "GREENMACHINE_DEVELOPER_HANDOFF.md"

# The heading that opens the revision history. Everything from here on is a
# historical record and is never asserted against.
_REVISION_HISTORY_HEADING = "## 16. REVISION HISTORY"


def _document() -> str:
    return HANDOFF.read_text(encoding="utf-8")


def _current_facing() -> str:
    """The document with its revision history removed.

    Splitting on the heading rather than on a line number keeps the guard
    working when sections move, and makes the exclusion explicit rather than
    incidental.
    """
    text = _document()
    index = text.find(_REVISION_HISTORY_HEADING)
    assert index != -1, "the revision-history heading moved; this guard needs updating"
    return text[:index]


def _section(heading_pattern: str) -> str:
    """One numbered top-level section of the current-facing document."""
    text = _current_facing()
    match = re.search(rf"^## {heading_pattern}.*$", text, re.MULTILINE)
    assert match, f"section {heading_pattern!r} not found"
    start = match.start()
    following = re.search(r"^## \d+", text[match.end() :], re.MULTILINE)
    end = match.end() + following.start() if following else len(text)
    return text[start:end]


def _flat(text: str) -> str:
    """Whitespace collapsed, so a line wrap cannot hide a phrase."""
    return " ".join(text.split())


# --------------------------------------------------------------------------
# The revision history is genuinely excluded
# --------------------------------------------------------------------------


def test_the_revision_history_exists_and_is_excluded() -> None:
    """Anti-vacuity: if the split silently failed, every guard below is empty.

    The historical phrasing this file must NOT police is asserted to be present
    in the document and absent from the slice the guards read.
    """
    document = _document()
    current = _current_facing()

    assert _REVISION_HISTORY_HEADING in document
    assert _REVISION_HISTORY_HEADING not in current
    assert len(current) < len(document)

    historical = "does not yet render the production engine's evaluation"
    assert historical in _flat(document), "the historical rev-6 sentence should still be recorded"
    assert historical not in _flat(current), "historical text must not reach the current slice"


# --------------------------------------------------------------------------
# 1. The engine evaluation is rendered, not pending
# --------------------------------------------------------------------------


def test_the_overview_states_the_console_renders_the_engine_evaluation() -> None:
    overview = _flat(_section(r"1\. PROJECT OVERVIEW"))

    assert "Engine Evaluation" in overview
    assert "renders that engine's evaluation" in overview


@pytest.mark.parametrize(
    "pending",
    (
        "does not yet render",
        "surfacing it belongs to GM-041.5",
        "belongs to GM-041.5",
    ),
    ids=lambda value: value,
)
def test_the_overview_does_not_call_the_engine_evaluation_pending(pending: str) -> None:
    assert pending not in _flat(_section(r"1\. PROJECT OVERVIEW"))


@pytest.mark.parametrize(
    ("label", "phrase"),
    (
        ("synthetic configuration", "synthetic, non-production"),
        ("no approved production configuration", "no approved production model configuration"),
        ("live capture is CLI only", "live capture remains command-line only"),
    ),
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_the_overview_keeps_the_three_bounds_on_what_that_means(label: str, phrase: str) -> None:
    """Rendering the engine is only safe to state alongside its limits."""
    assert phrase.lower() in _flat(_section(r"1\. PROJECT OVERVIEW")).lower(), label


# --------------------------------------------------------------------------
# 2. GM-041 and GM-041.5 are merged
# --------------------------------------------------------------------------


def _milestone_row(ticket: str) -> str:
    """The one table row whose FIRST cell names this ticket, exactly.

    Matching on the first cell rather than anywhere in the table is what makes
    the assertion about *this* ticket. Matching it exactly is what keeps
    `GM-041` from selecting the `GM-041.5` row — a substring test would, and
    would then read GM-041.5's status while claiming to check GM-041.
    """
    rows = [
        line
        for line in _section(r"2\. ").splitlines()
        if line.lstrip().startswith("|") and line.count("|") >= 3
    ]
    matched = [row for row in rows if row.split("|")[1].strip().strip("*` ") == ticket]

    assert len(matched) == 1, (
        f"expected exactly one milestone row whose first cell is {ticket!r}, found {len(matched)}"
    )
    return matched[0]


@pytest.mark.parametrize("ticket", ("GM-041", "GM-041.5"), ids=("GM-041", "GM-041.5"))
def test_the_milestone_table_marks_the_delivered_tickets_merged(ticket: str) -> None:
    """Each delivered ticket's OWN row says merged.

    The earlier version asserted only that "MERGED" appeared somewhere in the
    table, which one merged row could satisfy on behalf of every other. This
    reads the selected row's status cell.
    """
    row = _milestone_row(ticket)
    status = row.split("|")[2].upper()

    assert "MERGED" in status, f"{ticket} row does not say merged: {row.strip()}"

    # The same row, checked for the stale wordings it must never return to.
    # Asserted here rather than in a separate test because it is a statement
    # about this ticket's row, and the parametrization that selects that row
    # already lives here.
    for stale in ("AWAITING REVIEW", "PENDING INDEPENDENT REVIEW", "NOT STARTED"):
        assert stale not in status, f"{ticket} row carries stale status {stale!r}: {row.strip()}"


def test_meta_the_row_matcher_does_not_confuse_gm041_with_gm0415() -> None:
    """The bug a substring match would have: two tickets, one a prefix of the other."""
    assert _milestone_row("GM-041") != _milestone_row("GM-041.5")
    assert _milestone_row("GM-041").split("|")[1].strip().strip("*` ") == "GM-041"
    assert _milestone_row("GM-041.5").split("|")[1].strip().strip("*` ") == "GM-041.5"


def test_no_current_facing_section_heading_calls_merged_work_awaiting_review() -> None:
    """Headings drift too, and a heading is the most visible claim in a section.

    §12a read "CURRENT MILESTONE — GM-041.5 — COMPLETE, AWAITING REVIEW" after
    GM-041.5 had merged; the milestone-table guard above did not see it because
    it lives in a different section. Every current-facing heading is checked.
    """
    merged = ("GM-041", "GM-041.5")
    offenders = []
    for heading in re.findall(r"^##+ .*$", _current_facing(), re.MULTILINE):
        if "AWAITING REVIEW" not in heading.upper():
            continue
        if any(ticket in heading for ticket in merged) and "HF2" not in heading:
            offenders.append(heading.strip())

    assert offenders == [], f"merged work still headed as awaiting review: {offenders}"


def test_the_open_correction_is_named_and_separated_from_the_merged_work() -> None:
    table = _flat(_section(r"2\. "))

    assert "GM-041.5-HF1" in table
    assert "GM-041.5-HF2" in table
    assert "PR #6" in table


# --------------------------------------------------------------------------
# 3. Roadmap sequencing
# --------------------------------------------------------------------------


def test_the_roadmap_shows_the_delivered_tickets_complete() -> None:
    roadmap = _flat(_section(r"13\. FUTURE ROADMAP"))

    assert "awaiting review" not in roadmap
    assert "must not be started" not in roadmap
    assert roadmap.count("complete") >= 2


def test_the_roadmap_names_hf2_as_the_currently_open_correction() -> None:
    roadmap = _flat(_section(r"13\. FUTURE ROADMAP"))

    assert "GM-041.5-HF2 is the currently open correction" in roadmap
    assert "no later ticket begins until it is merged" in roadmap


def test_the_roadmap_keeps_gm042_as_the_next_planned_product_ticket() -> None:
    roadmap = _flat(_section(r"13\. FUTURE ROADMAP"))

    assert "GM-042 remains the next planned product ticket" in roadmap


# --------------------------------------------------------------------------
# 4. The Quick Start expected result
# --------------------------------------------------------------------------


def test_quick_start_reports_six_windows_platform_skips() -> None:
    """Six, not five: the discovery suite added a symlink-confinement case."""
    quick_start = _flat(_section(r"14\. "))

    assert "six Windows platform skips" in quick_start
    assert "five Windows platform skips" not in quick_start


# The suite size this revision actually produces. Stated once here so the two
# current-facing places that quote it cannot drift apart, or away from reality.
EXPECTED_PASS_COUNT = "3,746"


def test_the_current_expected_pass_count_matches_the_recorded_result() -> None:
    """One number, stated in both current-facing places, and they must agree.

    Only current-facing text is inspected. Revision-history entries quote the
    counts that were true at their own commits — revision 14 legitimately says
    3,727 — and are excluded by `_current_facing`.
    """
    current = _flat(_current_facing())
    counts = set(re.findall(r"([\d,]+) tests green \(rev \d+\)", current))
    counts |= set(re.findall(r"expect fully green \(([\d,]+) passed", current))

    assert counts, "the current-facing document states no expected pass count"
    assert len(counts) == 1, f"current-facing sections disagree about the pass count: {counts}"
    assert counts == {EXPECTED_PASS_COUNT}, (
        f"current-facing sections claim {counts}, but this revision runs {EXPECTED_PASS_COUNT}"
    )

"""Drift test: the code vocabulary and ``GLOSSARY.md`` must not diverge.

ENGINEERING_GUIDELINES 7: "Identifiers match GLOSSARY.md exactly. A drift test
enforces this."

The earlier version searched the whole document for each member's value as a
substring, which is far too weak to be trusted: ``Grade.A`` "passes" because the
letter A appears somewhere in a 400-line document, and a renamed or reordered
member could slip through unnoticed.

This version instead parses the delimited vocabulary block in ``GLOSSARY.md``
(§10, between the BEGIN/END DOMAIN VOCABULARY markers) and compares it to the code
**exactly** — every enum, every member, in declaration order, in both directions.
Nothing passes by accident.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

import pytest

from greenmachine.domain import (
    AcquisitionMethod,
    Category,
    ComponentId,
    CoverageStatus,
    EvaluationStatus,
    Grade,
    MeasurementId,
    MissingReason,
    PitcherRole,
    ProviderId,
    SampleStatus,
    SampleType,
    Signal,
    ValidationInputId,
    WindowProfile,
)

GLOSSARY_PATH = Path(__file__).resolve().parents[3] / "docs" / "GLOSSARY.md"

BEGIN_MARKER = "<!-- BEGIN DOMAIN VOCABULARY -->"
END_MARKER = "<!-- END DOMAIN VOCABULARY -->"

# Every enum exported by the domain package, keyed by its class name.
EXPORTED_ENUMS: dict[str, type[Enum]] = {
    enum_type.__name__: enum_type
    for enum_type in (
        AcquisitionMethod,
        Category,
        ComponentId,
        CoverageStatus,
        EvaluationStatus,
        Grade,
        MeasurementId,
        MissingReason,
        PitcherRole,
        ProviderId,
        SampleStatus,
        SampleType,
        Signal,
        ValidationInputId,
        WindowProfile,
    )
}


def parse_glossary_vocabulary(text: str) -> dict[str, list[str]]:
    """Extract ``{enum name: [member values in order]}`` from the delimited block."""
    start = text.index(BEGIN_MARKER) + len(BEGIN_MARKER)
    end = text.index(END_MARKER)
    block = text[start:end]

    vocabulary: dict[str, list[str]] = {}
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("|---"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) != 2 or cells[0] in ("Enum", ""):
            continue
        name = cells[0].strip("`")
        members = re.findall(r"`([^`]+)`", cells[1])
        vocabulary[name] = members
    return vocabulary


@pytest.fixture(scope="module")
def glossary_vocabulary() -> dict[str, list[str]]:
    if not GLOSSARY_PATH.exists():
        pytest.skip("GLOSSARY.md is unavailable outside a source checkout")
    return parse_glossary_vocabulary(GLOSSARY_PATH.read_text(encoding="utf-8"))


def test_the_vocabulary_block_parses(glossary_vocabulary: dict[str, list[str]]) -> None:
    """Guard the guard: an unparseable block must fail, not silently match nothing."""
    assert glossary_vocabulary, "the GLOSSARY.md domain vocabulary block parsed as empty"
    assert all(members for members in glossary_vocabulary.values()), (
        "an enum in the vocabulary block has no members"
    )


def test_every_exported_enum_is_documented(glossary_vocabulary: dict[str, list[str]]) -> None:
    """Code to glossary: no exported enum is missing from the vocabulary block."""
    undocumented = sorted(set(EXPORTED_ENUMS) - set(glossary_vocabulary))

    assert not undocumented, f"enums missing from GLOSSARY.md §10: {undocumented}"


def test_the_glossary_documents_no_unknown_enum(
    glossary_vocabulary: dict[str, list[str]],
) -> None:
    """Glossary to code: every documented enum exists in the domain package."""
    unknown = sorted(set(glossary_vocabulary) - set(EXPORTED_ENUMS))

    assert not unknown, f"GLOSSARY.md §10 documents enums absent from the code: {unknown}"


@pytest.mark.parametrize("enum_name", sorted(EXPORTED_ENUMS))
def test_enum_members_match_the_glossary_exactly(
    enum_name: str, glossary_vocabulary: dict[str, list[str]]
) -> None:
    """Members and their declaration order agree exactly, in both directions."""
    documented = glossary_vocabulary[enum_name]
    in_code = [str(member.value) for member in EXPORTED_ENUMS[enum_name]]

    assert in_code == documented, (
        f"{enum_name} drifted from GLOSSARY.md §10.\n"
        f"  code:     {in_code}\n"
        f"  glossary: {documented}"
    )


def test_signal_declaration_order_is_the_approved_priority_order() -> None:
    """MODEL_SPEC §16 / Q27: AVOID is evaluated first and the first match wins.

    The enum is declared in priority order so no reader infers precedence from a
    different ordering. This asserts the vocabulary only — signal resolution is
    Sprint 2.
    """
    assert list(Signal) == [Signal.AVOID, Signal.STRONG_BET, Signal.LEAN, Signal.PASS]


def test_signal_priority_order_is_documented(
    glossary_vocabulary: dict[str, list[str]],
) -> None:
    """The glossary records the same priority order the enum declares."""
    assert glossary_vocabulary["Signal"] == ["AVOID", "STRONG_BET", "LEAN", "PASS"]


def test_removed_form_metrics_are_absent_from_the_glossary() -> None:
    """The retired Form metrics must not creep back into the documentation."""
    text = GLOSSARY_PATH.read_text(encoding="utf-8")

    for removed in ("`chase_rate`", "`zone_contact_pct`", "`whiff_rate`"):
        assert removed not in text

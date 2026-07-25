"""GM-041.5: the canonical location of the non-production configuration.

The deployed Streamlit app must never read an executable configuration out of
``tests/``. GM-041.5 relocated the disclaimed synthetic configuration to one
canonical path outside the test tree, byte-for-byte, and left no second copy.

These tests pin the location, the uniqueness, and — most importantly — that the
relocation changed nothing: the same source bytes, the same semantic
``config_hash``, and therefore the same engine output.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from greenmachine.config import load_versioned_config

REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL = REPO_ROOT / "config" / "nonproduction" / "gm041_engine_synthetic.yaml"
RETIRED = REPO_ROOT / "tests" / "fixtures" / "config" / "valid" / "gm041_engine_synthetic.yaml"

# Captured from the file before the move and re-verified after it. A change to
# either value means the relocation was not byte-faithful, or that somebody
# edited a disclaimed non-production configuration without a ticket.
EXPECTED_SOURCE_DIGEST = "51dac8cccfbba66d69a9dd6b744f4f077ecb1a37bdbaf7185242f0c224a5ece5"
EXPECTED_CONFIG_HASH = "4502a00bc2f44deb9f79cae5f5439f49fe4e9dac3d2c7f169576013a9fc636a4"
EXPECTED_VERSION = "gm041-engine-synthetic-0"


def test_the_canonical_nonproduction_path_exists() -> None:
    assert CANONICAL.is_file()
    assert CANONICAL.parent == REPO_ROOT / "config" / "nonproduction"


def test_the_retired_fixture_path_is_gone() -> None:
    """No second copy: two configurations claiming one identity is a trap."""
    assert not RETIRED.exists()


def test_exactly_one_copy_exists_anywhere_in_the_canonical_project() -> None:
    matches = [
        path
        for path in REPO_ROOT.rglob("gm041_engine_synthetic.yaml")
        # The nested `greenmachine/` tree is a preserved noncanonical duplicate
        # (handoff §11a) and is deliberately out of scope.
        if "greenmachine" not in path.relative_to(REPO_ROOT).parts[:1]
    ]
    assert matches == [CANONICAL]


def test_the_relocation_preserved_the_exact_source_bytes() -> None:
    versioned = load_versioned_config(CANONICAL)

    assert versioned.source_digest == EXPECTED_SOURCE_DIGEST


def test_the_relocation_preserved_the_semantic_config_hash() -> None:
    """The behaviour-affecting projection is unchanged, so scores cannot move."""
    versioned = load_versioned_config(CANONICAL)

    assert versioned.config_hash.value == EXPECTED_CONFIG_HASH
    assert versioned.version_identifier == EXPECTED_VERSION


def test_the_versioned_record_reports_its_own_absolute_source_path() -> None:
    versioned = load_versioned_config(CANONICAL)

    assert versioned.source_path is not None
    assert Path(versioned.source_path) == CANONICAL.resolve()


def test_the_configuration_announces_itself_as_non_production() -> None:
    text = CANONICAL.read_text(encoding="utf-8")

    assert "NOT A MODEL CONFIGURATION" in text
    assert "Q11-Q16" in text


# --------------------------------------------------------------------------
# Every consumer points at the canonical path
# --------------------------------------------------------------------------

_CONSUMERS = (
    REPO_ROOT / "streamlit_app.py",
    REPO_ROOT / "scripts" / "generate_gm041_sample_evaluation.py",
    REPO_ROOT / "tests" / "unit" / "scoring" / "test_engine.py",
)


@pytest.mark.parametrize("path", _CONSUMERS, ids=lambda p: p.name)
def test_no_consumer_still_references_the_retired_fixture_path(path: Path) -> None:
    source = path.read_text(encoding="utf-8")

    assert (
        "fixtures" not in source
        or "gm041_engine_synthetic" not in source.split("fixtures", 1)[1][:200]
    ), f"{path.name} still points into tests/fixtures for the configuration"


@pytest.mark.parametrize("path", _CONSUMERS, ids=lambda p: p.name)
def test_every_consumer_uses_the_canonical_path(path: Path) -> None:
    source = path.read_text(encoding="utf-8")

    assert re.search(r'"config"\s*/\s*"nonproduction"', source), (
        f"{path.name} should build the configuration path from config/nonproduction"
    )


# --------------------------------------------------------------------------
# Typed failures for an unusable configuration
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "contents"),
    [
        ("malformed yaml", "allocations: { categories: ["),
        ("schema violation", "schema_version: 1\nmodel_configuration_version: 3\n"),
        ("semantic violation", "schema_version: 1\nfuzzy_scoring:\n  enabled: true\n"),
        ("empty", ""),
    ],
)
def test_an_unusable_configuration_raises_a_typed_configuration_error(
    label: str, contents: str, tmp_path: Path
) -> None:
    from greenmachine.common.errors import ConfigurationError

    target = tmp_path / "broken.yaml"
    target.write_text(contents, encoding="utf-8")

    with pytest.raises(ConfigurationError) as caught:
        load_versioned_config(target)

    assert caught.value.error_type, label


def test_an_absent_configuration_raises_a_typed_parse_error(tmp_path: Path) -> None:
    from greenmachine.config import ConfigParseError

    with pytest.raises(ConfigParseError):
        load_versioned_config(tmp_path / "does_not_exist.yaml")

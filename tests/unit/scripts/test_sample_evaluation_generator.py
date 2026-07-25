"""GM-041 sample-evaluation generator: output contract and path handling.

Two properties the independent review asked for. First, an evaluated profile
exposes **exactly** the six approved engine outputs — Total Score, Tier,
Component Breakdown, Audit Trail, Warnings, Fallbacks — and nothing else, so a
seventh key can never appear by accident. Second, ``--output`` accepts a
directory outside the repository, which previously wrote both files and then
crashed on ``Path.relative_to``.

The generator reads the frozen evidence bundle and never writes to it.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_gm041_sample_evaluation.py"
OHTANI_BUNDLE = REPO_ROOT / "evidence" / "gm020_vertical_slice" / "run_gm040_ohtani"


def _load_generator() -> ModuleType:
    """Import the composition-root script by path, as a runner would."""
    spec = importlib.util.spec_from_file_location("gm041_sample_generator", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    return _load_generator()


# --------------------------------------------------------------------------
# The six evaluated outputs
# --------------------------------------------------------------------------


def test_the_generator_declares_exactly_the_six_approved_outputs(
    generator: ModuleType,
) -> None:
    """The declared contract itself, before any document is built."""
    assert (
        frozenset(
            {
                "total_score",
                "tier",
                "component_breakdown",
                "audit_trail",
                "warnings",
                "fallbacks",
            }
        )
        == generator.EVALUATED_KEYS
    )


def test_every_evaluated_profile_carries_exactly_the_six_output_keys(
    generator: ModuleType,
) -> None:
    """No seventh key — evaluation_status included — on an evaluated profile."""
    config = generator.load_config(generator.DEFAULT_CONFIG)
    document = generator.build_document(OHTANI_BUNDLE, config)

    evaluated = 0
    for name, profile in document["profiles"].items():
        if "total_score" not in profile:
            continue  # a NOT_EVALUABLE profile is not an evaluated profile
        evaluated += 1
        assert set(profile) == generator.EVALUATED_KEYS, name

    assert evaluated == 2, "both archived profiles should evaluate under the fixture"


def test_sample_provenance_metadata_is_separate_from_engine_output(
    generator: ModuleType,
) -> None:
    """Top-level keys describe the sample, not the engine's analytical result."""
    config = generator.load_config(generator.DEFAULT_CONFIG)
    document = generator.build_document(OHTANI_BUNDLE, config)

    assert set(document) == generator.METADATA_KEYS | {"profiles"}
    assert generator.METADATA_KEYS.isdisjoint(generator.EVALUATED_KEYS)


def test_no_profile_carries_a_betting_classification(generator: ModuleType) -> None:
    config = generator.load_config(generator.DEFAULT_CONFIG)
    rendered = json.dumps(generator.build_document(OHTANI_BUNDLE, config), default=str)

    for banned in ("STRONG_BET", "LEAN", "AVOID", "signal", "recommend"):
        assert banned not in rendered, banned


# --------------------------------------------------------------------------
# Output directory outside the repository
# --------------------------------------------------------------------------


def test_an_output_directory_outside_the_repository_succeeds(
    generator: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """tmp_path is outside the repository, so relative_to would raise."""
    with pytest.raises(ValueError):
        tmp_path.relative_to(REPO_ROOT)  # the precondition this test exists for

    exit_code = generator.main(["--output", str(tmp_path)])

    assert exit_code == 0
    json_path = tmp_path / "gm041_sample_evaluation.json"
    markdown_path = tmp_path / "gm041_sample_evaluation.md"
    assert json_path.is_file()
    assert markdown_path.is_file()

    printed = capsys.readouterr().out
    assert "gm041_sample_evaluation.json" in printed
    assert "gm041_sample_evaluation.md" in printed


def test_generation_to_an_external_directory_is_deterministic(
    generator: ModuleType, tmp_path: Path
) -> None:
    assert generator.main(["--output", str(tmp_path)]) == 0
    first_json = (tmp_path / "gm041_sample_evaluation.json").read_bytes()
    first_markdown = (tmp_path / "gm041_sample_evaluation.md").read_bytes()

    assert generator.main(["--output", str(tmp_path)]) == 0

    assert (tmp_path / "gm041_sample_evaluation.json").read_bytes() == first_json
    assert (tmp_path / "gm041_sample_evaluation.md").read_bytes() == first_markdown


def test_a_repository_relative_output_prints_a_relative_path(
    generator: ModuleType,
) -> None:
    inside = REPO_ROOT / "docs" / "samples" / "gm041_sample_evaluation.json"
    assert generator._display_path(inside) == "docs/samples/gm041_sample_evaluation.json"


def test_an_external_output_prints_a_resolved_absolute_path(
    generator: ModuleType, tmp_path: Path
) -> None:
    displayed = generator._display_path(tmp_path / "gm041_sample_evaluation.json")

    assert displayed.endswith("gm041_sample_evaluation.json")
    assert Path(displayed).is_absolute()

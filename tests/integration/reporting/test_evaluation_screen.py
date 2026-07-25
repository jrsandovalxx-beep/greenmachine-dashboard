"""GM-041.5: the Engine Evaluation screen, driven through Streamlit AppTest.

Every assertion targets rendered content — exact totals, tiers, component ids,
audit sequence numbers, fallback provenance — rather than merely proving the app
did not crash. The suite-wide network guard is active, so a successful render is
itself proof the screen performs no network request.

The numbers below are **synthetic demonstrations** produced by the real engine
over the real archived bundles under
``config/nonproduction/gm041_engine_synthetic.yaml``. They are deterministic and
therefore assertable, and they say nothing about either hitter.
"""

from __future__ import annotations

import decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_PATH = REPO_ROOT / "streamlit_app.py"
EVIDENCE_ROOT = REPO_ROOT / "evidence" / "gm020_vertical_slice"
SYNTHETIC_CONFIG = REPO_ROOT / "config" / "nonproduction" / "gm041_engine_synthetic.yaml"

# (run, profile index) -> (total, tier). Deterministic under the synthetic
# configuration; regenerating them requires an explicit ticket.
_EXPECTED: dict[tuple[str, int], tuple[str, str]] = {
    ("prospective_run", 0): ("2.9", "D"),
    ("prospective_run", 1): ("4.55", "C"),
    ("run_gm040_ohtani", 0): ("5.15", "C"),
    ("run_gm040_ohtani", 1): ("7.1", "B"),
}
_AUDIT_ENTRIES = 20


def _app(evidence_root: Path | None = None) -> AppTest:
    app = AppTest.from_file(str(APP_PATH), default_timeout=600)
    if evidence_root is not None:
        app.session_state["_unused"] = None  # keeps the harness explicit
    app.run()
    return app


def _rendered_text(app: AppTest) -> str:
    pieces: list[str] = []
    for kind in (
        "title",
        "header",
        "subheader",
        "markdown",
        "caption",
        "warning",
        "info",
        "success",
        "error",
        "code",
    ):
        for element in getattr(app, kind):
            pieces.append(str(element.value))
    for metric in app.get("metric"):
        pieces.append(f"{metric.proto.label} {metric.proto.body}")
    for expander in app.get("expander"):
        pieces.append(str(expander.proto.label))
    for radio in app.radio:
        pieces.append(str(radio.label))
        pieces.append(str(radio.value))
    for button in app.button:
        pieces.append(str(button.label))
    return " \n".join(pieces)


def _open_evaluation(run_name: str = "prospective_run", profile_index: int = 0) -> AppTest:
    """Select a run, open Engine Evaluation, and choose a window profile."""
    app = _app()
    app.selectbox(key="run_select").select(run_name).run()
    app.button(key="nav_evaluate").click().run()
    app.radio(key="evaluation_profile").set_value(
        app.radio(key="evaluation_profile").options[profile_index]
    ).run()
    return app


# --------------------------------------------------------------------------
# Navigation
# --------------------------------------------------------------------------


def test_the_hub_offers_a_sixth_engine_evaluation_destination() -> None:
    app = _app()
    assert "ENGINE EVALUATION" in _rendered_text(app)
    assert app.button(key="nav_evaluate") is not None


def test_the_evaluation_screen_returns_to_the_hub() -> None:
    app = _app()
    app.button(key="nav_evaluate").click().run()
    assert "Deterministic Engine Evaluation" in _rendered_text(app)

    app.button(key="return_hub").click().run()

    text = _rendered_text(app)
    assert "ENGINE EVALUATION" in text
    assert "Deterministic Engine Evaluation" not in app.title[0].value


# --------------------------------------------------------------------------
# Both profiles, both real bundles, exact synthetic values
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("run_name", "profile_index"), sorted(_EXPECTED))
def test_each_bundle_and_profile_renders_its_exact_total_and_tier(
    run_name: str, profile_index: int
) -> None:
    total, tier = _EXPECTED[(run_name, profile_index)]
    app = _open_evaluation(run_name, profile_index)

    assert app.exception == []
    metrics = {metric.proto.label: metric.proto.body for metric in app.get("metric")}
    assert metrics["Total Score"] == f"{total} of 12"
    assert metrics["Tier"] == tier


@pytest.mark.parametrize("profile_index", [0, 1])
def test_both_window_profiles_are_selectable_and_score_the_matching_snapshot(
    profile_index: int,
) -> None:
    app = _open_evaluation("run_gm040_ohtani", profile_index)
    text = _rendered_text(app)

    expected_profile = ("RECENT_7D", "LONG_TERM_2Y")[profile_index]
    assert expected_profile in text
    assert f"profile `{expected_profile.lower()}`" in text.lower()


# --------------------------------------------------------------------------
# The six outputs
# --------------------------------------------------------------------------


def test_every_category_and_component_appears_in_the_breakdown() -> None:
    app = _open_evaluation("run_gm040_ohtani", 1)
    text = _rendered_text(app)

    for category in (
        "power_profile",
        "pitcher_matchup",
        "form",
        "pull_power",
        "environment",
    ):
        assert category in text, category
    for component in (
        "exit_velocity",
        "barrel_pct",
        "hard_hit_pct",
        "pitch_mix_pressure",
        "put_away_pitch_exploitation",
        "sweet_spot_pct",
        "attack_angle_quality",
        "bat_speed",
        "pull_pct_air_balls",
        "park",
        "weather",
    ):
        assert component in text, component


def test_missing_components_render_their_recorded_reason() -> None:
    app = _open_evaluation("run_gm040_ohtani", 1)
    text = _rendered_text(app)

    assert "Components with no observed value" in text
    assert "SOURCE_UNAVAILABLE" in text
    assert "WEATHER_UNAVAILABLE" in text
    assert "Nothing is imputed." in text


def test_the_audit_trail_renders_every_entry_in_contiguous_order() -> None:
    app = _open_evaluation("run_gm040_ohtani", 1)
    text = _rendered_text(app)

    assert f"contiguous 1..{_AUDIT_ENTRIES}" in text
    assert f"Complete derivation ({_AUDIT_ENTRIES} entries)" in text
    for sequence in range(1, _AUDIT_ENTRIES + 1):
        assert f"**{sequence}. `" in text, sequence
    assert "NON-CONTIGUOUS" not in text


def test_the_audit_trail_shows_each_entrys_full_derivation() -> None:
    app = _open_evaluation("run_gm040_ohtani", 1)
    text = _rendered_text(app)

    for field in ("rule reference:", "input:", "output:", "why:"):
        assert field in text, field
    assert "bucket_resolution" in text
    assert "total_aggregation" in text
    assert "grade_assignment" in text


def test_warnings_render_as_advisory_only() -> None:
    app = _open_evaluation("run_gm040_ohtani", 0)
    text = _rendered_text(app)

    assert "5. Warnings" in text
    assert "never silently alters a score" in text


def test_fallback_provenance_renders_with_every_ineligible_method() -> None:
    app = _open_evaluation("run_gm040_ohtani", 1)
    text = _rendered_text(app)

    assert "6. Fallbacks" in text
    assert "attack_angle_quality` resolved through" in text
    assert "event_derived" in text
    for ineligible in ("direct_aggregate", "structured_extract", "rendered_scrape"):
        assert f"`{ineligible}` ineligible:" in text, ineligible


# --------------------------------------------------------------------------
# Synthetic-configuration disclosure
# --------------------------------------------------------------------------


def test_the_synthetic_warning_appears_at_the_top_and_beside_the_score() -> None:
    app = _open_evaluation("run_gm040_ohtani", 1)

    warnings = [str(element.value) for element in app.warning]
    assert any("SYNTHETIC / NON-PRODUCTION CONFIGURATION" in text for text in warnings)
    assert len(warnings) >= 2, "the qualification must repeat, not appear once at the top"

    captions = [str(element.value) for element in app.caption]
    assert any("synthetic demonstration" in text for text in captions)

    metrics = app.get("metric")
    assert all("synthetic demonstration" in metric.proto.help for metric in metrics)


def test_the_configuration_version_and_semantic_hash_are_shown() -> None:
    from greenmachine.config import load_versioned_config

    versioned = load_versioned_config(SYNTHETIC_CONFIG)
    app = _open_evaluation("run_gm040_ohtani", 1)
    text = _rendered_text(app)

    assert versioned.version_identifier in text
    assert versioned.config_hash.value in text
    assert versioned.source_digest is not None
    assert versioned.source_digest in text


def test_the_screen_states_the_scores_are_not_a_production_model_result() -> None:
    app = _open_evaluation("prospective_run", 0)
    text = _rendered_text(app)

    assert "Q11-Q16 remain open" in text
    assert "do **not** evaluate this hitter under an approved production model" in text
    assert "deliberately wrong for baseball" in text


# --------------------------------------------------------------------------
# Failure states
# --------------------------------------------------------------------------


def _app_with_config(
    tmp_path: Path, contents: str | None, monkeypatch: pytest.MonkeyPatch
) -> AppTest:
    """Point the app at a temporary configuration through the supported override.

    ``GREENMACHINE_SYNTHETIC_CONFIG`` mirrors the existing
    ``GREENMACHINE_EVIDENCE_ROOT`` deployment override, so nothing in the real
    repository is touched and no symlink is needed (Windows forbids them here).
    """
    target = tmp_path / "gm041_engine_synthetic.yaml"
    if contents is not None:
        target.write_text(contents, encoding="utf-8")
    monkeypatch.setenv("GREENMACHINE_SYNTHETIC_CONFIG", str(target))
    app = AppTest.from_file(str(APP_PATH), default_timeout=600)
    app.run()
    app.button(key="nav_evaluate").click().run()
    return app


@pytest.mark.parametrize(
    ("label", "contents"),
    [
        ("absent", None),
        ("malformed yaml", "allocations: { categories: ["),
        ("schema violation", "schema_version: 1\nmodel_configuration_version: 3\n"),
        ("semantic violation", "schema_version: 1\nfuzzy_scoring:\n  enabled: true\n"),
    ],
)
def test_an_unusable_configuration_renders_evaluation_unavailable(
    label: str, contents: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A configuration failure is never reported as a run-verification failure."""
    app = _app_with_config(tmp_path, contents, monkeypatch)

    errors = " ".join(str(element.value) for element in app.error)
    assert "Evaluation unavailable" in errors, label
    assert "Archived run could not be verified" not in errors, label
    assert "error category:" in errors, label

    text = _rendered_text(app)
    assert "Total Score" not in text, "no partial evaluation may render"
    assert str(REPO_ROOT) not in text, "no absolute local path may be exposed"


def test_an_unusable_configuration_leaves_every_other_screen_working(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app_with_config(tmp_path, None, monkeypatch)

    for screen in ("overview", "metrics", "matchup", "audit", "review"):
        app.button(key="return_hub").click().run()
        app.button(key=f"nav_{screen}").click().run()
        assert app.exception == [], screen
        errors = " ".join(str(element.value) for element in app.error)
        assert "Evaluation unavailable" not in errors, screen


# --------------------------------------------------------------------------
# Separation from manual review
# --------------------------------------------------------------------------


def test_the_evaluation_screen_writes_no_manual_review_state() -> None:
    """The automated evaluation never creates or touches a worksheet field.

    Asserted on a session that has never opened Manual Review, so any
    ``review::`` key appearing here could only have come from the evaluation
    itself. Changing the profile must not create one either.
    """
    app = _app()
    app.button(key="nav_evaluate").click().run()
    app.radio(key="evaluation_profile").set_value(
        app.radio(key="evaluation_profile").options[1]
    ).run()

    review_keys = [
        key for key in app.session_state.filtered_state if str(key).startswith("review::")
    ]
    assert review_keys == []
    assert "evaluation_profile" in app.session_state.filtered_state


def _review_state_after_visiting(screen: str) -> object:
    """Type into the worksheet, visit ``screen``, and report what survives."""
    key = "review::prospective_run::rationale_power_profile"
    app = _app()
    app.button(key="nav_review").click().run()
    app.session_state[key] = "user typed this"

    app.button(key="return_hub").click().run()
    app.button(key=f"nav_{screen}").click().run()
    app.button(key="return_hub").click().run()
    app.button(key="nav_review").click().run()

    return app.session_state.filtered_state.get(key, "<absent>")


def test_the_evaluation_screen_affects_manual_review_exactly_like_any_other_screen() -> None:
    """Parity, not persistence.

    Streamlit resets a widget whose element was not rendered on the current
    run, so a worksheet entry does not survive a round trip through **any**
    screen — Overview and Data Audit included. That behaviour predates
    GM-041.5. What this ticket must guarantee is that the evaluation screen is
    not *special*: it must leave the worksheet in exactly the state an existing
    screen would. Asserting persistence here would pin a guarantee the app has
    never made.
    """
    through_evaluation = _review_state_after_visiting("evaluate")

    assert through_evaluation == _review_state_after_visiting("overview")
    assert through_evaluation == _review_state_after_visiting("audit")


def test_the_evaluation_screen_offers_no_copy_to_worksheet_control() -> None:
    app = _open_evaluation("run_gm040_ohtani", 1)

    labels = " ".join(str(button.label).lower() for button in app.button)
    for banned in ("apply score", "copy to worksheet", "copy to review", "use this score"):
        assert banned not in labels, banned


# --------------------------------------------------------------------------
# Determinism and vocabulary
# --------------------------------------------------------------------------


def test_rerendering_produces_identical_evaluation_text() -> None:
    first = _rendered_text(_open_evaluation("run_gm040_ohtani", 1))
    second = _rendered_text(_open_evaluation("run_gm040_ohtani", 1))

    assert first == second


@pytest.mark.parametrize(
    ("precision", "rounding"),
    [
        (1, decimal.ROUND_DOWN),
        (2, decimal.ROUND_UP),
        (3, decimal.ROUND_FLOOR),
    ],
)
def test_a_hostile_global_decimal_context_changes_nothing_rendered(
    precision: int, rounding: str
) -> None:
    """The engine sums under the project context; the UI must inherit that."""
    baseline = _rendered_text(_open_evaluation("run_gm040_ohtani", 1))

    with decimal.localcontext() as hostile:
        hostile.prec = precision
        hostile.rounding = rounding
        rendered = _rendered_text(_open_evaluation("run_gm040_ohtani", 1))

    assert rendered == baseline


def test_the_evaluation_screen_uses_no_betting_or_recommendation_language() -> None:
    import re

    app = _open_evaluation("run_gm040_ohtani", 1)
    text = _rendered_text(app)

    for token in ("STRONG_BET", "STRONG BET"):
        assert token not in text, token
    # Word-boundary matching: "pass" appears legitimately in ordinary prose, and
    # "lean"/"avoid" could appear inside unrelated words.
    for word in (r"\bLEAN\b", r"\bAVOID\b", r"\bPASS\b", r"\bwager\b", r"\bstake\b"):
        assert re.search(word, text) is None, word
    for phrase in ("betting signal", "signal reason", "recommendation engine"):
        assert phrase.lower() not in text.lower(), phrase
    assert "produces no automated recommendation and no decision output" in text

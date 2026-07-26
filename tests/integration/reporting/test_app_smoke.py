"""Streamlit app smoke tests through the supported AppTest API.

The suite-wide network guard is active for every test here, so a successful
render is itself proof that the app performs no network request. AppTest
renders the element tree without applying CSS, so every assertion below also
proves the content screens remain usable without the landing styling.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_PATH = REPO_ROOT / "streamlit_app.py"
SHIPPED_RUN = REPO_ROOT / "evidence" / "gm020_vertical_slice" / "prospective_run"

# GM-041.5 added the sixth blade, Engine Evaluation, after Manual Review.
_DESTINATIONS = ("overview", "metrics", "matchup", "audit", "review", "evaluate")
_HUB_LABELS = (
    "OVERVIEW",
    "HITTER METRICS",
    "MATCHUP CONTEXT",
    "DATA AUDIT",
    "MANUAL REVIEW",
    "ENGINE EVALUATION",
)


def _fresh_app() -> AppTest:
    app = AppTest.from_file(str(APP_PATH), default_timeout=300)
    app.run()
    return app


def _open(app: AppTest, screen: str) -> AppTest:
    app.button(key=f"nav_{screen}").click().run()
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
    for frame in app.dataframe:
        pieces.append(str(frame.value))
    for button in app.button:
        pieces.append(str(button.label))
    for selectbox in app.selectbox:
        pieces.append(str(selectbox.label))
    for download in app.get("download_button"):
        pieces.append(str(download.proto.label))
    return " \n".join(pieces)


# --------------------------------------------------------------------------
# Landing hub and navigation
# --------------------------------------------------------------------------


def test_the_landing_hub_is_the_default_screen() -> None:
    app = _fresh_app()
    assert not list(app.exception)
    assert not list(app.error)
    keys = [button.key for button in app.button]
    assert keys == [f"nav_{screen}" for screen in _DESTINATIONS]  # six blades, no more
    assert not any(button.key == "return_hub" for button in app.button)
    text = _rendered_text(app)
    for label in _HUB_LABELS:
        assert label in text, label
    # Metric content stays off the landing page: no cards, no tables, no hashes.
    assert len(app.dataframe) == 0
    assert "RECENT_7D (last 7 days)" not in text


def test_the_landing_hub_names_the_console_not_one_of_its_screens() -> None:
    """GM-041.5-HF1: the subtitle described the whole app as manual-review-only.

    That stopped being true when the Engine Evaluation screen began running the
    deterministic grading engine, and the subtitle is the largest text on the
    landing page. Asserted together with the six destinations, because the
    wording is only correct while the console really does carry more than the
    worksheet -- the two claims have to stand or fall together.
    """
    app = _fresh_app()
    text = _rendered_text(app)

    assert "GREENMACHINE RESEARCH CONSOLE" in text
    assert "v0.2.0" in text
    assert "MANUAL REVIEW CONSOLE" not in text

    for label in _HUB_LABELS:
        assert label in text, label
    assert "ENGINE EVALUATION" in text
    assert [button.key for button in app.button] == [f"nav_{screen}" for screen in _DESTINATIONS]
    assert not list(app.exception)


def test_every_destination_opens_and_returns_home() -> None:
    app = _fresh_app()
    headings = {
        "overview": "Overview",
        "metrics": "Hitter Metrics",
        "matchup": "Matchup Context",
        "audit": "Data Quality & Audit",
        "review": "Manual Review",
        "evaluate": "Deterministic Engine Evaluation",
    }
    for screen in _DESTINATIONS:
        _open(app, screen)
        assert not list(app.exception), screen
        assert app.title[0].value == headings[screen]
        assert any(button.key == "return_hub" for button in app.button), screen
        app.button(key="return_hub").click().run()
        assert [button.key for button in app.button] == [
            f"nav_{destination}" for destination in _DESTINATIONS
        ], screen


def test_content_screens_render_the_shipped_evidence() -> None:
    app = _fresh_app()
    _open(app, "overview")
    overview_text = _rendered_text(app)
    for expected in (
        "Rafael Devers",
        "Grayson Rodriguez",
        "823196",
        "Oracle Park",
        "prospective live capture",
        "replay-verified",
        "schema-validated for display",
    ):
        assert expected in overview_text, expected

    app.button(key="return_hub").click().run()
    _open(app, "metrics")
    metrics_text = _rendered_text(app)
    for expected in ("RECENT_7D", "LONG_TERM_2Y", "Recent vs. Long-Term", "Pull Air%"):
        assert expected in metrics_text, expected


def test_the_persistent_legend_explains_data_status_colors() -> None:
    app = _fresh_app()
    text = _rendered_text(app)
    assert "data state only" in text
    assert "never automatic" in text.lower()


# --------------------------------------------------------------------------
# Frozen rulings on the rendered tree
# --------------------------------------------------------------------------


def test_no_whiff_text_anywhere_in_the_complete_rendered_tree() -> None:
    """Every screen, sidebar included: no case-insensitive 'whiff' substring."""
    app = _fresh_app()
    collected = _rendered_text(app)
    for screen in _DESTINATIONS:
        _open(app, screen)
        collected += _rendered_text(app)
        app.button(key="return_hub").click().run()
    assert "whiff" not in collected.lower()


def test_the_matchup_screen_shows_identity_only_no_pitcher_metrics() -> None:
    app = _fresh_app()
    _open(app, "matchup")
    assert len(app.dataframe) == 0  # no pitcher table of any kind
    text = _rendered_text(app)
    assert "Grayson Rodriguez" in text
    assert "680570" in text
    assert "expected starter" in text
    assert "deferred" in text
    for banned in (
        "Usage",
        "Two-strike",
        "Putaway",
        "Pitch type",
        "vulnerability",
        "ranking",
    ):
        assert banned not in text, banned


def test_no_recommendation_language_is_rendered() -> None:
    app = _fresh_app()
    collected = _rendered_text(app)
    for screen in _DESTINATIONS:
        _open(app, screen)
        collected += _rendered_text(app)
        app.button(key="return_hub").click().run()
    for banned in ("STRONG_BET", "AVOID"):
        assert banned not in collected


# --------------------------------------------------------------------------
# Manual review flow
# --------------------------------------------------------------------------


def test_manual_review_completes_and_tiers() -> None:
    app = _fresh_app()
    _open(app, "review")
    prefix = "review_widget::prospective_run::"
    for key, value in (
        (prefix + "score_power_profile", "3"),
        (prefix + "score_pitcher_matchup", "3"),
        (prefix + "score_form", "2"),
        (prefix + "score_pull_power", "1"),
        (prefix + "score_environment", "2"),
    ):
        app.selectbox(key=key).select(value)
    app.run()
    assert not list(app.exception)
    success_text = " ".join(str(element.value) for element in app.success)
    assert "11 / 12" in success_text
    assert "tier **S**" in success_text
    assert "manual, user-entered" in success_text


def test_an_incomplete_worksheet_shows_no_final_tier() -> None:
    app = _fresh_app()
    _open(app, "review")
    app.selectbox(key="review_widget::prospective_run::score_power_profile").select("2")
    app.run()
    info_text = " ".join(str(element.value) for element in app.info)
    assert "Worksheet incomplete" in info_text
    assert "partial total 2" in info_text
    assert not list(app.success)


def test_explicit_export_controls_exist() -> None:
    app = _fresh_app()
    _open(app, "review")
    labels = {str(button.proto.label) for button in app.get("download_button")}
    assert "Download review (JSON)" in labels
    assert "Download review (CSV)" in labels


# --------------------------------------------------------------------------
# Error experience
# --------------------------------------------------------------------------


def _corrupted_root(tmp_path: Path, mutate_relative: str, mutate_byte: bool) -> Path:
    corrupted_root = tmp_path / "evidence_root"
    corrupted_root.mkdir()
    corrupted = corrupted_root / "corrupted_run"
    shutil.copytree(SHIPPED_RUN, corrupted)
    target = corrupted / mutate_relative
    if mutate_byte:
        body = bytearray(target.read_bytes())
        body[5] ^= 0x01
        target.write_bytes(bytes(body))
    else:
        document = json.loads(target.read_text(encoding="utf-8"))
        document["overall_pull_report_only"]["value"] = "garbage"
        target.write_text(json.dumps(document), encoding="utf-8")
    return corrupted_root


def test_integrity_failure_renders_a_focused_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _corrupted_root(tmp_path, "raw/mlb_schedule.json", mutate_byte=True)
    monkeypatch.setenv("GREENMACHINE_EVIDENCE_ROOT", str(root))
    app = _fresh_app()
    _open(app, "overview")

    assert not list(app.exception)  # no raw traceback — a focused error instead
    error_text = " ".join(str(element.value) for element in app.error)
    assert "Archived run could not be verified" in error_text
    assert "corrupted_run" in error_text
    assert "error category" in error_text
    assert "Select another approved run" in error_text
    assert str(tmp_path).lower() not in error_text.lower()


def test_a_corrupt_audit_report_renders_a_focused_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stable category and the run name, never the failure's own message.

    Before GM-041.5 this asserted the report FILENAME appeared, because the
    renderer printed ``failure.message`` verbatim. It no longer does: an
    engineer-facing message can carry an absolute path, so the screen shows the
    closed-vocabulary category and one fixed sentence instead. The no-path
    assertion below is unchanged, and a stricter one is added.
    """
    root = _corrupted_root(tmp_path, "reports/pull_audit_recent_7d.json", mutate_byte=False)
    monkeypatch.setenv("GREENMACHINE_EVIDENCE_ROOT", str(root))
    app = _fresh_app()
    _open(app, "overview")

    assert not list(app.exception)
    error_text = " ".join(str(element.value) for element in app.error)
    assert "DashboardLoadError" in error_text
    assert "corrupted_run" in error_text
    assert "failed its integrity or loading checks" in error_text
    assert str(tmp_path).lower() not in error_text.lower()
    assert "pull_audit_recent_7d.json" not in error_text
    assert str(root) not in error_text


# --------------------------------------------------------------------------
# Read-only behavior and local-only assets
# --------------------------------------------------------------------------


def test_rendering_all_screens_writes_nothing_to_the_shipped_run() -> None:
    before = {
        path.relative_to(SHIPPED_RUN).as_posix(): path.read_bytes()
        for path in sorted(SHIPPED_RUN.rglob("*"))
        if path.is_file()
    }
    app = _fresh_app()
    for screen in _DESTINATIONS:
        _open(app, screen)
        app.button(key="return_hub").click().run()
    after = {
        path.relative_to(SHIPPED_RUN).as_posix(): path.read_bytes()
        for path in sorted(SHIPPED_RUN.rglob("*"))
        if path.is_file()
    }
    assert after == before


def test_the_hub_styling_uses_no_remote_asset() -> None:
    """The CSS/HTML payloads themselves: no request-capable construct at all."""
    import hub_theme

    for payload in (hub_theme.BASE_THEME_CSS, hub_theme.HUB_CSS, hub_theme.HUB_HEADER_HTML):
        lowered = payload.lower()
        for banned in ("http://", "https://", "url(", "@import", "<img", "base64", "<script"):
            assert banned not in lowered, banned


def test_no_xbox_asset_or_branding_is_rendered() -> None:
    """Original GreenMachine artwork only: the rendered tree and the styling
    payloads carry no Xbox name, logo reference, or copied asset."""
    import hub_theme

    app = _fresh_app()
    assert "xbox" not in _rendered_text(app).lower()
    for payload in (hub_theme.BASE_THEME_CSS, hub_theme.HUB_CSS, hub_theme.HUB_HEADER_HTML):
        assert "xbox" not in payload.lower()

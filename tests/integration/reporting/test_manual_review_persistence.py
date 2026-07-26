"""GM-041.5: a Manual Review worksheet survives navigation, intact and per-run.

Streamlit discards a widget-owned ``session_state`` key when its widget is not
rendered on the current run. The worksheet originally used widget keys as its
only storage, so opening any other screen destroyed the reviewer's work. The fix
is a durable ``review_state::`` namespace that no widget owns, hydrated into
transient ``review_widget::`` keys on render and written back by ``on_change``.

Every test below drives **real widget interactions** — ``select``,
``set_value`` on the actual elements — rather than assigning session state
directly, because the defect lived in exactly the gap between what a widget
holds and what survives it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from greenmachine.reporting import (
    CATEGORIES,
    DashboardData,
    ManualReview,
    ReviewContext,
    RunHandle,
    export_review_csv,
    export_review_json,
    load_dashboard,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_PATH = REPO_ROOT / "streamlit_app.py"
EVIDENCE_ROOT = REPO_ROOT / "evidence" / "gm020_vertical_slice"


def _dashboard(run: str) -> DashboardData:
    return load_dashboard(RunHandle(name=run, directory=EVIDENCE_ROOT / run))


RUN_A = "prospective_run"
RUN_B = "run_gm040_ohtani"

# (category key, chosen score, rationale text)
_ENTRIES: tuple[tuple[str, str, str], ...] = (
    ("power_profile", "3", "hard contact over the window"),
    ("pitcher_matchup", "2", "reviewer judgement, no automated input"),
    ("form", "2", "recent form entered by hand"),
    ("pull_power", "1", "pull tendency noted manually"),
    ("environment", "0", "no park or weather source approved"),
)
_NOTES = "Reviewer notes typed by hand. Nothing automated wrote this."
_TIMESTAMP = "2026-07-25T18:00 typed by the reviewer"


def _widget(run: str, field: str) -> str:
    return f"review_widget::{run}::{field}"


def _state(run: str, field: str) -> str:
    return f"review_state::{run}::{field}"


def _app() -> AppTest:
    app = AppTest.from_file(str(APP_PATH), default_timeout=600)
    app.run()
    return app


def _open(app: AppTest, screen: str) -> AppTest:
    app.button(key=f"nav_{screen}").click().run()
    return app


def _to_hub(app: AppTest) -> AppTest:
    app.button(key="return_hub").click().run()
    return app


def _select_run(app: AppTest, run: str) -> AppTest:
    app.selectbox(key="run_select").select(run).run()
    return app


def _fill_worksheet(app: AppTest, run: str, suffix: str = "") -> None:
    """Complete the worksheet through real widget interactions only."""
    for key, score, rationale in _ENTRIES:
        app.selectbox(key=_widget(run, f"score_{key}")).select(score).run()
        app.text_input(key=_widget(run, f"rationale_{key}")).set_value(rationale + suffix).run()
    app.text_area(key=_widget(run, "notes")).set_value(_NOTES + suffix).run()
    app.text_input(key=_widget(run, "timestamp")).set_value(_TIMESTAMP + suffix).run()


def _visible_values(app: AppTest, run: str) -> dict[str, str]:
    """What the reviewer can actually see in the rendered widgets."""
    visible = {}
    for key, _score, _rationale in _ENTRIES:
        visible[f"score_{key}"] = str(app.selectbox(key=_widget(run, f"score_{key}")).value)
        visible[f"rationale_{key}"] = str(
            app.text_input(key=_widget(run, f"rationale_{key}")).value
        )
    visible["notes"] = str(app.text_area(key=_widget(run, "notes")).value)
    visible["timestamp"] = str(app.text_input(key=_widget(run, "timestamp")).value)
    return visible


def _export_bytes(app: AppTest, run: str) -> tuple[bytes, bytes]:
    """The exact JSON and CSV export payloads for the current worksheet.

    AppTest's download-button proto carries a deferred file id rather than the
    payload, so the bytes are reproduced the way the app produces them: the
    ``ManualReview`` is rebuilt from the **durable** session-state record and
    passed through the same public export functions. If navigation had disturbed
    that record, these bytes would move — which is exactly what is under test.
    """
    assert len(app.get("download_button")) == 2, "a JSON and a CSV export are offered"

    durable = app.session_state.filtered_state

    def value(field: str, default: str = "") -> str:
        return str(durable.get(_state(run, field), default))

    review = ManualReview(
        scores=tuple(
            (
                spec.key,
                None
                if value(f"score_{spec.key}", "Not scored") == "Not scored"
                else int(value(f"score_{spec.key}", "Not scored")),
            )
            for spec in CATEGORIES
        ),
        notes=value("notes"),
        rationales=tuple((spec.key, value(f"rationale_{spec.key}")) for spec in CATEGORIES),
        user_entered_timestamp=value("timestamp") or None,
    )
    data = _dashboard(run)
    context = ReviewContext(
        game_id=data.header.game_id,
        batter_id=data.header.batter_id,
        pitcher_id=data.header.pitcher_id,
        source_capture_id=data.header.source_capture_id,
        recent_snapshot_id=data.recent.snapshot_id,
        long_term_snapshot_id=data.long_term.snapshot_id,
        run_name=data.run_name,
    )
    return export_review_json(review, context), export_review_csv(review, context)


# --------------------------------------------------------------------------
# The core guarantee
# --------------------------------------------------------------------------


def test_a_completed_worksheet_survives_navigating_the_whole_console() -> None:
    """The requirement the parity test previously documented away.

    A reviewer fills the worksheet, walks every other screen including both
    evaluation profiles, and comes back. Nothing they typed may have moved.
    """
    app = _app()
    _open(app, "review")
    _fill_worksheet(app, RUN_A)

    before_visible = _visible_values(app, RUN_A)
    before_json, before_csv = _export_bytes(app, RUN_A)
    assert before_visible["score_power_profile"] == "3"
    assert before_visible["notes"] == _NOTES

    # The hub, two unrelated screens, and both evaluation profiles.
    _to_hub(app)
    _open(app, "overview")
    _to_hub(app)
    _open(app, "audit")
    _to_hub(app)
    _open(app, "evaluate")
    for index in (0, 1):
        app.radio(key="evaluation_profile").set_value(
            app.radio(key="evaluation_profile").options[index]
        ).run()
    _to_hub(app)
    _open(app, "review")

    assert _visible_values(app, RUN_A) == before_visible
    after_json, after_csv = _export_bytes(app, RUN_A)
    assert after_json == before_json
    assert after_csv == before_csv


def test_every_individual_field_is_restored_exactly() -> None:
    """Field-by-field, so a failure names the field that was lost."""
    app = _app()
    _open(app, "review")
    _fill_worksheet(app, RUN_A)

    _to_hub(app)
    _open(app, "evaluate")
    _to_hub(app)
    _open(app, "review")

    visible = _visible_values(app, RUN_A)
    for key, score, rationale in _ENTRIES:
        assert visible[f"score_{key}"] == score, key
        assert visible[f"rationale_{key}"] == rationale, key
    assert visible["notes"] == _NOTES
    assert visible["timestamp"] == _TIMESTAMP


def test_the_worksheet_total_and_tier_survive_navigation() -> None:
    """The derived summary is rebuilt from durable state, not from widgets."""
    app = _app()
    _open(app, "review")
    _fill_worksheet(app, RUN_A)

    def summary(current: AppTest) -> str:
        return " ".join(str(element.value) for element in current.success)

    before = summary(app)
    assert "8 / 12" in before  # 3 + 2 + 2 + 1 + 0
    assert "Worksheet complete" in before

    _to_hub(app)
    _open(app, "evaluate")
    _to_hub(app)
    _open(app, "review")

    assert summary(app) == before


def test_changing_the_evaluation_profile_alone_changes_nothing_in_the_worksheet() -> None:
    app = _app()
    _open(app, "review")
    _fill_worksheet(app, RUN_A)
    before_visible = _visible_values(app, RUN_A)
    before_json, before_csv = _export_bytes(app, RUN_A)

    _to_hub(app)
    _open(app, "evaluate")
    for _ in range(3):  # toggle repeatedly
        for index in (1, 0):
            app.radio(key="evaluation_profile").set_value(
                app.radio(key="evaluation_profile").options[index]
            ).run()
    _to_hub(app)
    _open(app, "review")

    assert _visible_values(app, RUN_A) == before_visible
    assert _export_bytes(app, RUN_A) == (before_json, before_csv)


# --------------------------------------------------------------------------
# Per-run isolation
# --------------------------------------------------------------------------


def test_each_archived_run_keeps_its_own_worksheet() -> None:
    """Two runs, two worksheets; switching away and back restores each."""
    app = _app()
    _open(app, "review")
    _fill_worksheet(app, RUN_A, suffix=" [A]")
    run_a_visible = _visible_values(app, RUN_A)
    run_a_json, run_a_csv = _export_bytes(app, RUN_A)

    # Switch to the other run: its worksheet must start empty, not inherit A's.
    _select_run(app, RUN_B)
    fresh = _visible_values(app, RUN_B)
    assert fresh["notes"] == ""
    assert fresh["timestamp"] == ""
    assert all(fresh[f"score_{key}"] == "Not scored" for key, _s, _r in _ENTRIES)

    _fill_worksheet(app, RUN_B, suffix=" [B]")
    run_b_visible = _visible_values(app, RUN_B)
    run_b_json, run_b_csv = _export_bytes(app, RUN_B)
    assert run_b_visible != run_a_visible
    assert run_b_json != run_a_json

    # Back to the first run: exactly what was left there.
    _select_run(app, RUN_A)
    assert _visible_values(app, RUN_A) == run_a_visible
    assert _export_bytes(app, RUN_A) == (run_a_json, run_a_csv)

    # And forward again to the second.
    _select_run(app, RUN_B)
    assert _visible_values(app, RUN_B) == run_b_visible
    assert _export_bytes(app, RUN_B) == (run_b_json, run_b_csv)


def test_one_runs_worksheet_never_leaks_into_another_runs_state() -> None:
    app = _app()
    _open(app, "review")
    _fill_worksheet(app, RUN_A, suffix=" [A]")
    _select_run(app, RUN_B)

    durable = app.session_state.filtered_state
    run_a_keys = [key for key in durable if str(key).startswith(f"review_state::{RUN_A}::")]
    run_b_keys = [key for key in durable if str(key).startswith(f"review_state::{RUN_B}::")]

    assert run_a_keys, "the first run's durable record is retained"
    assert all("[A]" not in str(durable[key]) for key in run_b_keys)


# --------------------------------------------------------------------------
# The state design itself
# --------------------------------------------------------------------------


def test_durable_state_is_held_outside_any_widget_key() -> None:
    """The separation that makes survival possible.

    A ``review_state::`` key must exist and must never be a widget key, so
    Streamlit has no reason to discard it.
    """
    app = _app()
    _open(app, "review")
    _fill_worksheet(app, RUN_A)

    state_keys = {
        key for key in app.session_state.filtered_state if str(key).startswith("review_state::")
    }
    widget_keys = {
        key for key in app.session_state.filtered_state if str(key).startswith("review_widget::")
    }
    assert state_keys
    assert widget_keys
    assert state_keys.isdisjoint(widget_keys)

    # Leaving the screen may drop the widget keys; it must not drop the record.
    _to_hub(app)
    _open(app, "overview")
    surviving = {
        key for key in app.session_state.filtered_state if str(key).startswith("review_state::")
    }
    assert state_keys <= surviving


def test_the_durable_record_holds_every_worksheet_field() -> None:
    app = _app()
    _open(app, "review")
    _fill_worksheet(app, RUN_A)

    durable = app.session_state.filtered_state
    for key, score, rationale in _ENTRIES:
        assert durable[_state(RUN_A, f"score_{key}")] == score
        assert durable[_state(RUN_A, f"rationale_{key}")] == rationale
    assert durable[_state(RUN_A, "notes")] == _NOTES
    assert durable[_state(RUN_A, "timestamp")] == _TIMESTAMP


def test_an_untouched_worksheet_exports_without_error() -> None:
    """The empty case still builds a record and both exports."""
    app = _app()
    _open(app, "review")

    assert app.exception == []
    json_bytes, csv_bytes = _export_bytes(app, RUN_A)
    assert json_bytes
    assert csv_bytes
    assert "Worksheet incomplete" in " ".join(str(e.value) for e in app.info)


@pytest.mark.parametrize("screen", ["overview", "metrics", "matchup", "audit", "evaluate"])
def test_no_other_screen_writes_into_the_durable_worksheet(screen: str) -> None:
    """Only the worksheet writes worksheet state — the evaluation never does."""
    app = _app()
    _open(app, screen)

    assert [
        key for key in app.session_state.filtered_state if str(key).startswith("review_state::")
    ] == []

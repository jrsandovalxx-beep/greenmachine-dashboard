"""GM-030 Streamlit manual-review prototype — the presentation composition root.

The ONLY module that imports Streamlit. Everything rendered comes from the
provider-neutral view models in ``greenmachine.reporting``, built over
approved archived GM-020 runs through the read-only replay/integrity path.
No provider network request, no write to any archived run, no automated
scoring, no recommendation.

Navigation is shallow: an original GreenMachine console-style **landing hub**
(the default screen) opens one of five content screens, each with a
return-to-hub control. The stylized hub carries the console aesthetic;
content screens keep the dark-green identity with a calmer layout. All
styling is local generated CSS (see ``hub_theme.py``) — no remote font,
image, stylesheet, script, or CDN request exists anywhere.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

_REPO_ROOT = Path(__file__).resolve().parent
_SRC_ROOT = _REPO_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:  # Community Cloud runs without installation
    sys.path.insert(0, str(_SRC_ROOT))

from hub_theme import BASE_THEME_CSS, HUB_CSS, HUB_HEADER_HTML  # noqa: E402

from greenmachine.common.errors import GreenMachineError  # noqa: E402
from greenmachine.reporting import (  # noqa: E402
    CATEGORIES,
    COLOR_LEGEND,
    ERROR_COLOR,
    MANUAL_REVIEW_DISCLAIMER,
    DashboardData,
    ManualReview,
    MetricCard,
    ReviewContext,
    RunHandle,
    discover_runs,
    export_review_csv,
    export_review_json,
    load_dashboard,
    status_badge,
)

# The configured evidence root: repository-relative by default, overridable
# only through deployment configuration (an environment variable set by the
# operator or the test harness) — never through a UI control. Adding another
# approved archived run beneath it requires no dashboard-code change.
_EVIDENCE_OVERRIDE = os.environ.get("GREENMACHINE_EVIDENCE_ROOT", "")
EVIDENCE_ROOT = (
    Path(_EVIDENCE_OVERRIDE).resolve()
    if _EVIDENCE_OVERRIDE
    else _REPO_ROOT / "evidence" / "gm020_vertical_slice"
)

# The five hub destinations: (state key, hub label, screen heading).
DESTINATIONS: tuple[tuple[str, str, str], ...] = (
    ("overview", "OVERVIEW", "Overview"),
    ("metrics", "HITTER METRICS", "Hitter Metrics"),
    ("matchup", "MATCHUP CONTEXT", "Matchup Context"),
    ("audit", "DATA AUDIT", "Data Quality & Audit"),
    ("review", "MANUAL REVIEW", "Manual Review"),
)

st.set_page_config(page_title="GreenMachine manual review (prototype)", layout="wide")
st.markdown(BASE_THEME_CSS, unsafe_allow_html=True)


@st.cache_resource(show_spinner="Verifying the archived run (read-only replay)...")
def _load_verified(run_name: str, run_directory: str) -> DashboardData:
    return load_dashboard(RunHandle(name=run_name, directory=Path(run_directory)))


def _go(screen: str) -> None:
    st.session_state["screen"] = screen


def _sidebar(run_names: list[str]) -> str:
    with st.sidebar:
        st.title("GreenMachine")
        st.caption("Manual-review prototype | archived runs only | version 0.2.0")
        selected = st.selectbox("Approved archived run", run_names, key="run_select")
        st.divider()
        st.subheader("Color legend - data status")
        st.caption(
            "Colors describe **data state only**. They are never automatic "
            "favorable/unfavorable grades: production thresholds are unresolved."
        )
        for color, meaning in COLOR_LEGEND:
            st.markdown(f"- `{color}` : {meaning}")
        st.divider()
        st.caption(
            "Manual scoring on the Manual Review screen is user-entered only: "
            "not the GreenMachine scoring engine, not a recommendation, not a "
            "betting signal."
        )
    return str(selected)


def _render_focused_error(run_name: str, failure: GreenMachineError) -> None:
    badge = ERROR_COLOR
    st.error(
        f"{badge.icon} **Archived run could not be verified** ({badge.label})\n\n"
        f"- run: `{run_name}`\n"
        f"- error category: `{failure.error_type}`\n"
        f"- {failure.message}\n\n"
        f"Select another approved run from the sidebar."
    )


def _render_hub() -> None:
    st.markdown(HUB_CSS, unsafe_allow_html=True)
    st.markdown(HUB_HEADER_HTML, unsafe_allow_html=True)
    _left, middle, _right = st.columns([1, 2, 1])
    with middle:
        st.markdown('<div class="gm-hub-menu">', unsafe_allow_html=True)
        for screen_key, hub_label, _heading in DESTINATIONS:
            st.button(
                f"◉  {hub_label}",
                key=f"nav_{screen_key}",
                on_click=_go,
                args=(screen_key,),
                width="stretch",
            )
        st.markdown("</div>", unsafe_allow_html=True)
    st.caption(
        "Read-only research console over approved archived GM-020 snapshots. "
        "No live capture. No automated scoring."
    )


def _render_return_control(heading: str) -> None:
    st.button("<< GREENMACHINE HUB", key="return_hub", on_click=_go, args=("hub",))
    st.title(heading)


def _render_card(card: MetricCard) -> None:
    badge = status_badge(card.status)
    with st.container(border=True):
        st.markdown(f"**{card.label}**")
        st.markdown(f"### {card.value_display if card.value_display is not None else '(missing)'}")
        st.caption(
            f"{badge.icon} {badge.label} | `{badge.color}` | "
            f"n = {card.sample_count} {card.sample_unit} | {card.profile.value}"
        )
        st.caption(card.provenance.acquisition_label)
        if card.explanation:
            st.caption(card.explanation)
        with st.expander("Provenance"):
            provenance = card.provenance
            source_as_of = provenance.source_as_of.isoformat() if provenance.source_as_of else "n/a"
            retrieved_at = provenance.retrieved_at.isoformat() if provenance.retrieved_at else "n/a"
            exact = card.value_exact if card.value_exact is not None else "n/a"
            note_line = (
                f"- note: {provenance.derivation_note}\n" if provenance.derivation_note else ""
            )
            st.markdown(
                f"- measurement: `{provenance.measurement_label}`\n"
                f"- exact value: `{exact}`\n"
                f"- provider: {provenance.provider_label}\n"
                f"- source_as_of: {source_as_of}\n"
                f"- retrieved_at: {retrieved_at}\n" + note_line
            )
            if provenance.fallback_summary:
                st.markdown("**Why higher-priority methods were ineligible:**")
                for line in provenance.fallback_summary:
                    st.markdown(f"- {line}")


def _render_profile_column(
    title: str, cards_by_group: list[tuple[str, tuple[MetricCard, ...]]]
) -> None:
    st.subheader(title)
    for group_title, cards in cards_by_group:
        st.markdown(f"**{group_title}**")
        for card in cards:
            _render_card(card)


def _render_overview(data: DashboardData) -> None:
    header = data.header
    integrity = data.integrity
    replay_mark = "verified" if integrity.replay_byte_identical else "FAILED"
    prospective_mark = (
        "prospective capture verified"
        if integrity.prospective_verified
        else "retrospective reconstruction"
    )
    st.markdown(
        f"**Integrity:** archived run verified | replay byte-identical: {replay_mark} | "
        f"{prospective_mark}"
    )
    st.caption(integrity.prospective_note)
    st.caption(integrity.verification_scope_note)

    left, right = st.columns(2)
    with left:
        st.markdown(
            f"**Hitter:** {header.batter_name} (MLBAM `{header.batter_id}`)\n\n"
            f"**Team:** {header.team_note}\n\n"
            f"**Opponent:** {header.opponent_note}\n\n"
            f"**Expected pitcher:** {header.pitcher_name} (MLBAM `{header.pitcher_id}`), "
            f"{header.pitcher_role_label}"
        )
    with right:
        st.markdown(
            f"**Game:** official ID `{header.game_id}` | slate {header.slate_date.isoformat()}\n\n"
            f"**Venue:** {header.venue_name} ({header.venue_timezone})\n\n"
            f"**Scheduled first pitch:** {header.scheduled_start_utc.isoformat()} UTC "
            f"({header.venue_local_start.isoformat()} local)\n\n"
            f"**Capture:** {header.capture_mode_label} | completed "
            f"{header.capture_completed_at.isoformat()}\n\n"
            f"**Snapshot as_of:** {header.as_of.isoformat()}"
        )
    abbreviated = header.source_capture_id[:24] + "..."
    st.caption(f"SourceCaptureId: `{abbreviated}`")
    with st.expander("View full SourceCaptureId (copyable)"):
        st.code(header.source_capture_id, language=None)


def _render_metrics(data: DashboardData) -> None:
    recent_column, long_column = st.columns(2)
    with recent_column:
        _render_profile_column(
            "RECENT_7D (last 7 days)",
            [
                ("Power Profile", data.recent.power_profile),
                ("Form", data.recent.form),
                ("Pull Power", data.recent.pull_power),
            ],
        )
    with long_column:
        _render_profile_column(
            "LONG_TERM_2Y (rolling 2 years)",
            [
                ("Power Profile", data.long_term.power_profile),
                ("Form", data.long_term.form),
                ("Pull Power", data.long_term.pull_power),
            ],
        )
    st.divider()
    st.subheader("Recent vs. Long-Term")
    st.caption(
        "Differences are arithmetic only (recent minus long-term). No value here "
        "is labeled good or bad, ranked, or colored by performance."
    )
    rows = [
        {
            "Metric": row.label + (" (audit-only)" if row.audit_only else ""),
            "RECENT_7D": row.recent_display if row.recent_display is not None else "missing",
            "recent n": row.recent_sample,
            "LONG_TERM_2Y": (
                row.long_term_display if row.long_term_display is not None else "missing"
            ),
            "long-term n": row.long_term_sample,
            "Difference": (row.difference_display if row.difference_display is not None else "n/a"),
            "Status notes": row.status_note,
        }
        for row in data.comparison
    ]
    st.dataframe(rows, width="stretch", hide_index=True)


def _render_matchup(data: DashboardData) -> None:
    context = data.pitcher_context
    st.subheader(f"{context.pitcher_name} (MLBAM `{context.pitcher_id}`)")
    st.markdown(f"**Role:** {context.role_label}")
    st.markdown(f"**Handedness:** {context.handedness_note}")
    st.info(context.deferred_note)


def _render_audit(data: DashboardData) -> None:
    audit = data.audit
    with st.expander("Missing observations", expanded=False):
        for note in audit.missing_components:
            st.markdown(
                f"- **{note.component_label}** ({note.profile.value}): "
                f"{note.reason_label} - {note.explanation}"
            )
    with st.expander("Insufficient samples"):
        if audit.insufficient_cards:
            for line in audit.insufficient_cards:
                st.markdown(f"- {line}")
        else:
            st.caption("No present metric is below the archived validation-only minimum.")
    with st.expander("Fallback records (method eligibility)"):
        if audit.fallback_notes:
            for line in audit.fallback_notes:
                st.markdown(f"- {line}")
            st.caption(
                "A fallback record means event derivation was genuinely selected over a "
                "higher-priority acquisition route. Method ineligibility is why each "
                "higher route could not be used; it is not a data error."
            )
        else:
            st.caption("No fallback was used.")
    with st.expander("Normalization audit (exclusions and duplicates)"):
        for line in audit.normalization_lines:
            st.markdown(f"- {line}")
    with st.expander("Manifest identity and raw captures"):
        st.markdown(f"manifest_id: `{audit.manifest_id}`")
        st.dataframe(
            [
                {
                    "Capture": entry.label,
                    "Participates in snapshots": entry.participates_in_snapshot,
                    "Completed (UTC)": entry.retrieval_completed_at.isoformat(),
                    "SHA-256": entry.sha256,
                }
                for entry in audit.capture_entries
            ],
            width="stretch",
            hide_index=True,
        )
    with st.expander("Prospective timing evidence"):
        for line in audit.prospective_evidence_lines:
            st.markdown(f"- {line}")
    with st.expander("Replay verification"):
        for line in audit.replay_lines:
            st.markdown(f"- `{line}`")
    with st.expander("Sample-minimum policy (validation-only)", expanded=False):
        st.warning(audit.sample_policy_disclaimer)


def _score_from_widget(raw: str) -> int | None:
    return None if raw == "Not scored" else int(raw)


def _render_manual_review(data: DashboardData) -> None:
    st.warning(
        f"**{MANUAL_REVIEW_DISCLAIMER}.** You assign every category yourself; the "
        f"app only adds the arithmetic and derives the frozen tier "
        f"(S 10-12, A 8-9, B 6-7, C 4-5, D 0-3). No recommendation or betting "
        f"signal is produced."
    )
    key_prefix = f"review::{data.run_name}::"
    score_columns = st.columns(len(CATEGORIES))
    for column, spec in zip(score_columns, CATEGORIES, strict=True):
        with column:
            st.selectbox(
                f"{spec.label} (0-{spec.maximum})",
                ["Not scored", *[str(value) for value in range(spec.maximum + 1)]],
                key=key_prefix + "score_" + spec.key,
            )
            st.text_input(
                "Rationale (optional)",
                key=key_prefix + "rationale_" + spec.key,
            )
    notes = st.text_area("Notes", key=key_prefix + "notes")
    user_timestamp = st.text_input(
        "Optional timestamp: typed by you; the app never reads the clock",
        key=key_prefix + "timestamp",
    )

    review = ManualReview(
        scores=tuple(
            (
                spec.key,
                _score_from_widget(
                    str(st.session_state.get(key_prefix + "score_" + spec.key, "Not scored"))
                ),
            )
            for spec in CATEGORIES
        ),
        notes=str(notes or ""),
        rationales=tuple(
            (spec.key, str(st.session_state.get(key_prefix + "rationale_" + spec.key, "") or ""))
            for spec in CATEGORIES
        ),
        user_entered_timestamp=(user_timestamp or None),
    )

    if review.is_complete:
        st.success(
            f"Worksheet complete: total **{review.total} / 12**, tier **{review.tier}** "
            f"(manual, user-entered)"
        )
    else:
        unscored = [spec.label for spec in CATEGORIES if dict(review.scores)[spec.key] is None]
        st.info(
            f"Worksheet incomplete: partial total {review.partial_total} so far; "
            f"still unscored: {', '.join(unscored)}. The final total and tier appear "
            f"only when every category is assigned."
        )

    context = ReviewContext(
        game_id=data.header.game_id,
        batter_id=data.header.batter_id,
        pitcher_id=data.header.pitcher_id,
        source_capture_id=data.header.source_capture_id,
        recent_snapshot_id=data.recent.snapshot_id,
        long_term_snapshot_id=data.long_term.snapshot_id,
        run_name=data.run_name,
    )
    json_column, csv_column = st.columns(2)
    with json_column:
        st.download_button(
            "Download review (JSON)",
            data=export_review_json(review, context),
            file_name=f"manual_review_{data.header.game_id}_{data.header.batter_id}.json",
            mime="application/json",
        )
    with csv_column:
        st.download_button(
            "Download review (CSV)",
            data=export_review_csv(review, context),
            file_name=f"manual_review_{data.header.game_id}_{data.header.batter_id}.csv",
            mime="text/csv",
        )
    st.caption(
        "Exports download to your machine only. Nothing is written to the archived "
        "run, the evidence bundle, or any database."
    )


def main() -> None:
    handles = discover_runs(EVIDENCE_ROOT)
    if not handles:
        st.error(
            f"{ERROR_COLOR.icon} No approved archived run was found beneath the "
            f"configured evidence root. Add an approved GM-020 run bundle under "
            f"`evidence/gm020_vertical_slice/`."
        )
        st.stop()

    by_name = {handle.name: handle for handle in handles}
    selected_name = _sidebar(sorted(by_name))
    handle = by_name[selected_name]

    screen = str(st.session_state.get("screen", "hub"))

    if screen == "hub":
        _render_hub()
        return

    headings = {screen_key: heading for screen_key, _label, heading in DESTINATIONS}
    _render_return_control(headings.get(screen, "Overview"))

    try:
        data = _load_verified(handle.name, str(handle.directory))
    except GreenMachineError as failure:
        _render_focused_error(handle.name, failure)
        st.stop()
        return

    if screen == "overview":
        _render_overview(data)
    elif screen == "metrics":
        _render_metrics(data)
    elif screen == "matchup":
        _render_matchup(data)
    elif screen == "audit":
        _render_audit(data)
    elif screen == "review":
        _render_manual_review(data)
    else:  # an unknown state falls back to the hub rather than a blank page
        _go("hub")
        _render_hub()


main()

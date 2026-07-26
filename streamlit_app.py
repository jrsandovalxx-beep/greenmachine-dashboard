"""GM-030 Streamlit manual-review prototype — the presentation composition root.

The ONLY module that imports Streamlit. Everything rendered comes from the
provider-neutral view models in ``greenmachine.reporting``, built over
approved archived GM-020 runs through the read-only replay/integrity path.
No provider network request, no write to any archived run, and no automated
recommendation or decision output of any kind.

GM-041.5 adds the **Engine Evaluation** screen. This composition root is the
only place permitted to combine the three pieces: ``reporting`` hands back a
replay-verified run (view models **plus** both frozen snapshots), ``config``
loads the disclaimed non-production configuration, and the pure
``scoring.score_snapshot`` turns those two immutable values into a
``GradeResult``. ``reporting`` itself never imports ``scoring`` or ``config``,
so the layering rule survives.

Navigation is shallow: an original GreenMachine console-style **landing hub**
(the default screen) opens one of six content screens, each with a
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

from greenmachine.common.errors import (  # noqa: E402
    ConfigurationError,
    ErrorContext,
    GreenMachineError,
)
from greenmachine.config import (  # noqa: E402
    ConfigParseError,
    VersionedConfiguration,
    load_versioned_config,
)
from greenmachine.domain import (  # noqa: E402
    EvaluatedGradeResult,
    GradeResult,
    InputSnapshot,
    WindowProfile,
)
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
    VerifiedRun,
    discover_runs,
    export_review_csv,
    export_review_json,
    load_verified_run,
    status_badge,
)
from greenmachine.scoring import ScoringError, score_snapshot  # noqa: E402

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

# The canonical NON-PRODUCTION configuration. No approved production model
# configuration exists (Q11-Q16 open), so this is the only executable one, and
# every surface that displays its numbers says so. It lives outside tests/ so
# the deployed app never reads from the test tree.
_CONFIG_OVERRIDE = os.environ.get("GREENMACHINE_SYNTHETIC_CONFIG", "")
SYNTHETIC_CONFIG_PATH = (
    Path(_CONFIG_OVERRIDE).resolve()
    if _CONFIG_OVERRIDE
    else _REPO_ROOT / "config" / "nonproduction" / "gm041_engine_synthetic.yaml"
)

SYNTHETIC_CONFIG_BANNER = (
    "SYNTHETIC / NON-PRODUCTION CONFIGURATION. No approved production model "
    "configuration exists - Q11-Q16 remain open Product Owner decisions. The "
    "scores below demonstrate **engine behaviour** only. They do **not** "
    "evaluate this hitter under an approved production model, and its category "
    "maxima, buckets, and cutoffs are deliberately wrong for baseball."
)

SCORE_QUALIFIER = "synthetic demonstration - not a production model result"

# The six hub destinations: (state key, hub label, screen heading).
DESTINATIONS: tuple[tuple[str, str, str], ...] = (
    ("overview", "OVERVIEW", "Overview"),
    ("metrics", "HITTER METRICS", "Hitter Metrics"),
    ("matchup", "MATCHUP CONTEXT", "Matchup Context"),
    ("audit", "DATA AUDIT", "Data Quality & Audit"),
    ("review", "MANUAL REVIEW", "Manual Review"),
    ("evaluate", "ENGINE EVALUATION", "Deterministic Engine Evaluation"),
)

st.set_page_config(page_title="GreenMachine research console", layout="wide")
st.markdown(BASE_THEME_CSS, unsafe_allow_html=True)


@st.cache_resource(show_spinner="Verifying the archived run (read-only replay)...")
def _load_verified(run_name: str, run_directory: str) -> VerifiedRun:
    """The one replay-verification boundary: one replay per run per session.

    Returns the view models **and** both frozen snapshots, so the Engine
    Evaluation screen can score without a second verification pass that could
    drift from this one.
    """
    return load_verified_run(RunHandle(name=run_name, directory=Path(run_directory)))


def _go(screen: str) -> None:
    st.session_state["screen"] = screen


def _sidebar(run_names: list[str]) -> str:
    with st.sidebar:
        st.title("GreenMachine")
        st.caption("Research console | archived evidence and evaluation prototype | version 0.2.0")
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
            "not the GreenMachine scoring engine, and not a recommendation of any "
            "kind. Evaluation only — every decision is yours."
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


# --------------------------------------------------------------------------
# GM-041.5: durable manual-review state
# --------------------------------------------------------------------------
#
# Streamlit discards a widget-owned session_state key when that widget is not
# rendered on the current run. The worksheet previously used widget keys as its
# ONLY storage, so navigating to any other screen destroyed the reviewer's work.
#
# The fix is two namespaces with one direction of flow:
#
#   review_state::<run>::<field>   durable, never bound to a widget
#   review_widget::<run>::<field>  transient, owned by Streamlit
#
# Widgets hydrate FROM the durable record when the screen renders, and an
# on_change callback copies the widget value back INTO it. Every read that
# matters -- the ManualReview record and both exports -- comes from the durable
# record, never from a widget key. Keys are namespaced per run, so each archived
# run keeps its own worksheet and gets it back on return.

_STATE_PREFIX = "review_state::"
_WIDGET_PREFIX = "review_widget::"

_TIMESTAMP_FIELD = "timestamp"
_NOTES_FIELD = "notes"
_NOT_SCORED = "Not scored"


def _state_key(run_name: str, field: str) -> str:
    return f"{_STATE_PREFIX}{run_name}::{field}"


def _widget_key(run_name: str, field: str) -> str:
    return f"{_WIDGET_PREFIX}{run_name}::{field}"


def _review_fields() -> tuple[str, ...]:
    """Every durable field of one run's worksheet, in a stable order."""
    fields = [f"score_{spec.key}" for spec in CATEGORIES]
    fields += [f"rationale_{spec.key}" for spec in CATEGORIES]
    fields += [_NOTES_FIELD, _TIMESTAMP_FIELD]
    return tuple(fields)


def _durable(run_name: str, field: str) -> str:
    """Read one durable value, defaulting to this field's empty representation."""
    default = _NOT_SCORED if field.startswith("score_") else ""
    return str(st.session_state.get(_state_key(run_name, field), default))


def _persist_field(run_name: str, field: str) -> None:
    """Copy a widget's current value into the durable record.

    Registered as the widget's ``on_change``. Streamlit runs it while the widget
    key still exists, which is precisely the window in which the value can be
    rescued before the key is discarded.
    """
    widget_key = _widget_key(run_name, field)
    if widget_key in st.session_state:
        st.session_state[_state_key(run_name, field)] = st.session_state[widget_key]


def _hydrate_widgets(run_name: str) -> None:
    """Seed the transient widget keys from the durable record before rendering.

    Only when the widget key is absent: an existing key means Streamlit is
    mid-interaction and already holds the newer value.
    """
    for field in _review_fields():
        widget_key = _widget_key(run_name, field)
        if widget_key not in st.session_state:
            st.session_state[widget_key] = _durable(run_name, field)


def _manual_review_from_state(run_name: str) -> ManualReview:
    """Build the record from DURABLE state only -- never from a widget key."""
    return ManualReview(
        scores=tuple(
            (spec.key, _score_from_widget(_durable(run_name, f"score_{spec.key}")))
            for spec in CATEGORIES
        ),
        notes=_durable(run_name, _NOTES_FIELD),
        rationales=tuple(
            (spec.key, _durable(run_name, f"rationale_{spec.key}")) for spec in CATEGORIES
        ),
        user_entered_timestamp=(_durable(run_name, _TIMESTAMP_FIELD) or None),
    )


def _render_manual_review(data: DashboardData) -> None:
    st.warning(
        f"**{MANUAL_REVIEW_DISCLAIMER}.** You assign every category yourself; the "
        f"app only adds the arithmetic and derives the frozen tier "
        f"(S 10-12, A 8-9, B 6-7, C 4-5, D 0-3). No automated recommendation and "
        f"no decision output is produced."
    )
    run_name = data.run_name
    _hydrate_widgets(run_name)

    score_options = {
        spec.key: [_NOT_SCORED, *[str(value) for value in range(spec.maximum + 1)]]
        for spec in CATEGORIES
    }
    score_columns = st.columns(len(CATEGORIES))
    for column, spec in zip(score_columns, CATEGORIES, strict=True):
        score_field = f"score_{spec.key}"
        rationale_field = f"rationale_{spec.key}"
        with column:
            st.selectbox(
                f"{spec.label} (0-{spec.maximum})",
                score_options[spec.key],
                key=_widget_key(run_name, score_field),
                on_change=_persist_field,
                args=(run_name, score_field),
            )
            st.text_input(
                "Rationale (optional)",
                key=_widget_key(run_name, rationale_field),
                on_change=_persist_field,
                args=(run_name, rationale_field),
            )
    st.text_area(
        "Notes",
        key=_widget_key(run_name, _NOTES_FIELD),
        on_change=_persist_field,
        args=(run_name, _NOTES_FIELD),
    )
    st.text_input(
        "Optional timestamp: typed by you; the app never reads the clock",
        key=_widget_key(run_name, _TIMESTAMP_FIELD),
        on_change=_persist_field,
        args=(run_name, _TIMESTAMP_FIELD),
    )

    # Built from the DURABLE record, so the worksheet and both exports survive
    # navigation to any other screen and come back intact.
    review = _manual_review_from_state(run_name)

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


# --------------------------------------------------------------------------
# GM-041.5: the deterministic engine evaluation screen
# --------------------------------------------------------------------------


def _plain_decimal(value: object) -> str:
    """Exact Decimal text. Never float() — ADR-0002 forbids the coercion."""
    return format(value, "f") if hasattr(value, "as_tuple") else str(value)


def _render_synthetic_banner() -> None:
    st.warning(f"**{SYNTHETIC_CONFIG_BANNER}**")


def _render_configuration_identity(versioned: VersionedConfiguration) -> None:
    """Which configuration produced what follows, and its verifiable identity."""
    st.caption("Configuration in force  ·  **SYNTHETIC / NON-PRODUCTION**")
    left, right = st.columns(2)
    with left:
        st.markdown(f"- version identifier: `{versioned.version_identifier}`")
        st.markdown(f"- specification version: `{versioned.configuration.specification_version}`")
    with right:
        st.markdown(f"- semantic config_hash: `{versioned.config_hash.value[:16]}...`")
        digest = versioned.source_digest or "not recorded"
        st.markdown(f"- source digest: `{digest[:16]}...`")
    with st.expander("Full configuration identity"):
        st.markdown(f"- semantic config_hash: `{versioned.config_hash.value}`")
        st.markdown(f"- source digest: `{versioned.source_digest or 'not recorded'}`")
        st.caption(
            "The semantic hash covers behaviour-affecting fields only, so "
            "reformatting the file cannot change it. The source digest covers "
            "the exact bytes read."
        )


def _render_component_breakdown(result: EvaluatedGradeResult) -> None:
    """Every category and every scored component, in the engine's own order."""
    st.subheader("3. Component Breakdown")
    st.caption(
        "Category maxima, buckets, and points below come from the synthetic "
        "configuration. They are not production allocations."
    )
    for category in result.category_scores:
        st.markdown(
            f"**{category.category.value}** — category points "
            f"`{_plain_decimal(category.points_awarded)}`"
        )
        for score in category.component_scores:
            measurement = (
                f" (measurement `{score.measurement_id.value}`)"
                if score.measurement_id is not None
                else ""
            )
            bucket = ""
            if score.bucket_hit is not None:
                upper = (
                    "inf"
                    if score.bucket_hit.upper_bound is None
                    else _plain_decimal(score.bucket_hit.upper_bound)
                )
                terminal = ", terminal" if score.bucket_hit.is_terminal else ""
                bucket = (
                    f" — bucket [{_plain_decimal(score.bucket_hit.lower_bound)}, {upper}){terminal}"
                )
            st.markdown(
                f"    - `{score.component_id.value}`{measurement}: "
                f"`{_plain_decimal(score.points_awarded)}` points{bucket}"
            )


def _render_missing_components(result: GradeResult) -> None:
    """Why a component recorded zero, with the reason carried on the record."""
    if not result.missing_observations:
        return
    st.markdown("**Components with no observed value**")
    st.caption(
        "Each records an explicit zero under its configured record_missing "
        "policy, with the reason carried on the record. Nothing is imputed."
    )
    for observation in result.missing_observations:
        measurement = (
            f" (measurement `{observation.measurement_id.value}`)"
            if observation.measurement_id is not None
            else ""
        )
        st.markdown(
            f"- `{observation.component_id.value}`{measurement}: "
            f"missing reason `{observation.missing_reason.value}`"
        )


def _render_audit_trail(result: GradeResult) -> None:
    """The complete ordered derivation. Nothing truncated, nothing omitted."""
    entries = result.audit_derivation
    sequences = [entry.sequence for entry in entries]
    contiguous = sequences == list(range(1, len(entries) + 1))
    ordering = f"contiguous 1..{len(entries)}" if contiguous else "NON-CONTIGUOUS"
    st.subheader("4. Audit Trail")
    st.caption(
        f"{len(entries)} ordered entries, sequence {ordering}. Every awarded "
        f"and withheld point explains itself."
    )
    if not contiguous:
        st.error(
            f"{ERROR_COLOR.icon} The audit derivation is not contiguously numbered: {sequences}"
        )
    with st.expander(f"Complete derivation ({len(entries)} entries)", expanded=False):
        for entry in entries:
            scope_bits = []
            if entry.component_id is not None:
                scope_bits.append(f"component `{entry.component_id.value}`")
            if entry.category is not None:
                scope_bits.append(f"category `{entry.category.value}`")
            scope = f" — {', '.join(scope_bits)}" if scope_bits else ""
            st.markdown(f"**{entry.sequence}. `{entry.stage}`**{scope}")
            st.markdown(f"    - rule reference: `{entry.rule_reference}`")
            st.markdown(f"    - input: {entry.input_summary}")
            st.markdown(f"    - output: {entry.output_summary}")
            st.markdown(f"    - why: {entry.explanation}")


def _render_warnings(result: GradeResult) -> None:
    st.subheader("5. Warnings")
    st.caption(
        "Advisory findings only. A warning never silently alters a score, a "
        "category total, or the tier."
    )
    findings = result.validation_findings
    if not findings:
        st.markdown("No validation findings for this profile.")
        return
    for finding in findings:
        component = f"`{finding.component_id.value}`: " if finding.component_id is not None else ""
        st.markdown(f"- [`{finding.input_id.value}`] {component}{finding.message}")


def _render_fallbacks(result: GradeResult) -> None:
    """Fallback provenance, read from the observations the RESULT carries."""
    st.subheader("6. Fallbacks")
    entries = [
        observation
        for observation in result.present_observations
        if observation.fallback_used is not None
    ]
    if not entries:
        st.markdown("No fallback acquisition was used for this profile.")
        return
    st.caption(
        "The ingestion layer selected a lower-priority acquisition method "
        "because the higher-priority ones were ineligible at this as_of. "
        "Eligibility outranks priority (MODEL_SPEC §11.2)."
    )
    for observation in entries:
        fallback = observation.fallback_used
        assert fallback is not None  # filtered above; narrows for the type checker
        st.markdown(
            f"- `{observation.component_id.value}` resolved through "
            f"`{observation.acquisition_method.value}`"
        )
        for record in fallback.higher_priority_ineligible:
            st.markdown(f"    - `{record.method.value}` ineligible: {record.reason}")


def _render_evaluated(result: EvaluatedGradeResult) -> None:
    """The six approved engine outputs, and nothing else."""
    st.subheader("1. Total Score  ·  2. Tier")
    score_column, tier_column = st.columns(2)
    with score_column:
        st.metric(
            "Total Score",
            f"{_plain_decimal(result.total_score)} of 12",
            help=SCORE_QUALIFIER,
        )
    with tier_column:
        st.metric("Tier", result.grade.value, help=SCORE_QUALIFIER)
    st.caption(f"**{SCORE_QUALIFIER}.**")
    _render_component_breakdown(result)
    _render_missing_components(result)
    _render_audit_trail(result)
    _render_warnings(result)
    _render_fallbacks(result)


def _render_not_evaluable(result: GradeResult) -> None:
    """A distinct terminal state. Never a zero, never a D tier."""
    st.error(
        f"{ERROR_COLOR.icon} **NOT EVALUABLE** — required data remained "
        f"unavailable after every approved fallback."
    )
    st.caption(
        "This is a structurally different result from an evaluated one: it "
        "carries no total score and no tier, and must never be read as zero "
        "points or as tier D."
    )
    unavailable = getattr(result, "unavailable_required_inputs", ())
    st.subheader("Unavailable required inputs")
    for entry in unavailable:
        measurement = (
            f" (measurement `{entry.measurement_id.value}`)"
            if entry.measurement_id is not None
            else ""
        )
        st.markdown(
            f"- `{entry.component_id.value}`{measurement}: "
            f"missing reason `{entry.missing_reason.value}`"
        )
        for ineligibility in entry.attempted_methods:
            st.markdown(f"    - attempted `{ineligibility.method.value}`: {ineligibility.reason}")
    _render_audit_trail(result)
    _render_warnings(result)
    _render_fallbacks(result)


# A typed failure's own message is written for engineers and can carry an
# absolute path, a username, or raw OSError prose — for example
# "[Errno 13] Permission denied: '/very/private/secret/config.yaml'". None of
# that belongs on a rendered screen, so the UI never prints `failure.message`
# (nor `failure.context.file_path`). It prints the stable error CATEGORY, which
# is a closed vocabulary, plus one of these fixed sentences.
#
# Keyed on the stable `error_type` string rather than on class identity, so the
# adapter stays deterministic and needs no import from the error hierarchy. An
# unrecognised category falls back to the generic sentence: safe by
# construction rather than by remembering to add an entry.
_SAFE_FAILURE_WORDING: dict[str, str] = {
    "ConfigParseError": ("The synthetic non-production configuration could not be read or parsed."),
    "ConfigSchemaError": (
        "The synthetic non-production configuration does not match the required "
        "configuration schema."
    ),
    "ConfigSemanticError": (
        "The synthetic non-production configuration is structurally valid but "
        "violates a model-specification invariant."
    ),
    "ConfigVersionError": (
        "The synthetic non-production configuration's version identity could not be established."
    ),
    "ConfigIntegrityError": (
        "The synthetic non-production configuration failed its integrity check."
    ),
    "SourceModifiedError": (
        "The synthetic non-production configuration changed on disk after it was "
        "loaded, so it can no longer be trusted for this evaluation."
    ),
    "SourceUnavailableError": (
        "The synthetic non-production configuration is no longer available to re-verify."
    ),
    "ScoringConfigError": "The configuration cannot drive the grading engine for this run.",
    "ScoringInputError": (
        "The archived snapshot and the configuration disagree, so no evaluation was produced."
    ),
    "ScoringError": "The grading engine could not produce an evaluation for this run.",
}

_GENERIC_FAILURE_WORDING = "The deterministic evaluation could not be produced for this run."


def _safe_failure_wording(failure: GreenMachineError) -> str:
    """One fixed, user-safe sentence for a typed failure. Never its own message."""
    return _SAFE_FAILURE_WORDING.get(failure.error_type, _GENERIC_FAILURE_WORDING)


def _render_evaluation_unavailable(failure: GreenMachineError) -> None:
    """A configuration or scoring failure — never a run-verification failure.

    The typed failure object is passed in whole and left unmutated; only its
    stable ``error_type`` reaches the screen. Nothing derived from a filesystem
    path, a username, or a traceback is rendered.
    """
    st.error(
        f"{ERROR_COLOR.icon} **Evaluation unavailable**\n\n"
        f"- error category: `{failure.error_type}`\n"
        f"- {_safe_failure_wording(failure)}"
    )
    st.caption(
        "The archived run itself verified successfully. Only the deterministic "
        "evaluation could not be produced, so no partial result is shown. Every "
        "other screen remains available. Diagnostic detail is deliberately not "
        "shown here: it can contain local filesystem paths."
    )


def _render_evaluation(run: VerifiedRun) -> None:
    """Compose verified snapshot + non-production configuration into a result.

    This is the only place the three layers meet. ``reporting`` supplied the
    replay-verified snapshots, ``config`` supplies the disclaimed configuration,
    and the pure engine turns those two immutable values into a ``GradeResult``.
    The configuration is loaded lazily here, so a missing or invalid file cannot
    affect any other screen.
    """
    _render_synthetic_banner()

    header = run.dashboard.header
    st.markdown(
        f"**Run** `{run.dashboard.run_name}`  ·  **Hitter** {header.batter_name} "
        f"(`{header.batter_id}`)  ·  **Expected pitcher** {header.pitcher_name} "
        f"(`{header.pitcher_id}`)  ·  **Game** `{header.game_id}`"
    )

    try:
        if not SYNTHETIC_CONFIG_PATH.is_file():
            raise ConfigParseError(
                "the non-production configuration file is not present in this "
                "deployment, so no evaluation can be produced",
                ErrorContext(subject=SYNTHETIC_CONFIG_PATH.name),
            )
        versioned = load_versioned_config(SYNTHETIC_CONFIG_PATH)
    except ConfigurationError as failure:
        _render_evaluation_unavailable(failure)
        return

    _render_configuration_identity(versioned)
    st.divider()

    labels = {
        WindowProfile.RECENT_7D: "RECENT_7D — Recent, last 7 days",
        WindowProfile.LONG_TERM_2Y: "LONG_TERM_2Y — Long-term, rolling 2 years",
    }
    profile = st.radio(
        "Window profile",
        options=(WindowProfile.RECENT_7D, WindowProfile.LONG_TERM_2Y),
        format_func=lambda value: labels[value],
        key="evaluation_profile",
        horizontal=True,
    )
    snapshot: InputSnapshot = (
        run.recent_snapshot if profile is WindowProfile.RECENT_7D else run.long_term_snapshot
    )
    st.caption(
        f"Scoring snapshot `{snapshot.snapshot_id.value}` "
        f"(profile `{snapshot.window_profile.value}`)."
    )

    try:
        result = score_snapshot(snapshot, versioned.configuration)
    except ScoringError as failure:
        _render_evaluation_unavailable(failure)
        return

    st.divider()
    if isinstance(result, EvaluatedGradeResult):
        _render_evaluated(result)
    else:
        _render_not_evaluable(result)

    st.divider()
    _render_synthetic_banner()
    st.caption(
        "GreenMachine separates evaluation from decision-making. This screen "
        "produces no automated recommendation and no decision output. Every "
        "decision is yours. The Manual Review worksheet remains entirely "
        "separate and is never written to from here."
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
        run = _load_verified(handle.name, str(handle.directory))
    except GreenMachineError as failure:
        _render_focused_error(handle.name, failure)
        st.stop()
        return

    data = run.dashboard

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
    elif screen == "evaluate":
        _render_evaluation(run)
    else:  # an unknown state falls back to the hub rather than a blank page
        _go("hub")
        _render_hub()


main()

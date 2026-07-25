"""Dashboard loading over the shipped archived run: read-only, confined, whiff-free."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from greenmachine.common.errors import GreenMachineError
from greenmachine.domain import WindowProfile
from greenmachine.reporting import (
    DashboardData,
    DashboardLoadError,
    DataStatus,
    RunHandle,
    discover_runs,
    load_dashboard,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_ROOT = REPO_ROOT / "evidence" / "gm020_vertical_slice"
SHIPPED_RUN = EVIDENCE_ROOT / "prospective_run"


@pytest.fixture(scope="module")
def dashboard() -> DashboardData:
    runs = discover_runs(EVIDENCE_ROOT)
    assert runs, "the shipped evidence run must be discoverable"
    return load_dashboard(runs[0])


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


def test_the_shipped_run_is_discovered() -> None:
    names = [handle.name for handle in discover_runs(EVIDENCE_ROOT)]
    assert "prospective_run" in names


def test_discovery_order_is_deterministic_by_name(tmp_path: Path) -> None:
    for name in ("zulu_run", "alpha_run", "mid_run"):
        shutil.copytree(SHIPPED_RUN, tmp_path / name)
    (tmp_path / "not_a_run").mkdir()  # no manifest.json: never offered
    (tmp_path / "stray_file.txt").write_text("ignored", encoding="utf-8")

    names = [handle.name for handle in discover_runs(tmp_path)]
    assert names == ["alpha_run", "mid_run", "zulu_run"]
    assert names == [handle.name for handle in discover_runs(tmp_path)]  # stable


def test_a_symlinked_run_escaping_the_root_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside_target"
    shutil.copytree(SHIPPED_RUN, outside)
    root = tmp_path / "root"
    root.mkdir()
    shutil.copytree(SHIPPED_RUN, root / "legit_run")
    try:
        (root / "sneaky_link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")
    names = [handle.name for handle in discover_runs(root)]
    assert names == ["legit_run"]  # the escaping link is never offered


def test_a_missing_root_discovers_nothing(tmp_path: Path) -> None:
    assert discover_runs(tmp_path / "does_not_exist") == ()


# --------------------------------------------------------------------------
# Integrity, read-only behavior, cwd independence
# --------------------------------------------------------------------------


def test_loading_is_read_only_byte_for_byte() -> None:
    before = {
        path.relative_to(SHIPPED_RUN).as_posix(): path.read_bytes()
        for path in sorted(SHIPPED_RUN.rglob("*"))
        if path.is_file()
    }
    load_dashboard(RunHandle(name="prospective_run", directory=SHIPPED_RUN))
    after = {
        path.relative_to(SHIPPED_RUN).as_posix(): path.read_bytes()
        for path in sorted(SHIPPED_RUN.rglob("*"))
        if path.is_file()
    }
    assert after == before


def test_a_corrupted_run_yields_a_focused_error(tmp_path: Path) -> None:
    corrupted = tmp_path / "corrupted_run"
    shutil.copytree(SHIPPED_RUN, corrupted)
    target = corrupted / "raw" / "batter_events_recent_7d.csv"
    body = bytearray(target.read_bytes())
    body[10] ^= 0x01
    target.write_bytes(bytes(body))

    with pytest.raises(GreenMachineError) as failure:
        load_dashboard(RunHandle(name="corrupted_run", directory=corrupted))
    # Focused and deterministic: an error type plus a concise message — the
    # app renders exactly these, never a traceback.
    assert failure.value.error_type
    assert "digest" in failure.value.message.lower() or "byte" in failure.value.message.lower()


def test_loading_is_independent_of_the_working_directory(tmp_path: Path) -> None:
    previous = Path.cwd()
    os.chdir(tmp_path)
    try:
        data = load_dashboard(RunHandle(name="prospective_run", directory=SHIPPED_RUN))
    finally:
        os.chdir(previous)
    assert data.header.game_id == "823196"


# --------------------------------------------------------------------------
# Profile separation
# --------------------------------------------------------------------------


def test_profiles_remain_separate_and_share_one_source_capture(
    dashboard: DashboardData,
) -> None:
    assert dashboard.recent.profile is WindowProfile.RECENT_7D
    assert dashboard.long_term.profile is WindowProfile.LONG_TERM_2Y
    assert dashboard.recent.snapshot_id != dashboard.long_term.snapshot_id
    assert dashboard.recent.input_hash != dashboard.long_term.input_hash
    # One SourceCaptureId, surfaced once on the header.
    assert dashboard.header.source_capture_id.startswith("source_capture-")


def test_every_card_is_tied_to_exactly_one_profile(dashboard: DashboardData) -> None:
    for card in dashboard.recent.all_cards:
        assert card.profile is WindowProfile.RECENT_7D
    for card in dashboard.long_term.all_cards:
        assert card.profile is WindowProfile.LONG_TERM_2Y


def test_no_blended_display_record_exists(dashboard: DashboardData) -> None:
    """Comparison rows carry both profiles side by side, explicitly labeled —
    never a merged or averaged value."""
    for row in dashboard.comparison:
        assert row.recent_display != "blended"
        assert "average of profiles" not in row.difference_note
    # And the model itself refuses same-profile construction (unit-level rule),
    # so a blended ProfileMetrics cannot even be built.


# --------------------------------------------------------------------------
# Metric presentation
# --------------------------------------------------------------------------

_EXPECTED_CARD_KEYS = [
    "exit_velocity",
    "barrel_pct",
    "hard_hit_pct",
    "bat_speed",
    "sweet_spot_pct",
    "attack_angle_quality",
    "pull_pct_air_balls",
    "overall_pull_context",
]


def test_the_approved_metric_set_appears_per_profile(dashboard: DashboardData) -> None:
    for metrics in (dashboard.recent, dashboard.long_term):
        assert [card.key for card in metrics.all_cards] == _EXPECTED_CARD_KEYS


def test_sample_counts_are_retained(dashboard: DashboardData) -> None:
    by_key = {card.key: card for card in dashboard.long_term.all_cards}
    assert by_key["exit_velocity"].sample_count == 824
    assert by_key["bat_speed"].sample_count == 2662
    assert by_key["pull_pct_air_balls"].sample_count == 439


def test_overall_pull_is_audit_only_and_blue(dashboard: DashboardData) -> None:
    for metrics in (dashboard.recent, dashboard.long_term):
        card = metrics.all_cards[-1]
        assert card.key == "overall_pull_context"
        assert card.audit_only
        assert card.status is DataStatus.AUDIT_CONTEXT
        assert "never a scoring input" in card.explanation


def test_status_reflects_observation_state_only(dashboard: DashboardData) -> None:
    """Wildly different values share statuses; status never encodes quality."""
    by_key = {card.key: card for card in dashboard.recent.all_cards}
    # 0.0% barrels and 92.8 mph exit velocity carry the same green badge,
    # because both are present with sufficient validation-policy samples.
    assert by_key["barrel_pct"].status is by_key["exit_velocity"].status


# --------------------------------------------------------------------------
# Hostile audit reports: every malformation is a focused DashboardLoadError
# --------------------------------------------------------------------------


def _run_with_mutated_report(
    tmp_path: Path,
    report_relative_path: str,
    mutate: Callable[[dict[str, object]], object],
) -> RunHandle:
    """A copy of the shipped run with one audit report rewritten.

    Audit reports are not replay-verified (they are display artifacts, not
    part of any identity), so the mutation reaches the dashboard's strict
    display adapters — exactly the surface under test.
    """
    mutated = tmp_path / "mutated_run"
    shutil.copytree(SHIPPED_RUN, mutated)
    target = mutated / report_relative_path
    document = json.loads(target.read_text(encoding="utf-8"))
    replacement = mutate(document)
    target.write_text(
        json.dumps(document if replacement is None else replacement), encoding="utf-8"
    )
    return RunHandle(name="mutated_run", directory=mutated)


def _expect_load_error(handle: RunHandle, match: str) -> None:
    with pytest.raises(DashboardLoadError, match=match) as failure:
        load_dashboard(handle)
    assert "mutated_run" in failure.value.message  # run name is always named


def test_a_malformed_overall_pull_value_is_focused(tmp_path: Path) -> None:
    def mutate(document: dict[str, object]) -> None:
        overall = document["overall_pull_report_only"]
        assert isinstance(overall, dict)
        overall["value"] = "not-a-decimal"

    handle = _run_with_mutated_report(tmp_path, "reports/pull_audit_recent_7d.json", mutate)
    _expect_load_error(handle, "not a valid Decimal string")


def test_a_malformed_overall_pull_sample_count_is_focused(tmp_path: Path) -> None:
    def negative(document: dict[str, object]) -> None:
        overall = document["overall_pull_report_only"]
        assert isinstance(overall, dict)
        overall["sample_count"] = -3

    handle = _run_with_mutated_report(tmp_path, "reports/pull_audit_recent_7d.json", negative)
    _expect_load_error(handle, "must not be negative")

    def stringly(document: dict[str, object]) -> None:
        overall = document["overall_pull_report_only"]
        assert isinstance(overall, dict)
        overall["sample_count"] = "13"

    handle = _run_with_mutated_report(
        tmp_path / "second", "reports/pull_audit_recent_7d.json", stringly
    )
    _expect_load_error(handle, "must be an integer")


def test_overall_pull_value_sample_coherence_is_enforced(tmp_path: Path) -> None:
    def mutate(document: dict[str, object]) -> None:
        overall = document["overall_pull_report_only"]
        assert isinstance(overall, dict)
        overall["value"] = None  # while sample_count stays nonzero

    handle = _run_with_mutated_report(tmp_path, "reports/pull_audit_recent_7d.json", mutate)
    _expect_load_error(handle, "coherence")


def test_a_malformed_game_type_exclusion_pair_is_focused(tmp_path: Path) -> None:
    def mutate(document: dict[str, object]) -> None:
        document["excluded_by_game_type"] = [["S"]]  # previously an IndexError

    handle = _run_with_mutated_report(tmp_path, "reports/normalization_recent_7d.json", mutate)
    _expect_load_error(handle, "malformed pair")


def test_a_malformed_pull_exclusion_pair_is_focused(tmp_path: Path) -> None:
    def mutate(document: dict[str, object]) -> None:
        chosen = document["chosen_pull_air"]
        assert isinstance(chosen, dict)
        chosen["exclusions"] = [["unusable_coordinates", -1]]

    handle = _run_with_mutated_report(tmp_path, "reports/pull_audit_long_term_2y.json", mutate)
    _expect_load_error(handle, "non-negative integers")


def test_a_duplicate_report_json_key_is_focused(tmp_path: Path) -> None:
    mutated = tmp_path / "mutated_run"
    shutil.copytree(SHIPPED_RUN, mutated)
    target = mutated / "reports" / "pull_audit_recent_7d.json"
    text = target.read_text(encoding="utf-8")
    assert '"statement":' in text
    target.write_text(
        text.replace('"statement":', '"statement":"shadowed","statement":', 1),
        encoding="utf-8",
    )
    _expect_load_error(
        RunHandle(name="mutated_run", directory=mutated), "duplicate JSON object key"
    )


def test_an_invalid_report_root_type_is_focused(tmp_path: Path) -> None:
    handle = _run_with_mutated_report(
        tmp_path, "reports/normalization_long_term_2y.json", lambda document: []
    )
    _expect_load_error(handle, "root must be a JSON object")


def test_a_profile_mismatched_report_is_focused(tmp_path: Path) -> None:
    def mutate(document: dict[str, object]) -> None:
        document["profile"] = "LONG_TERM_2Y"  # wrong report for this slot

    handle = _run_with_mutated_report(tmp_path, "reports/normalization_recent_7d.json", mutate)
    _expect_load_error(handle, "not the expected")


# --------------------------------------------------------------------------
# Whiff exclusion and deferred pitcher metrics
# --------------------------------------------------------------------------


def _walk_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if is_dataclass(value) and not isinstance(value, type):
        collected: list[str] = []
        for field in fields(value):
            collected.extend(_walk_strings(getattr(value, field.name)))
        return collected
    if isinstance(value, (list, tuple)):
        collected = []
        for item in value:
            collected.extend(_walk_strings(item))
        return collected
    return []


def test_whiff_never_appears_anywhere_in_the_view_model_tree(
    dashboard: DashboardData,
) -> None:
    for text in _walk_strings(dashboard):
        assert "whiff" not in text.lower(), text


def test_pitcher_context_is_identity_and_role_only(dashboard: DashboardData) -> None:
    """Pitcher-specific metrics are deferred: the view model structurally
    cannot carry a pitcher performance statistic."""
    context = dashboard.pitcher_context
    assert context.pitcher_name == "Grayson Rodriguez"
    assert context.pitcher_id == "680570"
    assert context.role_label == "expected starter"
    assert "deferred" in context.deferred_note
    field_names = {field.name for field in fields(context)}
    assert field_names == {
        "pitcher_name",
        "pitcher_id",
        "role_label",
        "handedness_note",
        "deferred_note",
    }
    # No usage, pitch-count, two-strike, or putaway field exists anywhere.
    for banned_fragment in ("usage", "pitch_type", "two_strike", "putaway", "pitches"):
        assert not any(banned_fragment in name for name in field_names), banned_fragment


def test_no_pitcher_metric_value_reaches_any_view_model(dashboard: DashboardData) -> None:
    """The ingredient report is never parsed for the UI: none of its values
    can appear in the dashboard data tree."""
    ingredient_document = json.loads(
        (SHIPPED_RUN / "reports" / "pitcher_ingredients.json").read_text(encoding="utf-8")
    )
    rows = ingredient_document["rows"]
    assert rows, "the archived report genuinely carries ingredient rows"
    usage_values = {str(row["usage_percent_within_stand"]) for row in rows}
    tree = " ".join(_walk_strings(dashboard))
    for value in usage_values:
        assert value not in tree


# --------------------------------------------------------------------------
# Audit content
# --------------------------------------------------------------------------


def test_the_audit_section_distinguishes_the_data_states(dashboard: DashboardData) -> None:
    audit = dashboard.audit
    assert len(audit.missing_components) == 8  # 4 components x 2 profiles
    assert audit.fallback_notes  # IAA fallback, per profile
    assert all("Ideal Attack Angle%" in note for note in audit.fallback_notes)
    assert audit.manifest_id.startswith("capture_manifest-")
    assert len(audit.capture_entries) == 5
    assert "VALIDATION-ONLY" in audit.sample_policy_disclaimer
    assert "not a production model configuration" in audit.sample_policy_disclaimer


def test_no_machine_local_path_appears_in_view_models(dashboard: DashboardData) -> None:
    for text in _walk_strings(dashboard):
        lowered = text.lower()
        assert "c:\\users" not in lowered
        assert "appdata" not in lowered

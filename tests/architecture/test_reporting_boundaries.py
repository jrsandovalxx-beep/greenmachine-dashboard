"""Architecture guards for the GM-030 reporting/dashboard layer.

Direction of dependencies, Streamlit confinement to the composition root,
no provider clients or transport in reporting, no floats in metric handling,
no hidden performance thresholds, no persistence, and no Whiff Rate surface.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from static_analysis import collect_imports, within

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "src" / "greenmachine"
REPORTING_ROOT = PACKAGE_ROOT / "reporting"
APP_PATH = REPO_ROOT / "streamlit_app.py"


def parse_file(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def reporting_files() -> list[Path]:
    return sorted(REPORTING_ROOT.rglob("*.py"))


def test_the_reporting_package_is_populated() -> None:
    names = {path.name for path in reporting_files()}
    assert {
        "dashboard_loader.py",
        "dashboard_models.py",
        "dashboard_formatting.py",
        "manual_review.py",
    } <= names


# --------------------------------------------------------------------------
# Dependency direction
# --------------------------------------------------------------------------

_FORBIDDEN_FOR_REPORTING = (
    "greenmachine.scoring",
    "greenmachine.features",
    "greenmachine.cli",
    "greenmachine.config",
    # Provider clients and live transport stay out of reporting: only the
    # approved read-only replay APIs are allowed.
    "greenmachine.ingestion.mlb",
    "greenmachine.ingestion.savant",
    "greenmachine.ingestion.transport",
    "greenmachine.ingestion.capture",
    "greenmachine.ingestion.events",
    "greenmachine.ingestion.mapping",
)


@pytest.mark.parametrize("path", reporting_files(), ids=lambda p: p.name)
def test_reporting_never_imports_scoring_clients_or_transport(path: Path) -> None:
    for record in collect_imports(parse_file(path)):
        resolved = record.resolved("greenmachine.reporting")
        for forbidden in _FORBIDDEN_FOR_REPORTING:
            assert not within(resolved, forbidden), f"{path.name} imports {resolved}"


def test_ingestion_never_imports_reporting_or_streamlit() -> None:
    for path in sorted((PACKAGE_ROOT / "ingestion").rglob("*.py")):
        for record in collect_imports(parse_file(path)):
            resolved = record.resolved("greenmachine.ingestion")
            assert not within(resolved, "greenmachine.reporting"), path.name
            assert record.top_level != "streamlit", path.name


def test_streamlit_is_confined_to_the_composition_root() -> None:
    """No module under src/ imports Streamlit — only streamlit_app.py does."""
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tops = {record.top_level for record in collect_imports(parse_file(path))}
        assert "streamlit" not in tops, f"{path} imports streamlit inside src/"
    app_tops = {record.top_level for record in collect_imports(parse_file(APP_PATH))}
    assert "streamlit" in app_tops  # anti-vacuity: the boundary really imports it


def test_the_app_composes_no_live_client_or_clock() -> None:
    source = parse_file(APP_PATH)
    for node in ast.walk(source):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {
                "UrllibTransport",
                "SystemClock",
                "SystemSleeper",
                "run_capture",
            }, f"streamlit_app.py must never compose live capture: {node.func.id}"
    tops = {record.top_level for record in collect_imports(source)}
    assert "urllib" not in tops
    assert "sqlite3" not in tops


# --------------------------------------------------------------------------
# No floats, no thresholds, no persistence
# --------------------------------------------------------------------------


def _float_offenders(tree: ast.Module) -> list[int]:
    offenders: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            offenders.append(getattr(node, "lineno", 0))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "float"
        ):
            offenders.append(node.lineno)
    return offenders


@pytest.mark.parametrize("path", reporting_files(), ids=lambda p: p.name)
def test_no_float_in_reporting(path: Path) -> None:
    assert _float_offenders(parse_file(path)) == []


def test_no_hidden_performance_threshold_exists() -> None:
    """No numeric comparison anywhere near status/color logic.

    In `dashboard_formatting` and `dashboard_models`, no comparison against a
    numeric literal exists at all — so a value-driven color cannot even be
    expressed there. Badges are keyed by DataStatus alone.
    """
    for name in ("dashboard_formatting.py", "dashboard_models.py"):
        tree = parse_file(REPORTING_ROOT / name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for comparator in node.comparators:
                    if isinstance(comparator, ast.Constant) and isinstance(
                        comparator.value, (int, float)
                    ):
                        raise AssertionError(
                            f"{name} compares against numeric literal at line "
                            f"{node.lineno}: a performance threshold has no home here"
                        )


def test_no_database_module_is_imported_by_reporting_or_the_app() -> None:
    for path in [*reporting_files(), APP_PATH]:
        tops = {record.top_level for record in collect_imports(parse_file(path))}
        assert "sqlite3" not in tops, path.name
        assert "sqlalchemy" not in tops, path.name


def test_reporting_opens_no_file_for_writing() -> None:
    """The reporting layer is read-only: no filesystem mutator and no
    write-mode ``open`` appears anywhere in it."""
    mutators = {"write_bytes", "write_text", "mkdir", "unlink", "rename", "rmdir"}
    for path in reporting_files():
        for node in ast.walk(parse_file(path)):
            if not isinstance(node, ast.Call):
                continue
            attribute = node.func
            if isinstance(attribute, ast.Attribute) and attribute.attr in mutators:
                raise AssertionError(f"{path.name} calls filesystem mutator '{attribute.attr}'")
            if isinstance(attribute, ast.Name) and attribute.id == "open":
                mode_arguments = list(node.args[1:]) + [keyword.value for keyword in node.keywords]
                for argument in mode_arguments:
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        assert "w" not in argument.value and "a" not in argument.value, (
                            f"{path.name} opens a file for writing"
                        )


# --------------------------------------------------------------------------
# Whiff Rate and deferred features have no surface
# --------------------------------------------------------------------------


def test_whiff_has_no_surface_in_reporting_or_the_presentation_layer() -> None:
    """GM-030-r1: the dashboard simply omits the metric without drawing
    attention to it. With pitcher metrics deferred, no reporting or
    presentation source needs the word at all — only tests may use it to
    enforce the rule."""
    for path in [*reporting_files(), APP_PATH, REPO_ROOT / "hub_theme.py"]:
        source = path.read_text(encoding="utf-8").lower()
        assert "whiff" not in source, f"{path.name} mentions whiff"


def test_no_pitcher_metric_field_exists_in_any_view_model() -> None:
    """Pitcher-specific metrics are deferred: no dataclass field in the
    models module carries a pitcher performance statistic."""
    tree = parse_file(REPORTING_ROOT / "dashboard_models.py")
    field_names = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and isinstance((target := node.target), ast.Name)
    }
    for banned_fragment in ("usage", "two_strike", "putaway", "pitch_type", "whiffs"):
        assert not any(banned_fragment in name for name in field_names), banned_fragment


def test_no_deferred_feature_is_implemented() -> None:
    """Pitchers to Target, bullpen, weather/park, betting, and full-slate
    surfaces do not exist in reporting or the presentation layer."""
    for path in [*reporting_files(), APP_PATH, REPO_ROOT / "hub_theme.py"]:
        source = path.read_text(encoding="utf-8").lower()
        for banned in (
            "pitchers to target",
            "pitcher_to_target",
            "bullpen",
            "strong_bet",
            "betting odds",
            "vulnerability",
            "full slate aggregation",
        ):
            assert banned not in source, f"{path.name} contains {banned!r}"


def test_reporting_and_app_carry_no_provider_wire_keys() -> None:
    wire_keys = (
        "hc_x",
        "hc_y",
        "launch_speed_angle",
        "bb_type",
        "batters_lookup[]",
        "pitchers_lookup[]",
        "hfGT",
        "gamePk",
        "probablePitchers",
        "abstractGameState",
    )
    for path in [*reporting_files(), APP_PATH, REPO_ROOT / "hub_theme.py"]:
        source = path.read_text(encoding="utf-8")
        for key in wire_keys:
            assert key not in source, f"{path.name} carries wire key {key!r}"


def test_the_hub_theme_asset_is_import_free_and_request_free() -> None:
    """`hub_theme.py` is a static presentation asset: no imports beyond
    __future__, and no request-capable CSS construct."""
    tree = parse_file(REPO_ROOT / "hub_theme.py")
    imports = [record.module for record in collect_imports(tree)]
    assert all(module == "__future__" for module in imports), imports
    source = (REPO_ROOT / "hub_theme.py").read_text(encoding="utf-8").lower()
    for banned in ("http://", "https://", "url(", "@import", "<script", "base64"):
        assert banned not in source, banned


# --------------------------------------------------------------------------
# GM-041.5: the composition root scores; reporting still may not
# --------------------------------------------------------------------------


def test_reporting_still_cannot_import_scoring_or_configuration() -> None:
    """The whole point of the VerifiedRun hand-off.

    Reporting returns frozen domain snapshots and stops there. If it ever
    imported ``scoring`` or ``config`` directly, the layering that keeps the
    grading engine independent of presentation would be gone — and this guard,
    not a code review, is what holds that line.
    """
    for path in reporting_files():
        package = "greenmachine.reporting"
        for record in collect_imports(parse_file(path)):
            resolved = record.resolved(package)
            for forbidden in ("greenmachine.scoring", "greenmachine.config"):
                assert not within(resolved, forbidden), f"{path.name} imports {resolved}"


def test_only_the_composition_root_imports_scoring() -> None:
    """`streamlit_app.py` is the one presentation-side module allowed to score."""
    app_modules = {record.module for record in collect_imports(parse_file(APP_PATH))}
    assert any(module.startswith("greenmachine.scoring") for module in app_modules), (
        "anti-vacuity: the composition root really does import the engine"
    )
    assert any(module.startswith("greenmachine.config") for module in app_modules)
    assert any(module.startswith("greenmachine.reporting") for module in app_modules)


def test_the_verified_run_record_carries_snapshots_and_no_scoring_behaviour() -> None:
    """VerifiedRun is a hand-off value, not a place to hide grading logic."""
    from greenmachine.reporting import VerifiedRun

    annotations = VerifiedRun.__annotations__
    assert set(annotations) == {"dashboard", "recent_snapshot", "long_term_snapshot"}
    for name in dir(VerifiedRun):
        if name.startswith("_"):
            continue
        attribute = getattr(VerifiedRun, name, None)
        assert not callable(attribute), f"VerifiedRun exposes behaviour: {name}"


def test_the_dashboard_view_model_stays_free_of_domain_snapshots() -> None:
    """DashboardData remains view-model-only; snapshots ride on VerifiedRun."""
    from greenmachine.reporting import DashboardData

    assert "snapshot" not in " ".join(DashboardData.__annotations__).lower() or all(
        "InputSnapshot" not in str(annotation)
        for annotation in DashboardData.__annotations__.values()
    )


def test_the_app_never_converts_a_decimal_through_float() -> None:
    """ADR-0002: rendering reads exact Decimal text, never a binary float."""
    tree = parse_file(APP_PATH)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "float", "streamlit_app.py must not call float()"
        if isinstance(node, ast.Attribute):
            assert node.attr != "__float__"


def test_the_app_writes_no_automated_value_into_manual_review_state() -> None:
    """No assignment into a `review::`-prefixed session-state key outside the
    manual worksheet renderer, and no copy-to-worksheet control anywhere."""
    source = APP_PATH.read_text(encoding="utf-8")
    evaluation_start = source.index("def _render_evaluation(")
    evaluation_source = source[evaluation_start:]
    assert "review::" not in evaluation_source
    for banned in ("apply score", "copy to worksheet", "copy to review"):
        assert banned not in source.lower(), banned

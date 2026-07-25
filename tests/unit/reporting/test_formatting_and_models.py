"""Data-status colors are state-driven; formatting is exact-Decimal only."""

from __future__ import annotations

from decimal import Decimal

from greenmachine.reporting import (
    COLOR_LEGEND,
    ERROR_COLOR,
    DataStatus,
    format_display_value,
    status_badge,
)


def test_every_data_status_maps_to_exactly_one_badge() -> None:
    colors = {status: status_badge(status).color for status in DataStatus}
    assert colors == {
        DataStatus.PRESENT_SUFFICIENT: "green",
        DataStatus.PRESENT_INSUFFICIENT: "yellow",
        DataStatus.MISSING: "gray",
        DataStatus.AUDIT_CONTEXT: "blue",
    }
    assert ERROR_COLOR.color == "red"


def test_badges_carry_a_text_label_and_icon_never_color_alone() -> None:
    for status in DataStatus:
        badge = status_badge(status)
        assert badge.icon and badge.label


def test_the_badge_depends_only_on_state_never_on_a_value() -> None:
    """The API is the proof: `status_badge` accepts a DataStatus and nothing
    else — no metric value can participate. Two wildly different values in
    the same state necessarily share one badge."""
    assert status_badge(DataStatus.PRESENT_SUFFICIENT) is status_badge(
        DataStatus.PRESENT_SUFFICIENT
    )


def test_the_legend_explains_every_color_as_data_status() -> None:
    colors = [color for color, _ in COLOR_LEGEND]
    assert colors == ["green", "yellow", "gray", "blue", "red"]
    legend_text = " ".join(meaning for _, meaning in COLOR_LEGEND)
    for performance_word in ("good", "bad", "strong", "weak", "favorable"):
        assert performance_word not in legend_text.lower()


def test_display_formatting_is_exact_decimal_presentation_rounding() -> None:
    assert format_display_value("92.79285714285714285714285714", "mph") == "92.8 mph"
    assert format_display_value("16.66666666666666666666666667", "%") == "16.7%"
    assert format_display_value("0", "%") == "0.0%"
    # Banker's rounding at the presentation boundary, consistent with ADR-0002.
    assert format_display_value("0.25", "") == "0.2"
    assert format_display_value("0.35", "") == "0.4"


def test_formatting_never_passes_through_float() -> None:
    rendered = format_display_value("101.4499999999999999999999999", "mph")
    assert rendered == "101.4 mph"  # float64 would have seen 101.45 and rounded up
    assert isinstance(rendered, str)
    assert Decimal("101.4") == Decimal(rendered.split()[0])

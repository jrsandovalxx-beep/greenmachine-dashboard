"""Savant CSV strictness and the exact-Decimal metric boundary matrix."""

from __future__ import annotations

from decimal import Decimal

import pytest
from tests.fixtures.ingestion import synthetic_provider_fixtures as fixtures

from greenmachine.ingestion.errors import SchemaDriftError
from greenmachine.ingestion.models import BatterEventRecord
from greenmachine.ingestion.savant.metrics import (
    TAN_15_DEGREES,
    classify_pull,
    compute_barrel_rate,
    compute_bat_speed,
    compute_exit_velocity,
    compute_hard_hit_rate,
    compute_ideal_attack_angle,
    compute_overall_pull,
    compute_pull_air,
    compute_sweet_spot_rate,
    pitcher_ingredient_rows,
)
from greenmachine.ingestion.savant.parser import (
    header_fingerprint_of,
    parse_batter_events,
    parse_pitcher_events,
)

# --------------------------------------------------------------------------
# Strict CSV parsing
# --------------------------------------------------------------------------


def test_a_valid_batter_csv_parses_with_decimal_values_only() -> None:
    records = parse_batter_events(fixtures.batter_csv([fixtures.batter_row()]))
    assert len(records) == 1
    row = records[0]
    assert isinstance(row.launch_speed, Decimal)
    assert isinstance(row.launch_angle, Decimal)
    assert isinstance(row.bat_speed, Decimal)
    assert isinstance(row.attack_angle, Decimal)
    assert isinstance(row.hit_x, Decimal)
    assert isinstance(row.hit_y, Decimal)
    assert row.launch_speed == Decimal("101.3")
    # No parsed numeric field is ever a float.
    for value in (row.launch_speed, row.launch_angle, row.bat_speed, row.attack_angle):
        assert not isinstance(value, float)


def test_null_cells_become_none_never_zero() -> None:
    records = parse_batter_events(
        fixtures.batter_csv(
            [fixtures.batter_row(launch_speed="", bat_speed="null", attack_angle="NA")]
        )
    )
    row = records[0]
    assert row.launch_speed is None
    assert row.bat_speed is None
    assert row.attack_angle is None


def test_zero_data_rows_parse_to_an_empty_tuple() -> None:
    assert parse_batter_events(fixtures.batter_csv([])) == ()


def test_a_missing_required_column_fails_closed() -> None:
    columns = tuple(c for c in fixtures.BATTER_COLUMNS if c != "launch_speed")
    body = (",".join(columns) + "\n").encode("utf-8")
    with pytest.raises(SchemaDriftError, match="missing required column"):
        parse_batter_events(body)


def test_an_unparseable_required_value_fails_closed() -> None:
    with pytest.raises(SchemaDriftError, match="not an integer"):
        parse_batter_events(fixtures.batter_csv([fixtures.batter_row(at_bat_number="three")]))


def test_an_unparseable_decimal_fails_closed() -> None:
    with pytest.raises(SchemaDriftError, match="not a decimal number"):
        parse_batter_events(fixtures.batter_csv([fixtures.batter_row(launch_speed="fast")]))


def test_malformed_csv_fails_closed() -> None:
    header = ",".join(fixtures.BATTER_COLUMNS)
    body = (header + "\n" + "only,two\n").encode("utf-8")
    with pytest.raises(SchemaDriftError, match="cells"):
        parse_batter_events(body)


def test_additive_unknown_columns_are_accepted_and_change_the_fingerprint() -> None:
    baseline = fixtures.batter_csv([fixtures.batter_row()])
    extended_columns = (*fixtures.BATTER_COLUMNS, "another_new_column")
    extended = (
        ",".join(extended_columns)
        + "\n"
        + ",".join(fixtures.batter_row().get(c, "") for c in extended_columns)
        + "\n"
    ).encode("utf-8")

    assert parse_batter_events(extended)  # accepted
    assert header_fingerprint_of(extended) != header_fingerprint_of(baseline)  # audited


def test_the_header_fingerprint_is_order_independent() -> None:
    reordered = tuple(reversed(fixtures.BATTER_COLUMNS))
    original = fixtures.batter_csv([])
    swapped = (",".join(reordered) + "\n").encode("utf-8")
    assert header_fingerprint_of(original) == header_fingerprint_of(swapped)


# --------------------------------------------------------------------------
# Metric boundary matrix (specification-owned definitions, exact Decimal)
# --------------------------------------------------------------------------


def _bbe_row(**overrides: str) -> BatterEventRecord:
    return parse_batter_events(fixtures.batter_csv([fixtures.batter_row(**overrides)]))[0]


def test_hard_hit_boundary_94_999_out_95_in() -> None:
    below = (_bbe_row(launch_speed="94.999"),)
    at = (_bbe_row(launch_speed="95"),)
    assert compute_hard_hit_rate(below).numerator == 0
    assert compute_hard_hit_rate(at).numerator == 1


def test_sweet_spot_8_and_32_are_included() -> None:
    rows = (
        _bbe_row(launch_angle="7.999"),
        _bbe_row(launch_angle="8", at_bat_number="2"),
        _bbe_row(launch_angle="32", at_bat_number="3"),
        _bbe_row(launch_angle="32.001", at_bat_number="4"),
    )
    computation = compute_sweet_spot_rate(rows)
    assert computation.numerator == 2
    assert computation.sample_count == 4


def test_ideal_attack_angle_5_and_20_are_included() -> None:
    rows = (
        _bbe_row(attack_angle="4.999"),
        _bbe_row(attack_angle="5", at_bat_number="2"),
        _bbe_row(attack_angle="20", at_bat_number="3"),
        _bbe_row(attack_angle="20.001", at_bat_number="4"),
    )
    computation = compute_ideal_attack_angle(rows)
    assert computation.numerator == 2
    assert computation.sample_count == 4


def test_ideal_attack_angle_uses_all_tracked_rows_not_bbe_only() -> None:
    swing_no_contact = _bbe_row(
        bb_type="",
        launch_speed="",
        launch_angle="",
        launch_speed_angle="",
        hc_x="",
        hc_y="",
        attack_angle="12",
    )
    contact = _bbe_row(attack_angle="30", at_bat_number="2")
    computation = compute_ideal_attack_angle((swing_no_contact, contact))
    assert computation.sample_count == 2  # the swing without contact counts
    assert computation.numerator == 1


def test_only_the_official_barrel_bucket_counts() -> None:
    rows = (
        _bbe_row(launch_speed_angle="6"),
        _bbe_row(launch_speed_angle="5", at_bat_number="2"),
        _bbe_row(launch_speed_angle="", at_bat_number="3"),
    )
    computation = compute_barrel_rate(rows)
    assert computation.numerator == 1
    assert computation.sample_count == 2  # unclassified BBE excluded and counted
    assert computation.exclusions == (("bbe_without_launch_speed_angle", 1),)


def test_exit_velocity_is_the_exact_context_mean() -> None:
    rows = (
        _bbe_row(launch_speed="100"),
        _bbe_row(launch_speed="101", at_bat_number="2"),
        _bbe_row(launch_speed="", at_bat_number="3"),
    )
    computation = compute_exit_velocity(rows)
    assert computation.value == Decimal("100.5")
    assert computation.sample_count == 2


def test_bat_speed_missingness_is_explicit() -> None:
    no_tracking = (_bbe_row(bat_speed=""),)
    computation = compute_bat_speed(no_tracking)
    assert computation.value is None
    assert computation.sample_count == 0
    assert computation.exclusions == (("rows_without_tracked_bat_speed", 1),)


# --------------------------------------------------------------------------
# Pull classification: exact geometry, row-level stand
# --------------------------------------------------------------------------

# For y = 100 the pull boundary sits exactly at TAN_15_DEGREES * 100.
_BOUNDARY_Y = Decimal("98.27")  # hc_y giving y = 198.27 - 98.27 = 100
_BOUNDARY_PULL = TAN_15_DEGREES * Decimal("100")  # 26.794919243112270647...


def test_pull_boundary_is_inclusive_on_the_pull_side() -> None:
    exactly_on = Decimal("125.42") - _BOUNDARY_PULL  # R-handed pull side
    assert classify_pull("R", exactly_on, _BOUNDARY_Y) is True
    assert classify_pull("R", exactly_on + Decimal("0.000000000000000001"), _BOUNDARY_Y) is False


def test_switch_hitters_classify_each_row_by_its_own_stand() -> None:
    # The same landing point is pulled for a left-handed stand and opposite
    # field for a right-handed stand.
    landing_x = Decimal("160")
    landing_y = Decimal("98.27")
    assert classify_pull("L", landing_x, landing_y) is True
    assert classify_pull("R", landing_x, landing_y) is False


def test_unusable_y_returns_none() -> None:
    assert classify_pull("R", Decimal("100"), Decimal("198.27")) is None
    assert classify_pull("R", Decimal("100"), Decimal("200")) is None


def test_pull_air_denominator_and_exclusion_counts() -> None:
    rows = (
        _bbe_row(),  # fly ball, usable
        _bbe_row(bb_type="line_drive", at_bat_number="2"),  # usable
        _bbe_row(bb_type="ground_ball", at_bat_number="3"),  # outside denominator
        _bbe_row(bb_type="popup", at_bat_number="4"),  # outside FB+LD
        _bbe_row(stand="", at_bat_number="5"),  # invalid stand, counted
        _bbe_row(hc_x="", hc_y="", at_bat_number="6"),  # unusable coords, counted
    )
    computation = compute_pull_air(rows)
    assert computation.sample_count == 2
    assert dict(computation.exclusions) == {"invalid_stand": 1, "unusable_coordinates": 1}


def test_overall_pull_uses_all_bbe_and_stays_report_only() -> None:
    rows = (
        _bbe_row(),
        _bbe_row(bb_type="ground_ball", at_bat_number="2"),
        _bbe_row(bb_type="popup", at_bat_number="3"),
    )
    overall = compute_overall_pull(rows)
    assert overall.sample_count == 3
    assert any("report" in note for note in overall.notes)


# --------------------------------------------------------------------------
# Pitcher ingredients (audit-only)
# --------------------------------------------------------------------------


def test_pitcher_ingredients_are_transparent_and_composite_free() -> None:
    rows = parse_pitcher_events(fixtures.pitcher_csv(fixtures.default_pitcher_rows()))
    ingredient_rows, exclusions = pitcher_ingredient_rows(rows)

    assert [(row.stand, row.pitch_type) for row in ingredient_rows] == [
        ("L", "CH"),
        ("L", "FF"),
        ("R", "FF"),
        ("R", "SL"),
    ]
    by_key = {(row.stand, row.pitch_type): row for row in ingredient_rows}
    assert by_key[("R", "SL")].two_strike_pitches == 1
    assert by_key[("R", "SL")].putaway_finishes == 1
    assert by_key[("R", "FF")].usage_percent_within_stand == Decimal("50")
    assert dict(exclusions) == {
        "rows_with_invalid_stand": 1,
        "rows_without_pitch_type": 1,
    }

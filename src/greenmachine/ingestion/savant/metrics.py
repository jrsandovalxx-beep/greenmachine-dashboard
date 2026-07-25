"""Event-derived metric computation over eligible batter rows. Decimal only.

Every computation here implements a specification-owned definition frozen by
Product Owner ruling for the GM-020 slice (MODEL_SPEC §9.2 and the GM-020
rulings) — never an invented scoring threshold:

* exit velocity — mean ``launch_speed`` over BBE rows with a measured value;
* barrel rate — the provider's official barrel bucket, ``launch_speed_angle == "6"``,
  over BBE rows with a valid classification (the dynamic boundary is never
  recreated for behavior);
* hard-hit rate — ``launch_speed >= 95`` over BBE rows with a measured value;
* sweet-spot rate — ``8 <= launch_angle <= 32`` (inclusive, via the frozen
  inclusive-range helper) over BBE rows with a measured value;
* bat speed — mean tracked ``bat_speed``; no imputation;
* Ideal Attack Angle % — ``5 <= attack_angle <= 20`` (inclusive) over **all**
  valid rows carrying ``attack_angle`` (swing-level, not BBE-only) — the
  event-derived measurement, never the official published aggregate;
* Pull Air % — frozen initial denominator ``bb_type in {fly_ball, line_drive}``
  with valid row-level ``stand`` and usable coordinates, classified by the exact
  Decimal geometry ``pull_side_x >= tan(15 degrees) * y``. Fly-only and
  fly+line+popup remain audit-only alternatives; Overall Pull % is report-only.

All arithmetic runs through the frozen GM-005 numeric helpers under the
project Decimal context; no float participates anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from greenmachine.common.numeric import (
    add,
    decimal_from,
    divide,
    in_inclusive_range,
    multiply,
    percentage,
    subtract,
)

from ..errors import IngestionModelError
from ..models import BatterEventRecord, PitcherEventRecord

__all__ = [
    "BARREL_BUCKET",
    "HARD_HIT_MINIMUM_MPH",
    "HOME_PLATE_X",
    "HOME_PLATE_Y",
    "IDEAL_ATTACK_ANGLE_HIGH",
    "IDEAL_ATTACK_ANGLE_LOW",
    "PITCHER_PUTAWAY_EVENTS",
    "PULL_AIR_DENOMINATOR_BB_TYPES",
    "SWEET_SPOT_HIGH",
    "SWEET_SPOT_LOW",
    "TAN_15_DEGREES",
    "MetricComputation",
    "PitcherIngredientRow",
    "PullAudit",
    "classify_pull",
    "compute_barrel_rate",
    "compute_bat_speed",
    "compute_exit_velocity",
    "compute_hard_hit_rate",
    "compute_ideal_attack_angle",
    "compute_overall_pull",
    "compute_pull_air",
    "compute_pull_audit",
    "compute_sweet_spot_rate",
    "pitcher_ingredient_rows",
]

# Specification-owned constants (Product Owner rulings 6 and 10). Exact Decimal.
TAN_15_DEGREES = Decimal("0.26794919243112270647")
HOME_PLATE_X = Decimal("125.42")
HOME_PLATE_Y = Decimal("198.27")
HARD_HIT_MINIMUM_MPH = Decimal("95")
SWEET_SPOT_LOW = Decimal("8")
SWEET_SPOT_HIGH = Decimal("32")
IDEAL_ATTACK_ANGLE_LOW = Decimal("5")
IDEAL_ATTACK_ANGLE_HIGH = Decimal("20")
BARREL_BUCKET = "6"
PULL_AIR_DENOMINATOR_BB_TYPES = frozenset({"fly_ball", "line_drive"})
_FLY_ONLY = frozenset({"fly_ball"})
_FLY_LINE_POPUP = frozenset({"fly_ball", "line_drive", "popup"})
_VALID_STANDS = frozenset({"R", "L"})
PITCHER_PUTAWAY_EVENTS = frozenset({"strikeout", "strikeout_double_play"})


@dataclass(frozen=True, slots=True)
class MetricComputation:
    """One computed metric: exact value, counts, and every exclusion."""

    name: str
    value: Decimal | None
    numerator: int | None
    sample_count: int
    unit: str
    exclusions: tuple[tuple[str, int], ...]
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.value is not None and not isinstance(self.value, Decimal):
            raise IngestionModelError("MetricComputation.value must be Decimal or None")
        if isinstance(self.sample_count, bool) or not isinstance(self.sample_count, int):
            raise IngestionModelError("MetricComputation.sample_count must be an int")
        if self.sample_count < 0:
            raise IngestionModelError("MetricComputation.sample_count must be >= 0")
        # A value exists exactly when the denominator is nonempty, and vice
        # versa: no metric here maps an empty denominator to zero.
        if (self.value is None) != (self.sample_count == 0):
            raise IngestionModelError(
                f"MetricComputation '{self.name}' must carry a value exactly when its "
                f"sample_count is nonzero (value={'set' if self.value is not None else 'None'}, "
                f"sample_count={self.sample_count})"
            )


def _bbe(rows: tuple[BatterEventRecord, ...]) -> tuple[BatterEventRecord, ...]:
    return tuple(row for row in rows if row.bb_type is not None)


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    return divide(add(*values), decimal_from(len(values)))


def compute_exit_velocity(rows: tuple[BatterEventRecord, ...]) -> MetricComputation:
    bbe = _bbe(rows)
    measured = tuple(row.launch_speed for row in bbe if row.launch_speed is not None)
    unmeasured = len(bbe) - len(measured)
    return MetricComputation(
        name="exit_velocity_mean",
        value=_mean(measured) if measured else None,
        numerator=None,
        sample_count=len(measured),
        unit="mph",
        exclusions=(("bbe_without_measured_launch_speed", unmeasured),),
        notes=("mean launch_speed over batted-ball events with a measured launch_speed",),
    )


def compute_barrel_rate(rows: tuple[BatterEventRecord, ...]) -> MetricComputation:
    bbe = _bbe(rows)
    classified = tuple(row for row in bbe if row.launch_speed_angle is not None)
    barrels = sum(1 for row in classified if row.launch_speed_angle == BARREL_BUCKET)
    return MetricComputation(
        name="barrel_rate",
        value=(
            percentage(decimal_from(barrels), decimal_from(len(classified))) if classified else None
        ),
        numerator=barrels,
        sample_count=len(classified),
        unit="percent",
        exclusions=(("bbe_without_launch_speed_angle", len(bbe) - len(classified)),),
        notes=(
            "official provider barrel bucket: launch_speed_angle == '6'; the dynamic "
            "barrel boundary is never recreated",
        ),
    )


def compute_hard_hit_rate(rows: tuple[BatterEventRecord, ...]) -> MetricComputation:
    bbe = _bbe(rows)
    measured = tuple(row.launch_speed for row in bbe if row.launch_speed is not None)
    hard = sum(1 for speed in measured if speed >= HARD_HIT_MINIMUM_MPH)
    return MetricComputation(
        name="hard_hit_rate",
        value=(percentage(decimal_from(hard), decimal_from(len(measured))) if measured else None),
        numerator=hard,
        sample_count=len(measured),
        unit="percent",
        exclusions=(("bbe_without_measured_launch_speed", len(bbe) - len(measured)),),
        notes=("hard hit: launch_speed >= 95 (specification-owned definition)",),
    )


def compute_sweet_spot_rate(rows: tuple[BatterEventRecord, ...]) -> MetricComputation:
    bbe = _bbe(rows)
    measured = tuple(row.launch_angle for row in bbe if row.launch_angle is not None)
    sweet = sum(
        1 for angle in measured if in_inclusive_range(angle, SWEET_SPOT_LOW, SWEET_SPOT_HIGH)
    )
    return MetricComputation(
        name="sweet_spot_rate",
        value=(percentage(decimal_from(sweet), decimal_from(len(measured))) if measured else None),
        numerator=sweet,
        sample_count=len(measured),
        unit="percent",
        exclusions=(("bbe_without_measured_launch_angle", len(bbe) - len(measured)),),
        notes=("sweet spot: 8 <= launch_angle <= 32, inclusive at both ends",),
    )


def compute_bat_speed(rows: tuple[BatterEventRecord, ...]) -> MetricComputation:
    tracked = tuple(row.bat_speed for row in rows if row.bat_speed is not None)
    return MetricComputation(
        name="bat_speed_mean",
        value=_mean(tracked) if tracked else None,
        numerator=None,
        sample_count=len(tracked),
        unit="mph",
        exclusions=(("rows_without_tracked_bat_speed", len(rows) - len(tracked)),),
        notes=("mean tracked bat_speed; swing-level sample; no imputation",),
    )


def compute_ideal_attack_angle(rows: tuple[BatterEventRecord, ...]) -> MetricComputation:
    tracked = tuple(row.attack_angle for row in rows if row.attack_angle is not None)
    ideal = sum(
        1
        for angle in tracked
        if in_inclusive_range(angle, IDEAL_ATTACK_ANGLE_LOW, IDEAL_ATTACK_ANGLE_HIGH)
    )
    return MetricComputation(
        name="ideal_attack_angle_pct_event_derived",
        value=(percentage(decimal_from(ideal), decimal_from(len(tracked))) if tracked else None),
        numerator=ideal,
        sample_count=len(tracked),
        unit="percent",
        exclusions=(("rows_without_tracked_attack_angle", len(rows) - len(tracked)),),
        notes=(
            "event-derived Ideal Attack Angle %: 5 <= attack_angle <= 20 inclusive, over "
            "all valid rows carrying attack_angle (swing-level, not BBE-only)",
            "not the official published leaderboard aggregate",
        ),
    )


def classify_pull(stand: str, hit_x: Decimal, hit_y: Decimal) -> bool | None:
    """Exact-Decimal pull classification; ``None`` when coordinates are unusable.

    ``y`` is the distance from home plate toward the field
    (``HOME_PLATE_Y - hc_y``); a non-positive ``y`` is unusable. The pull-side
    displacement is toward left field for a right-handed stand and toward
    right field for a left-handed stand. A ball is pulled exactly when
    ``pull_side_x >= TAN_15_DEGREES * y``.
    """
    if stand not in _VALID_STANDS:
        raise IngestionModelError(f"classify_pull requires stand 'R' or 'L', got {stand!r}")
    y = subtract(HOME_PLATE_Y, hit_y)
    if y <= 0:
        return None
    pull_side_x = subtract(HOME_PLATE_X, hit_x) if stand == "R" else subtract(hit_x, HOME_PLATE_X)
    return pull_side_x >= multiply(TAN_15_DEGREES, y)


def _pull_computation(
    rows: tuple[BatterEventRecord, ...],
    denominator_types: frozenset[str] | None,
    name: str,
    notes: tuple[str, ...],
) -> MetricComputation:
    bbe = _bbe(rows)
    if denominator_types is None:
        candidates = bbe
    else:
        candidates = tuple(row for row in bbe if row.bb_type in denominator_types)

    invalid_stand = 0
    unusable_coordinates = 0
    pulled = 0
    eligible = 0
    for row in candidates:
        stand = row.stand
        if stand is None or stand not in _VALID_STANDS:
            invalid_stand += 1
            continue
        if row.hit_x is None or row.hit_y is None:
            unusable_coordinates += 1
            continue
        classification = classify_pull(stand, row.hit_x, row.hit_y)
        if classification is None:
            unusable_coordinates += 1
            continue
        eligible += 1
        if classification:
            pulled += 1

    return MetricComputation(
        name=name,
        value=(percentage(decimal_from(pulled), decimal_from(eligible)) if eligible else None),
        numerator=pulled,
        sample_count=eligible,
        unit="percent",
        exclusions=(
            ("invalid_stand", invalid_stand),
            ("unusable_coordinates", unusable_coordinates),
        ),
        notes=notes,
    )


@dataclass(frozen=True, slots=True)
class PullAudit:
    """The frozen Pull Air % plus the audit-only alternatives and Overall Pull %.

    Only ``pull_air`` may reach an ``InputSnapshot``; the alternatives and
    Overall Pull % are report/audit-only by Product Owner ruling.
    """

    pull_air: MetricComputation
    alternative_fly_only: MetricComputation
    alternative_fly_line_popup: MetricComputation
    overall_pull: MetricComputation


def compute_pull_air(rows: tuple[BatterEventRecord, ...]) -> MetricComputation:
    return _pull_computation(
        rows,
        PULL_AIR_DENOMINATOR_BB_TYPES,
        "pull_air_rate",
        (
            "frozen GM-020 denominator: bb_type in {fly_ball, line_drive} with valid "
            "row-level stand and usable coordinates",
            "pulled: pull_side_x >= tan(15 degrees) * y, exact Decimal geometry",
        ),
    )


def compute_overall_pull(rows: tuple[BatterEventRecord, ...]) -> MetricComputation:
    return _pull_computation(
        rows,
        None,
        "overall_pull_rate",
        (
            "report/audit-only: never enters an InputSnapshot, never scored",
            "denominator: all eligible BBE with valid row-level stand and usable coordinates",
        ),
    )


def compute_pull_audit(rows: tuple[BatterEventRecord, ...]) -> PullAudit:
    return PullAudit(
        pull_air=compute_pull_air(rows),
        alternative_fly_only=_pull_computation(
            rows, _FLY_ONLY, "pull_air_rate_fly_only", ("audit-only alternative denominator",)
        ),
        alternative_fly_line_popup=_pull_computation(
            rows,
            _FLY_LINE_POPUP,
            "pull_air_rate_fly_line_popup",
            ("audit-only alternative denominator",),
        ),
        overall_pull=compute_overall_pull(rows),
    )


# --------------------------------------------------------------------------
# Pitcher ingredients (audit-only: Q15/Q16 formulas remain undefined)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PitcherIngredientRow:
    """One transparent (stand, pitch_type) ingredient row. No composite value."""

    stand: str
    pitch_type: str
    pitches: int
    usage_percent_within_stand: Decimal
    two_strike_pitches: int
    putaway_finishes: int


def pitcher_ingredient_rows(
    rows: tuple[PitcherEventRecord, ...],
) -> tuple[tuple[PitcherIngredientRow, ...], tuple[tuple[str, int], ...]]:
    """Raw pitch-mix and put-away ingredients per (stand, pitch_type).

    Returns the sorted ingredient rows and the exclusion counts (rows missing
    a stand or a pitch type). Usage is within the batter-side denominator per
    Product Owner ruling 12.1's shape — but no threshold, grouping, or
    composite is applied: Q15/Q16 remain undefined.
    """
    excluded_missing_stand = 0
    excluded_missing_pitch_type = 0
    per_stand_totals: dict[str, int] = {}
    per_cell: dict[tuple[str, str], dict[str, int]] = {}

    for row in rows:
        stand = row.stand
        if stand is None or stand not in _VALID_STANDS:
            excluded_missing_stand += 1
            continue
        if row.pitch_type is None:
            excluded_missing_pitch_type += 1
            continue
        per_stand_totals[stand] = per_stand_totals.get(stand, 0) + 1
        cell = per_cell.setdefault(
            (stand, row.pitch_type),
            {"pitches": 0, "two_strike": 0, "putaway": 0},
        )
        cell["pitches"] += 1
        if row.strikes == 2:
            cell["two_strike"] += 1
        if row.events in PITCHER_PUTAWAY_EVENTS:
            cell["putaway"] += 1

    ingredient_rows = tuple(
        PitcherIngredientRow(
            stand=stand,
            pitch_type=pitch_type,
            pitches=cell["pitches"],
            usage_percent_within_stand=percentage(
                decimal_from(cell["pitches"]), decimal_from(per_stand_totals[stand])
            ),
            two_strike_pitches=cell["two_strike"],
            putaway_finishes=cell["putaway"],
        )
        for (stand, pitch_type), cell in sorted(per_cell.items())
    )
    exclusions = (
        ("rows_with_invalid_stand", excluded_missing_stand),
        ("rows_without_pitch_type", excluded_missing_pitch_type),
    )
    return ingredient_rows, exclusions

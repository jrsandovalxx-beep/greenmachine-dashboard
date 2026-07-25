"""Display formatting for the GM-030 dashboard.

Presentation only: exact-Decimal display rounding (never floats, never before
any computation — nothing here computes), stable labels, and the frozen
**data-status** color policy. Colors communicate data state, not performance:
no production threshold exists (Q11 through Q14 are open), so no value
comparison of any kind happens in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from .dashboard_models import DataStatus

__all__ = [
    "COLOR_LEGEND",
    "ERROR_COLOR",
    "StatusBadge",
    "format_display_value",
    "status_badge",
]


@dataclass(frozen=True, slots=True)
class StatusBadge:
    """Color + icon + text label, so meaning never relies on color alone."""

    color: str
    icon: str
    label: str


# The frozen GM-030 data-status palette. Deliberately keyed by DataStatus and
# nothing else: a badge cannot depend on a metric's value.
_BADGES: dict[DataStatus, StatusBadge] = {
    DataStatus.PRESENT_SUFFICIENT: StatusBadge(
        color="green", icon="✅", label="present · sufficient sample"
    ),
    DataStatus.PRESENT_INSUFFICIENT: StatusBadge(
        color="yellow", icon="⚠️", label="present · insufficient sample"
    ),
    DataStatus.MISSING: StatusBadge(color="gray", icon="—", label="missing / unavailable"),
    DataStatus.AUDIT_CONTEXT: StatusBadge(color="blue", icon="🔵", label="audit-only context"),
}

ERROR_COLOR = StatusBadge(color="red", icon="❌", label="data / integrity error")

COLOR_LEGEND: tuple[tuple[str, str], ...] = (
    ("green", "present, and sufficient under the archived GM-020 validation-only policy"),
    ("yellow", "present, but the sample is below the validation-only minimum"),
    ("gray", "missing or unavailable"),
    ("blue", "audit-only or contextual — never a scoring input"),
    ("red", "data validation, loading, replay, or integrity error"),
)


def status_badge(status: DataStatus) -> StatusBadge:
    """The badge for a data state. Takes a state — never a value."""
    return _BADGES[status]


def format_display_value(exact: str, unit: str) -> str:
    """One-decimal presentation rendering of an exact Decimal string.

    Presentation rounding only (the exact value stays available on every
    card); ``ROUND_HALF_EVEN`` for consistency with the project numeric
    policy; no float ever participates.
    """
    quantized = Decimal(exact).quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)
    rendered = format(quantized, "f")
    if unit == "%":
        return f"{rendered}%"
    if unit:
        return f"{rendered} {unit}"
    return rendered

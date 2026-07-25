"""GM-030 manual-review dashboard reporting layer.

Read-only view models over approved archived GM-020 runs, plus the
user-entered manual-review worksheet. No scoring engine, no provider client,
no live transport, no persistence; the metric excluded by frozen Product
Owner ruling is simply omitted, and pitcher-specific metrics are deferred to
a later ticket. Streamlit itself is never imported here: the presentation
boundary lives in the repository-root ``streamlit_app.py`` composition root.
"""

from __future__ import annotations

from .dashboard_formatting import (
    COLOR_LEGEND,
    ERROR_COLOR,
    StatusBadge,
    format_display_value,
    status_badge,
)
from .dashboard_loader import (
    PITCHER_ANALYSIS_DEFERRED_NOTE,
    VERIFICATION_SCOPE_NOTE,
    DashboardLoadError,
    RunHandle,
    discover_runs,
    load_dashboard,
)
from .dashboard_models import (
    AuditSection,
    CaptureEntrySummary,
    ComparisonRow,
    DashboardData,
    DataStatus,
    IntegrityStatus,
    MetricCard,
    MetricProvenance,
    MissingComponentNote,
    OverviewHeader,
    PitcherContext,
    ProfileMetrics,
)
from .manual_review import (
    CATEGORIES,
    MANUAL_REVIEW_DISCLAIMER,
    CategorySpec,
    ManualReview,
    ManualReviewError,
    ReviewContext,
    export_review_csv,
    export_review_json,
    tier_for_total,
)

__all__ = [
    "CATEGORIES",
    "COLOR_LEGEND",
    "ERROR_COLOR",
    "MANUAL_REVIEW_DISCLAIMER",
    "PITCHER_ANALYSIS_DEFERRED_NOTE",
    "VERIFICATION_SCOPE_NOTE",
    "AuditSection",
    "CaptureEntrySummary",
    "CategorySpec",
    "ComparisonRow",
    "DashboardData",
    "DashboardLoadError",
    "DataStatus",
    "IntegrityStatus",
    "ManualReview",
    "ManualReviewError",
    "MetricCard",
    "MetricProvenance",
    "MissingComponentNote",
    "OverviewHeader",
    "PitcherContext",
    "ProfileMetrics",
    "ReviewContext",
    "RunHandle",
    "StatusBadge",
    "discover_runs",
    "export_review_csv",
    "export_review_json",
    "format_display_value",
    "load_dashboard",
    "status_badge",
    "tier_for_total",
]

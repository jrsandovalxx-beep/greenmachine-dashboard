"""Metric observations: a present measured value, or a typed missing state.

``MODEL_SPEC.md`` §8 keeps three states strictly distinct — *zero*, *insufficient
sample*, and *missing* — and requires that insufficiency and missingness be
different types. This module realises that with two records:

* :class:`MetricObservation` — a **present** value with full provenance and a
  :class:`SampleStatus`. An insufficient sample is still a present, scored value
  and lives here, carrying ``SampleStatus.INSUFFICIENT``.
* :class:`MissingObservation` — a **typed missing** state carrying a
  :class:`MissingReason` and no value at all.

Splitting them makes the illegal states unrepresentable: a present value can
never lack a sample status, and a missing one can never smuggle in a raw value or
a ``None`` standing in for a number.

``measurement_id`` is a single optional slot, and the component decides what
belongs in it: ``attack_angle_quality`` requires exactly one
:class:`MeasurementId`, every other component requires ``None``. Because the slot
holds at most one value, an observation can never carry two measurements for one
component.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from ._guards import (
    ensure_aware_datetime,
    ensure_finite_decimal,
    ensure_instance,
    ensure_measurement_matches_component,
    ensure_non_empty_text,
    ensure_non_negative_int,
    ensure_optional_instance,
    ensure_ordered,
)
from .enums import (
    AcquisitionMethod,
    ComponentId,
    MeasurementId,
    MissingReason,
    ProviderId,
    SampleStatus,
    SampleType,
    WindowProfile,
)
from .errors import DomainValidationError
from .values import DataCoverage, FallbackRecord, SourceCaptureId

__all__ = ["MetricObservation", "MissingObservation"]


@dataclass(frozen=True, slots=True)
class MetricObservation:
    """A present, measured value for one component under one window profile.

    Preserves every provenance field required by ``MODEL_SPEC.md`` §8.4 that
    describes the *measured input* (the bucket configuration used and the resolved
    points are scoring artefacts, recorded on the bucket result at grading time,
    not on the raw observation). Every field below is required at construction;
    only ``fallback_used`` is optional, and only because a fallback does not always
    occur.

    ``raw_value`` is a finite ``Decimal`` — never ``NaN``, never a float, never a
    zero standing in for missing data.

    ``sample_status`` must agree with the counts it describes: at or above the
    minimum is ``SUFFICIENT``, below it is ``INSUFFICIENT``. A mislabelled
    observation is rejected rather than carried into the audit trail. An
    insufficient observation remains perfectly constructable and scoreable — the
    minimum governs the label, never whether the value may exist — and it is never
    converted into a missing one.
    """

    component_id: ComponentId
    measurement_id: MeasurementId | None
    window_profile: WindowProfile
    window_start: datetime
    window_end: datetime
    as_of: datetime
    raw_value: Decimal
    unit: str
    sample_type: SampleType
    sample_count: int
    minimum_sample_required: int
    sample_status: SampleStatus
    data_coverage: DataCoverage
    provider_id: ProviderId
    acquisition_method: AcquisitionMethod
    source_as_of: datetime
    retrieved_at: datetime
    source_capture_id: SourceCaptureId
    fallback_used: FallbackRecord | None = None

    def __post_init__(self) -> None:
        ensure_measurement_matches_component(
            self.component_id, self.measurement_id, "MetricObservation"
        )
        ensure_instance(self.window_profile, WindowProfile, "MetricObservation.window_profile")
        ensure_ordered(
            self.window_start,
            self.window_end,
            "MetricObservation.window_start",
            "MetricObservation.window_end",
        )
        ensure_aware_datetime(self.as_of, "MetricObservation.as_of")
        ensure_aware_datetime(self.source_as_of, "MetricObservation.source_as_of")
        ensure_aware_datetime(self.retrieved_at, "MetricObservation.retrieved_at")
        ensure_finite_decimal(self.raw_value, "MetricObservation.raw_value")
        ensure_non_empty_text(self.unit, "MetricObservation.unit")
        ensure_instance(self.sample_type, SampleType, "MetricObservation.sample_type")
        sample_count = ensure_non_negative_int(self.sample_count, "MetricObservation.sample_count")
        minimum = ensure_non_negative_int(
            self.minimum_sample_required, "MetricObservation.minimum_sample_required"
        )
        status = ensure_instance(
            self.sample_status, SampleStatus, "MetricObservation.sample_status"
        )
        coverage = ensure_instance(
            self.data_coverage, DataCoverage, "MetricObservation.data_coverage"
        )
        ensure_instance(self.provider_id, ProviderId, "MetricObservation.provider_id")
        method = ensure_instance(
            self.acquisition_method, AcquisitionMethod, "MetricObservation.acquisition_method"
        )
        ensure_instance(
            self.source_capture_id, SourceCaptureId, "MetricObservation.source_capture_id"
        )
        fallback = ensure_optional_instance(
            self.fallback_used, FallbackRecord, "MetricObservation.fallback_used"
        )

        expected_status = (
            SampleStatus.SUFFICIENT if sample_count >= minimum else SampleStatus.INSUFFICIENT
        )
        if status is not expected_status:
            raise DomainValidationError(
                f"MetricObservation.sample_status must be '{expected_status.value}' when "
                f"sample_count ({sample_count}) is "
                f"{'>=' if sample_count >= minimum else '<'} "
                f"minimum_sample_required ({minimum}), got '{status.value}'"
            )

        if coverage.sample_count != sample_count:
            raise DomainValidationError(
                f"MetricObservation.data_coverage.sample_count ({coverage.sample_count}) "
                f"must equal MetricObservation.sample_count ({sample_count})"
            )

        if fallback is not None and fallback.selected_method is not method:
            raise DomainValidationError(
                f"MetricObservation.fallback_used.selected_method "
                f"('{fallback.selected_method.value}') must equal "
                f"MetricObservation.acquisition_method ('{method.value}')"
            )


@dataclass(frozen=True, slots=True)
class MissingObservation:
    """A typed missing state for one component under one window profile.

    Carries a :class:`MissingReason` and the identifying/coverage context, and no
    value. ``INSUFFICIENT`` is never a valid reason here — insufficiency is a
    present-value status, not a missing reason (``MODEL_SPEC.md`` §8.2).
    ``acquisition_method`` is absent by design: unavailability is not an
    acquisition method (§10). ``provider_id`` may be ``None`` when no source was
    reached at all.
    """

    component_id: ComponentId
    measurement_id: MeasurementId | None
    window_profile: WindowProfile
    window_start: datetime
    window_end: datetime
    as_of: datetime
    sample_type: SampleType
    provider_id: ProviderId | None
    source_capture_id: SourceCaptureId
    missing_reason: MissingReason
    data_coverage: DataCoverage

    def __post_init__(self) -> None:
        ensure_measurement_matches_component(
            self.component_id, self.measurement_id, "MissingObservation"
        )
        ensure_instance(self.window_profile, WindowProfile, "MissingObservation.window_profile")
        ensure_ordered(
            self.window_start,
            self.window_end,
            "MissingObservation.window_start",
            "MissingObservation.window_end",
        )
        ensure_aware_datetime(self.as_of, "MissingObservation.as_of")
        ensure_instance(self.sample_type, SampleType, "MissingObservation.sample_type")
        ensure_optional_instance(self.provider_id, ProviderId, "MissingObservation.provider_id")
        ensure_instance(
            self.source_capture_id, SourceCaptureId, "MissingObservation.source_capture_id"
        )
        ensure_instance(self.missing_reason, MissingReason, "MissingObservation.missing_reason")
        ensure_instance(self.data_coverage, DataCoverage, "MissingObservation.data_coverage")

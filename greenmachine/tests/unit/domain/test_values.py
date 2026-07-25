"""Value objects: identifier wrappers, coverage, and fallback provenance."""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest
from domain_builders import WINDOW_END, WINDOW_START, make_coverage

from greenmachine.domain import (
    AcquisitionMethod,
    CoverageStatus,
    CoverageWindow,
    DataCoverage,
    DomainValidationError,
    EvaluationId,
    FallbackRecord,
    GameId,
    MethodIneligibility,
    PlayerId,
    SnapshotId,
    SourceCaptureId,
    VenueId,
)

ID_TYPES = (GameId, PlayerId, VenueId, SnapshotId, SourceCaptureId, EvaluationId)


# --------------------------------------------------------------------------
# Identifier wrappers
# --------------------------------------------------------------------------


@pytest.mark.parametrize("id_type", ID_TYPES, ids=lambda t: t.__name__)
def test_identifier_accepts_a_non_empty_value(id_type: type) -> None:
    identifier = id_type("synthetic-0001")

    assert identifier.value == "synthetic-0001"


@pytest.mark.parametrize("id_type", ID_TYPES, ids=lambda t: t.__name__)
@pytest.mark.parametrize("bad", ["", "   ", "\t\n"])
def test_identifier_rejects_empty_or_blank(id_type: type, bad: str) -> None:
    with pytest.raises(DomainValidationError, match=r"non-empty"):
        id_type(bad)


@pytest.mark.parametrize("id_type", ID_TYPES, ids=lambda t: t.__name__)
def test_identifier_is_frozen(id_type: type) -> None:
    identifier = id_type("synthetic-0001")

    with pytest.raises(dataclasses.FrozenInstanceError):
        identifier.value = "mutated"


@pytest.mark.parametrize("id_type", ID_TYPES, ids=lambda t: t.__name__)
def test_identifier_equality_and_hashing_are_by_value(id_type: type) -> None:
    first = id_type("synthetic-0001")
    second = id_type("synthetic-0001")
    other = id_type("synthetic-0002")

    assert first == second
    assert hash(first) == hash(second)
    assert first != other
    assert len({first, second, other}) == 2


@pytest.mark.parametrize("id_type", ID_TYPES, ids=lambda t: t.__name__)
def test_identifier_repr_is_stable(id_type: type) -> None:
    identifier = id_type("synthetic-0001")

    assert repr(identifier) == f"{id_type.__name__}(value='synthetic-0001')"


def test_identifier_types_are_not_interchangeable() -> None:
    """A GameId is not a PlayerId, even with an identical underlying string.

    Distinct wrapper types are what stop a wrong-identifier join (ARCHITECTURE R7).
    """
    assert GameId("same-string") != PlayerId("same-string")
    assert len({GameId("same-string"), PlayerId("same-string")}) == 2


def test_identifier_preserves_the_provider_string_verbatim() -> None:
    """MODEL_SPEC 7.2: the official provider identifier is canonical.

    It is stored exactly as given — not normalised, not re-cased, not regenerated.
    """
    assert GameId("2026-07-15-BOS-NYY-1").value == "2026-07-15-BOS-NYY-1"
    assert GameId(" padded-id ").value == " padded-id "


def test_no_identifier_generates_its_own_value() -> None:
    """Construction only: no factory, no default, no auto-generated id."""
    for id_type in ID_TYPES:
        with pytest.raises(TypeError):
            id_type()


# --------------------------------------------------------------------------
# CoverageWindow / DataCoverage
# --------------------------------------------------------------------------


def test_coverage_window_accepts_ordered_bounds() -> None:
    window = CoverageWindow(WINDOW_START, WINDOW_END)

    assert window.start == WINDOW_START
    assert window.end == WINDOW_END


def test_coverage_window_accepts_a_zero_length_window() -> None:
    """start == end is ordered, so it is valid."""
    window = CoverageWindow(WINDOW_START, WINDOW_START)

    assert window.start == window.end


def test_coverage_window_rejects_reversed_bounds() -> None:
    with pytest.raises(DomainValidationError, match=r"must be <="):
        CoverageWindow(WINDOW_END, WINDOW_START)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (datetime(2026, 7, 8, 16, 30), WINDOW_END),
        (WINDOW_START, datetime(2026, 7, 15, 16, 30)),
    ],
)
def test_coverage_window_rejects_naive_datetimes(start: datetime, end: datetime) -> None:
    with pytest.raises(DomainValidationError, match=r"timezone-aware"):
        CoverageWindow(start, end)


def test_data_coverage_records_a_complete_window() -> None:
    coverage = make_coverage()

    assert coverage.status is CoverageStatus.COMPLETE
    assert coverage.actual == coverage.requested
    assert coverage.source_available is True
    assert coverage.sample_count == 42


def test_data_coverage_represents_absent_actual_coverage() -> None:
    """MODEL_SPEC 11.1: partial or absent coverage stays visible."""
    coverage = make_coverage(actual=None, status=CoverageStatus.NONE, sample_count=0)

    assert coverage.actual is None
    assert coverage.status is CoverageStatus.NONE


def test_data_coverage_rejects_a_negative_sample_count() -> None:
    with pytest.raises(DomainValidationError, match=r"sample_count"):
        make_coverage(sample_count=-1)


def test_data_coverage_is_frozen_and_hashable() -> None:
    coverage = make_coverage()

    with pytest.raises(dataclasses.FrozenInstanceError):
        coverage.sample_count = 99
    assert hash(coverage) == hash(make_coverage())
    assert coverage == make_coverage()


# --------------------------------------------------------------------------
# Fallback provenance
# --------------------------------------------------------------------------


def test_method_ineligibility_requires_a_reason() -> None:
    """MODEL_SPEC 11.2: every fallback records *why* a higher-priority method
    was ineligible, so a backtest stays interpretable."""
    with pytest.raises(DomainValidationError, match=r"reason"):
        MethodIneligibility(AcquisitionMethod.DIRECT_AGGREGATE, "")


def test_fallback_record_requires_the_methods_it_skipped() -> None:
    """A fallback that skipped nothing is not a fallback, so there is no default."""
    with pytest.raises(TypeError):
        FallbackRecord(AcquisitionMethod.EVENT_DERIVED)  # type: ignore[call-arg]


def test_fallback_record_carries_ineligibility_reasons() -> None:
    record = FallbackRecord(
        selected_method=AcquisitionMethod.EVENT_DERIVED,
        higher_priority_ineligible=(
            MethodIneligibility(
                AcquisitionMethod.DIRECT_AGGREGATE,
                "cannot reproduce the historical as_of window",
            ),
            MethodIneligibility(
                AcquisitionMethod.STRUCTURED_EXTRACT,
                "endpoint does not expose the requested window bounds",
            ),
        ),
    )

    assert record.selected_method is AcquisitionMethod.EVENT_DERIVED
    assert len(record.higher_priority_ineligible) == 2
    assert hash(record)


def test_fallback_record_is_frozen() -> None:
    record = FallbackRecord(
        AcquisitionMethod.CONFIGURED_PROXY,
        (MethodIneligibility(AcquisitionMethod.DIRECT_AGGREGATE, "no eligible aggregate"),),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        record.selected_method = AcquisitionMethod.DIRECT_AGGREGATE


def test_data_coverage_requires_every_field() -> None:
    """No silent defaults: each coverage field must be supplied explicitly."""
    for omitted in ("requested", "actual", "status", "source_available", "sample_count"):
        kwargs = {
            "requested": CoverageWindow(WINDOW_START, WINDOW_END),
            "actual": None,
            "status": CoverageStatus.NONE,
            "source_available": False,
            "sample_count": 0,
        }
        del kwargs[omitted]
        with pytest.raises(TypeError):
            DataCoverage(**kwargs)

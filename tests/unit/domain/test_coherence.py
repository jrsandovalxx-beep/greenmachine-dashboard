"""Construction coherence: wrong runtime types and contradictory records.

Domain objects are built from ingestion adapters and deserialized records, so a
wrong type or an internally inconsistent record must fail as a
``DomainValidationError`` naming the field — never as an incidental
``AttributeError``, ``TypeError``, or unhashable-object error.

Every rule here is structural. None of it scores, resolves a bucket, or applies a
baseball threshold; each one only decides whether a record is well-formed.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from domain_builders import (
    START_LOCAL,
    START_UTC,
    WINDOW_END,
    WINDOW_START,
    make_coverage,
    make_fallback,
    make_game_context,
    make_ineligibility,
    make_missing_observation,
    make_observation,
    make_venue,
)

from greenmachine.domain import (
    AcquisitionMethod,
    Batter,
    BucketHit,
    Category,
    CategoryScore,
    ComponentId,
    ComponentScore,
    CoverageStatus,
    CoverageWindow,
    DataCoverage,
    DomainValidationError,
    FallbackRecord,
    MeasurementId,
    MethodIneligibility,
    Pitcher,
    PitcherRole,
    PlayerId,
    SampleStatus,
    ValidationFinding,
    Venue,
)

# --------------------------------------------------------------------------
# Raw values where a typed wrapper or enum is required
# --------------------------------------------------------------------------


def test_batter_rejects_a_raw_string_player_id() -> None:
    with pytest.raises(DomainValidationError, match=r"Batter\.player_id must be PlayerId"):
        Batter(player_id="p", full_name="Name")


def test_pitcher_rejects_a_raw_string_role() -> None:
    with pytest.raises(DomainValidationError, match=r"Pitcher\.role must be PitcherRole"):
        Pitcher(player_id=PlayerId("p"), full_name="Name", role="opener")


def test_pitcher_rejects_a_raw_string_player_id() -> None:
    with pytest.raises(DomainValidationError, match=r"Pitcher\.player_id must be PlayerId"):
        Pitcher(player_id="p", full_name="Name", role=PitcherRole.OPENER)


def test_venue_rejects_a_raw_string_venue_id() -> None:
    with pytest.raises(DomainValidationError, match=r"Venue\.venue_id must be VenueId"):
        Venue(venue_id="venue-id", name="Park", timezone="America/New_York")


def test_observation_rejects_a_raw_string_component_id() -> None:
    with pytest.raises(
        DomainValidationError, match=r"MetricObservation\.component_id must be ComponentId"
    ):
        make_observation(component_id="exit_velocity")


def test_observation_rejects_a_raw_string_sample_type() -> None:
    with pytest.raises(
        DomainValidationError, match=r"MetricObservation\.sample_type must be SampleType"
    ):
        make_observation(sample_type="batted_ball_events")


def test_observation_rejects_a_raw_string_provider_id() -> None:
    with pytest.raises(
        DomainValidationError, match=r"MetricObservation\.provider_id must be ProviderId"
    ):
        make_observation(provider_id="baseball_savant")


def test_observation_rejects_a_raw_string_window_profile() -> None:
    with pytest.raises(
        DomainValidationError, match=r"MetricObservation\.window_profile must be WindowProfile"
    ):
        make_observation(window_profile="RECENT_7D")


def test_data_coverage_rejects_a_raw_string_requested_window() -> None:
    with pytest.raises(
        DomainValidationError, match=r"DataCoverage\.requested must be CoverageWindow"
    ):
        make_coverage(requested="not-a-window")


def test_data_coverage_rejects_a_raw_string_status() -> None:
    with pytest.raises(DomainValidationError, match=r"DataCoverage\.status must be CoverageStatus"):
        make_coverage(status="COMPLETE")


def test_data_coverage_rejects_a_non_bool_source_available() -> None:
    with pytest.raises(DomainValidationError, match=r"DataCoverage\.source_available must be bool"):
        make_coverage(source_available="yes")


def test_observation_rejects_a_raw_dict_data_coverage() -> None:
    with pytest.raises(
        DomainValidationError, match=r"MetricObservation\.data_coverage must be DataCoverage"
    ):
        make_observation(data_coverage={"sample_count": 42})


def test_category_score_rejects_a_raw_string_category() -> None:
    with pytest.raises(DomainValidationError, match=r"CategoryScore\.category must be Category"):
        CategoryScore(category="form", points_awarded=Decimal("1"))


def test_validation_finding_rejects_a_raw_string_input_id() -> None:
    with pytest.raises(
        DomainValidationError, match=r"ValidationFinding\.input_id must be ValidationInputId"
    ):
        ValidationFinding(input_id="sample_warnings", message="warned")


def test_bucket_hit_rejects_a_non_bool_terminal_flag() -> None:
    with pytest.raises(DomainValidationError, match=r"BucketHit\.is_terminal must be bool"):
        BucketHit(Decimal("10"), Decimal("20"), "no", Decimal("1"))


# --------------------------------------------------------------------------
# Tuple fields must stay hashable
# --------------------------------------------------------------------------


def test_category_score_rejects_a_list_of_components() -> None:
    """A list would make the record unhashable; it is refused, not converted."""
    with pytest.raises(
        DomainValidationError, match=r"CategoryScore\.component_scores must be a tuple"
    ):
        CategoryScore(category=Category.FORM, points_awarded=Decimal("1"), component_scores=[])


def test_fallback_record_rejects_a_list_of_ineligibilities() -> None:
    with pytest.raises(
        DomainValidationError,
        match=r"FallbackRecord\.higher_priority_ineligible must be a tuple",
    ):
        FallbackRecord(
            selected_method=AcquisitionMethod.EVENT_DERIVED, higher_priority_ineligible=[]
        )


def test_category_score_rejects_a_wrong_tuple_member_type() -> None:
    with pytest.raises(
        DomainValidationError,
        match=r"CategoryScore\.component_scores\[0\] must be ComponentScore",
    ):
        CategoryScore(Category.FORM, Decimal("1"), ("not-a-component-score",))


def test_fallback_record_rejects_a_wrong_tuple_member_type() -> None:
    with pytest.raises(
        DomainValidationError,
        match=r"FallbackRecord\.higher_priority_ineligible\[0\] must be MethodIneligibility",
    ):
        FallbackRecord(AcquisitionMethod.EVENT_DERIVED, (AcquisitionMethod.DIRECT_AGGREGATE,))


def test_a_valid_tuple_keeps_the_record_hashable() -> None:
    score = CategoryScore(
        Category.POWER_PROFILE,
        Decimal("1"),
        (ComponentScore(ComponentId.EXIT_VELOCITY, None, Decimal("1")),),
    )

    assert isinstance(hash(score), int)


# --------------------------------------------------------------------------
# Component / measurement relation (MODEL_SPEC 9.1)
# --------------------------------------------------------------------------


def test_attack_angle_component_requires_a_measurement_on_an_observation() -> None:
    with pytest.raises(
        DomainValidationError,
        match=r"MetricObservation\.measurement_id must be a MeasurementId",
    ):
        make_observation(component_id=ComponentId.ATTACK_ANGLE_QUALITY, measurement_id=None)


def test_non_attack_component_rejects_a_measurement_on_an_observation() -> None:
    with pytest.raises(
        DomainValidationError, match=r"MetricObservation\.measurement_id must be None"
    ):
        make_observation(
            component_id=ComponentId.EXIT_VELOCITY,
            measurement_id=MeasurementId.IDEAL_ATTACK_ANGLE_PCT,
        )


def test_attack_angle_component_requires_a_measurement_on_a_missing_observation() -> None:
    with pytest.raises(
        DomainValidationError,
        match=r"MissingObservation\.measurement_id must be a MeasurementId",
    ):
        make_missing_observation(component_id=ComponentId.ATTACK_ANGLE_QUALITY, measurement_id=None)


def test_non_attack_component_rejects_a_measurement_on_a_missing_observation() -> None:
    with pytest.raises(
        DomainValidationError, match=r"MissingObservation\.measurement_id must be None"
    ):
        make_missing_observation(
            component_id=ComponentId.BAT_SPEED,
            measurement_id=MeasurementId.ATTACK_ANGLE_THRESHOLD_PROXY,
        )


def test_attack_angle_component_requires_a_measurement_on_a_component_score() -> None:
    with pytest.raises(
        DomainValidationError, match=r"ComponentScore\.measurement_id must be a MeasurementId"
    ):
        ComponentScore(ComponentId.ATTACK_ANGLE_QUALITY, None, Decimal("1"))


def test_non_attack_component_rejects_a_measurement_on_a_component_score() -> None:
    with pytest.raises(DomainValidationError, match=r"ComponentScore\.measurement_id must be None"):
        ComponentScore(ComponentId.WEATHER, MeasurementId.IDEAL_ATTACK_ANGLE_PCT, Decimal("1"))


@pytest.mark.parametrize(
    "measurement",
    [MeasurementId.IDEAL_ATTACK_ANGLE_PCT, MeasurementId.ATTACK_ANGLE_THRESHOLD_PROXY],
)
def test_either_attack_angle_measurement_satisfies_the_component(
    measurement: MeasurementId,
) -> None:
    score = ComponentScore(ComponentId.ATTACK_ANGLE_QUALITY, measurement, Decimal("1"))

    assert score.measurement_id is measurement


# --------------------------------------------------------------------------
# Sample consistency (MODEL_SPEC 8.2)
# --------------------------------------------------------------------------


def test_sufficient_label_below_the_minimum_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"sample_status must be 'INSUFFICIENT'"):
        make_observation(
            sample_count=2, minimum_sample_required=7, sample_status=SampleStatus.SUFFICIENT
        )


def test_insufficient_label_at_or_above_the_minimum_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match=r"sample_status must be 'SUFFICIENT'"):
        make_observation(
            sample_count=7, minimum_sample_required=7, sample_status=SampleStatus.INSUFFICIENT
        )


def test_an_insufficient_observation_remains_constructable() -> None:
    """S3a: a value below its minimum is still scored, never converted to missing."""
    observation = make_observation(sample_count=2, minimum_sample_required=7)

    assert observation.sample_status is SampleStatus.INSUFFICIENT
    assert observation.raw_value == Decimal("12.3456")


def test_sample_count_equal_to_the_minimum_is_sufficient() -> None:
    observation = make_observation(sample_count=7, minimum_sample_required=7)

    assert observation.sample_status is SampleStatus.SUFFICIENT


def test_observation_and_coverage_sample_counts_must_agree() -> None:
    with pytest.raises(DomainValidationError, match=r"data_coverage\.sample_count .* must equal"):
        make_observation(sample_count=42, data_coverage=make_coverage(sample_count=41))


# --------------------------------------------------------------------------
# Data coverage coherence (MODEL_SPEC 11.1)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", [CoverageStatus.COMPLETE, CoverageStatus.PARTIAL])
def test_covered_status_requires_an_actual_window(status: CoverageStatus) -> None:
    with pytest.raises(
        DomainValidationError, match=r"DataCoverage\.actual must be a CoverageWindow"
    ):
        make_coverage(status=status, actual=None)


@pytest.mark.parametrize("status", [CoverageStatus.COMPLETE, CoverageStatus.PARTIAL])
def test_unavailable_source_cannot_claim_coverage(status: CoverageStatus) -> None:
    """A source that was never reached cannot report COMPLETE or PARTIAL coverage."""
    with pytest.raises(
        DomainValidationError,
        match=r"DataCoverage\.status must be 'NONE' when source_available is False",
    ):
        make_coverage(status=status, source_available=False)


def test_unavailable_source_rejects_an_actual_window() -> None:
    with pytest.raises(
        DomainValidationError,
        match=r"DataCoverage\.actual must be None when source_available is False",
    ):
        make_coverage(status=CoverageStatus.NONE, source_available=False, sample_count=0)


def test_unavailable_source_rejects_a_positive_sample_count() -> None:
    with pytest.raises(
        DomainValidationError,
        match=r"DataCoverage\.sample_count must be 0 when source_available is False",
    ):
        make_coverage(
            status=CoverageStatus.NONE, actual=None, source_available=False, sample_count=5
        )


def test_none_status_rejects_a_positive_sample_count() -> None:
    with pytest.raises(
        DomainValidationError, match=r"DataCoverage\.sample_count must be 0 when status is 'NONE'"
    ):
        make_coverage(status=CoverageStatus.NONE, actual=None, sample_count=5)


def test_none_status_rejects_an_actual_window() -> None:
    with pytest.raises(
        DomainValidationError, match=r"DataCoverage\.actual must be None when status is 'NONE'"
    ):
        make_coverage(status=CoverageStatus.NONE, sample_count=0)


def test_available_source_may_still_report_no_coverage() -> None:
    """A reachable source that returned no eligible events is NONE, not a failure."""
    coverage = DataCoverage(
        requested=CoverageWindow(WINDOW_START, WINDOW_END),
        actual=None,
        status=CoverageStatus.NONE,
        source_available=True,
        sample_count=0,
    )

    assert coverage.status is CoverageStatus.NONE
    assert coverage.source_available is True


def test_actual_coverage_must_start_within_the_requested_window() -> None:
    earlier = WINDOW_START.replace(year=2020)

    with pytest.raises(DomainValidationError, match=r"DataCoverage\.actual\.start"):
        make_coverage(actual=CoverageWindow(earlier, WINDOW_END))


def test_actual_coverage_must_end_within_the_requested_window() -> None:
    later = WINDOW_END.replace(year=2030)

    with pytest.raises(DomainValidationError, match=r"DataCoverage\.actual\.end"):
        make_coverage(actual=CoverageWindow(WINDOW_START, later))


def test_partial_coverage_is_representable_and_visible() -> None:
    """MODEL_SPEC 11.1: partial coverage must never be dressed up as complete."""
    coverage = make_coverage(
        status=CoverageStatus.PARTIAL,
        actual=CoverageWindow(WINDOW_START, WINDOW_END.replace(day=10)),
    )

    assert coverage.status is CoverageStatus.PARTIAL
    assert coverage.actual is not None
    assert coverage.actual.end < coverage.requested.end


# --------------------------------------------------------------------------
# Fallback coherence (MODEL_SPEC 8.4, 11.2)
# --------------------------------------------------------------------------


def test_fallback_requires_at_least_one_ineligible_method() -> None:
    with pytest.raises(
        DomainValidationError, match=r"must record at least one ineligible higher-priority method"
    ):
        FallbackRecord(AcquisitionMethod.EVENT_DERIVED, ())


def test_fallback_rejects_duplicate_skipped_methods() -> None:
    with pytest.raises(
        DomainValidationError,
        match=r"FallbackRecord\.higher_priority_ineligible contains a duplicate",
    ):
        FallbackRecord(
            AcquisitionMethod.EVENT_DERIVED,
            (
                make_ineligibility(method=AcquisitionMethod.DIRECT_AGGREGATE),
                make_ineligibility(method=AcquisitionMethod.DIRECT_AGGREGATE, reason="again"),
            ),
        )


def test_fallback_rejects_selected_method_among_the_skipped() -> None:
    with pytest.raises(
        DomainValidationError, match=r"must not also appear in higher_priority_ineligible"
    ):
        FallbackRecord(
            AcquisitionMethod.DIRECT_AGGREGATE,
            (make_ineligibility(method=AcquisitionMethod.DIRECT_AGGREGATE),),
        )


def test_method_ineligibility_rejects_a_raw_string_method() -> None:
    with pytest.raises(
        DomainValidationError, match=r"MethodIneligibility\.method must be AcquisitionMethod"
    ):
        MethodIneligibility(method="direct_aggregate", reason="ineligible")


def test_observation_fallback_method_must_match_acquisition_method() -> None:
    with pytest.raises(
        DomainValidationError,
        match=r"fallback_used\.selected_method .* must equal",
    ):
        make_observation(
            acquisition_method=AcquisitionMethod.DIRECT_AGGREGATE,
            fallback_used=make_fallback(selected_method=AcquisitionMethod.EVENT_DERIVED),
        )


def test_observation_accepts_a_consistent_fallback() -> None:
    observation = make_observation(
        acquisition_method=AcquisitionMethod.EVENT_DERIVED, fallback_used=make_fallback()
    )

    assert observation.fallback_used is not None
    assert observation.fallback_used.selected_method is AcquisitionMethod.EVENT_DERIVED


# --------------------------------------------------------------------------
# BucketHit terminal coherence (MODEL_SPEC 4.1)
# --------------------------------------------------------------------------


def test_terminal_bucket_cannot_declare_an_upper_bound() -> None:
    with pytest.raises(DomainValidationError, match=r"is_terminal must be False"):
        BucketHit(Decimal("10"), Decimal("20"), True, Decimal("1"))


def test_non_terminal_bucket_requires_an_upper_bound() -> None:
    with pytest.raises(DomainValidationError, match=r"is_terminal must be True"):
        BucketHit(Decimal("10"), None, False, Decimal("1"))


def test_non_terminal_bounds_must_be_strictly_increasing() -> None:
    with pytest.raises(DomainValidationError, match=r"must be < upper_bound"):
        BucketHit(Decimal("20"), Decimal("20"), False, Decimal("1"))


def test_terminal_bucket_constructs_with_no_upper_bound() -> None:
    hit = BucketHit(Decimal("10"), None, True, Decimal("1"))

    assert hit.is_terminal is True
    assert hit.upper_bound is None


# --------------------------------------------------------------------------
# Game time coherence (MODEL_SPEC 7.2)
# --------------------------------------------------------------------------


def test_game_context_rejects_mismatched_instants() -> None:
    with pytest.raises(DomainValidationError, match=r"must be the same instant"):
        make_game_context(venue_local_scheduled_time=START_LOCAL.replace(hour=18))


def test_game_context_accepts_the_same_instant_in_two_zones() -> None:
    context = make_game_context()

    assert context.venue_local_scheduled_time.utctimetuple() == START_UTC.utctimetuple()
    assert context.scheduled_start_utc == START_UTC


def test_game_context_rejects_a_raw_string_venue() -> None:
    with pytest.raises(DomainValidationError, match=r"GameContext\.venue must be Venue"):
        make_game_context(venue="Synthetic Park")


def test_game_context_rejects_a_raw_string_game_id() -> None:
    with pytest.raises(DomainValidationError, match=r"GameContext\.game_id must be GameId"):
        make_game_context(game_id="official-game-000123")


def test_game_context_preserves_both_supplied_times() -> None:
    """Neither value is derived from nor replaced by the other."""
    context = make_game_context()

    assert context.scheduled_start_utc is START_UTC
    assert context.venue_local_scheduled_time is START_LOCAL
    assert context.venue_timezone == make_venue().timezone

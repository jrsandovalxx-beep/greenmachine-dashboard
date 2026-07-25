"""Neutral ingestion records and the injected sample-minimum policy."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from greenmachine.domain import ComponentId, WindowProfile
from greenmachine.ingestion.errors import IngestionModelError, SamplePolicyError
from greenmachine.ingestion.models import (
    POLICY_COMPONENTS,
    CaptureProvider,
    IngestionEligibilityResult,
    ProviderRequest,
    SampleMinimumPolicy,
)

INSTANT = datetime(2026, 7, 15, 18, 0, tzinfo=UTC)


def complete_policy_entries(
    recent: int = 2, long_term: int = 13
) -> tuple[tuple[ComponentId, WindowProfile, int], ...]:
    entries: list[tuple[ComponentId, WindowProfile, int]] = []
    for component in POLICY_COMPONENTS:
        entries.append((component, WindowProfile.RECENT_7D, recent))
        entries.append((component, WindowProfile.LONG_TERM_2Y, long_term))
    return tuple(entries)


# --------------------------------------------------------------------------
# ProviderRequest canonical form
# --------------------------------------------------------------------------


def test_provider_request_requires_sorted_unique_parameters() -> None:
    with pytest.raises(IngestionModelError, match="sorted by key"):
        ProviderRequest(
            label="synthetic_label",
            provider=CaptureProvider.BASEBALL_SAVANT,
            endpoint="statcast_search_csv",
            parameters=(("b", "2"), ("a", "1")),
        )
    with pytest.raises(IngestionModelError, match="unique keys"):
        ProviderRequest(
            label="synthetic_label",
            provider=CaptureProvider.BASEBALL_SAVANT,
            endpoint="statcast_search_csv",
            parameters=(("a", "1"), ("a", "2")),
        )


def test_provider_request_label_must_be_stable() -> None:
    with pytest.raises(IngestionModelError, match="stable lowercase label"):
        ProviderRequest(
            label="Not Stable!",
            provider=CaptureProvider.MLB_STATS_API,
            endpoint="schedule",
            parameters=(),
        )


# --------------------------------------------------------------------------
# Eligibility coherence
# --------------------------------------------------------------------------


def test_eligibility_result_coherence() -> None:
    with pytest.raises(IngestionModelError, match="cannot be eligible with blockers"):
        IngestionEligibilityResult(eligible=True, blockers=("x",), notes=())
    with pytest.raises(IngestionModelError, match="at least one blocker"):
        IngestionEligibilityResult(eligible=False, blockers=(), notes=())


# --------------------------------------------------------------------------
# Sample-minimum policy: explicit, complete, no hidden defaults
# --------------------------------------------------------------------------


def test_a_complete_policy_constructs_and_answers() -> None:
    policy = SampleMinimumPolicy(
        disclaimer="GM-020 vertical-slice validation only; not production.",
        entries=complete_policy_entries(),
    )
    assert policy.minimum_for(ComponentId.EXIT_VELOCITY, WindowProfile.RECENT_7D) == 2
    assert policy.minimum_for(ComponentId.BAT_SPEED, WindowProfile.LONG_TERM_2Y) == 13


def test_an_incomplete_policy_is_rejected() -> None:
    entries = complete_policy_entries()[:-1]  # drop one required pairing
    with pytest.raises(SamplePolicyError, match="incomplete"):
        SampleMinimumPolicy(disclaimer="validation only", entries=entries)


def test_a_blank_disclaimer_is_rejected() -> None:
    with pytest.raises(SamplePolicyError, match="disclaimer"):
        SampleMinimumPolicy(disclaimer="   ", entries=complete_policy_entries())


def test_duplicate_policy_entries_are_rejected() -> None:
    entries = (*complete_policy_entries(), (ComponentId.EXIT_VELOCITY, WindowProfile.RECENT_7D, 5))
    with pytest.raises(SamplePolicyError, match="duplicate"):
        SampleMinimumPolicy(disclaimer="validation only", entries=entries)


def test_negative_minimums_are_rejected() -> None:
    entries = (
        *complete_policy_entries()[:-1],
        (ComponentId.PULL_PCT_AIR_BALLS, WindowProfile.LONG_TERM_2Y, -1),
    )
    with pytest.raises(SamplePolicyError, match=">= 0"):
        SampleMinimumPolicy(disclaimer="validation only", entries=entries)


def test_the_policy_type_carries_no_default_values() -> None:
    """No hidden or module-level default exists: both fields are required."""
    import dataclasses

    for field in dataclasses.fields(SampleMinimumPolicy):
        assert field.default is dataclasses.MISSING
        assert field.default_factory is dataclasses.MISSING


def test_no_policy_instance_exists_at_module_level() -> None:
    """The mapper receives a policy from its caller — never from the module."""
    import greenmachine.ingestion.mapping as mapping_module
    import greenmachine.ingestion.models as models_module

    for module in (mapping_module, models_module):
        instances = [
            name for name, value in vars(module).items() if isinstance(value, SampleMinimumPolicy)
        ]
        assert instances == [], f"{module.__name__} holds a policy instance: {instances}"

"""Immutability across every public domain type, on every supported Python.

The earlier version of this suite assigned to fields that did not exist on the
target type (``Venue.full_name``, ``ValidationFinding.points_awarded``). On a
frozen *slotted* dataclass the exception raised for an unknown attribute is not
guaranteed to be ``FrozenInstanceError`` — CPython 3.13 raises ``TypeError`` —
so those cases passed on one interpreter and failed on another while never
actually testing immutability.

The fix is structural: every case names a **real** field, and the test asserts the
field exists before assigning. A future mis-parameterisation fails loudly on the
existence check instead of drifting between interpreters. The immutability
assertion itself is unchanged and unweakened: assigning to a real field must
raise ``FrozenInstanceError``.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest
from domain_builders import (
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
    CoverageWindow,
    EvaluationId,
    GameId,
    MissingReason,
    Pitcher,
    PitcherRole,
    PlayerId,
    SnapshotId,
    SourceCaptureId,
    ValidationFinding,
    ValidationInputId,
    VenueId,
)

# (instance, existing field name, a valid replacement value)
FROZEN_CASES = [
    (GameId("g-1"), "value", "g-2"),
    (PlayerId("p-1"), "value", "p-2"),
    (VenueId("v-1"), "value", "v-2"),
    (SnapshotId("s-1"), "value", "s-2"),
    (SourceCaptureId("c-1"), "value", "c-2"),
    (EvaluationId("e-1"), "value", "e-2"),
    (CoverageWindow(WINDOW_START, WINDOW_END), "start", WINDOW_END),
    (make_coverage(), "sample_count", 7),
    (make_ineligibility(), "reason", "a different reason"),
    (make_fallback(), "selected_method", AcquisitionMethod.CONFIGURED_PROXY),
    (Batter(PlayerId("p-1"), "Synthetic Batter"), "full_name", "Other Name"),
    (
        Pitcher(PlayerId("p-2"), "Synthetic Pitcher", PitcherRole.EXPECTED_STARTER),
        "role",
        PitcherRole.OPENER,
    ),
    (make_venue(), "name", "Other Park"),
    (make_game_context(), "game_id", GameId("official-game-000999")),
    (make_observation(), "raw_value", Decimal("1")),
    (make_missing_observation(), "missing_reason", MissingReason.SOURCE_UNAVAILABLE),
    (
        BucketHit(Decimal("10"), Decimal("20"), False, Decimal("0.75")),
        "points_awarded",
        Decimal("1"),
    ),
    (
        ComponentScore(ComponentId.PARK, None, Decimal("1")),
        "points_awarded",
        Decimal("0"),
    ),
    (
        CategoryScore(Category.ENVIRONMENT, Decimal("2")),
        "points_awarded",
        Decimal("1"),
    ),
    (
        ValidationFinding(ValidationInputId.FALLBACK_STATUS, "used event derivation"),
        "message",
        "another message",
    ),
]

FROZEN_IDS = [f"{type(obj).__name__}.{name}" for obj, name, _ in FROZEN_CASES]


@pytest.mark.parametrize(("instance", "field_name", "replacement"), FROZEN_CASES, ids=FROZEN_IDS)
def test_field_exists_on_the_type(instance: object, field_name: str, replacement: object) -> None:
    """Guard the guard: the case below must target a field that really exists.

    Without this, assigning to a typo'd field can raise the wrong exception type
    and the immutability assertion becomes accidentally satisfied.
    """
    declared = {f.name for f in dataclasses.fields(instance)}  # type: ignore[arg-type]

    assert field_name in declared, (
        f"{type(instance).__name__} has no field {field_name!r}; declared: {sorted(declared)}"
    )


@pytest.mark.parametrize(("instance", "field_name", "replacement"), FROZEN_CASES, ids=FROZEN_IDS)
def test_assigning_to_a_real_field_raises_frozen_instance_error(
    instance: object, field_name: str, replacement: object
) -> None:
    """Every domain object refuses mutation of a genuine field."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, field_name, replacement)


@pytest.mark.parametrize(("instance", "field_name", "replacement"), FROZEN_CASES, ids=FROZEN_IDS)
def test_deleting_a_real_field_raises_frozen_instance_error(
    instance: object, field_name: str, replacement: object
) -> None:
    """Deletion is mutation too, and is refused the same way."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        delattr(instance, field_name)


@pytest.mark.parametrize(("instance", "field_name", "replacement"), FROZEN_CASES, ids=FROZEN_IDS)
def test_value_is_unchanged_after_a_refused_assignment(
    instance: object, field_name: str, replacement: object
) -> None:
    """The refusal is real: the original value survives the attempt."""
    before = getattr(instance, field_name)

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, field_name, replacement)

    assert getattr(instance, field_name) == before


@pytest.mark.parametrize(("instance", "field_name", "replacement"), FROZEN_CASES, ids=FROZEN_IDS)
def test_every_domain_object_is_hashable(
    instance: object, field_name: str, replacement: object
) -> None:
    """Hashability is what lets these sit in sets and dict keys downstream."""
    assert isinstance(hash(instance), int)


@pytest.mark.parametrize(("instance", "field_name", "replacement"), FROZEN_CASES, ids=FROZEN_IDS)
def test_every_domain_object_uses_slots(
    instance: object, field_name: str, replacement: object
) -> None:
    """Slotted types cannot grow arbitrary attributes at runtime."""
    assert not hasattr(instance, "__dict__")

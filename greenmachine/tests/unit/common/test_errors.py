"""The project error taxonomy: branches, context, and reparenting.

ADR-0007. The point of the hierarchy is that a caller can catch
``GreenMachineError`` deliberately and never need ``except Exception``, and that
a failure carries structured fields rather than prose.
"""

from __future__ import annotations

import dataclasses

import pytest

from greenmachine.common.errors import (
    ConfigurationError,
    DataInputError,
    DomainInvariantError,
    ErrorContext,
    GreenMachineError,
    IngestionError,
    PersistenceError,
    ProviderSchemaChangeError,
)

BRANCHES = (
    ConfigurationError,
    DataInputError,
    DomainInvariantError,
    IngestionError,
    PersistenceError,
)

ALL_ERRORS = (*BRANCHES, GreenMachineError, ProviderSchemaChangeError)


# --------------------------------------------------------------------------
# Hierarchy
# --------------------------------------------------------------------------


@pytest.mark.parametrize("branch", BRANCHES, ids=lambda c: c.__name__)
def test_every_branch_subclasses_the_root(branch: type[GreenMachineError]) -> None:
    assert issubclass(branch, GreenMachineError)


def test_the_five_branches_are_distinct() -> None:
    """No branch is a subclass of another; they are siblings."""
    for branch in BRANCHES:
        others = [b for b in BRANCHES if b is not branch]
        assert not any(issubclass(branch, other) for other in others)


def test_provider_schema_change_is_an_ingestion_error() -> None:
    """ADR-0007 names this the failure that must stop a pipeline loudly."""
    assert issubclass(ProviderSchemaChangeError, IngestionError)
    assert issubclass(ProviderSchemaChangeError, GreenMachineError)


def test_the_root_is_an_exception_not_a_base_exception_shortcut() -> None:
    assert issubclass(GreenMachineError, Exception)
    assert not issubclass(GreenMachineError, KeyboardInterrupt)


@pytest.mark.parametrize("error_type", ALL_ERRORS, ids=lambda c: c.__name__)
def test_catching_the_root_catches_every_branch(error_type: type[GreenMachineError]) -> None:
    with pytest.raises(GreenMachineError):
        raise error_type("failure")


@pytest.mark.parametrize("error_type", ALL_ERRORS, ids=lambda c: c.__name__)
def test_error_type_is_derived_from_the_class(error_type: type[GreenMachineError]) -> None:
    """A stable machine-readable code, not free-form prose."""
    assert error_type("failure").error_type == error_type.__name__


# --------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------


def test_message_and_context_are_exposed_structurally() -> None:
    context = ErrorContext(metric="exit_velocity", subject="player-1")
    error = ConfigurationError("bad allocation", context)

    assert error.message == "bad allocation"
    assert error.context is context
    assert str(error) == "bad allocation"


def test_context_always_exists_even_when_not_supplied() -> None:
    error = DataInputError("no context given")

    assert isinstance(error.context, ErrorContext)
    assert error.context.is_empty


def test_the_empty_context_is_shared_not_a_mutable_default() -> None:
    """Two contextless errors share one frozen singleton; nothing accumulates."""
    first = DataInputError("one")
    second = PersistenceError("two")

    assert first.context == second.context
    assert first.context.is_empty


@pytest.mark.parametrize("bad", [None, 7, b"bytes", ErrorContext()])
def test_a_non_string_message_is_refused(bad: object) -> None:
    with pytest.raises(TypeError, match=r"message must be a string"):
        GreenMachineError(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["", "   ", "\t\n"])
def test_a_blank_message_is_refused(bad: str) -> None:
    with pytest.raises(ValueError, match=r"message must not be blank"):
        GreenMachineError(bad)


@pytest.mark.parametrize("bad", ["context", 7, {"metric": "x"}, ()])
def test_a_non_context_context_is_refused(bad: object) -> None:
    """Malformed state is refused rather than stored."""
    with pytest.raises(TypeError, match=r"context must be an ErrorContext"):
        GreenMachineError("message", bad)  # type: ignore[arg-type]


def test_repr_shows_both_fields() -> None:
    error = IngestionError("boom", ErrorContext(provider="baseball_savant"))

    assert "IngestionError" in repr(error)
    assert "boom" in repr(error)
    assert "baseball_savant" in repr(error)


# --------------------------------------------------------------------------
# ErrorContext
# --------------------------------------------------------------------------


def test_context_defaults_to_entirely_empty() -> None:
    context = ErrorContext()

    assert context.is_empty
    assert context.as_dict() == {}
    assert context.key_path == ()


def test_context_carries_every_documented_field() -> None:
    context = ErrorContext(
        file_path="config/model/v0.1.0/model.yaml",
        key_path=("categories", "form", "max_points"),
        metric="bat_speed",
        window_profile="RECENT_7D",
        subject="player-000001",
    )

    assert context.as_dict() == {
        "file_path": "config/model/v0.1.0/model.yaml",
        "key_path": ["categories", "form", "max_points"],
        "metric": "bat_speed",
        "window_profile": "RECENT_7D",
        "subject": "player-000001",
    }


def test_context_is_frozen() -> None:
    context = ErrorContext(metric="park")

    with pytest.raises(dataclasses.FrozenInstanceError):
        context.metric = "weather"


def test_context_is_hashable_and_equal_by_value() -> None:
    first = ErrorContext(metric="park", key_path=("a", "b"))
    second = ErrorContext(metric="park", key_path=("a", "b"))

    assert first == second
    assert hash(first) == hash(second)
    assert len({first, second}) == 1


def test_context_uses_slots_and_holds_no_dict() -> None:
    """No mutable dictionary is stored internally."""
    assert not hasattr(ErrorContext(), "__dict__")


@pytest.mark.parametrize(
    "field_name", ["file_path", "metric", "window_profile", "subject", "provider"]
)
def test_context_rejects_a_non_string_field(field_name: str) -> None:
    with pytest.raises(TypeError, match=rf"ErrorContext\.{field_name} must be a string"):
        ErrorContext(**{field_name: 7})


def test_context_rejects_a_list_key_path() -> None:
    """A list would make the context unhashable and mutable."""
    with pytest.raises(TypeError, match=r"key_path must be a tuple"):
        ErrorContext(key_path=["a", "b"])  # type: ignore[arg-type]


def test_context_rejects_a_non_string_key_path_element() -> None:
    with pytest.raises(TypeError, match=r"key_path\[1\] must be a string"):
        ErrorContext(key_path=("a", 2))  # type: ignore[arg-type]


def test_as_dict_returns_a_new_dictionary_each_call() -> None:
    context = ErrorContext(metric="park", key_path=("a",))

    first = context.as_dict()
    second = context.as_dict()

    assert first == second
    assert first is not second


def test_mutating_the_returned_dictionary_cannot_reach_the_error() -> None:
    """The conversion is safe to hand to a formatter."""
    error = ConfigurationError("bad", ErrorContext(metric="park", key_path=("a", "b")))

    payload = error.context.as_dict()
    payload["metric"] = "TAMPERED"
    payload["key_path"].append("injected")  # type: ignore[union-attr]

    assert error.context.metric == "park"
    assert error.context.key_path == ("a", "b")
    assert error.context.as_dict()["metric"] == "park"


def test_as_dict_omits_unset_fields() -> None:
    assert ErrorContext(metric="park").as_dict() == {"metric": "park"}


# --------------------------------------------------------------------------
# Structured logging representation
# --------------------------------------------------------------------------


def test_as_log_record_exposes_fields_not_a_parsed_string() -> None:
    error = ProviderSchemaChangeError(
        "leaderboard column renamed",
        ErrorContext(
            provider="baseball_savant",
            expected="launch_speed",
            observed="exit_velocity",
            subject="leaderboard",
        ),
    )

    record = error.as_log_record()

    assert record["error_type"] == "ProviderSchemaChangeError"
    assert record["message"] == "leaderboard column renamed"
    assert record["context"] == {
        "provider": "baseball_savant",
        "expected": "launch_speed",
        "observed": "exit_velocity",
        "subject": "leaderboard",
    }


def test_provider_schema_change_context_survives_intact() -> None:
    context = ErrorContext(provider="p", expected="a", observed="b", subject="s")
    error = ProviderSchemaChangeError("mismatch", context)

    assert error.context == context
    assert error.context.provider == "p"
    assert error.context.expected == "a"
    assert error.context.observed == "b"


def test_as_log_record_is_freshly_built() -> None:
    error = DataInputError("bad", ErrorContext(metric="park"))

    first = error.as_log_record()
    first["message"] = "TAMPERED"

    assert error.as_log_record()["message"] == "bad"
    assert error.message == "bad"


def test_a_contextless_error_still_serializes() -> None:
    record = PersistenceError("append conflict").as_log_record()

    assert record["context"] == {}
    assert record["error_type"] == "PersistenceError"


# --------------------------------------------------------------------------
# Reparenting of the GM-002 and GM-005 errors
# --------------------------------------------------------------------------


def test_domain_errors_sit_under_domain_invariant_error() -> None:
    from greenmachine.domain import DomainError, DomainValidationError

    assert issubclass(DomainError, DomainInvariantError)
    assert issubclass(DomainValidationError, DomainError)
    assert issubclass(DomainValidationError, GreenMachineError)


def test_determinism_primitive_errors_sit_under_data_input_error() -> None:
    from greenmachine.common import (
        CanonicalizationError,
        ClockError,
        IdentifierError,
        NumericPolicyError,
    )

    for error_type in (NumericPolicyError, ClockError, CanonicalizationError, IdentifierError):
        assert issubclass(error_type, DataInputError), error_type.__name__
        assert issubclass(error_type, GreenMachineError), error_type.__name__


def test_builtin_compatibility_is_preserved() -> None:
    """Callers already catching ValueError/TypeError keep working."""
    from greenmachine.common import (
        CanonicalizationError,
        ClockError,
        IdentifierError,
        NumericPolicyError,
    )
    from greenmachine.domain import DomainValidationError

    for error_type in (NumericPolicyError, ClockError, IdentifierError, DomainValidationError):
        assert issubclass(error_type, ValueError), error_type.__name__
    assert issubclass(CanonicalizationError, TypeError)


def test_reparented_errors_are_still_catchable_by_their_public_names() -> None:
    """The existing raise sites and suites keep working untouched."""
    from decimal import Decimal

    from greenmachine.common import (
        CanonicalizationError,
        ClockError,
        NumericPolicyError,
        canonical_json,
        decimal_from,
    )
    from greenmachine.common.clock import FixedClock
    from greenmachine.domain import DomainValidationError, GameId

    with pytest.raises(NumericPolicyError):
        decimal_from(0.1)  # type: ignore[arg-type]
    with pytest.raises(CanonicalizationError):
        canonical_json(1.5)
    with pytest.raises(ClockError):
        FixedClock("not a datetime")  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError):
        GameId("")

    # And each is now also reachable through the taxonomy root.
    with pytest.raises(GreenMachineError):
        decimal_from(0.1)  # type: ignore[arg-type]
    with pytest.raises(DataInputError):
        canonical_json({1.5})
    with pytest.raises(DomainInvariantError):
        GameId("")
    assert Decimal("1") == decimal_from("1")


def test_reparented_errors_accept_structured_context_without_requiring_it() -> None:
    """Existing raise sites pass a message alone; new ones may add context."""
    from greenmachine.common import NumericPolicyError

    plain = NumericPolicyError("no context")
    enriched = NumericPolicyError("with context", ErrorContext(metric="bat_speed"))

    assert plain.context.is_empty
    assert enriched.context.metric == "bat_speed"
    assert enriched.error_type == "NumericPolicyError"

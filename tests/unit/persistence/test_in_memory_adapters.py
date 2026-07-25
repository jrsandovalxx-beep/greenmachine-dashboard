"""In-memory adapter specifics beyond the shared port contract.

The behavioral port contract lives in ``tests/integration`` and runs against
these adapters unchanged; this file covers only what is adapter-specific —
instance-local state, hidden internals, and protocol conformance.
"""

from __future__ import annotations

import pytest
import synthetic_records as sr

from greenmachine.persistence import (
    EvaluationQuery,
    EvaluationRepository,
    InMemoryEvaluationRepository,
    InMemoryOutcomeRepository,
    InMemorySnapshotRepository,
    OutcomeQuery,
    OutcomeRepository,
    SnapshotQuery,
    SnapshotRepository,
    create_outcome_revision,
)

ADAPTERS = [
    InMemorySnapshotRepository,
    InMemoryEvaluationRepository,
    InMemoryOutcomeRepository,
]


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda a: a.__name__)
def test_every_internal_attribute_is_private(adapter: type) -> None:
    """The backing collections are never exposed as public attributes."""
    instance = adapter()
    assert all(name.startswith("_") for name in vars(instance))


def test_the_adapters_conform_to_their_ports() -> None:
    assert isinstance(InMemorySnapshotRepository(), SnapshotRepository)
    assert isinstance(InMemoryEvaluationRepository(), EvaluationRepository)
    assert isinstance(InMemoryOutcomeRepository(), OutcomeRepository)


def test_no_module_level_repository_singleton_exists() -> None:
    """Repository state is instance-local; the module holds no store."""
    import greenmachine.persistence.in_memory as module

    module_dicts = [
        name
        for name, value in vars(module).items()
        if isinstance(value, dict) and not name.startswith("__")
    ]
    assert module_dicts == []


def test_repositories_of_different_kinds_share_nothing() -> None:
    snapshots = InMemorySnapshotRepository()
    evaluations = InMemoryEvaluationRepository()
    outcomes = InMemoryOutcomeRepository()

    snapshots.append(sr.input_snapshot())
    evaluations.append(sr.evaluation_envelope())
    outcomes.append(create_outcome_revision(sr.outcome_record()))

    assert len(snapshots.query(SnapshotQuery())) == 1
    assert len(evaluations.query(EvaluationQuery())) == 1
    assert len(outcomes.query(OutcomeQuery())) == 1


def test_query_results_are_snapshots_of_state_not_views() -> None:
    """A returned tuple does not change when the repository grows later."""
    repository = InMemoryOutcomeRepository()
    root = create_outcome_revision(sr.outcome_record())
    repository.append(root)

    before = repository.query(OutcomeQuery())
    child = create_outcome_revision(sr.outcome_record(), supersedes=root.outcome_revision_id)
    repository.append(child)
    after = repository.query(OutcomeQuery())

    assert len(before) == 1
    assert len(after) == 2


def test_public_surface_is_exactly_append_get_query() -> None:
    for adapter in ADAPTERS:
        public = {
            name
            for name in vars(adapter)
            if not name.startswith("_") and callable(getattr(adapter, name))
        }
        assert public == {"append", "get", "query"}, adapter.__name__

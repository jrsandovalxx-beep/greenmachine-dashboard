"""The in-memory adapters run the full repository contract suite, unchanged.

A future durable adapter (file, SQLite, …) gets its behavioral coverage the same
way: subclass the three contract classes from ``repository_contracts`` and
override only ``make_repository`` with a factory for a fresh, empty repository.
No behavioral assertion is copied or edited.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from repository_contracts import (
    EvaluationRepositoryContract,
    OutcomeRepositoryContract,
    SnapshotRepositoryContract,
)

from greenmachine.persistence import (
    EvaluationRepository,
    InMemoryEvaluationRepository,
    InMemoryOutcomeRepository,
    InMemorySnapshotRepository,
    OutcomeRepository,
    SnapshotRepository,
)


class TestInMemorySnapshotRepository(SnapshotRepositoryContract):
    @pytest.fixture
    def make_repository(self) -> Callable[[], SnapshotRepository]:
        return InMemorySnapshotRepository


class TestInMemoryEvaluationRepository(EvaluationRepositoryContract):
    @pytest.fixture
    def make_repository(self) -> Callable[[], EvaluationRepository]:
        return InMemoryEvaluationRepository


class TestInMemoryOutcomeRepository(OutcomeRepositoryContract):
    @pytest.fixture
    def make_repository(self) -> Callable[[], OutcomeRepository]:
        return InMemoryOutcomeRepository


def test_the_adapters_satisfy_their_ports_structurally() -> None:
    assert isinstance(InMemorySnapshotRepository(), SnapshotRepository)
    assert isinstance(InMemoryEvaluationRepository(), EvaluationRepository)
    assert isinstance(InMemoryOutcomeRepository(), OutcomeRepository)

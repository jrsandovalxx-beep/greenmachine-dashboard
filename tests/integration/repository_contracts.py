"""Reusable behavioral contracts for the three append-only repository ports.

A future adapter (file, SQLite, …) runs these assertions **unchanged**: subclass
the three contract classes and override only the ``make_repository`` fixture
with a factory for a fresh, empty repository. Nothing here inspects private
implementation details — every assertion goes through the port operations.

The record builders produce visibly synthetic variants of the GM-006 fixtures so
queries, ordering, and correction chains can be exercised with controlled field
differences.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import timedelta

import pytest
import synthetic_records as sr

from greenmachine.domain import (
    Batter,
    EvaluationEnvelope,
    EvaluationId,
    GameContext,
    GameId,
    InputSnapshot,
    OutcomeRecord,
    Pitcher,
    PitcherRole,
    PlayerId,
    Sha256Digest,
    SnapshotId,
    SourceCaptureId,
    WindowProfile,
)
from greenmachine.evaluation import freeze_input_snapshot
from greenmachine.persistence import (
    BranchingSupersessionError,
    ConflictingRecordError,
    DuplicateRecordError,
    EvaluationQuery,
    EvaluationRepository,
    InvalidSupersessionError,
    MalformedRepositoryInputError,
    MissingSupersededParentError,
    OutcomeQuery,
    OutcomeRepository,
    OutcomeRevision,
    OutcomeRevisionId,
    SnapshotQuery,
    SnapshotRepository,
    create_outcome_revision,
)

# --------------------------------------------------------------------------
# Synthetic record variants
# --------------------------------------------------------------------------


def make_snapshot(
    *,
    game: str = "SYNTHETIC-GAME-0001",
    batter: str = "SYNTHETIC-BATTER-0001",
    pitcher: str = "SYNTHETIC-PITCHER-0009",
    day_offset: int = 0,
    profile: WindowProfile = WindowProfile.RECENT_7D,
    capture: str = "SYNTHETIC-CAPTURE-0001",
) -> InputSnapshot:
    """A frozen snapshot variant with controlled query-relevant fields."""
    delta = timedelta(days=day_offset)
    context = GameContext(
        game_id=GameId(game),
        slate_date=sr.SLATE_DATE + delta,
        scheduled_start_utc=sr.SCHEDULED_START_UTC + delta,
        venue_local_scheduled_time=sr.VENUE_LOCAL_START + delta,
        venue=sr.game_context().venue,
    )
    observation = dataclasses.replace(
        sr.present_exit_velocity(),
        window_profile=profile,
        source_capture_id=SourceCaptureId(capture),
    )
    return freeze_input_snapshot(
        source_capture_id=SourceCaptureId(capture),
        game_context=context,
        batter=Batter(player_id=PlayerId(batter), full_name="Synthetic Batter Variant"),
        expected_starting_pitcher=Pitcher(
            player_id=PlayerId(pitcher),
            full_name="Synthetic Pitcher Variant",
            role=PitcherRole.EXPECTED_STARTER,
        ),
        pitcher_role=PitcherRole.EXPECTED_STARTER,
        as_of=sr.AS_OF,
        window_profile=profile,
        window_start=sr.WINDOW_START,
        window_end=sr.WINDOW_END,
        present_observations=(observation,),
        missing_observations=(),
        validation_inputs=(),
        weather_is_forecast=False,
    )


def make_envelope(
    *,
    evaluation_id: str = "SYNTHETIC-EVAL-1001",
    game: str | None = None,
    batter: str | None = None,
    pitcher: str | None = None,
    day_offset: int = 0,
    config_version: str | None = None,
    profile: WindowProfile | None = None,
    capture: str | None = None,
    minutes_offset: int = 0,
    supersedes: str | None = None,
) -> EvaluationEnvelope:
    """An envelope variant with controlled query-relevant fields."""
    envelope = sr.evaluation_envelope()
    overrides: dict[str, object] = {"evaluation_id": EvaluationId(evaluation_id)}
    if game is not None:
        overrides["game_id"] = GameId(game)
    if batter is not None:
        overrides["batter_id"] = PlayerId(batter)
    if pitcher is not None:
        overrides["expected_starting_pitcher_id"] = PlayerId(pitcher)
    if day_offset:
        overrides["slate_date"] = sr.SLATE_DATE + timedelta(days=day_offset)
    if config_version is not None:
        overrides["model_configuration_version"] = config_version
    if minutes_offset:
        overrides["evaluated_at"] = sr.EVALUATED_AT + timedelta(minutes=minutes_offset)
    if supersedes is not None:
        overrides["supersedes"] = EvaluationId(supersedes)
    if capture is not None or profile is not None:
        result = envelope.grade_result
        new_capture = (
            SourceCaptureId(capture) if capture is not None else envelope.source_capture_id
        )
        new_profile = profile if profile is not None else envelope.window_profile
        present = tuple(
            dataclasses.replace(o, source_capture_id=new_capture, window_profile=new_profile)
            for o in result.present_observations
        )
        missing = tuple(
            dataclasses.replace(o, source_capture_id=new_capture, window_profile=new_profile)
            for o in result.missing_observations
        )
        overrides["grade_result"] = dataclasses.replace(
            result,
            window_profile=new_profile,
            present_observations=present,
            missing_observations=missing,
        )
        overrides["source_capture_id"] = new_capture
        overrides["window_profile"] = new_profile
    return dataclasses.replace(envelope, **overrides)


def make_outcome(
    *,
    game: str = "SYNTHETIC-GAME-0001",
    batter: str = "SYNTHETIC-BATTER-0001",
    homered: bool = True,
) -> OutcomeRecord:
    return OutcomeRecord(
        game_id=GameId(game), batter_id=PlayerId(batter), hit_at_least_one_home_run=homered
    )


def make_revision(
    *,
    game: str = "SYNTHETIC-GAME-0001",
    batter: str = "SYNTHETIC-BATTER-0001",
    homered: bool = True,
    supersedes: OutcomeRevisionId | None = None,
) -> OutcomeRevision:
    return create_outcome_revision(
        make_outcome(game=game, batter=batter, homered=homered), supersedes=supersedes
    )


# --------------------------------------------------------------------------
# Snapshot repository contract
# --------------------------------------------------------------------------


class SnapshotRepositoryContract:
    """Every SnapshotRepository adapter must pass these unchanged."""

    @pytest.fixture
    def make_repository(self) -> Callable[[], SnapshotRepository]:
        raise NotImplementedError("adapter test class must supply a repository factory")

    @pytest.fixture
    def repository(self, make_repository: Callable[[], SnapshotRepository]) -> SnapshotRepository:
        return make_repository()

    def test_append_get_round_trip(self, repository: SnapshotRepository) -> None:
        snapshot = make_snapshot()
        repository.append(snapshot)
        assert repository.get(snapshot.snapshot_id) == snapshot

    def test_missing_get_returns_none(self, repository: SnapshotRepository) -> None:
        assert repository.get(SnapshotId("input_snapshot-unknown")) is None

    def test_empty_query_returns_empty_tuple(self, repository: SnapshotRepository) -> None:
        assert repository.query(SnapshotQuery()) == ()

    def test_duplicate_append_raises_and_preserves_original(
        self, repository: SnapshotRepository
    ) -> None:
        snapshot = make_snapshot()
        repository.append(snapshot)
        with pytest.raises(DuplicateRecordError):
            repository.append(snapshot)
        assert repository.get(snapshot.snapshot_id) == snapshot
        assert len(repository.query(SnapshotQuery())) == 1

    def test_conflicting_identity_reuse_is_rejected(self, repository: SnapshotRepository) -> None:
        snapshot = make_snapshot()
        repository.append(snapshot)
        different = sr.rebuild_snapshot(snapshot, weather_is_forecast=True)
        with pytest.raises(ConflictingRecordError):
            repository.append(different)
        assert repository.get(snapshot.snapshot_id) == snapshot

    def test_invalid_append_type_is_translated(self, repository: SnapshotRepository) -> None:
        with pytest.raises(MalformedRepositoryInputError):
            repository.append("not a snapshot")  # type: ignore[arg-type]

    def test_invalid_get_id_is_translated(self, repository: SnapshotRepository) -> None:
        with pytest.raises(MalformedRepositoryInputError):
            repository.get("bare string")  # type: ignore[arg-type]

    def test_invalid_query_type_is_translated(self, repository: SnapshotRepository) -> None:
        with pytest.raises(MalformedRepositoryInputError):
            repository.query(EvaluationQuery())  # type: ignore[arg-type]

    @pytest.fixture
    def populated(self, repository: SnapshotRepository) -> SnapshotRepository:
        repository.append(make_snapshot())
        repository.append(make_snapshot(game="SYNTHETIC-GAME-0002", day_offset=1))
        repository.append(
            make_snapshot(
                batter="SYNTHETIC-BATTER-0002",
                pitcher="SYNTHETIC-PITCHER-0010",
                capture="SYNTHETIC-CAPTURE-0002",
            )
        )
        repository.append(make_snapshot(profile=WindowProfile.LONG_TERM_2Y))
        return repository

    def test_query_by_slate_date(self, populated: SnapshotRepository) -> None:
        rows = populated.query(SnapshotQuery(slate_date=sr.SLATE_DATE + timedelta(days=1)))
        assert [s.game_context.game_id.value for s in rows] == ["SYNTHETIC-GAME-0002"]

    def test_query_by_game_id(self, populated: SnapshotRepository) -> None:
        rows = populated.query(SnapshotQuery(game_id=GameId("SYNTHETIC-GAME-0002")))
        assert len(rows) == 1

    def test_query_by_batter_id(self, populated: SnapshotRepository) -> None:
        rows = populated.query(SnapshotQuery(batter_id=PlayerId("SYNTHETIC-BATTER-0002")))
        assert len(rows) == 1

    def test_query_by_expected_starting_pitcher(self, populated: SnapshotRepository) -> None:
        rows = populated.query(
            SnapshotQuery(expected_starting_pitcher_id=PlayerId("SYNTHETIC-PITCHER-0010"))
        )
        assert len(rows) == 1

    def test_query_by_window_profile(self, populated: SnapshotRepository) -> None:
        rows = populated.query(SnapshotQuery(window_profile=WindowProfile.LONG_TERM_2Y))
        assert len(rows) == 1
        assert rows[0].window_profile is WindowProfile.LONG_TERM_2Y

    def test_query_by_source_capture_id(self, populated: SnapshotRepository) -> None:
        rows = populated.query(
            SnapshotQuery(source_capture_id=SourceCaptureId("SYNTHETIC-CAPTURE-0002"))
        )
        assert len(rows) == 1

    def test_combined_filters_use_and(self, populated: SnapshotRepository) -> None:
        rows = populated.query(
            SnapshotQuery(
                game_id=GameId("SYNTHETIC-GAME-0001"),
                batter_id=PlayerId("SYNTHETIC-BATTER-0002"),
            )
        )
        assert len(rows) == 1
        none = populated.query(
            SnapshotQuery(
                game_id=GameId("SYNTHETIC-GAME-0002"),
                batter_id=PlayerId("SYNTHETIC-BATTER-0002"),
            )
        )
        assert none == ()

    def test_order_is_deterministic_across_append_permutations(
        self, make_repository: Callable[[], SnapshotRepository]
    ) -> None:
        records = [
            make_snapshot(),
            make_snapshot(game="SYNTHETIC-GAME-0002", day_offset=1),
            make_snapshot(batter="SYNTHETIC-BATTER-0002"),
            make_snapshot(profile=WindowProfile.LONG_TERM_2Y),
        ]
        first = make_repository()
        for record in records:
            first.append(record)
        second = make_repository()
        for record in reversed(records):
            second.append(record)

        assert first.query(SnapshotQuery()) == second.query(SnapshotQuery())

    def test_paired_profile_snapshots_coexist_and_query_together(
        self, repository: SnapshotRepository
    ) -> None:
        recent = sr.input_snapshot()
        long_term = sr.input_snapshot_long_term()
        repository.append(recent)
        repository.append(long_term)

        assert recent.snapshot_id != long_term.snapshot_id
        assert recent.input_hash != long_term.input_hash
        assert repository.get(recent.snapshot_id) == recent
        assert repository.get(long_term.snapshot_id) == long_term
        joint = repository.query(SnapshotQuery(source_capture_id=recent.source_capture_id))
        assert len(joint) == 2

    def test_query_returns_a_fresh_tuple(self, repository: SnapshotRepository) -> None:
        repository.append(make_snapshot())
        first = repository.query(SnapshotQuery())
        second = repository.query(SnapshotQuery())
        assert isinstance(first, tuple)
        assert first == second
        assert first is not second

    def test_separate_instances_share_no_state(
        self, make_repository: Callable[[], SnapshotRepository]
    ) -> None:
        first, second = make_repository(), make_repository()
        snapshot = make_snapshot()
        first.append(snapshot)
        assert second.get(snapshot.snapshot_id) is None
        assert second.query(SnapshotQuery()) == ()


# --------------------------------------------------------------------------
# Evaluation repository contract
# --------------------------------------------------------------------------


class EvaluationRepositoryContract:
    """Every EvaluationRepository adapter must pass these unchanged."""

    @pytest.fixture
    def make_repository(self) -> Callable[[], EvaluationRepository]:
        raise NotImplementedError("adapter test class must supply a repository factory")

    @pytest.fixture
    def repository(
        self, make_repository: Callable[[], EvaluationRepository]
    ) -> EvaluationRepository:
        return make_repository()

    def test_append_get_round_trip(self, repository: EvaluationRepository) -> None:
        envelope = make_envelope()
        repository.append(envelope)
        assert repository.get(envelope.evaluation_id) == envelope

    def test_missing_get_returns_none(self, repository: EvaluationRepository) -> None:
        assert repository.get(EvaluationId("SYNTHETIC-EVAL-UNKNOWN")) is None

    def test_empty_query_returns_empty_tuple(self, repository: EvaluationRepository) -> None:
        assert repository.query(EvaluationQuery()) == ()

    def test_duplicate_identity_rejected_without_overwrite(
        self, repository: EvaluationRepository
    ) -> None:
        envelope = make_envelope()
        repository.append(envelope)
        with pytest.raises(DuplicateRecordError):
            repository.append(envelope)
        different = dataclasses.replace(envelope, code_version="9.9.9")
        with pytest.raises(ConflictingRecordError):
            repository.append(different)
        assert repository.get(envelope.evaluation_id) == envelope

    def test_invalid_inputs_are_translated(self, repository: EvaluationRepository) -> None:
        with pytest.raises(MalformedRepositoryInputError):
            repository.append(make_snapshot())  # type: ignore[arg-type]
        with pytest.raises(MalformedRepositoryInputError):
            repository.get("bare string")  # type: ignore[arg-type]
        with pytest.raises(MalformedRepositoryInputError):
            repository.query(SnapshotQuery())  # type: ignore[arg-type]

    def test_no_outcome_shaped_value_can_enter(self, repository: EvaluationRepository) -> None:
        with pytest.raises(MalformedRepositoryInputError):
            repository.append(make_outcome())  # type: ignore[arg-type]
        with pytest.raises(MalformedRepositoryInputError):
            repository.append(make_revision())  # type: ignore[arg-type]

    @pytest.fixture
    def populated(self, repository: EvaluationRepository) -> EvaluationRepository:
        repository.append(make_envelope())
        repository.append(
            make_envelope(
                evaluation_id="SYNTHETIC-EVAL-1002",
                game="SYNTHETIC-GAME-0002",
                day_offset=1,
                minutes_offset=1,
            )
        )
        repository.append(
            make_envelope(
                evaluation_id="SYNTHETIC-EVAL-1003",
                batter="SYNTHETIC-BATTER-0002",
                pitcher="SYNTHETIC-PITCHER-0010",
                config_version="synthetic-fixture-1",
                capture="SYNTHETIC-CAPTURE-0002",
                minutes_offset=2,
            )
        )
        repository.append(
            make_envelope(
                evaluation_id="SYNTHETIC-EVAL-1004",
                profile=WindowProfile.LONG_TERM_2Y,
                minutes_offset=3,
            )
        )
        return repository

    @pytest.mark.parametrize(
        ("query", "expected_ids"),
        [
            (
                {"game_id": GameId("SYNTHETIC-GAME-0002")},
                ["SYNTHETIC-EVAL-1002"],
            ),
            (
                {"batter_id": PlayerId("SYNTHETIC-BATTER-0002")},
                ["SYNTHETIC-EVAL-1003"],
            ),
            (
                {"expected_starting_pitcher_id": PlayerId("SYNTHETIC-PITCHER-0010")},
                ["SYNTHETIC-EVAL-1003"],
            ),
            (
                {"model_configuration_version": "synthetic-fixture-1"},
                ["SYNTHETIC-EVAL-1003"],
            ),
            (
                {"window_profile": WindowProfile.LONG_TERM_2Y},
                ["SYNTHETIC-EVAL-1004"],
            ),
            (
                {"source_capture_id": SourceCaptureId("SYNTHETIC-CAPTURE-0002")},
                ["SYNTHETIC-EVAL-1003"],
            ),
        ],
        ids=["game", "batter", "pitcher", "config_version", "profile", "capture"],
    )
    def test_query_by_each_approved_field(
        self,
        populated: EvaluationRepository,
        query: dict[str, object],
        expected_ids: list[str],
    ) -> None:
        rows = populated.query(EvaluationQuery(**query))  # type: ignore[arg-type]
        assert [e.evaluation_id.value for e in rows] == expected_ids

    def test_query_by_slate_date(self, populated: EvaluationRepository) -> None:
        rows = populated.query(EvaluationQuery(slate_date=sr.SLATE_DATE + timedelta(days=1)))
        assert [e.evaluation_id.value for e in rows] == ["SYNTHETIC-EVAL-1002"]

    def test_combined_filters_use_and(self, populated: EvaluationRepository) -> None:
        rows = populated.query(
            EvaluationQuery(
                game_id=GameId("SYNTHETIC-GAME-0001"),
                batter_id=PlayerId("SYNTHETIC-BATTER-0002"),
            )
        )
        assert [e.evaluation_id.value for e in rows] == ["SYNTHETIC-EVAL-1003"]
        assert (
            populated.query(
                EvaluationQuery(
                    game_id=GameId("SYNTHETIC-GAME-0002"),
                    batter_id=PlayerId("SYNTHETIC-BATTER-0002"),
                )
            )
            == ()
        )

    def test_order_is_deterministic_across_append_permutations(
        self, make_repository: Callable[[], EvaluationRepository]
    ) -> None:
        records = [
            make_envelope(),
            make_envelope(evaluation_id="SYNTHETIC-EVAL-1002", game="SYNTHETIC-GAME-0002"),
            make_envelope(evaluation_id="SYNTHETIC-EVAL-1003", minutes_offset=5),
            make_envelope(evaluation_id="SYNTHETIC-EVAL-1004", profile=WindowProfile.LONG_TERM_2Y),
        ]
        first = make_repository()
        for record in records:
            first.append(record)
        second = make_repository()
        for record in reversed(records):
            second.append(record)

        assert first.query(EvaluationQuery()) == second.query(EvaluationQuery())

    def test_paired_profile_envelopes_coexist(self, repository: EvaluationRepository) -> None:
        recent = make_envelope()
        long_term = make_envelope(
            evaluation_id="SYNTHETIC-EVAL-1005", profile=WindowProfile.LONG_TERM_2Y
        )
        repository.append(recent)
        repository.append(long_term)

        stored_recent = repository.get(recent.evaluation_id)
        stored_long = repository.get(long_term.evaluation_id)
        assert stored_recent is not None and stored_long is not None
        assert stored_recent.grade_result.window_profile is WindowProfile.RECENT_7D
        assert stored_long.grade_result.window_profile is WindowProfile.LONG_TERM_2Y

    def test_supersession_chain_is_traversable_and_parent_retained(
        self, repository: EvaluationRepository
    ) -> None:
        root = make_envelope()
        child = make_envelope(
            evaluation_id="SYNTHETIC-EVAL-1002",
            minutes_offset=1,
            supersedes=root.evaluation_id.value,
        )
        grandchild = make_envelope(
            evaluation_id="SYNTHETIC-EVAL-1003",
            minutes_offset=2,
            supersedes=child.evaluation_id.value,
        )
        repository.append(root)
        repository.append(child)
        repository.append(grandchild)

        current = repository.get(grandchild.evaluation_id)
        assert current is not None and current.supersedes is not None
        parent = repository.get(current.supersedes)
        assert parent is not None and parent.supersedes is not None
        origin = repository.get(parent.supersedes)
        assert origin == root
        assert origin.supersedes is None

    def test_missing_superseded_parent_is_rejected(self, repository: EvaluationRepository) -> None:
        orphan = make_envelope(supersedes="SYNTHETIC-EVAL-MISSING")
        with pytest.raises(MissingSupersededParentError):
            repository.append(orphan)
        assert repository.query(EvaluationQuery()) == ()

    def test_branching_supersession_is_rejected(self, repository: EvaluationRepository) -> None:
        root = make_envelope()
        first_child = make_envelope(
            evaluation_id="SYNTHETIC-EVAL-1002", supersedes=root.evaluation_id.value
        )
        second_child = make_envelope(
            evaluation_id="SYNTHETIC-EVAL-1003", supersedes=root.evaluation_id.value
        )
        repository.append(root)
        repository.append(first_child)
        with pytest.raises(BranchingSupersessionError):
            repository.append(second_child)
        # The failed append changed nothing.
        assert repository.get(second_child.evaluation_id) is None
        assert len(repository.query(EvaluationQuery())) == 2

    def test_separate_instances_share_no_state(
        self, make_repository: Callable[[], EvaluationRepository]
    ) -> None:
        first, second = make_repository(), make_repository()
        envelope = make_envelope()
        first.append(envelope)
        assert second.get(envelope.evaluation_id) is None

    # -- r1: a correction concerns one game, one batter, one window profile --

    def test_a_child_with_another_game_is_rejected(self, repository: EvaluationRepository) -> None:
        root = make_envelope()
        repository.append(root)
        wrong_game = make_envelope(
            evaluation_id="SYNTHETIC-EVAL-1002",
            game="SYNTHETIC-GAME-0002",
            supersedes=root.evaluation_id.value,
        )
        with pytest.raises(InvalidSupersessionError, match=r"same game") as caught:
            repository.append(wrong_game)
        assert caught.value.context.subject == "SYNTHETIC-EVAL-1002"
        assert caught.value.context.expected != caught.value.context.observed

    def test_a_child_with_another_batter_is_rejected(
        self, repository: EvaluationRepository
    ) -> None:
        root = make_envelope()
        repository.append(root)
        wrong_batter = make_envelope(
            evaluation_id="SYNTHETIC-EVAL-1002",
            batter="SYNTHETIC-BATTER-0002",
            supersedes=root.evaluation_id.value,
        )
        with pytest.raises(InvalidSupersessionError, match=r"same batter"):
            repository.append(wrong_batter)

    def test_a_child_with_another_window_profile_is_rejected(
        self, repository: EvaluationRepository
    ) -> None:
        root = make_envelope()
        repository.append(root)
        wrong_profile = make_envelope(
            evaluation_id="SYNTHETIC-EVAL-1002",
            profile=WindowProfile.LONG_TERM_2Y,
            supersedes=root.evaluation_id.value,
        )
        with pytest.raises(InvalidSupersessionError, match=r"same window profile"):
            repository.append(wrong_profile)

    def test_a_failed_coherence_append_changes_nothing(
        self, repository: EvaluationRepository
    ) -> None:
        root = make_envelope()
        repository.append(root)
        wrong_game = make_envelope(
            evaluation_id="SYNTHETIC-EVAL-1002",
            game="SYNTHETIC-GAME-0002",
            supersedes=root.evaluation_id.value,
        )
        with pytest.raises(InvalidSupersessionError):
            repository.append(wrong_game)

        # Repository content is unchanged and the parent is still unsuperseded:
        # a valid child can still extend the chain.
        assert repository.get(wrong_game.evaluation_id) is None
        assert len(repository.query(EvaluationQuery())) == 1
        valid_child = make_envelope(
            evaluation_id="SYNTHETIC-EVAL-1003",
            minutes_offset=1,
            supersedes=root.evaluation_id.value,
        )
        repository.append(valid_child)
        assert repository.get(valid_child.evaluation_id) == valid_child

    def test_a_changed_expected_pitcher_is_an_accepted_correction(
        self, repository: EvaluationRepository
    ) -> None:
        root = make_envelope()
        repository.append(root)
        corrected = make_envelope(
            evaluation_id="SYNTHETIC-EVAL-1002",
            pitcher="SYNTHETIC-PITCHER-0010",
            minutes_offset=1,
            supersedes=root.evaluation_id.value,
        )
        repository.append(corrected)
        assert repository.get(corrected.evaluation_id) == corrected

    def test_changed_snapshot_capture_config_and_hash_metadata_are_accepted(
        self, repository: EvaluationRepository
    ) -> None:
        root = make_envelope()
        repository.append(root)
        corrected = make_envelope(
            evaluation_id="SYNTHETIC-EVAL-1002",
            capture="SYNTHETIC-CAPTURE-0002",
            config_version="synthetic-fixture-1",
            minutes_offset=1,
            supersedes=root.evaluation_id.value,
        )
        corrected = dataclasses.replace(
            corrected,
            snapshot_id=SnapshotId("input_snapshot-corrected-synthetic"),
            input_hash=Sha256Digest("c" * 64),
            config_hash=Sha256Digest("d" * 64),
        )
        repository.append(corrected)
        assert repository.get(corrected.evaluation_id) == corrected

    def test_a_valid_chain_remains_traversable_after_the_coherence_rule(
        self, repository: EvaluationRepository
    ) -> None:
        root = make_envelope()
        child = make_envelope(
            evaluation_id="SYNTHETIC-EVAL-1002",
            pitcher="SYNTHETIC-PITCHER-0010",
            minutes_offset=1,
            supersedes=root.evaluation_id.value,
        )
        grandchild = make_envelope(
            evaluation_id="SYNTHETIC-EVAL-1003",
            minutes_offset=2,
            supersedes=child.evaluation_id.value,
        )
        repository.append(root)
        repository.append(child)
        repository.append(grandchild)

        current = repository.get(grandchild.evaluation_id)
        assert current is not None and current.supersedes is not None
        middle = repository.get(current.supersedes)
        assert middle is not None and middle.supersedes is not None
        assert repository.get(middle.supersedes) == root

    def test_profiles_coexist_but_cannot_supersede_each_other(
        self, repository: EvaluationRepository
    ) -> None:
        recent = make_envelope()
        long_term = make_envelope(
            evaluation_id="SYNTHETIC-EVAL-1002", profile=WindowProfile.LONG_TERM_2Y
        )
        repository.append(recent)
        repository.append(long_term)
        assert len(repository.query(EvaluationQuery())) == 2

        cross_profile = make_envelope(
            evaluation_id="SYNTHETIC-EVAL-1003",
            profile=WindowProfile.LONG_TERM_2Y,
            supersedes=recent.evaluation_id.value,
        )
        with pytest.raises(InvalidSupersessionError, match=r"same window profile"):
            repository.append(cross_profile)


# --------------------------------------------------------------------------
# Outcome repository contract
# --------------------------------------------------------------------------


class OutcomeRepositoryContract:
    """Every OutcomeRepository adapter must pass these unchanged."""

    @pytest.fixture
    def make_repository(self) -> Callable[[], OutcomeRepository]:
        raise NotImplementedError("adapter test class must supply a repository factory")

    @pytest.fixture
    def repository(self, make_repository: Callable[[], OutcomeRepository]) -> OutcomeRepository:
        return make_repository()

    def test_append_get_round_trip(self, repository: OutcomeRepository) -> None:
        revision = make_revision()
        repository.append(revision)
        assert repository.get(revision.outcome_revision_id) == revision

    def test_missing_get_returns_none(self, repository: OutcomeRepository) -> None:
        unknown = OutcomeRevisionId("outcome-revision-" + "0" * 64)
        assert repository.get(unknown) is None

    def test_empty_query_returns_empty_tuple(self, repository: OutcomeRepository) -> None:
        assert repository.query(OutcomeQuery()) == ()

    def test_a_bare_outcome_record_is_rejected(self, repository: OutcomeRepository) -> None:
        with pytest.raises(MalformedRepositoryInputError, match=r"create_outcome_revision"):
            repository.append(make_outcome())  # type: ignore[arg-type]

    def test_no_evaluation_can_enter(self, repository: OutcomeRepository) -> None:
        with pytest.raises(MalformedRepositoryInputError):
            repository.append(make_envelope())  # type: ignore[arg-type]

    def test_duplicate_revision_rejected_without_overwrite(
        self, repository: OutcomeRepository
    ) -> None:
        revision = make_revision()
        repository.append(revision)
        with pytest.raises(DuplicateRecordError):
            repository.append(make_revision())
        assert repository.get(revision.outcome_revision_id) == revision
        assert len(repository.query(OutcomeQuery())) == 1

    def test_invalid_inputs_are_translated(self, repository: OutcomeRepository) -> None:
        with pytest.raises(MalformedRepositoryInputError):
            repository.get("bare string")  # type: ignore[arg-type]
        with pytest.raises(MalformedRepositoryInputError):
            repository.query(SnapshotQuery())  # type: ignore[arg-type]

    @pytest.fixture
    def chain(self, repository: OutcomeRepository) -> tuple[OutcomeRevision, ...]:
        root = make_revision(homered=True)
        first = make_revision(homered=False, supersedes=root.outcome_revision_id)
        second = make_revision(homered=True, supersedes=first.outcome_revision_id)
        repository.append(root)
        repository.append(first)
        repository.append(second)
        return (root, first, second)

    def test_correction_chain_is_traversable(
        self, repository: OutcomeRepository, chain: tuple[OutcomeRevision, ...]
    ) -> None:
        root, first, second = chain
        current = repository.get(second.outcome_revision_id)
        assert current is not None and current.supersedes is not None
        parent = repository.get(current.supersedes)
        assert parent == first and parent.supersedes is not None
        origin = repository.get(parent.supersedes)
        assert origin == root and origin.supersedes is None

    def test_old_outcomes_remain_readable(
        self, repository: OutcomeRepository, chain: tuple[OutcomeRevision, ...]
    ) -> None:
        root, first, second = chain
        assert repository.get(root.outcome_revision_id) == root
        assert repository.get(first.outcome_revision_id) == first
        assert repository.get(second.outcome_revision_id) == second

    def test_query_by_game_id(self, repository: OutcomeRepository) -> None:
        repository.append(make_revision())
        repository.append(make_revision(game="SYNTHETIC-GAME-0002"))
        rows = repository.query(OutcomeQuery(game_id=GameId("SYNTHETIC-GAME-0002")))
        assert len(rows) == 1

    def test_query_by_batter_id(self, repository: OutcomeRepository) -> None:
        repository.append(make_revision())
        repository.append(make_revision(batter="SYNTHETIC-BATTER-0002"))
        rows = repository.query(OutcomeQuery(batter_id=PlayerId("SYNTHETIC-BATTER-0002")))
        assert len(rows) == 1

    def test_query_by_revision_id(
        self, repository: OutcomeRepository, chain: tuple[OutcomeRevision, ...]
    ) -> None:
        _, first, _ = chain
        rows = repository.query(OutcomeQuery(outcome_revision_id=first.outcome_revision_id))
        assert rows == (first,)

    def test_query_by_supersedes(
        self, repository: OutcomeRepository, chain: tuple[OutcomeRevision, ...]
    ) -> None:
        root, first, _ = chain
        rows = repository.query(OutcomeQuery(supersedes=root.outcome_revision_id))
        assert rows == (first,)

    def test_combined_filters_use_and(self, repository: OutcomeRepository) -> None:
        repository.append(make_revision())
        repository.append(make_revision(game="SYNTHETIC-GAME-0002"))
        rows = repository.query(
            OutcomeQuery(
                game_id=GameId("SYNTHETIC-GAME-0002"),
                batter_id=PlayerId("SYNTHETIC-BATTER-0001"),
            )
        )
        assert len(rows) == 1
        assert (
            repository.query(
                OutcomeQuery(
                    game_id=GameId("SYNTHETIC-GAME-0002"),
                    batter_id=PlayerId("SYNTHETIC-BATTER-0002"),
                )
            )
            == ()
        )

    def test_order_is_deterministic_across_append_permutations(
        self, make_repository: Callable[[], OutcomeRepository]
    ) -> None:
        root = make_revision(homered=True)
        child = make_revision(homered=False, supersedes=root.outcome_revision_id)
        other_game = make_revision(game="SYNTHETIC-GAME-0002")
        other_batter = make_revision(batter="SYNTHETIC-BATTER-0002")

        first = make_repository()
        for record in (root, child, other_game, other_batter):
            first.append(record)
        second = make_repository()
        # Parents must precede children; everything else is permuted.
        for record in (other_batter, other_game, root, child):
            second.append(record)

        assert first.query(OutcomeQuery()) == second.query(OutcomeQuery())
        ordered = first.query(
            OutcomeQuery(
                game_id=GameId("SYNTHETIC-GAME-0001"), batter_id=PlayerId("SYNTHETIC-BATTER-0001")
            )
        )
        # Root-first by chain depth, never append order.
        assert ordered == (root, child)

    def test_missing_parent_is_rejected(self, repository: OutcomeRepository) -> None:
        dangling = OutcomeRevisionId("outcome-revision-" + "1" * 64)
        orphan = make_revision(supersedes=dangling)
        with pytest.raises(MissingSupersededParentError):
            repository.append(orphan)
        assert repository.query(OutcomeQuery()) == ()

    def test_parent_child_game_mismatch_is_rejected(self, repository: OutcomeRepository) -> None:
        root = make_revision()
        repository.append(root)
        wrong_game = make_revision(game="SYNTHETIC-GAME-0002", supersedes=root.outcome_revision_id)
        with pytest.raises(InvalidSupersessionError, match=r"same game"):
            repository.append(wrong_game)
        assert len(repository.query(OutcomeQuery())) == 1

    def test_parent_child_batter_mismatch_is_rejected(self, repository: OutcomeRepository) -> None:
        root = make_revision()
        repository.append(root)
        wrong_batter = make_revision(
            batter="SYNTHETIC-BATTER-0002", supersedes=root.outcome_revision_id
        )
        with pytest.raises(InvalidSupersessionError, match=r"same batter"):
            repository.append(wrong_batter)

    def test_branching_correction_is_rejected(self, repository: OutcomeRepository) -> None:
        root = make_revision(homered=True)
        first = make_revision(homered=False, supersedes=root.outcome_revision_id)
        fork = make_revision(homered=True, supersedes=root.outcome_revision_id)
        repository.append(root)
        repository.append(first)
        with pytest.raises(BranchingSupersessionError):
            repository.append(fork)
        assert repository.get(fork.outcome_revision_id) is None
        assert len(repository.query(OutcomeQuery())) == 2

    def test_separate_instances_share_no_state(
        self, make_repository: Callable[[], OutcomeRepository]
    ) -> None:
        first, second = make_repository(), make_repository()
        revision = make_revision()
        first.append(revision)
        assert second.get(revision.outcome_revision_id) is None

"""The postgame outcome, stored entirely apart from any evaluation (ADR-0006).

An outcome is what actually happened; an evaluation is a pregame judgement. Fusing
them makes a pregame record mutable and hands every reader the future. So the
outcome is its own minimal contract, carrying only game and batter identity and
the single fact backtesting needs — whether the batter hit at least one home run.

There is deliberately no field here for a grade, signal, wager, odds, profit, or
timestamp, and — enforced structurally elsewhere — no outcome-shaped field on any
evaluation contract. Research joins the two at analysis time, explicitly. Sprint 1
delivers this contract and its tests only; no outcome ingestion exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._guards import ensure_bool, ensure_instance
from .values import GameId, PlayerId

__all__ = ["OutcomeRecord"]


@dataclass(frozen=True, slots=True)
class OutcomeRecord:
    """One batter's home-run outcome in one game. Immutable and hashable.

    ``hit_at_least_one_home_run`` is a strict ``bool`` — ``1``/``0`` or ``"true"``
    are refused, so the outcome can never be a truthy stand-in.
    """

    game_id: GameId
    batter_id: PlayerId
    hit_at_least_one_home_run: bool

    def __post_init__(self) -> None:
        ensure_instance(self.game_id, GameId, "OutcomeRecord.game_id")
        ensure_instance(self.batter_id, PlayerId, "OutcomeRecord.batter_id")
        ensure_bool(self.hit_at_least_one_home_run, "OutcomeRecord.hit_at_least_one_home_run")

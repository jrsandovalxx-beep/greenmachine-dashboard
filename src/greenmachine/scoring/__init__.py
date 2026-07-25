"""The grading core: bucket resolution, aggregation, and grades.

Pure and deterministic (GM-041): a :class:`~greenmachine.domain.GradeResult`
is a function of ``(frozen InputSnapshot, loaded GreenMachineConfig)`` and
nothing else. No I/O, no clock, no randomness, no network, no pandas, no
provider knowledge, and no imports from ``ingestion``, ``persistence``,
``reporting``, or ``features``. Every awarded and withheld point explains
itself in the ordered audit derivation.

No production configuration exists (Q11-Q16 remain open Product Owner
decisions): every executable configuration in this repository is a loudly
disclaimed synthetic fixture, and the engine never embeds a threshold.
"""

from __future__ import annotations

from .engine import OBSERVED_VALUE_INPUT_NAME, score_snapshot
from .errors import ScoringConfigError, ScoringError, ScoringInputError

__all__ = [
    "OBSERVED_VALUE_INPUT_NAME",
    "ScoringConfigError",
    "ScoringError",
    "ScoringInputError",
    "score_snapshot",
]

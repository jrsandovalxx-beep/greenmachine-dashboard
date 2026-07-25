"""Typed, fail-closed errors for the deterministic grading engine.

Every error is a :class:`~greenmachine.common.errors.GreenMachineError`
subclass carrying a deterministic message: the engine never swallows a
problem, never substitutes a value, and never lets an incidental exception
leak. A configuration/snapshot disagreement is an error — not a guess.
"""

from __future__ import annotations

from greenmachine.common.errors import GreenMachineError

__all__ = ["ScoringConfigError", "ScoringError", "ScoringInputError"]


class ScoringError(GreenMachineError):
    """Base class for every grading-engine failure."""


class ScoringInputError(ScoringError):
    """The snapshot cannot be scored under the supplied configuration.

    Examples: a configured component with neither a present nor a missing
    observation; a missing reason the configuration did not anticipate; an
    observed value outside its declared scoring domain; both mutually
    exclusive attack-angle measurements present at once.
    """


class ScoringConfigError(ScoringError):
    """The configuration cannot be executed deterministically as written.

    Examples: a binary predicate referencing an input name the engine cannot
    resolve from the snapshot; a profile scoring block missing for the
    observed measurement. Structural and semantic validity are already
    enforced at load time (MODEL_SPEC §19); this covers execution-time
    resolution only.
    """

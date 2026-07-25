"""The GM-030 manual-review worksheet: user-entered scoring only.

This is explicitly **not** the GreenMachine scoring engine. The user assigns
every category by hand; the module only enforces the allowed ranges, tracks
completeness, sums arithmetic, derives the frozen tier, and produces
deterministic exports. It generates no recommendation of any kind and no
timestamp of its own — a timestamp appears in an export only when the user
explicitly typed one.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from greenmachine.common.serialization import canonical_bytes

__all__ = [
    "CATEGORIES",
    "MANUAL_REVIEW_DISCLAIMER",
    "CategorySpec",
    "ManualReview",
    "ManualReviewError",
    "ReviewContext",
    "export_review_csv",
    "export_review_json",
    "tier_for_total",
]

MANUAL_REVIEW_DISCLAIMER = "manual user review — not automated GreenMachine scoring"


class ManualReviewError(ValueError):
    """A worksheet input outside its allowed range."""


@dataclass(frozen=True, slots=True)
class CategorySpec:
    key: str
    label: str
    maximum: int


# The five research categories with their frozen point ceilings.
CATEGORIES: tuple[CategorySpec, ...] = (
    CategorySpec(key="power_profile", label="Power Profile", maximum=3),
    CategorySpec(key="pitcher_matchup", label="Pitcher Matchup", maximum=3),
    CategorySpec(key="form", label="Form", maximum=2),
    CategorySpec(key="pull_power", label="Pull Power", maximum=2),
    CategorySpec(key="environment", label="Environment", maximum=2),
)

_MAX_BY_KEY = {spec.key: spec.maximum for spec in CATEGORIES}

# The frozen manual tier bands over the 0-12 arithmetic total.
_TIERS: tuple[tuple[str, int, int], ...] = (
    ("S", 10, 12),
    ("A", 8, 9),
    ("B", 6, 7),
    ("C", 4, 5),
    ("D", 0, 3),
)


def tier_for_total(total: int) -> str:
    for tier, low, high in _TIERS:
        if low <= total <= high:
            return tier
    raise ManualReviewError(f"a manual total of {total} is outside the 0-12 range")


@dataclass(frozen=True, slots=True)
class ManualReview:
    """One worksheet's state. ``None`` means the category is not yet scored.

    Construction **canonicalizes**: scores and rationales are validated
    (exactly one entry per approved category, no duplicate/unknown/missing
    keys, approved types and ranges) and re-ordered into the frozen
    ``CATEGORIES`` order. Every display total, the tier, and both exports
    read the same canonical mapping, so they can never disagree — and two
    inputs differing only in tuple order construct equal reviews with
    byte-identical exports.
    """

    scores: tuple[tuple[str, int | None], ...]
    notes: str = ""
    rationales: tuple[tuple[str, str], ...] = ()
    user_entered_timestamp: str | None = None

    def __post_init__(self) -> None:
        score_keys = [key for key, _ in self.scores]
        if len(score_keys) != len(set(score_keys)):
            duplicates = sorted({key for key in score_keys if score_keys.count(key) > 1})
            raise ManualReviewError(f"duplicate score entr(y/ies) for {duplicates}")
        recorded = dict(self.scores)
        if sorted(recorded) != sorted(_MAX_BY_KEY):
            raise ManualReviewError(
                f"a review must carry exactly one score entry for each of {sorted(_MAX_BY_KEY)}"
            )
        for key, score in recorded.items():
            candidate: object = score
            if candidate is None:
                continue
            if isinstance(candidate, bool) or not isinstance(candidate, int):
                raise ManualReviewError(f"the {key} score must be an integer or unscored")
            if not 0 <= candidate <= _MAX_BY_KEY[key]:
                raise ManualReviewError(f"the {key} score must be between 0 and {_MAX_BY_KEY[key]}")

        rationale_keys = [key for key, _ in self.rationales]
        if len(rationale_keys) != len(set(rationale_keys)):
            raise ManualReviewError("duplicate rationale entries are not allowed")
        rationale_map = dict(self.rationales)
        for key, value in rationale_map.items():
            if key not in _MAX_BY_KEY:
                raise ManualReviewError(f"a rationale references unknown category '{key}'")
            value_candidate: object = value
            if not isinstance(value_candidate, str):
                raise ManualReviewError(f"the {key} rationale must be a string")
        notes_candidate: object = self.notes
        if not isinstance(notes_candidate, str):
            raise ManualReviewError("notes must be a string")
        timestamp_candidate: object = self.user_entered_timestamp
        if timestamp_candidate is not None and not isinstance(timestamp_candidate, str):
            raise ManualReviewError("user_entered_timestamp must be a string or None")

        # Canonicalize: one ordering for every consumer (display, tier, exports).
        object.__setattr__(
            self,
            "scores",
            tuple((spec.key, recorded[spec.key]) for spec in CATEGORIES),
        )
        object.__setattr__(
            self,
            "rationales",
            tuple((spec.key, rationale_map.get(spec.key, "")) for spec in CATEGORIES),
        )

    @property
    def is_complete(self) -> bool:
        return all(score is not None for _, score in self.scores)

    @property
    def partial_total(self) -> int:
        """The running arithmetic sum over the categories scored so far."""
        return sum(score for _, score in self.scores if score is not None)

    @property
    def total(self) -> int | None:
        """The final total — only once every category is scored."""
        return self.partial_total if self.is_complete else None

    @property
    def tier(self) -> str | None:
        """The frozen manual tier — only once every category is scored."""
        total = self.total
        return tier_for_total(total) if total is not None else None


@dataclass(frozen=True, slots=True)
class ReviewContext:
    """The archived-run identities an export is anchored to."""

    game_id: str
    batter_id: str
    pitcher_id: str
    source_capture_id: str
    recent_snapshot_id: str
    long_term_snapshot_id: str
    run_name: str = field(default="")


def _export_document(review: ManualReview, context: ReviewContext) -> dict[str, object]:
    scores = dict(review.scores)
    rationales = dict(review.rationales)
    return {
        "disclaimer": MANUAL_REVIEW_DISCLAIMER,
        "game_id": context.game_id,
        "batter_id": context.batter_id,
        "pitcher_id": context.pitcher_id,
        "source_capture_id": context.source_capture_id,
        "recent_snapshot_id": context.recent_snapshot_id,
        "long_term_snapshot_id": context.long_term_snapshot_id,
        "run_name": context.run_name,
        "categories": [
            {
                "category": spec.key,
                "label": spec.label,
                "maximum": spec.maximum,
                "score": scores[spec.key],
                "rationale": rationales.get(spec.key, ""),
            }
            for spec in CATEGORIES
        ],
        "complete": review.is_complete,
        "partial_total": review.partial_total,
        "total": review.total,
        "tier": review.tier,
        "notes": review.notes,
        "user_entered_timestamp": review.user_entered_timestamp,
    }


def export_review_json(review: ManualReview, context: ReviewContext) -> bytes:
    """Deterministic canonical JSON export. No clock is read anywhere."""
    return canonical_bytes(_export_document(review, context))


def export_review_csv(review: ManualReview, context: ReviewContext) -> bytes:
    """Deterministic CSV summary (one row per category plus a summary row)."""
    scores = dict(review.scores)
    rationales = dict(review.rationales)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["disclaimer", MANUAL_REVIEW_DISCLAIMER])
    writer.writerow(["game_id", context.game_id])
    writer.writerow(["batter_id", context.batter_id])
    writer.writerow(["pitcher_id", context.pitcher_id])
    writer.writerow(["source_capture_id", context.source_capture_id])
    writer.writerow(["recent_snapshot_id", context.recent_snapshot_id])
    writer.writerow(["long_term_snapshot_id", context.long_term_snapshot_id])
    writer.writerow([])
    writer.writerow(["category", "label", "maximum", "score", "rationale"])
    for spec in CATEGORIES:
        score = scores[spec.key]
        writer.writerow(
            [
                spec.key,
                spec.label,
                spec.maximum,
                "" if score is None else score,
                rationales.get(spec.key, ""),
            ]
        )
    writer.writerow([])
    writer.writerow(["complete", str(review.is_complete).lower()])
    writer.writerow(["partial_total", review.partial_total])
    writer.writerow(["total", "" if review.total is None else review.total])
    writer.writerow(["tier", "" if review.tier is None else review.tier])
    writer.writerow(["notes", review.notes])
    writer.writerow(
        [
            "user_entered_timestamp",
            "" if review.user_entered_timestamp is None else review.user_entered_timestamp,
        ]
    )
    return buffer.getvalue().encode("utf-8")

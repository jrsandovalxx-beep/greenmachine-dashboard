"""The manual-review worksheet: ranges, completeness, tiers, deterministic exports."""

from __future__ import annotations

import json

import pytest

from greenmachine.reporting import (
    CATEGORIES,
    MANUAL_REVIEW_DISCLAIMER,
    ManualReview,
    ManualReviewError,
    ReviewContext,
    export_review_csv,
    export_review_json,
    tier_for_total,
)

CONTEXT = ReviewContext(
    game_id="823196",
    batter_id="646240",
    pitcher_id="680570",
    source_capture_id="source_capture-" + "f" * 64,
    recent_snapshot_id="input_snapshot-" + "a" * 64,
    long_term_snapshot_id="input_snapshot-" + "b" * 64,
    run_name="prospective_run",
)


def _review(**scores: int | None) -> ManualReview:
    base: dict[str, int | None] = {spec.key: None for spec in CATEGORIES}
    base.update(scores)
    return ManualReview(scores=tuple(base.items()))


def test_the_categories_and_maxima_are_frozen() -> None:
    assert [(spec.key, spec.maximum) for spec in CATEGORIES] == [
        ("power_profile", 3),
        ("pitcher_matchup", 3),
        ("form", 2),
        ("pull_power", 2),
        ("environment", 2),
    ]


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("power_profile", 4),
        ("pitcher_matchup", -1),
        ("form", 3),
        ("pull_power", 3),
        ("environment", 3),
    ],
)
def test_out_of_range_scores_are_rejected(key: str, bad: int) -> None:
    with pytest.raises(ManualReviewError, match="between 0 and"):
        _review(**{key: bad})


def test_a_boolean_score_is_rejected() -> None:
    with pytest.raises(ManualReviewError, match="integer or unscored"):
        _review(power_profile=True)  # type: ignore[arg-type]


def test_a_missing_category_is_rejected() -> None:
    with pytest.raises(ManualReviewError, match="exactly one score entry"):
        ManualReview(scores=(("power_profile", 2),))


def test_an_incomplete_review_has_no_final_total_or_tier() -> None:
    review = _review(power_profile=3, form=2)
    assert not review.is_complete
    assert review.partial_total == 5
    assert review.total is None
    assert review.tier is None


def test_a_complete_review_totals_and_tiers() -> None:
    review = _review(power_profile=3, pitcher_matchup=3, form=2, pull_power=2, environment=2)
    assert review.is_complete
    assert review.total == 12
    assert review.tier == "S"


@pytest.mark.parametrize(
    ("total", "tier"),
    [
        (12, "S"),
        (10, "S"),
        (9, "A"),
        (8, "A"),
        (7, "B"),
        (6, "B"),
        (5, "C"),
        (4, "C"),
        (3, "D"),
        (0, "D"),
    ],
)
def test_tier_boundaries_are_exact(total: int, tier: str) -> None:
    assert tier_for_total(total) == tier


def test_totals_outside_the_band_are_rejected() -> None:
    with pytest.raises(ManualReviewError):
        tier_for_total(13)
    with pytest.raises(ManualReviewError):
        tier_for_total(-1)


def test_json_export_is_deterministic_and_disclaimed() -> None:
    review = _review(power_profile=2, pitcher_matchup=1, form=1, pull_power=0, environment=2)
    first = export_review_json(review, CONTEXT)
    second = export_review_json(review, CONTEXT)
    assert first == second  # bit-identical on repeat

    document = json.loads(first.decode("utf-8"))
    assert document["disclaimer"] == MANUAL_REVIEW_DISCLAIMER
    assert document["game_id"] == "823196"
    assert document["batter_id"] == "646240"
    assert document["pitcher_id"] == "680570"
    assert document["source_capture_id"].startswith("source_capture-")
    assert document["recent_snapshot_id"] != document["long_term_snapshot_id"]
    assert document["total"] == 6
    assert document["tier"] == "B"


def test_csv_export_is_deterministic_and_disclaimed() -> None:
    review = _review(power_profile=2, pitcher_matchup=1, form=1, pull_power=0, environment=2)
    first = export_review_csv(review, CONTEXT)
    assert first == export_review_csv(review, CONTEXT)
    text = first.decode("utf-8")
    assert MANUAL_REVIEW_DISCLAIMER in text
    assert "823196" in text
    assert "tier,B" in text


def test_no_implicit_timestamp_ever_appears() -> None:
    review = _review()
    document = json.loads(export_review_json(review, CONTEXT).decode("utf-8"))
    assert document["user_entered_timestamp"] is None
    # Only an explicitly user-entered value is carried through, verbatim.
    stamped = ManualReview(scores=review.scores, user_entered_timestamp="written by the reviewer")
    stamped_doc = json.loads(export_review_json(stamped, CONTEXT).decode("utf-8"))
    assert stamped_doc["user_entered_timestamp"] == "written by the reviewer"


def test_no_signal_or_recommendation_is_generated() -> None:
    review = _review(power_profile=3, pitcher_matchup=3, form=2, pull_power=2, environment=2)
    rendered = (export_review_json(review, CONTEXT) + export_review_csv(review, CONTEXT)).decode(
        "utf-8"
    )
    for banned in ("STRONG_BET", "LEAN", "PASS", "AVOID", "recommendation", "signal"):
        assert banned not in rendered, banned


# --------------------------------------------------------------------------
# GM-030-r1: one canonical category mapping — no duplicate/incoherent state
# --------------------------------------------------------------------------


def test_a_duplicate_score_key_is_rejected() -> None:
    scores = (
        ("power_profile", 3),
        ("power_profile", 1),  # the reviewer-confirmed incoherence shape
        ("pitcher_matchup", 3),
        ("form", 2),
        ("pull_power", 2),
        ("environment", 2),
    )
    with pytest.raises(ManualReviewError, match="duplicate score"):
        ManualReview(scores=scores)


def test_a_duplicate_rationale_key_is_rejected() -> None:
    review_scores = tuple((spec.key, 1 if spec.maximum >= 1 else 0) for spec in CATEGORIES)
    with pytest.raises(ManualReviewError, match="duplicate rationale"):
        ManualReview(
            scores=review_scores,
            rationales=(("form", "first"), ("form", "second")),
        )


def test_an_unknown_rationale_key_is_rejected() -> None:
    review_scores = tuple((spec.key, None) for spec in CATEGORIES)
    with pytest.raises(ManualReviewError, match="unknown category"):
        ManualReview(scores=review_scores, rationales=(("velocity", "x"),))


def test_non_string_notes_rationale_and_timestamp_are_rejected() -> None:
    review_scores = tuple((spec.key, None) for spec in CATEGORIES)
    with pytest.raises(ManualReviewError, match="notes must be a string"):
        ManualReview(scores=review_scores, notes=7)  # type: ignore[arg-type]
    with pytest.raises(ManualReviewError, match="rationale must be a string"):
        ManualReview(scores=review_scores, rationales=(("form", 7),))  # type: ignore[arg-type]
    with pytest.raises(ManualReviewError, match="timestamp must be a string or None"):
        ManualReview(scores=review_scores, user_entered_timestamp=7)  # type: ignore[arg-type]


def test_input_order_produces_one_canonical_state_and_identical_exports() -> None:
    forward = ManualReview(
        scores=(
            ("power_profile", 2),
            ("pitcher_matchup", 1),
            ("form", 1),
            ("pull_power", 0),
            ("environment", 2),
        ),
        rationales=(("environment", "wind note"), ("form", "swing note")),
    )
    shuffled = ManualReview(
        scores=(
            ("environment", 2),
            ("form", 1),
            ("pull_power", 0),
            ("power_profile", 2),
            ("pitcher_matchup", 1),
        ),
        rationales=(("form", "swing note"), ("environment", "wind note")),
    )
    assert forward == shuffled  # one canonical normalized state
    assert export_review_json(forward, CONTEXT) == export_review_json(shuffled, CONTEXT)
    assert export_review_csv(forward, CONTEXT) == export_review_csv(shuffled, CONTEXT)


def test_totals_tier_and_exports_read_one_coherent_mapping() -> None:
    review = _review(power_profile=3, pitcher_matchup=2, form=1, pull_power=1, environment=1)
    document = json.loads(export_review_json(review, CONTEXT).decode("utf-8"))
    categories = {entry["category"]: entry["score"] for entry in document["categories"]}
    assert sum(categories.values()) == review.total == document["total"] == 8
    assert document["tier"] == review.tier == "A"
    csv_text = export_review_csv(review, CONTEXT).decode("utf-8")
    assert "total,8" in csv_text and "tier,A" in csv_text


def test_app_shaped_worksheets_remain_valid() -> None:
    """The composition root builds exactly one entry per category, in
    CATEGORIES order, with all-five rationales — that shape stays valid."""
    review = ManualReview(
        scores=tuple((spec.key, 0) for spec in CATEGORIES),
        notes="",
        rationales=tuple((spec.key, "") for spec in CATEGORIES),
        user_entered_timestamp=None,
    )
    assert review.is_complete and review.total == 0 and review.tier == "D"


def test_exports_never_mention_whiff() -> None:
    review = _review(power_profile=1)
    rendered = (export_review_json(review, CONTEXT) + export_review_csv(review, CONTEXT)).decode(
        "utf-8"
    )
    assert "whiff" not in rendered.lower()

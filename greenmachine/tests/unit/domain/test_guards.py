"""Defensive type rejection at the construction boundary.

``mypy --strict`` covers ``src/``, but the domain is also constructed from
ingestion adapters and deserialized records, where a wrong type can arrive at
runtime. These paths must fail with a typed :class:`DomainValidationError` naming
the field — not with an incidental ``AttributeError`` from deep inside a guard.

Each case deliberately passes a type the annotation forbids, so the ``type:
ignore`` comments are the point of the test rather than a workaround.
"""

from __future__ import annotations

from datetime import date

import pytest
from domain_builders import make_coverage, make_game_context, make_observation

from greenmachine.domain import DomainValidationError, GameId


def test_identifier_rejects_a_non_string_value() -> None:
    with pytest.raises(DomainValidationError, match=r"must be a string"):
        GameId(12345)  # type: ignore[arg-type]


def test_window_bound_rejects_a_non_datetime() -> None:
    with pytest.raises(DomainValidationError, match=r"must be a datetime"):
        make_observation(window_start="2026-07-08T16:30:00Z")


def test_sample_count_rejects_a_non_integer() -> None:
    with pytest.raises(DomainValidationError, match=r"must be an int"):
        make_observation(sample_count="42")


def test_sample_count_rejects_a_bool() -> None:
    """``bool`` is a subclass of ``int``; a flag is never a sample count."""
    with pytest.raises(DomainValidationError, match=r"must be an int"):
        make_observation(sample_count=True)


def test_coverage_sample_count_rejects_a_non_integer() -> None:
    with pytest.raises(DomainValidationError, match=r"must be an int"):
        make_coverage(sample_count=1.5)


def test_slate_date_rejects_a_non_date() -> None:
    with pytest.raises(DomainValidationError, match=r"GameContext\.slate_date must be date"):
        make_game_context(slate_date="2026-07-15")


def test_slate_date_accepts_a_real_date() -> None:
    context = make_game_context(slate_date=date(2026, 7, 15))

    assert context.slate_date == date(2026, 7, 15)

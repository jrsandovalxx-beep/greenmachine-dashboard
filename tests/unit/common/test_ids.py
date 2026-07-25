"""Content-derived identifiers: repeatable, content- and namespace-sensitive."""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from greenmachine.common import (
    DIGEST_ALGORITHM,
    CanonicalizationError,
    IdentifierError,
    canonical_bytes,
    content_digest,
    deterministic_id,
)


@dataclasses.dataclass(frozen=True)
class Sample:
    name: str
    value: Decimal


CONTENT = {"profile": "RECENT_7D", "value": Decimal("12.34"), "count": 42}


# --------------------------------------------------------------------------
# content_digest
# --------------------------------------------------------------------------


def test_digest_is_sha256_over_canonical_bytes() -> None:
    expected = hashlib.sha256(canonical_bytes(CONTENT)).hexdigest()

    assert content_digest(CONTENT) == expected
    assert DIGEST_ALGORITHM == "sha256"


def test_digest_is_repeatable() -> None:
    assert len({content_digest(CONTENT) for _ in range(50)}) == 1


def test_digest_is_a_64_character_hex_string() -> None:
    digest = content_digest(CONTENT)

    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_digest_ignores_mapping_insertion_order() -> None:
    first = {"a": 1, "b": 2}
    second = {"b": 2, "a": 1}

    assert content_digest(first) == content_digest(second)


def test_equal_decimals_produce_the_same_digest() -> None:
    assert content_digest(Decimal("2.50")) == content_digest(Decimal("2.5"))


def test_digest_changes_when_content_changes() -> None:
    changed = dict(CONTENT) | {"count": 43}

    assert content_digest(changed) != content_digest(CONTENT)


def test_digest_changes_for_a_different_decimal_value() -> None:
    assert content_digest(Decimal("1.01")) != content_digest(Decimal("1.02"))


def test_digest_distinguishes_structure() -> None:
    assert content_digest([1, 2]) != content_digest([2, 1])
    assert content_digest({"a": 1}) != content_digest([["a", 1]])


def test_digest_handles_dataclasses_and_datetimes() -> None:
    record = Sample("x", Decimal("1.0"))
    moment = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)

    assert content_digest(record) == content_digest(Sample("x", Decimal("1")))
    assert len(content_digest({"at": moment})) == 64


def test_digest_refuses_unsupported_content() -> None:
    with pytest.raises(CanonicalizationError):
        content_digest({"bad": 1.5})


# --------------------------------------------------------------------------
# deterministic_id
# --------------------------------------------------------------------------


def test_identifier_is_repeatable() -> None:
    assert deterministic_id("snapshot", CONTENT) == deterministic_id("snapshot", CONTENT)


def test_identifier_carries_its_namespace_prefix() -> None:
    identifier = deterministic_id("snapshot", CONTENT)

    assert identifier.startswith("snapshot-")
    assert len(identifier) == len("snapshot-") + 64


def test_identifier_changes_with_content() -> None:
    first = deterministic_id("snapshot", {"a": 1})
    second = deterministic_id("snapshot", {"a": 2})

    assert first != second


def test_identifier_changes_with_namespace() -> None:
    """Namespace is hashed with the content, not merely prefixed onto the digest."""
    first = deterministic_id("snapshot", CONTENT)
    second = deterministic_id("evaluation", CONTENT)

    assert first != second
    assert first.split("-", 1)[1] != second.split("-", 1)[1]


def test_identical_content_under_two_namespaces_does_not_share_a_digest() -> None:
    snapshot = deterministic_id("snapshot", CONTENT).split("-", 1)[1]
    outcome = deterministic_id("outcome", CONTENT).split("-", 1)[1]

    assert snapshot != outcome


@pytest.mark.parametrize("namespace", ["", "   ", "\t"])
def test_empty_namespace_is_refused(namespace: str) -> None:
    with pytest.raises(IdentifierError, match=r"non-empty"):
        deterministic_id(namespace, CONTENT)


def test_non_string_namespace_is_refused() -> None:
    with pytest.raises(IdentifierError, match=r"must be a string"):
        deterministic_id(7, CONTENT)  # type: ignore[arg-type]


def test_identifier_refuses_unsupported_content() -> None:
    with pytest.raises(CanonicalizationError):
        deterministic_id("snapshot", {"bad": {1.5}})


def test_no_randomness_two_ids_of_equal_content_match() -> None:
    """No UUID4, no clock, no process hash seed anywhere in the derivation."""
    left = deterministic_id("snapshot", Sample("x", Decimal("1.00")))
    right = deterministic_id("snapshot", Sample("x", Decimal("1")))

    assert left == right

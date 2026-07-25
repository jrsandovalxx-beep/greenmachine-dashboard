"""The Sha256Digest domain reference: validate a stored hash, never compute one."""

from __future__ import annotations

import dataclasses

import pytest

from greenmachine.domain import DomainValidationError, Sha256Digest

VALID = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"


def test_a_valid_digest_is_accepted_and_exposed() -> None:
    assert Sha256Digest(VALID).value == VALID
    assert str(Sha256Digest(VALID)) == VALID


def test_the_value_object_does_not_compute_a_hash() -> None:
    # It is constructed from a stored string with no content present.
    assert Sha256Digest("0" * 64).value == "0" * 64


def test_it_is_frozen_and_hashable() -> None:
    digest = Sha256Digest(VALID)
    assert hash(digest) == hash(Sha256Digest(VALID))
    assert digest == Sha256Digest(VALID)
    with pytest.raises(dataclasses.FrozenInstanceError):
        digest.value = "b" * 64  # type: ignore[misc]


@pytest.mark.parametrize(
    "bad",
    [
        "A" * 64,  # uppercase
        "a" * 63,  # too short
        "a" * 65,  # too long
        "a" * 63 + "g",  # non-hex
        " " + "a" * 63,  # whitespace
        "a" * 63 + "\n",  # trailing newline
        "",  # empty
    ],
)
def test_a_malformed_digest_is_rejected(bad: str) -> None:
    with pytest.raises(DomainValidationError):
        Sha256Digest(bad)


@pytest.mark.parametrize("bad", [123, b"a" * 64, None, ["a" * 64]])
def test_a_non_string_digest_is_rejected(bad: object) -> None:
    with pytest.raises(DomainValidationError):
        Sha256Digest(bad)  # type: ignore[arg-type]

"""Strict JSON parsing for GreenMachine-owned documents.

Ordinary ``json.loads`` silently keeps the **last** value when an object
repeats a key — which would let a hostile or corrupted document smuggle a
second value past field-set validation. Every GreenMachine-owned document
(the capture manifest, the replay inputs, the sample-minimum policy) is
parsed through this loader instead, which rejects duplicate keys at every
object nesting level and reports malformed JSON through the caller's own
deterministic error type.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from greenmachine.common.errors import GreenMachineError

__all__ = ["strict_json_loads"]


class _DuplicateKeyError(ValueError):
    """Internal signal: a JSON object repeated a key."""


def _rejecting_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def strict_json_loads(
    raw: bytes, *, describe: str, on_error: Callable[[str], GreenMachineError]
) -> object:
    """Parse ``raw`` strictly; duplicate keys and malformed JSON fail closed.

    ``on_error`` builds the caller's deterministic ingestion error from a
    message, so manifest problems and policy problems keep their own types.
    """
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_rejecting_pairs)
    except _DuplicateKeyError as duplicate:
        raise on_error(f"{describe} carries a {duplicate}") from duplicate
    except (UnicodeDecodeError, json.JSONDecodeError) as malformed:
        raise on_error(f"{describe} is not valid JSON: {malformed}") from malformed

"""Content-derived identifiers: same content in, same identifier out, forever.

Identifiers are derived from what they identify — never from a random source, a
clock, or the process's ``hash()`` (ENGINEERING_GUIDELINES D3, and the GM-005
acceptance criteria: "no randomness, no UUID4, no time"). That is what lets an
archived record be recomputed years later and still match.

SHA-256 over :func:`~greenmachine.common.serialization.canonical_bytes` gives all
of this for free: the canonical encoding is already byte-stable across processes,
platforms, and ``PYTHONHASHSEED`` values, so the digest is too.

These helpers stay generic. Building ``SnapshotId``, ``EvaluationId``, or any
composite record is GM-006's work, not theirs.
"""

from __future__ import annotations

import hashlib

from .errors import DataInputError
from .serialization import canonical_bytes

__all__ = ["DIGEST_ALGORITHM", "IdentifierError", "content_digest", "deterministic_id"]

DIGEST_ALGORITHM = "sha256"


class IdentifierError(DataInputError, ValueError):
    """An identifier could not be derived from the inputs given.

    Reparented under :class:`~greenmachine.common.errors.DataInputError` by
    GM-009; ``ValueError`` is retained for callers already catching it.
    """


def content_digest(content: object) -> str:
    """Return the SHA-256 hex digest of ``content``'s canonical bytes.

    Any change to the content changes the digest. Equal supported object graphs
    always produce the same digest, in any process on any machine.

    Raises:
        CanonicalizationError: if the content cannot be canonically serialized.
    """
    return hashlib.sha256(canonical_bytes(content)).hexdigest()


def deterministic_id(namespace: str, content: object) -> str:
    """Return a stable ``"<namespace>-<digest>"`` identifier for ``content``.

    The namespace is hashed **with** the content rather than merely prefixed onto
    the digest, so the same content under two namespaces yields two different
    digests. Without that, identical content would collide across record types
    and only the human-readable prefix would distinguish them.

    Args:
        namespace: A non-empty type or record prefix, e.g. ``"snapshot"``.
        content: Any canonically serializable object graph.

    Raises:
        IdentifierError: if the namespace is not a non-empty, non-blank string.
        CanonicalizationError: if the content cannot be canonically serialized.
    """
    if not isinstance(namespace, str):
        raise IdentifierError(f"namespace must be a string, got {type(namespace).__name__}")
    if not namespace.strip():
        raise IdentifierError("namespace must be a non-empty, non-blank string")

    digest = content_digest({"namespace": namespace, "content": content})
    return f"{namespace}-{digest}"

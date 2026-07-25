"""Semantic identity for a validated configuration: one hash per set of rules.

A stored evaluation has to be able to prove, years later, exactly which rules
produced it. That needs an identity derived from the configuration's *meaning* —
not from the bytes it happened to be typed in, because comments, indentation, key
order, and equivalent decimal spellings all change the bytes without changing a
single grade (ENGINEERING_GUIDELINES §"config_hash is semantic"; GLOSSARY).

Two facts are kept deliberately separate:

* :func:`config_hash` answers *did the meaning change?* It is computed over the
  fully validated, typed :class:`~greenmachine.config.schema.GreenMachineConfig`,
  so it is blind to everything textual.
* :func:`source_digest` answers *did the file change?* It is computed over the
  source text with newlines normalized, so a reworded comment moves it even
  though :func:`config_hash` stands still.

Neither invents its own canonical form. The semantic hash reuses GM-005's
canonical serialization and SHA-256 content hashing verbatim
(:func:`greenmachine.common.ids.content_digest`); there is no second serializer.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from greenmachine.common.ids import DIGEST_ALGORITHM, content_digest

from .errors import MalformedConfigHashError, context_for
from .schema import GreenMachineConfig

__all__ = [
    "ConfigHash",
    "config_hash",
    "semantic_projection",
    "source_digest",
]

# The human-assigned label is the one field excluded from semantic identity: two
# configurations with identical rules but different labels are the same rules.
_VERSION_LABEL_FIELD = "model_configuration_version"

# A SHA-256 digest in the one spelling we store: lowercase hex, exactly 64 chars.
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def is_sha256_hex(value: object) -> bool:
    """True when ``value`` is exactly one lowercase 64-character SHA-256 digest.

    The single definition of a well-formed digest, shared by :class:`ConfigHash`
    and the versioning layer's ``source_digest`` validation. The two fingerprints
    describe different facts and are deliberately different types, but they agree
    on what a valid digest string looks like — this is where that agreement lives.
    """
    return isinstance(value, str) and _SHA256_HEX.fullmatch(value) is not None


@dataclass(frozen=True)
class ConfigHash:
    """A validated semantic configuration digest — never a free-form string.

    Wraps exactly one lowercase 64-character SHA-256 hex digest. Construction
    *validates* the string it is given; it never computes a hash (that is
    :func:`config_hash`'s job), so a ``ConfigHash`` can be rebuilt from a stored
    value without the configuration being present.

    Frozen and hashable, so it is safe as a dict key, in a set, or on another
    frozen record. Uppercase, wrong length, whitespace, and non-hex are refused
    with :class:`~greenmachine.config.errors.MalformedConfigHashError`.
    """

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise MalformedConfigHashError(
                f"config hash must be a string, got {type(self.value).__name__}",
                context_for(None),
            )
        if not _SHA256_HEX.fullmatch(self.value):
            raise MalformedConfigHashError(
                f"config hash must be exactly 64 lowercase hexadecimal characters "
                f"(a {DIGEST_ALGORITHM} digest), got {self.value!r}",
                context_for(None),
            )

    def __str__(self) -> str:
        return self.value


def semantic_projection(config: GreenMachineConfig) -> dict[str, object]:
    """The exact data that defines a configuration's behavior.

    The whole validated model as canonically serializable values — Decimals stay
    Decimal so equivalent spellings collapse, enums carry their stable member
    value, sequences keep their order — with **one** field removed: the
    human-assigned ``model_configuration_version`` label, which names the rules
    but is not part of them (approved identity ruling).

    Building the projection by *removing* the single excluded field, rather than
    by listing the fields to keep, is deliberate: it makes it impossible to
    silently drop a behavior-affecting field when the schema grows. Nothing here
    is a Pydantic internal, a repr, a path, or any formatting — only field data.
    """
    if not isinstance(config, GreenMachineConfig):
        raise TypeError(
            f"semantic_projection expects a GreenMachineConfig, got {type(config).__name__}"
        )
    payload = config.model_dump(mode="python")
    payload.pop(_VERSION_LABEL_FIELD, None)
    return payload


def config_hash(config: GreenMachineConfig) -> ConfigHash:
    """Return the semantic :class:`ConfigHash` of a validated configuration.

    Deterministic, lowercase, SHA-256, and stable across processes, machines, and
    ``PYTHONHASHSEED`` values — every one of those guarantees comes from GM-005's
    :func:`~greenmachine.common.ids.content_digest`, which this reuses rather than
    reimplements. Unaffected by comments, indentation, key order, source newline
    style, or equivalent decimal spellings; changed by any behavior-affecting
    field (a threshold, an allocation, a cutoff, a policy, a profile).
    """
    return ConfigHash(content_digest(semantic_projection(config)))


def source_digest(source_text: str) -> str:
    """Return the newline-normalized SHA-256 hex fingerprint of source text.

    This is the *source* fingerprint, not the semantic hash: it deliberately
    moves when comments or formatting change. Newlines are normalized first —
    ``CRLF`` and a lone ``CR`` both become ``LF`` — so the same file checked out
    on Windows and on Linux fingerprints identically; every other character is
    preserved exactly.

    Never call this ``config_hash``: the two answer different questions.
    """
    if not isinstance(source_text, str):
        raise TypeError(
            f"source_digest expects source text as a str, got {type(source_text).__name__}"
        )
    normalized = source_text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

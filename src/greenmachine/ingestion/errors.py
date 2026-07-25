"""Ingestion-layer errors, extending the frozen GM-009 taxonomy.

Every type here subclasses the frozen :class:`~greenmachine.common.errors.IngestionError`
branch (schema drift additionally subclasses the frozen
:class:`~greenmachine.common.errors.ProviderSchemaChangeError`, which ADR-0007
singles out), so existing catch sites keep working and nothing frozen changes.

Messages are deterministic and carry no raw response bodies, secrets, object
reprs, or absolute paths — structured detail belongs on the
:class:`~greenmachine.common.errors.ErrorContext`.
"""

from __future__ import annotations

from greenmachine.common.errors import IngestionError, ProviderSchemaChangeError

__all__ = [
    "CapturePublicationError",
    "DigestMismatchError",
    "IdentityMismatchError",
    "IngestionEligibilityError",
    "IngestionModelError",
    "ProviderResponseError",
    "ProviderTransportError",
    "SamplePolicyError",
    "SchemaDriftError",
]


class ProviderTransportError(IngestionError):
    """The provider could not be reached: timeout, connection failure, interruption."""


class ProviderResponseError(IngestionError):
    """The provider answered, but the response is unusable (status, encoding, shape)."""


class SchemaDriftError(ProviderSchemaChangeError):
    """A provider response no longer matches its endpoint schema contract.

    Missing required fields, incompatible required types, and malformed payloads
    fail closed with this error; additive unknown fields do not raise — they are
    accepted and audited via the schema fingerprint.
    """


class IdentityMismatchError(IngestionError):
    """Provider identities disagree: a fail-closed cross-source integrity error."""


class DigestMismatchError(IngestionError):
    """Archived raw bytes no longer match their recorded SHA-256 digest."""


class CapturePublicationError(IngestionError):
    """A coordinated capture could not be published atomically."""


class IngestionEligibilityError(IngestionError):
    """The requested slice is not eligible for snapshot production.

    Raised (or recorded) when policy — not a provider fault — blocks the run:
    no identified expected pitcher, a non-pregame game in prospective mode, an
    ineligible game type, a postponed game.
    """


class IngestionModelError(IngestionError):
    """A provider-neutral ingestion record was constructed with invalid content."""


class SamplePolicyError(IngestionError):
    """The injected sample-minimum policy is missing, incomplete, or malformed."""

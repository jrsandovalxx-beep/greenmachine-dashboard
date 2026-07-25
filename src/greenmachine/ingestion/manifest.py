"""Deterministic capture identities and the canonical manifest document.

No UUIDs, no randomness, no clock-derived identity: every identifier here is
derived from content through the frozen GM-005
:func:`~greenmachine.common.ids.deterministic_id`, so an archived run can be
re-identified years later from its bytes alone.

Three identities exist, each over an explicit canonical projection:

* **request-capture identity** — deliberately narrow: provider, endpoint,
  canonical parameters, retrieval completion instant, HTTP status, and the
  exact raw digest;
* **manifest identity** — the **complete** canonical manifest content: every
  field the manifest document publishes, at the top level and per entry
  (including attempt histories, fingerprints, contract versions, artifact
  paths, and participation flags), excluding only the recorded
  ``manifest_id`` itself and using **recomputed** capture identities rather
  than trusting recorded values. Changing any published manifest field
  changes the ``manifest_id``;
* **domain ``SourceCaptureId``** — the approved spike convention: derived only
  from the sorted ``(label, sha256)`` pairs of **participating** captures.
  Paths, reports, normalized output, comparison artifacts, non-participating
  captures, filesystem metadata, and retrieval timing deliberately do not
  contribute — so a byte-identical refresh may retain the same
  ``SourceCaptureId`` while its new manifest remains a distinct record.
"""

from __future__ import annotations

import hashlib

from greenmachine.common.ids import deterministic_id
from greenmachine.domain import SourceCaptureId

from .errors import DigestMismatchError
from .models import CaptureManifest, RawCaptureEntry

__all__ = [
    "capture_entry_identity",
    "manifest_document",
    "manifest_identity",
    "source_capture_identity",
    "verify_raw_bytes",
]

_REQUEST_NAMESPACE = "raw_capture"
_MANIFEST_NAMESPACE = "capture_manifest"
_SOURCE_CAPTURE_NAMESPACE = "source_capture"


def _entry_projection(entry: RawCaptureEntry) -> dict[str, object]:
    """The identity-bearing projection of one capture entry.

    Deliberately excludes the artifact path (a storage detail) and the attempt
    history (operational provenance) — identity follows what was asked and what
    came back, not where it was put or how many tries it took.
    """
    return {
        "provider": entry.request.provider.value,
        "endpoint": entry.request.endpoint,
        "parameters": entry.request.parameters,
        "retrieval_completed_at": entry.retrieval_completed_at.isoformat(),
        "http_status": entry.http_status,
        "sha256": entry.sha256,
    }


def capture_entry_identity(entry: RawCaptureEntry) -> str:
    """Deterministic identity of one request capture."""
    return deterministic_id(_REQUEST_NAMESPACE, _entry_projection(entry))


def _manifest_content(manifest: CaptureManifest) -> dict[str, object]:
    """The complete canonical manifest content — everything the document
    publishes except the recorded ``manifest_id``, with each entry's
    ``capture_id`` **recomputed** from its content.

    This one structure feeds both :func:`manifest_identity` and
    :func:`manifest_document`, so the identity can never silently cover less
    than what is published.
    """
    return {
        "manifest_schema_version": manifest.manifest_schema_version,
        "slate_date": manifest.slate_date.isoformat(),
        "game_id": manifest.game_id,
        "batter_id": manifest.batter_id,
        "capture_mode": manifest.capture_mode.value,
        "run_started_at": manifest.run_started_at.isoformat(),
        "run_completed_at": manifest.run_completed_at.isoformat(),
        "entries": [
            {
                "label": entry.request.label,
                "capture_id": capture_entry_identity(entry),
                "provider": entry.request.provider.value,
                "endpoint": entry.request.endpoint,
                "parameters": entry.request.parameters,
                "capture_mode": entry.capture_mode.value,
                "retrieval_started_at": entry.retrieval_started_at.isoformat(),
                "retrieval_completed_at": entry.retrieval_completed_at.isoformat(),
                "http_status": entry.http_status,
                "content_type": entry.content_type,
                "byte_length": entry.byte_length,
                "sha256": entry.sha256,
                "schema_fingerprint": entry.schema_fingerprint,
                "required_field_contract_version": entry.required_field_contract_version,
                "attempts": [
                    {
                        "index": attempt.index,
                        "started_at": attempt.started_at.isoformat(),
                        "completed_at": attempt.completed_at.isoformat(),
                        "outcome": attempt.outcome.value,
                        "http_status": attempt.http_status,
                        "error_category": attempt.error_category,
                    }
                    for attempt in entry.attempts
                ],
                "artifact_relative_path": entry.artifact_relative_path,
                "participates_in_snapshot": entry.participates_in_snapshot,
                "error_category": entry.error_category,
            }
            for entry in manifest.entries
        ],
    }


def manifest_identity(manifest: CaptureManifest) -> str:
    """Deterministic identity of one coordinated capture run.

    Content-derived from the **complete** canonical manifest content, so any
    change to any published field — an attempt outcome, a schema fingerprint,
    a contract version, a content type, an entry capture mode, an error
    category — changes the identity.
    """
    return deterministic_id(_MANIFEST_NAMESPACE, _manifest_content(manifest))


def source_capture_identity(manifest: CaptureManifest) -> SourceCaptureId:
    """The domain ``SourceCaptureId`` for a run, from participating bytes only."""
    participating = sorted(
        (entry.request.label, entry.sha256) for entry in manifest.participating_entries
    )
    if not participating:
        raise DigestMismatchError(
            "a SourceCaptureId requires at least one participating capture entry"
        )
    return SourceCaptureId(deterministic_id(_SOURCE_CAPTURE_NAMESPACE, participating))


def manifest_document(manifest: CaptureManifest) -> dict[str, object]:
    """The manifest as a plain, canonically serializable document.

    This is the exact structure written to ``manifest.json`` (through the
    frozen canonical encoder) and read back for replay: precisely the complete
    canonical content that :func:`manifest_identity` covers, plus the derived
    ``manifest_id`` itself so an archive is self-describing. The identities
    are always recomputable from the content alone.
    """
    document = _manifest_content(manifest)
    document["manifest_id"] = manifest_identity(manifest)
    return document


def verify_raw_bytes(entry: RawCaptureEntry, raw: bytes) -> None:
    """Refuse bytes whose digest or length disagrees with the manifest entry."""
    if len(raw) != entry.byte_length:
        raise DigestMismatchError(
            f"raw artifact for '{entry.request.label}' is {len(raw)} bytes, but the "
            f"manifest records {entry.byte_length}"
        )
    digest = hashlib.sha256(raw).hexdigest()
    if digest != entry.sha256:
        raise DigestMismatchError(
            f"raw artifact for '{entry.request.label}' has digest {digest}, but the "
            f"manifest records {entry.sha256}; the archived bytes are not the captured bytes"
        )

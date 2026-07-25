"""Injected transport, deterministic retry, and raw-byte retrieval.

The ingestion layer never touches the network directly: it speaks to an
injected :class:`HttpTransport`, waits through an injected :class:`Sleeper`,
and reads time from the injected GM-005 ``Clock`` — so every retrieval decision
is reproducible in tests without a socket, a real sleep, or a wall clock.

Retrieval policy (Product Owner ruling): synchronous only, no concurrency, an
explicit timeout, at most three total attempts, deterministic no-jitter
backoff, retries only for transport interruptions, HTTP 429, and selected
transient 5xx statuses. A valid integer ``Retry-After`` is honored (bounded).
Ordinary 4xx responses are never retried. Every attempt is recorded.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from greenmachine.common.clock import Clock

from .errors import IngestionModelError, ProviderTransportError
from .models import AttemptOutcome, AttemptRecord

__all__ = [
    "FetchResult",
    "HttpResponse",
    "HttpTransport",
    "RetryPolicy",
    "Sleeper",
    "fetch_with_retry",
]

_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_RETRY_AFTER_CAP_SECONDS = 120


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """One HTTP response: status, selected headers (lowercased names), raw body."""

    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes

    def __post_init__(self) -> None:
        if isinstance(self.status, bool) or not isinstance(self.status, int):
            raise IngestionModelError("HttpResponse.status must be an int")
        if not isinstance(self.headers, tuple):
            raise IngestionModelError("HttpResponse.headers must be a tuple")
        for index, pair in enumerate(self.headers):
            candidate: object = pair
            if not (
                isinstance(candidate, tuple)
                and len(candidate) == 2
                and isinstance(candidate[0], str)
                and isinstance(candidate[1], str)
            ):
                raise IngestionModelError(
                    f"HttpResponse.headers[{index}] must be a (name, value) string pair"
                )
        if not isinstance(self.body, bytes):
            raise IngestionModelError("HttpResponse.body must be bytes")

    def header(self, name: str) -> str | None:
        lowered = name.lower()
        for header_name, value in self.headers:
            if header_name.lower() == lowered:
                return value
        return None


class HttpTransport(Protocol):
    """The single network seam. GET-only, synchronous, byte-exact.

    Implementations raise :class:`ProviderTransportError` for anything that
    prevented an HTTP response from existing (timeout, connection failure,
    interruption); an HTTP error *status* is a response, not a transport error.
    """

    def request(self, url: str, timeout_seconds: int) -> HttpResponse: ...


class Sleeper(Protocol):
    """Injected waiting, so tests never actually sleep."""

    def sleep(self, seconds: int) -> None: ...


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Deterministic retrieval policy: explicit timeout, bounded attempts, fixed backoff."""

    timeout_seconds: int
    max_attempts: int
    backoff_seconds: tuple[int, ...]

    def __post_init__(self) -> None:
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, int):
            raise IngestionModelError("RetryPolicy.timeout_seconds must be an int")
        if self.timeout_seconds < 1:
            raise IngestionModelError("RetryPolicy.timeout_seconds must be >= 1")
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int):
            raise IngestionModelError("RetryPolicy.max_attempts must be an int")
        if not 1 <= self.max_attempts <= 3:
            raise IngestionModelError(
                f"RetryPolicy.max_attempts must be between 1 and 3 (ruling: at most three "
                f"total attempts), got {self.max_attempts}"
            )
        if not isinstance(self.backoff_seconds, tuple):
            raise IngestionModelError("RetryPolicy.backoff_seconds must be a tuple")
        for index, value in enumerate(self.backoff_seconds):
            candidate: object = value
            if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate < 0:
                raise IngestionModelError(
                    f"RetryPolicy.backoff_seconds[{index}] must be an int >= 0"
                )
        if len(self.backoff_seconds) < self.max_attempts - 1:
            raise IngestionModelError(
                "RetryPolicy.backoff_seconds must supply a delay for every retry gap"
            )


@dataclass(frozen=True, slots=True)
class FetchResult:
    """The outcome of one retrieval, successful or not, with every attempt recorded."""

    response: HttpResponse | None
    attempts: tuple[AttemptRecord, ...]
    body_sha256: str | None

    @property
    def succeeded(self) -> bool:
        return self.response is not None and 200 <= self.response.status < 300


def _retry_after_seconds(response: HttpResponse) -> int | None:
    raw = response.header("retry-after")
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped.isdigit():
        return None
    seconds = int(stripped)
    if seconds <= 0:
        return None
    return min(seconds, _RETRY_AFTER_CAP_SECONDS)


def fetch_with_retry(
    transport: HttpTransport,
    url: str,
    policy: RetryPolicy,
    clock: Clock,
    sleeper: Sleeper,
) -> FetchResult:
    """Retrieve ``url`` under the deterministic retry policy, recording every attempt.

    Never raises for a failed retrieval: the caller inspects
    :attr:`FetchResult.succeeded` and the attempt records, so partial evidence
    is preserved rather than lost in an exception. A retryable failure sleeps
    the fixed backoff (or a valid bounded ``Retry-After``) through the injected
    sleeper; a fatal HTTP status stops immediately.
    """
    attempts: list[AttemptRecord] = []
    response: HttpResponse | None = None

    for attempt_index in range(1, policy.max_attempts + 1):
        started_at = clock.now()
        try:
            candidate = transport.request(url, policy.timeout_seconds)
        except ProviderTransportError:
            attempts.append(
                AttemptRecord(
                    index=attempt_index,
                    started_at=started_at,
                    completed_at=clock.now(),
                    outcome=AttemptOutcome.RETRYABLE_TRANSPORT_ERROR,
                    http_status=None,
                    error_category="transport",
                )
            )
            if attempt_index < policy.max_attempts:
                sleeper.sleep(policy.backoff_seconds[attempt_index - 1])
            continue

        completed_at = clock.now()
        if 200 <= candidate.status < 300:
            attempts.append(
                AttemptRecord(
                    index=attempt_index,
                    started_at=started_at,
                    completed_at=completed_at,
                    outcome=AttemptOutcome.SUCCESS,
                    http_status=candidate.status,
                    error_category=None,
                )
            )
            response = candidate
            break

        if candidate.status in _RETRYABLE_STATUSES:
            attempts.append(
                AttemptRecord(
                    index=attempt_index,
                    started_at=started_at,
                    completed_at=completed_at,
                    outcome=AttemptOutcome.RETRYABLE_HTTP_STATUS,
                    http_status=candidate.status,
                    error_category="http_status",
                )
            )
            if attempt_index < policy.max_attempts:
                retry_after = _retry_after_seconds(candidate)
                delay = (
                    retry_after
                    if retry_after is not None
                    else policy.backoff_seconds[attempt_index - 1]
                )
                sleeper.sleep(delay)
            continue

        attempts.append(
            AttemptRecord(
                index=attempt_index,
                started_at=started_at,
                completed_at=completed_at,
                outcome=AttemptOutcome.FATAL_HTTP_STATUS,
                http_status=candidate.status,
                error_category="http_status",
            )
        )
        break

    digest = (
        hashlib.sha256(response.body).hexdigest()
        if response is not None and 200 <= response.status < 300
        else None
    )
    return FetchResult(response=response, attempts=tuple(attempts), body_sha256=digest)

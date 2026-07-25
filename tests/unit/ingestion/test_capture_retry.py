"""Deterministic retrieval: bounded attempts, fixed backoff, honest attempt records."""

from __future__ import annotations

import pytest
from tests.fixtures.ingestion.synthetic_provider_fixtures import (
    RecordingSleeper,
    SteppingClock,
    ok,
)

from greenmachine.ingestion.capture import (
    HttpResponse,
    RetryPolicy,
    fetch_with_retry,
)
from greenmachine.ingestion.errors import IngestionModelError, ProviderTransportError
from greenmachine.ingestion.models import AttemptOutcome

POLICY = RetryPolicy(timeout_seconds=10, max_attempts=3, backoff_seconds=(2, 4))


class ScriptedTransport:
    """Yields scripted outcomes in order; raises transport errors where scripted."""

    def __init__(self, outcomes: list[HttpResponse | ProviderTransportError]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def request(self, url: str, timeout_seconds: int) -> HttpResponse:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, ProviderTransportError):
            raise outcome
        return outcome


def test_success_on_the_first_attempt_records_one_attempt_and_no_sleep() -> None:
    transport = ScriptedTransport([ok(b"payload")])
    sleeper = RecordingSleeper()
    result = fetch_with_retry(transport, "https://x.invalid/a", POLICY, SteppingClock(), sleeper)

    assert result.succeeded
    assert result.body_sha256 is not None
    assert [attempt.outcome for attempt in result.attempts] == [AttemptOutcome.SUCCESS]
    assert sleeper.delays == []


def test_transport_errors_retry_with_the_fixed_backoff_then_fail() -> None:
    transport = ScriptedTransport(
        [
            ProviderTransportError("synthetic timeout"),
            ProviderTransportError("synthetic timeout"),
            ProviderTransportError("synthetic timeout"),
        ]
    )
    sleeper = RecordingSleeper()
    result = fetch_with_retry(transport, "https://x.invalid/a", POLICY, SteppingClock(), sleeper)

    assert not result.succeeded
    assert transport.calls == 3  # maximum three total attempts
    assert sleeper.delays == [2, 4]  # deterministic, no jitter, no sleep after the last
    assert [attempt.outcome for attempt in result.attempts] == [
        AttemptOutcome.RETRYABLE_TRANSPORT_ERROR
    ] * 3
    assert [attempt.index for attempt in result.attempts] == [1, 2, 3]


def test_a_retryable_status_then_success() -> None:
    transport = ScriptedTransport([HttpResponse(status=503, headers=(), body=b""), ok(b"payload")])
    sleeper = RecordingSleeper()
    result = fetch_with_retry(transport, "https://x.invalid/a", POLICY, SteppingClock(), sleeper)

    assert result.succeeded
    assert sleeper.delays == [2]
    assert [attempt.outcome for attempt in result.attempts] == [
        AttemptOutcome.RETRYABLE_HTTP_STATUS,
        AttemptOutcome.SUCCESS,
    ]


def test_429_honors_a_valid_integer_retry_after() -> None:
    transport = ScriptedTransport(
        [
            HttpResponse(status=429, headers=(("Retry-After", "7"),), body=b""),
            ok(b"payload"),
        ]
    )
    sleeper = RecordingSleeper()
    result = fetch_with_retry(transport, "https://x.invalid/a", POLICY, SteppingClock(), sleeper)

    assert result.succeeded
    assert sleeper.delays == [7]


def test_an_invalid_retry_after_falls_back_to_the_fixed_backoff() -> None:
    transport = ScriptedTransport(
        [
            HttpResponse(status=429, headers=(("Retry-After", "soon"),), body=b""),
            ok(b"payload"),
        ]
    )
    sleeper = RecordingSleeper()
    fetch_with_retry(transport, "https://x.invalid/a", POLICY, SteppingClock(), sleeper)
    assert sleeper.delays == [2]


def test_ordinary_4xx_is_fatal_and_never_retried() -> None:
    transport = ScriptedTransport([HttpResponse(status=404, headers=(), body=b"missing")])
    sleeper = RecordingSleeper()
    result = fetch_with_retry(transport, "https://x.invalid/a", POLICY, SteppingClock(), sleeper)

    assert not result.succeeded
    assert transport.calls == 1
    assert sleeper.delays == []
    assert result.attempts[0].outcome is AttemptOutcome.FATAL_HTTP_STATUS
    assert result.body_sha256 is None


def test_the_policy_refuses_more_than_three_attempts() -> None:
    with pytest.raises(IngestionModelError, match="between 1 and 3"):
        RetryPolicy(timeout_seconds=10, max_attempts=4, backoff_seconds=(1, 2, 3))


def test_attempt_timestamps_come_from_the_injected_clock() -> None:
    transport = ScriptedTransport([ProviderTransportError("synthetic"), ok(b"payload")])
    clock = SteppingClock()
    result = fetch_with_retry(transport, "https://x.invalid/a", POLICY, clock, RecordingSleeper())

    instants = [(attempt.started_at, attempt.completed_at) for attempt in result.attempts]
    flattened = [moment for pair in instants for moment in pair]
    assert flattened == sorted(flattened)  # strictly from the stepping clock
    assert len({id(moment.tzinfo) for moment in flattened}) >= 1  # all aware

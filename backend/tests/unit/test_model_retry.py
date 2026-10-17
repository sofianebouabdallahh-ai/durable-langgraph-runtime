"""Retries with backoff and the circuit breaker (R14.7, SC15), on a fake clock."""

from typing import Any

import pytest

from agent_runtime.models.retry import (
    CircuitBreaker,
    CircuitOpen,
    ModelCaller,
    is_retryable,
    retry_after_s,
)


class HttpError(Exception):
    def __init__(self, status: int, retry_after: str | None = None) -> None:
        super().__init__(f"HTTP {status}")
        self.status_code = status
        self.response = type("R", (), {"status_code": status,
                                       "headers": {"retry-after": retry_after} if retry_after
                                       else {}})()  # fmt: skip


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.now += s


def failing(*errors: Exception, then: Any = "ok") -> Any:
    queue = list(errors)

    async def fn() -> Any:
        if queue:
            raise queue.pop(0)
        return then

    return fn


async def test_retryable_errors_are_retried_with_capped_full_jitter() -> None:
    clock, charges = Clock(), []

    async def charge() -> None:
        charges.append(1)

    caller = ModelCaller(attempts=3, base_s=1, cap_s=20, sleep=clock.sleep, rand=lambda: 1.0)
    out = await caller.call(failing(HttpError(503), TimeoutError()), charge=charge)
    assert out == "ok" and caller.attempts_made == 3
    assert len(charges) == 3  # every attempt is charged
    assert clock.slept == [1.0, 2.0]  # base · 2^(n-1), at the top of the jitter range


async def test_jitter_is_random_within_the_range_and_capped() -> None:
    caller = ModelCaller(base_s=1, cap_s=5, rand=lambda: 0.5)
    assert caller.backoff_s(1, HttpError(500)) == 0.5
    assert caller.backoff_s(10, HttpError(500)) == 2.5  # capped at 5 before jitter


async def test_retry_after_is_honoured_up_to_the_cap() -> None:
    caller = ModelCaller(base_s=1, cap_s=20, rand=lambda: 0.0)
    assert caller.backoff_s(1, HttpError(429, retry_after="7")) == 7.0
    assert caller.backoff_s(1, HttpError(429, retry_after="99")) == 20.0
    assert retry_after_s(HttpError(429, retry_after="soon")) is None


async def test_non_retryable_errors_fail_at_once_and_attempts_are_bounded() -> None:
    clock = Clock()

    async def charge() -> None:
        pass

    caller = ModelCaller(sleep=clock.sleep)
    with pytest.raises(HttpError):
        await caller.call(failing(HttpError(400)), charge=charge)
    assert caller.attempts_made == 1
    caller = ModelCaller(attempts=3, sleep=clock.sleep)
    with pytest.raises(HttpError):
        await caller.call(failing(*[HttpError(502)] * 5), charge=charge)
    assert caller.attempts_made == 3


def test_what_counts_as_retryable() -> None:
    assert all(is_retryable(HttpError(s)) for s in (429, 500, 502, 503, 504))
    assert not any(is_retryable(HttpError(s)) for s in (400, 401, 403, 404, 422))
    assert is_retryable(TimeoutError()) and not is_retryable(ValueError("bug"))


def test_the_breaker_opens_after_5_failures_in_30s_and_half_opens_after_30s() -> None:
    clock = Clock()
    b = CircuitBreaker("p", failures=5, window_s=30, open_s=30, clock=clock)
    for _ in range(4):
        b.record_failure()
        clock.now += 5
    assert b.state == "closed"
    b.record_failure()  # 5 failures within 20 s
    assert str(b.state) == "open"
    with pytest.raises(CircuitOpen):
        b.before_call()
    clock.now += 30
    assert str(b.state) == "half_open"
    b.before_call()  # the trial call is let through
    b.record_failure()  # ... and fails: open again
    assert str(b.state) == "open"
    clock.now += 30
    b.record_success()
    assert b.state == "closed"


def test_failures_outside_the_window_do_not_count() -> None:
    clock = Clock()
    b = CircuitBreaker("p", failures=5, window_s=30, clock=clock)
    for _ in range(10):
        b.record_failure()
        clock.now += 10  # never 5 within 30 s
    assert b.state == "closed"


async def test_an_open_breaker_fails_fast_without_charging() -> None:
    clock, charges = Clock(), []

    async def charge() -> None:
        charges.append(1)

    b = CircuitBreaker("p", failures=2, window_s=30, open_s=30, clock=clock)
    caller = ModelCaller(attempts=3, breaker=b, sleep=clock.sleep, rand=lambda: 0.0)
    with pytest.raises(CircuitOpen):
        await caller.call(failing(*[HttpError(503)] * 5), charge=charge)
    assert len(charges) == 2  # the 3rd attempt never happened: the breaker opened

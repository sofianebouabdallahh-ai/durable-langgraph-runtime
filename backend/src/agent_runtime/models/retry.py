"""Retries with backoff and a circuit breaker for model calls (CR-003 R14.7).

Pattern: Decorator around one model call (`ModelCaller.call`), plus a Circuit
Breaker per provider.

- Only **retryable** errors are retried: HTTP 429, 5xx and timeouts. Anything else
  (400, auth, content policy, a bug) fails at once.
- At most `attempts` attempts, exponential backoff from `base_s`, capped at
  `cap_s`, with **full jitter** (sleep a random time in [0, backoff]), and a
  server's `Retry-After` honoured when it asks for longer.
- **Every attempt is charged** to the budget (`charge` runs before each one):
  a retry storm can't hide from the budget.
- **Breaker** (SHOULD): `failures` retryable failures within `window_s` open it
  for `open_s`. While open, calls fail fast with `CircuitOpen`; the executor
  then releases the run instead of burning retries. After `open_s` one trial
  call is let through (half-open): success closes it, failure re-opens it.

Clock, sleep and randomness are injected, so the tests use a fake clock.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

T = TypeVar("T")

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class CircuitOpen(Exception):
    def __init__(self, provider: str, retry_in_s: float) -> None:
        super().__init__(f"provider {provider!r} is failing; circuit open for {retry_in_s:.0f}s")
        self.provider = provider
        self.retry_in_s = retry_in_s


def _status(exc: BaseException) -> int | None:
    for candidate in (exc, getattr(exc, "response", None)):
        status = getattr(candidate, "status_code", None) or getattr(candidate, "status", None)
        if isinstance(status, int):
            return status
    return None


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return True
    if type(exc).__name__ in ("APITimeoutError", "APIConnectionError", "ConnectError",
                              "ReadTimeout", "ConnectTimeout"):  # fmt: skip
        return True
    status = _status(exc)
    return status is not None and status in RETRYABLE_STATUS


def retry_after_s(exc: BaseException) -> float | None:
    """The server's `Retry-After` (seconds form), if it sent one."""
    headers = getattr(getattr(exc, "response", None), "headers", None) or getattr(
        exc, "headers", None
    )
    if not headers:
        return None
    value = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return max(0.0, float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


@dataclass
class CircuitBreaker:
    provider: str
    failures: int = 5
    window_s: float = 30.0
    open_s: float = 30.0
    clock: Callable[[], float] = time.monotonic
    _recent: deque[float] = field(default_factory=deque)
    _opened_at: float | None = None

    @property
    def state(self) -> Literal["closed", "open", "half_open"]:
        if self._opened_at is None:
            return "closed"
        return "half_open" if self.clock() - self._opened_at >= self.open_s else "open"

    def before_call(self) -> None:
        if self.state == "open":
            assert self._opened_at is not None
            raise CircuitOpen(self.provider, self.open_s - (self.clock() - self._opened_at))

    def record_success(self) -> None:
        self._recent.clear()
        self._opened_at = None

    def record_failure(self) -> None:
        now = self.clock()
        if self.state == "half_open":  # the trial call failed: open again
            self._opened_at = now
            return
        self._recent.append(now)
        while self._recent and now - self._recent[0] > self.window_s:
            self._recent.popleft()
        if len(self._recent) >= self.failures:
            self._opened_at = now
            self._recent.clear()


_BREAKERS: dict[str, CircuitBreaker] = {}


def breaker_for(provider: str, **config: Any) -> CircuitBreaker:
    """One breaker per provider per process (workers are separate processes)."""
    if provider not in _BREAKERS:
        _BREAKERS[provider] = CircuitBreaker(provider, **config)
    return _BREAKERS[provider]


def reset_breakers() -> None:  # tests
    _BREAKERS.clear()


@dataclass
class ModelCaller:
    attempts: int = 3
    base_s: float = 1.0
    cap_s: float = 20.0
    breaker: CircuitBreaker | None = None
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    rand: Callable[[], float] = random.random
    attempts_made: int = 0  # observability and tests

    def backoff_s(self, attempt: int, exc: BaseException) -> float:
        """Full jitter: uniform in [0, min(cap, base · 2^(attempt-1))], or the server's
        Retry-After if it asks for longer."""
        jittered = float(self.rand() * min(self.cap_s, self.base_s * 2 ** (attempt - 1)))
        hinted = retry_after_s(exc)
        return max(jittered, min(hinted, self.cap_s)) if hinted is not None else jittered

    async def call(
        self, fn: Callable[[], Awaitable[T]], *, charge: Callable[[], Awaitable[None]]
    ) -> T:
        for attempt in range(1, self.attempts + 1):
            if self.breaker is not None:
                self.breaker.before_call()  # CircuitOpen: fail fast
            await charge()  # every attempt counts (R14.7)
            self.attempts_made += 1
            try:
                result = await fn()
            except Exception as exc:
                retryable = is_retryable(exc)
                if retryable and self.breaker is not None:
                    self.breaker.record_failure()
                if not retryable or attempt == self.attempts:
                    raise
                await self.sleep(self.backoff_s(attempt, exc))
                continue
            if self.breaker is not None:
                self.breaker.record_success()
            return result
        raise AssertionError("unreachable")  # pragma: no cover

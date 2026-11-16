"""Which requests are retried, and how long to wait (CR-007 R19.6).

Pattern: Strategy. A request is retried only when sending it again can't do anything twice:
a read, or a send carrying its `Idempotency-Key` (Nuria answers the same key with the same
turn). Everything else (a cancel, say) is sent once.

- connection failures, 429, 502, 503, 504: retry, after `Retry-After` when the server gave
  one, else after a jittered backoff (0.5 s doubling, at most 8 s);
- `409 duplicate-send`: the same send is still being made: retry with the same key;
- any other 409 is final. In particular a 409 on an approval ("already decided") is never
  retried, whatever the base clients of other SDKs do.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

RETRY_STATUSES = frozenset({429, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    retries: int = 3
    base_s: float = 0.5
    cap_s: float = 8.0
    retry_after_cap_s: float = 60.0
    jitter: Callable[[], float] = field(default=random.random, repr=False, compare=False)

    def delay(
        self, attempt: int, *, safe: bool, status: int | None = None,
        problem_kind: str = "", retry_after_s: float | None = None,
    ) -> float | None:  # fmt: skip
        """Seconds to wait before attempt `attempt + 1`, or None: don't retry.

        `attempt` counts from 1; `safe` says whether sending it again can't do anything
        twice; `status` is None when the request never got an answer."""
        if not safe or attempt > self.retries:
            return None
        if status is None or status in RETRY_STATUSES:
            if retry_after_s is not None:
                return min(retry_after_s, self.retry_after_cap_s)
            return self._backoff(attempt)
        if status == 409 and problem_kind == "duplicate-send":
            return self._backoff(attempt)
        return None

    def _backoff(self, attempt: int) -> float:
        jitter = 0.5 + float(self.jitter()) / 2  # half to all of the delay
        return min(self.cap_s, self.base_s * 2.0 ** (attempt - 1)) * jitter


NO_RETRIES = RetryPolicy(retries=0)

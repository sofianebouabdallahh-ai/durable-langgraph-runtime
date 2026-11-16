"""How to resume a Nuria stream without losing or repeating an event (CR-007 R19.5), as a
state machine without I/O.

Pattern: State, sans-IO. The async and the sync client drive the same machine; it decides,
they do the I/O. Each rule is one branch here, with its own unit test:

- the cursor moves only on events that carry an `id` (persisted events: their `seq`);
- `event: reconnect` (a replica draining) means reconnect now, from the cursor;
- an event at or below the cursor is a replay of one already seen: dropped;
- a dropped or refused connection, a 429 or a 5xx: retry with jittered backoff (1 s,
  doubling, at most 5 s; `Retry-After` when the server gives one), 5 attempts, and any
  event received since earns a fresh set (as langgraph-sdk's loop does);
- a clean close without a terminal event: ask the run its status, then go on;
- 401, 403 and 404 are fatal, and so is any other 4xx.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from nuria._sse import Event


class Verdict(Enum):
    NEW = "new"  # pass it on
    DUPLICATE = "duplicate"  # a replayed persisted event already seen: drop it
    RECONNECT = "reconnect"  # the replica is draining: reconnect now


@dataclass(frozen=True, slots=True)
class Retry:
    after_s: float


@dataclass(frozen=True, slots=True)
class Fatal:
    status: int | None  # None: the attempts ran out


@dataclass(frozen=True, slots=True)
class Proceed:
    pass


Decision = Retry | Fatal | Proceed

FATAL_STATUSES = frozenset({401, 403, 404})
RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class Resumption:
    def __init__(
        self,
        cursor: int | None = None,
        *,
        attempts: int = 5,
        base_s: float = 1.0,
        cap_s: float = 5.0,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.cursor = cursor  # the last persisted seq this client has seen
        self._max_attempts = attempts
        self._base_s, self._cap_s, self._jitter = base_s, cap_s, jitter
        self._attempts = 0
        self.reconnects = 0  # every new connection after the first
        self.drains = 0  # of them, asked for by `event: reconnect`

    def headers(self) -> dict[str, str]:
        """What to send on (re)connecting: the cursor, as the standard's `Last-Event-ID`."""
        return {} if self.cursor is None else {"Last-Event-ID": str(self.cursor)}

    def accept(self, event: Event) -> Verdict:
        if event.event == "reconnect":
            # The server's `after_seq` is what it sent; the cursor is what this client saw,
            # and resuming from it can only replay (then drop), never skip.
            self.drains += 1
            return Verdict.RECONNECT
        self._attempts = 0  # progress since the last drop earns a fresh set of attempts
        if event.id is None or not event.id.isdigit():
            return Verdict.NEW  # transient: no place in the sequence
        seq = int(event.id)
        if self.cursor is not None and seq <= self.cursor:
            return Verdict.DUPLICATE
        self.cursor = seq
        return Verdict.NEW

    def opened(
        self, status: int, content_type: str | None, retry_after_s: float | None
    ) -> Decision:
        """The response to a (re)connection, before any event."""
        if status == 200 and (content_type or "").split(";")[0].strip() == "text/event-stream":
            return Proceed()
        if status in FATAL_STATUSES or (400 <= status < 500 and status not in RETRY_STATUSES):
            return Fatal(status)
        if status == 200:
            return self.dropped(None)  # a 200 that isn't an event stream: a proxy's page
        return self.dropped(retry_after_s)

    def dropped(self, retry_after_s: float | None = None) -> Retry | Fatal:
        """The connection failed, was refused, or broke mid-stream."""
        self._attempts += 1
        if self._attempts > self._max_attempts:
            return Fatal(None)
        if retry_after_s is not None:
            return Retry(min(retry_after_s, 60.0))
        backoff = min(self._cap_s, self._base_s * 2.0 ** (self._attempts - 1))
        return Retry(backoff * (0.5 + self._jitter() / 2))

    def reconnecting(self) -> None:
        self.reconnects += 1


def reconnect_after_seq(event: Event) -> int | None:
    """The `after_seq` a draining replica sent (for logs and tests; resuming uses the cursor)."""
    try:
        value = json.loads(event.data).get("after_seq")
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, int) else None

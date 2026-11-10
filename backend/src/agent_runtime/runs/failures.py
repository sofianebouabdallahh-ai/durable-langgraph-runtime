"""Which errors are the infrastructure's, not the run's (phase H4).

A run that fails because Postgres restarted, the pool ran dry or Redis dropped a
connection hasn't failed: the same step, run again from its checkpoint, will most likely
work. Those errors release the run (back to `queued`) instead of ending it, a bounded
number of times. Everything else (a bug, a bad input) still fails the run at once.

Transient here (as Temporal, DBOS and Restate retry them):
- psycopg `OperationalError`: connection lost, `admin_shutdown` (57P01),
  `cannot_connect_now` (57P03), `too_many_connections` (53300), serialization failures
  (40001), deadlocks (40P01), a statement timeout; the pool's `PoolTimeout` is one too;
- Redis connection and timeout errors, and the work queue's `QueueUnavailable`;
- `ConnectionError` (a socket reset on the way to either).

The error, its cause (`raise … from`), else its context (as a traceback shows them), and
the members of exception groups are all looked at: LangGraph and anyio may wrap the
error that actually happened.
"""

from __future__ import annotations

import psycopg
import redis.exceptions

from agent_runtime.queue import QueueUnavailable

TRANSIENT: tuple[type[BaseException], ...] = (
    psycopg.OperationalError,
    redis.exceptions.ConnectionError,
    redis.exceptions.TimeoutError,
    QueueUnavailable,
    ConnectionError,
)

# Failures a person may try again (POST /runs/{id}/redrive): they might not happen again.
# A budget, a loop, a step limit or a refusal would end the same way, so those are final.
# Not context_overflow (H5): a redrive resumes the same turn, which would overflow again;
# the next message starts compacted.
REDRIVABLE = frozenset({"error", "infrastructure", "max_reclaims", "timeout"})


def is_transient(exc: BaseException) -> bool:
    """True if `exc`, or anything it wraps, is an infrastructure error."""
    seen: set[int] = set()
    todo: list[BaseException] = [exc]
    while todo:
        e = todo.pop()
        if id(e) in seen:
            continue
        seen.add(id(e))
        if isinstance(e, TRANSIENT):
            return True
        if isinstance(e, BaseExceptionGroup):
            todo.extend(e.exceptions)
        if e.__cause__ is not None:
            todo.append(e.__cause__)
        elif e.__context__ is not None and not e.__suppress_context__:  # as tracebacks do
            todo.append(e.__context__)
    return False

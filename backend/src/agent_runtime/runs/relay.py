"""Outbox relay: (re)send work messages for runs that need one.

Postgres is the source of truth and `runs` is effectively the outbox: a run
that is `queued` (or `running` under a dead owner) must have a message in the
work stream. Sending that message is a separate step from creating the run (a
dual write), so it can be lost. This sweep repairs it:

  1. claim candidates with `UPDATE … WHERE id IN (… FOR UPDATE SKIP LOCKED)`:
     several workers can sweep at once without sending the same run twice, and
     no transaction stays open across the network call to Redis;
  2. for each, if its last message no longer exists in the stream, send a new
     one and record it.

Duplicate messages are harmless: the run's lease decides who executes it.
"""

from __future__ import annotations

import logging
import uuid

from agent_runtime.db import Pool
from agent_runtime.queue import WorkQueue

log = logging.getLogger(__name__)


class OutboxRelay:
    def __init__(self, pool: Pool, queue: WorkQueue, *, stale_s: float, batch: int = 100) -> None:
        self._pool = pool
        self._queue = queue
        self._stale_s = stale_s
        self._batch = batch

    async def enqueue(self, run_id: uuid.UUID) -> str:
        """Send a message for `run_id` now and record it."""
        message_id = await self._queue.enqueue(run_id)
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE runs SET message_id = %s, enqueued_at = now() WHERE id = %s",
                (message_id, run_id),
            )
        return message_id

    async def sweep(self) -> int:
        """One pass; returns how many runs were (re)sent."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                UPDATE runs SET enqueued_at = now()
                WHERE id IN (
                    SELECT id FROM runs
                    WHERE (status = 'queued'
                           AND (enqueued_at IS NULL
                                OR enqueued_at < now() - make_interval(secs => %(stale)s)))
                       OR (status = 'running'
                           AND lease_expires_at < now() - make_interval(secs => %(stale)s)
                           AND (enqueued_at IS NULL
                                OR enqueued_at < now() - make_interval(secs => %(stale)s)))
                    ORDER BY enqueued_at NULLS FIRST
                    LIMIT %(batch)s
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, message_id
                """,
                {"stale": self._stale_s, "batch": self._batch},
            )
            candidates = await cur.fetchall()
        sent = 0
        for row in candidates:
            if row["message_id"] is not None and await self._queue.exists(row["message_id"]):
                continue  # its message is still waiting or being worked on
            await self.enqueue(row["id"])
            sent += 1
        if sent:
            log.info("relay re-sent %d run(s) whose work message was missing", sent)
        return sent

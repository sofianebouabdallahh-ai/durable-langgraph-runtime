"""Fencing tokens (R2.3): reject writes from a worker that lost ownership.

A run's `epoch` increases every time a worker acquires its lease. Every write a
worker makes carries the epoch it acquired; `check_fence` locks the run row
(shared) and refuses the write if the epoch has moved on. Checkpoints, events,
transitions and (later) tool results all go through it, so a paused "zombie"
worker can't persist anything once another worker has taken over.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from agent_runtime.db import Conn


@dataclass(frozen=True, slots=True)
class Fence:
    """The identity a writer claims: this run, at this lease epoch."""

    run_id: uuid.UUID
    epoch: int


class FencedError(Exception):
    """A write was attempted with an epoch that no longer owns the run."""

    def __init__(self, fence: Fence, current_epoch: int | None) -> None:
        owner = "run not found" if current_epoch is None else f"current epoch {current_epoch}"
        super().__init__(
            f"run {fence.run_id}: write fenced off (writer epoch {fence.epoch}, {owner})"
        )
        self.fence = fence
        self.current_epoch = current_epoch


async def check_fence(conn: Conn, fence: Fence) -> None:
    """Lock the run row (shared) and verify `fence` still owns it.

    Must run inside a transaction; the shared lock is held until it ends.
    """
    cur = await conn.execute("SELECT epoch FROM runs WHERE id = %s FOR SHARE", (fence.run_id,))
    row = await cur.fetchone()
    current = None if row is None else int(row["epoch"])
    if current != fence.epoch:
        raise FencedError(fence, current)

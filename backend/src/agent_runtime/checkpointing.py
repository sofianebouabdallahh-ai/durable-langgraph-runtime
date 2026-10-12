"""Epoch-fenced LangGraph checkpointer (F1 / R2.10).

Problem: LangGraph's AsyncPostgresSaver writes checkpoints with no idea who
owns the run. A worker that froze (GC pause, SIGSTOP, network partition) past
its lease can wake up after another worker reclaimed the run (bumping the
epoch) and overwrite the new owner's progress: the "zombie" write.

Pattern: Protection Proxy. `FencedCheckpointer` *is* an AsyncPostgresSaver
(reads are inherited unchanged), but every write goes through a guard:

    BEGIN
      SELECT epoch FROM runs WHERE id = :run_id FOR SHARE   -- fence check
      -- epoch != ours  → raise FencedError, ROLLBACK, nothing written
      <LangGraph's own checkpoint INSERTs, on this same connection>
    COMMIT

`FOR SHARE` makes the check and the write atomic with respect to a takeover:
the lease acquisition `UPDATE runs SET epoch = epoch + 1` needs a row lock that
conflicts with FOR SHARE, so either the checkpoint commits first (and the new
owner then resumes from it) or the takeover commits first (and this write sees
the new epoch and is rejected). There is no window in between.

Only public LangGraph API is used: a short-lived AsyncPostgresSaver is bound to
the connection that holds our transaction, and its own aput/aput_writes run
inside it. No private methods are overridden, so LangGraph upgrades can't
silently bypass the fence.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import ChannelVersions, Checkpoint, CheckpointMetadata
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.base import SerializerProtocol

from agent_runtime.db import Conn, Pool


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


class FencedCheckpointer(AsyncPostgresSaver):
    """AsyncPostgresSaver whose writes are rejected once `fence` is stale.

    One instance per run execution (the fence is fixed for its lifetime).
    """

    def __init__(
        self, pool: Pool, fence: Fence, *, serde: SerializerProtocol | None = None
    ) -> None:
        super().__init__(pool, serde=serde)
        self._pool = pool
        self.fence = fence

    @asynccontextmanager
    async def _fenced(self) -> AsyncIterator[AsyncPostgresSaver]:
        async with self._pool.connection() as conn, conn.transaction():
            await check_fence(conn, self.fence)
            # Bound to the transaction's connection, so LangGraph's own writes
            # commit or roll back together with the fence check.
            yield AsyncPostgresSaver(conn, serde=self.serde)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        async with self._fenced() as inner:
            return await inner.aput(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        async with self._fenced() as inner:
            await inner.aput_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        async with self._fenced() as inner:
            await inner.adelete_thread(thread_id)

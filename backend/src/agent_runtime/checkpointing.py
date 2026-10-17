"""Epoch-fenced LangGraph checkpointer (F1 / R2.10).

Problem: LangGraph's AsyncPostgresSaver writes checkpoints with no idea who
owns the run. A worker that froze (GC pause, SIGSTOP, network partition) past
its lease can wake up after another worker reclaimed the run (bumping the
epoch) and overwrite the new owner's progress: the "zombie" write.

Pattern: Protection Proxy. `FencedCheckpointer` *is* an AsyncPostgresSaver
(reads are inherited unchanged), but every write goes through a guard:

    BEGIN
      SELECT epoch FROM runs WHERE id = :run_id FOR NO KEY UPDATE   -- fence
      -- epoch != ours  → raise FencedError, ROLLBACK, nothing written
      <LangGraph's own checkpoint INSERTs, on this same connection>
    COMMIT

The row lock makes the check and the write atomic with respect to a takeover:
the lease acquisition `UPDATE runs SET epoch = epoch + 1` needs a row lock that
conflicts with it, so either the checkpoint commits first (and the new
owner then resumes from it) or the takeover commits first (and this write sees
the new epoch and is rejected). There is no window in between. (`check_fence`
explains why the lock is NO KEY UPDATE rather than SHARE.)

Only public LangGraph API is used: a short-lived AsyncPostgresSaver is bound to
the connection that holds our transaction, and its own aput/aput_writes run
inside it. No private methods are overridden, so LangGraph upgrades can't
silently bypass the fence.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import ChannelVersions, Checkpoint, CheckpointMetadata
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.base import SerializerProtocol

from agent_runtime.db import Conn, Pool
from agent_runtime.fencing import Fence, FencedError, check_fence

__all__ = ["AfterCommit", "Fence", "FencedCheckpointer", "FencedError", "OnCommit", "check_fence"]

# Called inside the checkpoint's transaction, after LangGraph's write: whatever it
# writes commits atomically with the checkpoint (Transactional Outbox, R1.5).
OnCommit = Callable[[Conn, CheckpointMetadata], Awaitable[None]]
# Called after that transaction has committed (e.g. publish its events).
AfterCommit = Callable[[], Awaitable[None]]


class FencedCheckpointer(AsyncPostgresSaver):
    """AsyncPostgresSaver whose writes are rejected once `fence` is stale.

    One instance per run execution (the fence is fixed for its lifetime).
    """

    def __init__(
        self,
        pool: Pool,
        fence: Fence,
        *,
        on_commit: OnCommit | None = None,
        after_commit: AfterCommit | None = None,
        serde: SerializerProtocol | None = None,
    ) -> None:
        super().__init__(pool, serde=serde)
        self._pool = pool
        self._on_commit = on_commit
        self._after_commit = after_commit
        self.fence = fence

    @asynccontextmanager
    async def _fenced(self) -> AsyncIterator[tuple[Conn, AsyncPostgresSaver]]:
        async with self._pool.connection() as conn, conn.transaction():
            await check_fence(conn, self.fence)
            # Bound to the transaction's connection, so LangGraph's own writes
            # commit or roll back together with the fence check.
            yield conn, AsyncPostgresSaver(conn, serde=self.serde)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        async with self._fenced() as (conn, inner):
            next_config = await inner.aput(config, checkpoint, metadata, new_versions)
            if self._on_commit is not None:
                await self._on_commit(conn, metadata)
        # Only reached if the transaction committed.
        if self._after_commit is not None:
            await self._after_commit()
        return next_config

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        async with self._fenced() as (_, inner):
            await inner.aput_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        async with self._fenced() as (_, inner):
            await inner.adelete_thread(thread_id)

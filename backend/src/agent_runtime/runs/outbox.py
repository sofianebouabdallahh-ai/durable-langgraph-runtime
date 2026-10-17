"""The step outbox: events staged while a superstep runs, committed with its checkpoint.

Pattern: Transactional Outbox (R1.5). Nodes, tools and hooks *stage* events;
`FencedCheckpointer.on_commit` writes them inside the superstep's checkpoint
transaction, and `after_commit` publishes them once that commits. A committed
step always has its events; a step lost to a crash has none and is re-run.

One outbox per checkpoint thread. A sub-agent (CR-005) has its own thread and
therefore its own outbox, writing into the MAIN run's event log, but its steps
must not count toward the main run's `max_steps` (`counts_steps=False`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata

from agent_runtime.db import Conn
from agent_runtime.fencing import Fence
from agent_runtime.runs.events import EventType
from agent_runtime.runs.store import Event, RunRepository
from agent_runtime.sessions.transcript import TranscriptWriter
from agent_runtime.streaming.bus import EventBus, publish_events


@dataclass
class Outbox:
    run_id: uuid.UUID
    fence: Fence
    committed_steps: int  # steps committed for this run so far (all executions)
    bus: EventBus | None = None
    counts_steps: bool = True
    transcript: TranscriptWriter | None = None  # chat turns: the transcript, same txn
    pending: list[tuple[EventType, dict[str, Any]]] = field(default_factory=list)
    _just_written: list[Event] = field(default_factory=list)

    def stage(self, type: EventType, payload: dict[str, Any]) -> None:
        self.pending.append((type, payload))

    async def flush(self, repo: RunRepository) -> None:
        for type, payload in self.pending:
            await repo.append_event(self.run_id, epoch=self.fence.epoch, type=type, payload=payload)
        self.pending.clear()

    async def on_commit(
        self, conn: Conn, checkpoint: Checkpoint, metadata: CheckpointMetadata
    ) -> None:
        """FencedCheckpointer hook: runs inside the checkpoint's transaction."""
        repo = RunRepository(conn)
        if self.transcript is not None:
            messages = checkpoint["channel_values"].get("messages") or []
            await self.transcript.write(conn, list(messages))
        # Step 0 only maps the input into state; supersteps ≥ 1 executed nodes.
        loop_step = metadata.get("source") == "loop" and metadata.get("step", 0) >= 1
        if self.counts_steps and loop_step:
            self.committed_steps = await repo.add_steps(self.run_id, 1)
        await self.flush(repo)
        self._just_written = repo.emitted  # replaced, not appended: a rollback discards it

    async def after_commit(self) -> None:
        """FencedCheckpointer hook: the transaction committed; now announce it."""
        written, self._just_written = self._just_written, []
        await publish_events(self.bus, written)
        if self.transcript is not None:
            await self.transcript.publish()

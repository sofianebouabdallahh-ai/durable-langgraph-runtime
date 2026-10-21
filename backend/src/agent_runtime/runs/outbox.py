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
    # Tokens and cost of this step's model calls: counted when the step commits, so the
    # run's totals are exactly the sum of its committed steps (AC26), across reclaims.
    tokens: int = 0
    cost: float = 0.0
    # The same, per model (calls, tokens in, tokens out, cost, ms): the Activity page's
    # per-model numbers, committed with the step as the totals are (L7).
    models: dict[str, list[float]] = field(default_factory=dict)
    _just_written: list[Event] = field(default_factory=list)

    def stage(self, type: EventType, payload: dict[str, Any]) -> None:
        self.pending.append((type, payload))

    def add_usage(self, tokens: int, cost: float) -> None:
        self.tokens += tokens
        self.cost += cost

    def add_model_call(
        self, model: str, tokens_in: int, tokens_out: int, cost: float, ms: int
    ) -> None:
        row = self.models.setdefault(model, [0, 0, 0, 0.0, 0])
        for i, v in enumerate((1, tokens_in, tokens_out, cost, ms)):
            row[i] += v

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
        if self.tokens or self.cost:
            await repo.add_usage(self.run_id, self.tokens, self.cost)
            self.tokens, self.cost = 0, 0.0
        if self.models:
            await repo.add_model_usage(self.run_id, self.models)
            self.models = {}
        self._just_written = repo.emitted  # replaced, not appended: a rollback discards it

    async def after_commit(self) -> None:
        """FencedCheckpointer hook: the transaction committed; now announce it."""
        written, self._just_written = self._just_written, []
        await publish_events(self.bus, written)
        if self.transcript is not None:
            await self.transcript.publish()

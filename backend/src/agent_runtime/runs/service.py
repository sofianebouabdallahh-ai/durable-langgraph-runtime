"""Application service for runs: the use cases the API and CLI share.

Pattern: Service Layer. Transport code (HTTP handlers, CLI commands) parses
requests and renders responses; the rules for *creating* a run (graph exists,
input valid for that graph, options within ceilings) live here once.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from agent_runtime.admin import AdminRepository
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import GraphRegistry
from agent_runtime.runs.limits import RunOptions, resolve_limits
from agent_runtime.runs.relay import OutboxRelay
from agent_runtime.runs.state import RunStatus
from agent_runtime.runs.store import Run, RunRepository, RunTerminal
from agent_runtime.streaming.bus import EventBus, publish_events

log = logging.getLogger(__name__)


class AdmissionPaused(Exception):
    """The kill switch is on (R14.18): no new runs are accepted."""

    def __init__(self, reason: str | None) -> None:
        super().__init__(f"the runtime is paused{f': {reason}' if reason else ''}")
        self.reason = reason


class RunService:
    def __init__(
        self,
        pool: Pool,
        settings: Settings,
        graphs: GraphRegistry,
        relay: OutboxRelay | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self._pool = pool
        self._settings = settings
        self._graphs = graphs
        self._relay = relay
        self._bus = bus

    async def create_run(
        self,
        graph: str,
        input: dict[str, Any],
        options: dict[str, Any] | None = None,
        *,
        enqueue: bool = True,
    ) -> Run:
        """Validate, create a `queued` run, and hand it to the workers.

        Raises UnknownGraph, pydantic.ValidationError (input or options) or
        LimitAboveCeiling; the transport layer maps them to 404/422.

        The run is durable once created. Sending its work message is best
        effort: if Redis is unavailable, the outbox relay sends it later.
        """
        async with self._pool.connection() as conn:
            state = await AdminRepository(conn).get()
        if state.paused:
            raise AdmissionPaused(state.reason)
        spec = self._graphs.get(graph)
        validated_input = spec.input_model.model_validate(input)
        run_options = RunOptions.model_validate(options or {})
        limits = resolve_limits(self._settings, run_options)
        async with self._pool.connection() as conn:
            repo = RunRepository(conn)
            run = await repo.create(
                graph_name=graph,
                input=validated_input.model_dump(mode="json"),
                options=run_options.model_dump(exclude_none=True),
                limits=limits.model_dump(),
            )
        await publish_events(self._bus, repo.emitted)  # after commit (R1.5)
        if enqueue and self._relay is not None:
            try:
                await self._relay.enqueue(run.id)
            except Exception:
                log.warning("run %s created but not enqueued; the relay will send it", run.id,
                            exc_info=True)  # fmt: skip
        return run

    async def cancel(self, run_id: uuid.UUID) -> Run:
        """R1.6: queued or waiting → cancelled now; running → its worker stops at the
        next node. Raises RunTerminal (→ 409) or RunNotFound (→ 404)."""
        async with self._pool.connection() as conn:
            repo = RunRepository(conn)
            run = await repo.request_cancel(run_id)
        await publish_events(self._bus, repo.emitted)
        return run

    async def resume(self, run_id: uuid.UUID) -> Run:
        """R1.3, idempotent: (re)send work for a run that needs it; do nothing for a
        run a live worker is executing. Raises RunTerminal (→ 409)."""
        async with self._pool.connection() as conn:
            run = await RunRepository(conn).get(run_id)
        if run.status.is_terminal:
            raise RunTerminal(run)
        orphaned = (
            run.status is RunStatus.RUNNING
            and run.lease_expires_at is not None
            and run.lease_expires_at < datetime.now(UTC)
        )
        if (run.status is RunStatus.QUEUED or orphaned) and self._relay is not None:
            await self._relay.enqueue(run.id)
        return run

    async def cancel_all(self) -> int:
        """Kill switch helper: request cancellation of every non-terminal run."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id FROM runs WHERE status NOT IN ('completed', 'failed', 'cancelled')"
            )
            ids = [r["id"] for r in await cur.fetchall()]
        cancelled = 0
        for run_id in ids:
            try:
                await self.cancel(run_id)
                cancelled += 1
            except RunTerminal:
                pass  # finished meanwhile
        return cancelled

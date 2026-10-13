"""Application service for runs: the use cases the API and CLI share.

Pattern: Service Layer. Transport code (HTTP handlers, CLI commands) parses
requests and renders responses; the rules for *creating* a run (graph exists,
input valid for that graph, options within ceilings) live here once.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import GraphRegistry
from agent_runtime.runs.limits import RunOptions, resolve_limits
from agent_runtime.runs.relay import OutboxRelay
from agent_runtime.runs.store import Run, RunRepository

log = logging.getLogger(__name__)


class RunService:
    def __init__(
        self,
        pool: Pool,
        settings: Settings,
        graphs: GraphRegistry,
        relay: OutboxRelay | None = None,
    ) -> None:
        self._pool = pool
        self._settings = settings
        self._graphs = graphs
        self._relay = relay

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
        spec = self._graphs.get(graph)
        validated_input = spec.input_model.model_validate(input)
        run_options = RunOptions.model_validate(options or {})
        limits = resolve_limits(self._settings, run_options)
        async with self._pool.connection() as conn:
            run = await RunRepository(conn).create(
                graph_name=graph,
                input=validated_input.model_dump(mode="json"),
                options=run_options.model_dump(exclude_none=True),
                limits=limits.model_dump(),
            )
        if enqueue and self._relay is not None:
            try:
                await self._relay.enqueue(run.id)
            except Exception:
                log.warning("run %s created but not enqueued; the relay will send it", run.id,
                            exc_info=True)  # fmt: skip
        return run

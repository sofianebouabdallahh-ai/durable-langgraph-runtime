"""Application service for runs: the use cases the API and CLI share.

Pattern: Service Layer. Transport code (HTTP handlers, CLI commands) parses
requests and renders responses; the rules for *creating* a run (graph exists,
input valid for that graph, options within ceilings) live here once.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import GraphRegistry
from agent_runtime.runs.limits import RunOptions, resolve_limits
from agent_runtime.runs.store import Run, RunRepository


class RunService:
    def __init__(self, pool: Pool, settings: Settings, graphs: GraphRegistry) -> None:
        self._pool = pool
        self._settings = settings
        self._graphs = graphs

    async def create_run(
        self, graph: str, input: dict[str, Any], options: dict[str, Any] | None = None
    ) -> Run:
        """Validate and create a `queued` run.

        Raises UnknownGraph, pydantic.ValidationError (input or options) or
        LimitAboveCeiling; the transport layer maps them to 404/422.
        """
        spec = self._graphs.get(graph)
        validated_input = spec.input_model.model_validate(input)
        run_options = RunOptions.model_validate(options or {})
        limits = resolve_limits(self._settings, run_options)
        async with self._pool.connection() as conn:
            return await RunRepository(conn).create(
                graph_name=graph,
                input=validated_input.model_dump(mode="json"),
                options=run_options.model_dump(exclude_none=True),
                limits=limits.model_dump(),
            )

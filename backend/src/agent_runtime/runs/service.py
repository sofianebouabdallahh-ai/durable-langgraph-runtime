"""Application service for runs: the use cases the API and CLI share.

Pattern: Service Layer. Transport code (HTTP handlers, CLI commands) parses
requests and renders responses; the rules for *creating* a run (graph exists,
input valid for that graph, options within ceilings) live here once, in
`prepare`, which the executor also uses to validate child runs (R2.8).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from agent_runtime import logs
from agent_runtime.admin import AdminRepository
from agent_runtime.agents.resolver import AgentResolver, Resolved
from agent_runtime.audit import AuditLog
from agent_runtime.config import AgentSettings, Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import GraphRegistry, GraphSpec
from agent_runtime.models.connections import ModelRouter, any_local
from agent_runtime.runs.limits import RunOptions, local_model_limits, profile_of, resolve_limits
from agent_runtime.runs.relay import OutboxRelay
from agent_runtime.runs.state import RunStatus
from agent_runtime.runs.store import Run, RunRepository, RunTerminal
from agent_runtime.runs.switches import ensure_on
from agent_runtime.streaming.bus import EventBus, publish_events
from agent_runtime.tools.builtin import default_tools

log = logging.getLogger(__name__)


class AdmissionPaused(Exception):
    """The kill switch is on (R14.18): no new runs are accepted."""

    def __init__(self, reason: str | None) -> None:
        super().__init__(f"the runtime is paused{f': {reason}' if reason else ''}")
        self.reason = reason


class Overloaded(Exception):
    """Admission control: backpressure (R2.9) or a rate / cost ceiling (R14.8)."""

    def __init__(
        self,
        depth: int,
        limit: int,
        retry_after_s: int,
        *,
        reason: str = "queue_depth",
        detail: str | None = None,
    ) -> None:
        super().__init__(detail or f"{depth} runs are queued (limit {limit}); retry later")
        self.depth = depth
        self.limit = limit
        self.retry_after_s = retry_after_s
        self.reason = reason  # queue_depth | rate_limited | daily_budget


@dataclass(frozen=True)
class Prepared:
    """A run that passed validation and is ready to insert."""

    graph_name: str
    input: dict[str, Any]
    options: dict[str, Any]
    limits: dict[str, Any]


def prepare(
    graphs: GraphRegistry,
    settings: AgentSettings,
    graph: str,
    input: dict[str, Any],
    options: dict[str, Any] | None,
) -> Prepared:
    """Validate a new run: the graph exists, the input is valid for it, the options
    are within the ceilings. Raises UnknownGraph, pydantic.ValidationError or
    LimitAboveCeiling."""
    return prepare_spec(graphs.get(graph), settings, input, options)


def prepare_spec(
    spec: GraphSpec,
    settings: AgentSettings,
    input: dict[str, Any],
    options: dict[str, Any] | None,
) -> Prepared:
    """`prepare` for a spec already resolved (an agent pinned by hash)."""
    graph = spec.name
    validated_input = spec.input_model.model_validate(input)
    run_options = RunOptions.model_validate(options or {})
    limits = resolve_limits(settings, run_options, profile_of(spec))
    return Prepared(
        graph_name=graph,
        input=validated_input.model_dump(mode="json"),
        options=run_options.model_dump(exclude_none=True),
        limits=limits.model_dump(exclude_none=True),
    )


class RunService:
    def __init__(
        self,
        pool: Pool,
        settings: Settings,
        graphs: GraphRegistry,
        relay: OutboxRelay | None = None,
        bus: EventBus | None = None,
        agents: AgentResolver | None = None,
    ) -> None:
        self._pool = pool
        self._settings = settings
        self._graphs = graphs
        self._relay = relay
        self._bus = bus
        self.agents = agents or AgentResolver(pool, graphs, default_tools())
        self.models = ModelRouter(pool, settings)  # model strings → connections (L3b)
        self._depth: tuple[float, int] | None = None  # (read at, value): cached per replica

    async def create_run(
        self,
        graph: str,
        input: dict[str, Any],
        options: dict[str, Any] | None = None,
        *,
        enqueue: bool = True,
    ) -> Run:
        """Validate, create a `queued` run, and hand it to the workers.

        Raises AdmissionPaused, Overloaded, UnknownGraph, pydantic.ValidationError
        (input or options) or LimitAboveCeiling; the transport layer maps them to
        503/429/404/422.

        The run is durable once created. Sending its work message is best
        effort: if Redis is unavailable, the outbox relay sends it later.
        """
        await self._check_paused()
        pinned: Resolved | None = None
        agent: tuple[str, str, int] | None = None
        bindings: dict[str, Any] | None = None
        if self.agents.builtin(graph) is not None:  # an agent: pin its definition (R15.4)
            async with self._pool.connection() as conn:
                pinned = await self.agents.resolve(conn, graph)
                await ensure_on(conn, pinned.definition.id)  # its kill switch (L6)
                bindings = await self.models.bind(conn, pinned.definition)
            prepared = prepare_spec(self.agents.spec_of(pinned), self._settings, input, options)
            if any_local(bindings):  # a local model: more time per turn (the Studio's drafts)
                prepared = replace(prepared, limits=local_model_limits(prepared.limits,
                                                                       self._settings))  # fmt: skip
            agent = (pinned.bundle_hash, pinned.definition.id, pinned.version)
        else:
            prepared = prepare(self._graphs, self._settings, graph, input, options)
        await self.admit()
        async with self._pool.connection() as conn:
            repo = RunRepository(conn)
            run = await repo.create(
                graph_name=prepared.graph_name,
                input=prepared.input,
                options=prepared.options,
                limits=prepared.limits,
                agent=agent,
                model_bindings=bindings,
            )
        await publish_events(self._bus, repo.emitted)  # after commit (R1.5)
        if enqueue and self._relay is not None:
            try:
                await self._relay.enqueue(run.id)
            except Exception:
                log.warning("run %s created but not enqueued; the relay will send it", run.id,
                            exc_info=True)  # fmt: skip
        return run

    async def _check_paused(self) -> None:
        async with self._pool.connection() as conn:
            state = await AdminRepository(conn).get()
        if state.paused:
            raise AdmissionPaused(state.reason)

    async def admit(self) -> None:
        """Admission control for new work from outside (runs, chat turns): the kill
        switch (R14.18) and backpressure (R2.9). Workers' own fan-outs skip it."""
        await self._check_paused()
        depth = await self.queue_depth()
        if depth >= self._settings.queue_depth_limit:
            raise Overloaded(
                depth, self._settings.queue_depth_limit, self._settings.overload_retry_after_s
            )
        if (ceiling := self._settings.global_daily_cost_usd) is not None:
            spent = await self.cost_today()
            if spent >= ceiling:  # R14.8: new runs are refused; runs in flight finish
                raise Overloaded(
                    depth, self._settings.queue_depth_limit, retry_after_s=_until_midnight_s(),
                    reason="daily_budget",
                    detail=f"today's cost ceiling (${ceiling:g}) is reached (${spent:.4f})",
                )  # fmt: skip

    async def cost_today(self) -> float:
        """Spend since midnight UTC, over root runs only (children roll up into them)."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT coalesce(sum(cost), 0) AS spent FROM runs WHERE parent_run_id IS NULL "
                "AND created_at >= date_trunc('day', now() AT TIME ZONE 'utc') AT TIME ZONE 'utc'"
            )
            row = await cur.fetchone()
        return float(row["spent"]) if row else 0.0

    async def queue_depth(self) -> int:
        """Runs waiting for a worker (R2.9), cached for `queue_depth_cache_s` so a
        burst of POST /runs costs one COUNT per replica per second."""
        now = time.monotonic()
        if self._depth is not None and now - self._depth[0] < self._settings.queue_depth_cache_s:
            return self._depth[1]
        async with self._pool.connection() as conn:
            depth = await RunRepository(conn).queue_depth()
        self._depth = (now, depth)
        return depth

    async def cancel(self, run_id: uuid.UUID) -> Run:
        """R1.6: queued or waiting → cancelled now; running → its worker stops at the
        next node; live descendants are cancelled too (R2.8).
        Raises RunTerminal (→ 409) or RunNotFound (→ 404)."""
        async with self._pool.connection() as conn:
            repo = RunRepository(conn)
            run = await repo.request_cancel(run_id)
        await publish_events(self._bus, repo.emitted)
        await self._enqueue(repo.ready)  # a cancelled child may have been its parent's last
        return run

    async def _enqueue(self, run_ids: list[uuid.UUID]) -> None:
        if self._relay is None:
            return
        for run_id in run_ids:
            try:
                await self._relay.enqueue(run_id)
            except Exception:
                log.warning("run %s is queued but not sent; the relay will send it", run_id,
                            exc_info=True)  # fmt: skip

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

    async def decide_approval(
        self,
        run_id: uuid.UUID,
        decision: Literal["approve", "reject"],
        edits: dict[str, Any] | None = None,
        reason: str | None = None,
        *,
        approval_id: uuid.UUID | None = None,
    ) -> Run:
        """R1.4: decide one of the run's pending approvals; the run is re-queued once
        none is left, or cancelled (rejected). No live worker is needed. Raises
        NotWaitingForApproval or ApprovalConflict (→ 409)."""
        async with self._pool.connection() as conn, conn.transaction():
            repo = RunRepository(conn)
            run, decided = await repo.decide_approval(
                run_id, approval_id=approval_id, decision=decision, edits=edits, reason=reason,
                decided_by="local",  # an authenticated principal once auth exists (roadmap)
            )  # fmt: skip
            await AuditLog(conn).record("approval.decided", "run", run_id, after={
                "approval_id": str(decided.id), "tool": decided.tool, "decision": decision,
                "reason": reason, "edited": bool(edits)})  # fmt: skip
        await publish_events(self._bus, repo.emitted)
        logs.event(log, f"approval decided: {decision}", run_id=str(run_id), decision=decision,
                   approval_id=str(decided.id), tool=decided.tool)  # fmt: skip
        if run.status is RunStatus.QUEUED and self._relay is not None:
            await self._relay.enqueue(run.id)
        return run


def _until_midnight_s() -> int:
    now = datetime.now(UTC)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - now).total_seconds()))

"""The sub-agent orchestrator (CR-005 R16.3-R16.9): leaf agents a main agent runs
in its own worker, durably.

Pattern: Supervisor (in-process). The orchestrator owns its sub-agents'
lifecycle; the main agent only sees four tools (spawn, status, wait, cancel).

    spawn ── row in subagent_invocations (handle = f(idempotency key)) ── task
    task  ── create_agent graph, own checkpoint thread `<run>/sub/<handle>`,
             FencedCheckpointer under the MAIN run's fence (one lease for all),
             own outbox into the main run's event log, its steps not counted
    ends  ── completed | failed | cancelled | timed_out, exactly once

Rules:
- **Fresh context.** Each task starts in an empty contextvars.Context(): a graph
  started inside a running node otherwise inherits the parent's run, and the
  parent's callbacks see its nodes (measured in the phase 5 research).
- **One recovery path.** `stop()` cancels the tasks and leaves their rows
  `running`; `recover()` resumes every running row from its checkpoint. A pause,
  a graceful release and a crash all end up there. Completed handles are never
  re-run (AC41).
- **Stop before the main run leaves `running`.** The fence compares epochs only,
  and a pause or release doesn't change the epoch: a sub-agent left running
  could keep writing under a lease nobody holds. The executor stops (or cancels)
  them first.
- **Budgets roll up** (R16.8): each model/tool call charges the sub-agent's own
  limits AND the main run's. At the soft limit (80 %) sub-agents are asked to
  wrap up; when the run's hard limit is hit they are cancelled.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.pregel import Pregel

from agent_runtime import logs, telemetry
from agent_runtime.agents.schema import AgentDefinition, SubAgentDefinition
from agent_runtime.checkpointing import FencedCheckpointer
from agent_runtime.db import Conn, Pool
from agent_runtime.fencing import Fence, FencedError, check_fence
from agent_runtime.models.scripted import ScriptTurn
from agent_runtime.runs.outbox import Outbox
from agent_runtime.streaming.bus import EventBus, StreamEvent, publish_events, session_channel
from agent_runtime.subagents.store import Invocation, SpawnRefused, Status, SubagentRepository
from agent_runtime.subagents.tools import SubagentToolError
from agent_runtime.tools.hooks import HookRegistry
from agent_runtime.tools.invocations import BudgetExceeded, charge_model_call
from agent_runtime.tools.pipeline import Grant, ToolPipeline, ToolRunContext
from agent_runtime.tools.policy import ToolPolicy
from agent_runtime.tools.spec import ToolRegistry

if TYPE_CHECKING:
    from agent_runtime.runs.limits import RunLimits

log = logging.getLogger(__name__)

BuildGraph = Callable[[SubAgentDefinition, BaseCheckpointSaver[Any]], Pregel[Any, Any]]

WRAP_UP_NOTE = (
    "[runtime] The run's budget is nearly used up. Stop now: call `return_result` with "
    "what you have (status `partial` if the task isn't finished)."
)


class SubagentCancelled(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SubagentLimits:
    """Per run (R16.3); configuration may only lower them (R14.3)."""

    max_parallel: int = 4
    max_total: int = 10
    default_timeout_s: int = 180  # when the sub-agent's file sets no timeout_s
    soft_limit: float = 0.8  # of the main run's budgets (R16.8)


def _no_interrupt(_: Any) -> Any:
    raise RuntimeError("sub-agents never pause for approval")  # approvals=False denies first


@dataclass
class SubagentRuntime:
    """One running sub-agent, as its middleware and tools see it."""

    orchestrator: SubagentOrchestrator
    inv: Invocation
    defn: SubAgentDefinition
    returned: dict[str, Any] | None = None  # set by return_result (or recovered from the row)
    caps: dict[str, int | None] = field(default_factory=dict)

    @property
    def handle(self) -> uuid.UUID:
        return self.inv.handle

    async def before_model(self) -> None:
        """Between steps: honour a cancel, then charge one model call to the
        sub-agent's max_turns and to the run's budget, in one fenced transaction."""
        o = self.orchestrator
        await self._check_cancel()
        async with o.pool.connection() as conn, conn.transaction():
            await check_fence(conn, o.fence)
            await SubagentRepository(conn).charge(
                o.fence, self.handle, model_calls=1,
                max_model_calls=self.defn.frontmatter.max_turns, max_tool_calls=None,
            )  # fmt: skip
            await charge_model_call(
                conn, fence=o.fence, max_calls=o.run_limits.max_model_calls,
                max_tokens=o.run_limits.max_tokens, max_cost_usd=o.run_limits.max_cost_usd,
            )  # fmt: skip
            await o.check_soft_limit(conn)

    async def before_tool(self) -> None:
        await self._check_cancel()

    async def charge_tool(self, conn: Conn, tool: str) -> None:
        """The ledger's extra charge: this sub-agent's own tool budget."""
        await SubagentRepository(conn).charge(
            self.orchestrator.fence, self.handle, tool=tool, max_model_calls=None,
            max_tool_calls=self.defn.frontmatter.limits.max_tool_calls,
            max_for_tool=self.caps.get(tool),
        )  # fmt: skip

    async def report_progress(self, message: str, percent: int | None) -> str | None:
        o = self.orchestrator
        async with o.pool.connection() as conn:
            repo = SubagentRepository(conn)
            dropped = await repo.report_progress(o.fence, self.handle, message, percent)
        await o.announce(repo.emitted)
        return dropped

    async def return_result(self, result: dict[str, Any]) -> None:
        if self.returned is not None:
            raise SubagentToolError("return_result was already called")
        o = self.orchestrator
        async with o.pool.connection() as conn:
            await SubagentRepository(conn).set_result(o.fence, self.handle, result)
        self.returned = result

    async def _check_cancel(self) -> None:
        o = self.orchestrator
        async with o.pool.connection() as conn:
            current = await SubagentRepository(conn).get(self.handle)
        if current is not None and current.cancel_requested:
            raise SubagentCancelled(current.cancel_reason or "cancel requested")


class SubagentOrchestrator:
    def __init__(
        self,
        *,
        pool: Pool,
        fence: Fence,
        bus: EventBus | None,
        main: AgentDefinition,
        build: BuildGraph,
        tools: ToolRegistry,
        hooks: HookRegistry,
        policy: ToolPolicy,
        run_limits: RunLimits,
        deadline: float,  # the main run's timeout, as a time.time() value
        scripts: dict[str, list[ScriptTurn]] | None = None,
        limits: SubagentLimits | None = None,
        worker: str | None = None,  # the main run's owner, recorded on subagent.spawned
        session_id: uuid.UUID | None = None,  # chat turns: events also go to the session
        model_caller: Callable[[], Any] | None = None,  # retries + breaker (R14.7)
        usage_recorder: Callable[[Outbox], Callable[[str, int, int], float]] | None = None,
        chat_model: Callable[[str, float, list[ScriptTurn]], Callable[[int], Any]] | None = None,
        skills: Mapping[str, tuple[Any, ...]] | None = None,  # by helper name (R17.4)
    ) -> None:
        self.pool = pool
        self.fence = fence
        self.bus = bus
        self.run_limits = run_limits
        self.limits = limits or SubagentLimits()
        self._defs = {s.frontmatter.name: s for s in main.subagents}
        self._skills = skills or {}
        self._build = build
        self._tools = tools
        self._hooks = hooks
        self._policy = policy
        self._deadline = deadline
        self._scripts = scripts or {}
        self.worker = worker
        self._session_id = session_id
        self._model_caller = model_caller
        self._usage_recorder = usage_recorder
        self._chat_model = chat_model
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._sem = asyncio.Semaphore(self.limits.max_parallel)
        self.wrap_up = False  # the soft limit was reached (R16.8)
        self.exhausted: str | None = None  # the run's hard limit, once hit
        self.running_now = 0
        self.max_running_seen = 0  # observability and tests (≤ max_parallel)

    @property
    def run_id(self) -> uuid.UUID:
        return self.fence.run_id

    # --------------------------------------------------------------- lifecycle

    async def recover(self) -> list[uuid.UUID]:
        """Resume every sub-agent still `running` from its own checkpoint (R16.3)."""
        async with self.pool.connection() as conn:
            invs = [i for i in await SubagentRepository(conn).list(self.run_id) if i.is_running]
        for inv in invs:
            self._start(inv)
        return [i.handle for i in invs]

    def running(self) -> bool:
        return any(not t.done() for t in self._tasks.values())

    async def stop(self) -> None:
        """Stop every task now, leaving its row `running`: `recover` resumes it later
        from its last checkpoint (pause, release, crash)."""
        tasks = [t for t in self._tasks.values() if not t.done()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def cancel_all(self, reason: str) -> None:
        """The main run is ending: no sub-agent outlives it (R16.9)."""
        await self.stop()
        async with self.pool.connection() as conn:
            running = [i for i in await SubagentRepository(conn).list(self.run_id) if i.is_running]
        for inv in running:
            await self._finish(inv.handle, "cancelled", {"status": "failed", "reason": reason})

    # ------------------------------------------------------------------- tools

    async def spawn(self, key: str, agent: str, task: str, context: str | None) -> Invocation:
        if agent not in self._defs:
            available = ", ".join(sorted(self._defs)) or "none"
            raise SubagentToolError(f"unknown sub-agent {agent!r}; available: {available}")
        if self.exhausted:
            raise SubagentToolError(f"the run's budget is exhausted ({self.exhausted})")
        try:
            async with self.pool.connection() as conn:
                repo = SubagentRepository(conn)
                inv, _ = await repo.spawn(
                    self.fence, key=key, agent=self._defs[agent].id, task=task,
                    context=context, max_total=self.limits.max_total, worker=self.worker,
                )  # fmt: skip
        except SpawnRefused as exc:
            raise SubagentToolError(str(exc)) from None
        await self.announce(repo.emitted)
        if inv.is_running and inv.handle not in self._tasks:
            self._start(inv)  # replayed spawn of a live handle: already running here
        return inv

    async def status(self, handles: list[uuid.UUID] | None = None) -> list[dict[str, Any]]:
        invs = await self._list(handles)
        return [i.view() for i in invs]

    async def wait(self, handles: list[uuid.UUID], timeout_s: float) -> dict[str, Any]:
        invs = await self._list(handles)  # validates the handles first
        tasks = [self._tasks[h] for h in handles if h in self._tasks and not self._tasks[h].done()]
        budget = min(timeout_s, self._deadline - time.time())
        if tasks and budget > 0:
            await asyncio.wait(tasks, timeout=budget)
        invs = await self._list(handles)
        return {
            "completed": [self.outcome(i) for i in invs if not i.is_running],
            "pending": [i.view() for i in invs if i.is_running],
        }

    async def wait_all(self) -> list[dict[str, Any]]:
        """R16.9: the main agent answered while sub-agents ran. Wait for them (bounded
        by the run's remaining time) and return every outcome."""
        tasks = [t for t in self._tasks.values() if not t.done()]
        budget = self._deadline - time.time()
        if tasks and budget > 0:
            await asyncio.wait(tasks, timeout=budget)
        return [self.outcome(i) for i in await self._list(None)]

    async def cancel(self, handle: uuid.UUID, reason: str) -> bool:
        await self._list([handle])
        async with self.pool.connection() as conn:
            return await SubagentRepository(conn).request_cancel(self.fence, handle, reason)

    async def announce(self, events: list[Any]) -> None:
        """After commit: the run's channel (persisted events), and, for a chat turn,
        the session's channel as transient events, so the chat shows sub-agents'
        progress live (CR-005 R16.10, AC37)."""
        await publish_events(self.bus, events)
        if self.bus is None or self._session_id is None:
            return
        for e in events:
            try:
                await self.bus.publish(session_channel(self._session_id), StreamEvent(
                    run_id=e.run_id, seq=None, ts=e.ts, epoch=e.epoch, type=str(e.type),
                    payload=e.payload, after_seq=0,
                ))  # fmt: skip
            except Exception:
                log.warning("session relay of %s failed (transient: dropped)", e.type,
                            exc_info=True)  # fmt: skip

    @staticmethod
    def outcome(inv: Invocation) -> dict[str, Any]:
        return {"handle": str(inv.handle), "agent": inv.name, "status": inv.status,
                **(inv.result or {})}  # fmt: skip

    async def check_soft_limit(self, conn: Conn) -> None:
        """At 80 % of the run's model or tool budget, ask sub-agents to wrap up."""
        if self.wrap_up:
            return
        cur = await conn.execute(
            "SELECT model_calls, tool_calls_total FROM runs WHERE id = %s", (self.run_id,)
        )
        row = await cur.fetchone()
        if row is None:
            return
        for used, limit in (
            (row["model_calls"], self.run_limits.max_model_calls),
            (row["tool_calls_total"], self.run_limits.max_tool_calls),
        ):
            if limit and used >= self.limits.soft_limit * limit:
                self.wrap_up = True

    # --------------------------------------------------------------- internals

    async def _list(self, handles: list[uuid.UUID] | None) -> list[Invocation]:
        async with self.pool.connection() as conn:
            invs = await SubagentRepository(conn).list(self.run_id, handles)
        if handles is not None and len(invs) != len(set(handles)):
            unknown = set(handles) - {i.handle for i in invs}
            raise SubagentToolError(f"unknown handle(s): {', '.join(map(str, sorted(unknown)))}")
        return invs

    def _start(self, inv: Invocation) -> None:
        # An empty context: the task must not inherit the main graph's run (measured).
        # Its span hangs below the node that spawned it (or the run, on recovery).
        # Its log lines carry the run's ids, taken over explicitly for the same reason
        # (not the spawning tool call's: the helper isn't part of it).
        parent = telemetry.parent_context()
        fields = logs.fields(without=("tool", "tool_call_id"))
        self._tasks[inv.handle] = asyncio.create_task(
            self._run(inv, parent, fields), name=f"subagent:{inv.agent}",
            context=contextvars.Context(),
        )  # fmt: skip

    async def _run(
        self, inv: Invocation, parent: Any = None, fields: dict[str, Any] | None = None
    ) -> None:
        attrs = {"subagent.handle": str(inv.handle), "subagent.name": inv.name,
                 "worker": self.worker or ""}  # fmt: skip
        run = {"run_id": str(self.run_id), "epoch": self.fence.epoch,
               "trace_id": telemetry.run_trace_id()}  # fmt: skip
        with (
            telemetry.child_span(f"subagent:{inv.name}", attrs, current=True, parent=parent),
            logs.bind(**{**run, **(fields or {})}, helper=inv.name, helper_handle=str(inv.handle)),
        ):
            logs.event(log, f"helper {inv.name} started")
            await self._run_traced(inv)

    async def _run_traced(self, inv: Invocation) -> None:
        try:
            async with self._sem:
                self.running_now += 1
                self.max_running_seen = max(self.max_running_seen, self.running_now)
                try:
                    await self._execute(inv)
                finally:
                    self.running_now -= 1
        except asyncio.CancelledError:
            raise  # stopped: the row stays running and is recovered later
        except FencedError:
            log.info("sub-agent %s: fenced off (the run has a new owner)", inv.handle)
        except Exception:
            log.exception("sub-agent %s crashed", inv.handle)
            await self._finish(inv.handle, "failed", {"status": "failed", "reason": "error"})

    async def _execute(self, inv: Invocation) -> None:
        defn = self._defs[inv.name]
        runtime = SubagentRuntime(
            self, inv, defn, returned=inv.result,
            caps={t.name: t.max_calls for t in defn.frontmatter.tools},
        )  # fmt: skip
        outbox = Outbox(self.run_id, self.fence, committed_steps=0, bus=self.bus,
                        counts_steps=False)  # fmt: skip
        checkpointer = FencedCheckpointer(
            self.pool, self.fence, on_commit=outbox.on_commit, after_commit=outbox.after_commit
        )
        graph = self._build(defn, checkpointer)
        config: RunnableConfig = {
            "configurable": {"thread_id": inv.thread_id},
            "recursion_limit": 4 * defn.frontmatter.max_turns + 10,
        }
        resuming = await checkpointer.aget_tuple(config) is not None
        graph_input = None if resuming else {"messages": [{"role": "user", "content": _task(inv)}]}
        timeout_s = defn.frontmatter.limits.timeout_s or self.limits.default_timeout_s
        remaining = min(inv.created_at.timestamp() + timeout_s, self._deadline) - time.time()

        status: Status
        try:
            if remaining <= 0:
                raise TimeoutError
            context = self._context(inv, runtime, outbox)
            async with asyncio.timeout(remaining):
                final = await graph.ainvoke(graph_input, config, durability="sync", context=context)
            result = runtime.returned or {"status": "success", "summary": _last_answer(final)}
            status = "failed" if result.get("status") == "failed" else "completed"
        except TimeoutError:
            status, result = "timed_out", await self._limit_result(inv, "timeout")
        except SubagentCancelled as exc:
            status, result = "cancelled", {"status": "failed", "reason": f"cancelled: {exc.reason}"}
        except BudgetExceeded as exc:
            status, result = "failed", await self._limit_result(inv, exc.reason)
            if not exc.reason.startswith("subagent:"):  # the RUN's hard limit (R16.8)
                await self._exhausted(exc.reason, inv.handle)
        await self._finish(inv.handle, status, result, outbox)

    def _context(self, inv: Invocation, runtime: SubagentRuntime, outbox: Outbox) -> Any:
        from agent_runtime.graphs.assistant import granted_tools  # imports this module
        from agent_runtime.tools.middleware import RunContext  # imports this module

        fm = runtime.defn.frontmatter
        handle = str(inv.handle)
        tools = ToolRunContext(
            fence=self.fence,
            pool=self.pool,
            # Its own tools and skills only (R16.7); per-tool caps are charged per sub-agent.
            grants={n: Grant() for n in granted_tools(runtime.defn)},
            skills={s.name: s for s in self._skills.get(fm.name, ())},
            emit=lambda type, payload: outbox.stage(type, {**payload, "subagent": handle}),
            pre_hooks=[self._hooks.get(h) for h in fm.hooks.pre_tool],
            post_hooks=[self._hooks.get(h) for h in fm.hooks.post_tool],
            max_tool_calls=self.run_limits.max_tool_calls,
            node=f"sub/{handle}",
            approvals=False,
            subagent=runtime,
            extra_charge=runtime.charge_tool,
        )
        pipeline = ToolPipeline(self._tools, self._policy, interrupt=_no_interrupt)
        extras: dict[str, Any] = {}
        if self._model_caller is not None:
            extras["caller"] = self._model_caller()
        if self._usage_recorder is not None:  # its tokens and cost roll up into the run
            extras["record_usage"] = self._usage_recorder(outbox)
        if self._chat_model is not None:  # its own model role (R16.2: `model:` in its file)
            extras["chat_model"] = self._chat_model(
                fm.model, fm.temperature, self._scripts.get(inv.name, [])
            )
        return RunContext(
            tools, pipeline, max_model_calls=self.run_limits.max_model_calls,
            script=self._scripts.get(inv.name, []), subagent=runtime, **extras,
        )  # fmt: skip

    async def _limit_result(self, inv: Invocation, reason: str) -> dict[str, Any]:
        """A limit hit: `partial` if it reported progress, else `failed` (R16.5)."""
        async with self.pool.connection() as conn:
            current = await SubagentRepository(conn).get(inv.handle)
        progress = (current.progress if current else {}).get("message")
        return {"status": "partial" if progress else "failed", "summary": progress or "",
                "reason": reason}  # fmt: skip

    async def _exhausted(self, reason: str, hit_by: uuid.UUID) -> None:
        """The run's hard limit: cancel every other sub-agent now (R16.8)."""
        self.exhausted = reason
        others = [t for h, t in self._tasks.items() if h != hit_by and not t.done()]
        for t in others:
            t.cancel()
        await asyncio.gather(*others, return_exceptions=True)
        async with self.pool.connection() as conn:
            running = [i for i in await SubagentRepository(conn).list(self.run_id) if i.is_running]
        for i in running:
            if i.handle != hit_by:
                await self._finish(i.handle, "cancelled", {"status": "failed", "reason": reason})

    async def _finish(
        self,
        handle: uuid.UUID,
        status: Status,
        result: dict[str, Any],
        outbox: Outbox | None = None,
    ) -> None:
        try:
            async with self.pool.connection() as conn:
                repo = SubagentRepository(conn)
                async with conn.transaction():
                    if outbox is not None:
                        await outbox.flush(repo.runs)  # what its last, unfinished step staged
                    await repo.finish(self.fence, handle, status, result)
            await self.announce(repo.emitted)
            logs.event(log, f"helper {handle} {status}", status=status,
                       reason=result.get("reason"))  # fmt: skip
        except FencedError:
            log.info("sub-agent %s: not finished here (fenced off)", handle)


def _task(inv: Invocation) -> str:
    """R16.6: the sub-agent's only user message. It sees nothing else of the main run."""
    return inv.task if not inv.context else f"{inv.task}\n\nContext:\n{inv.context}"


def _last_answer(state: dict[str, Any]) -> str:
    messages = state.get("messages", [])
    return next((str(m.content) for m in reversed(messages) if isinstance(m, AIMessage)), "")

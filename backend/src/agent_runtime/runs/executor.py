"""Run executor: drive one run's graph durably, under a lease (R1.2, R1.3, R1.7, R2.3).

    acquire lease (epoch+1) ──► started | reclaimed ──► graph.ainvoke(durability="sync")
      │ held elsewhere: return its status (R1.3)          │ per superstep, ONE fenced txn:
      ▼                                                   ▼   checkpoint + events + step count
                                 completed | failed(reason): fenced, lease released

Patterns:
- Transactional Outbox: node events are *staged* in memory while a superstep
  runs and *committed inside that superstep's checkpoint transaction*
  (`FencedCheckpointer.on_commit`). A committed step always has its events; a
  step lost to a crash has none and is re-run, so events are exactly-once per
  committed step.
- Observer: `_NodeRecorder` is a LangChain callback handler. LangGraph calls it
  inline when each node starts and ends, before the step's checkpoint is
  written (verified in the phase 1 spike), so it can stage events, and it can
  refuse to start a node once the step budget is spent.
- Lease + heartbeat: ownership is renewed every `heartbeat_s`; if renewal
  fails, another worker has taken over and this execution stops. Fencing makes
  any write it still attempts fail anyway (defence in depth).

`durability="sync"` is mandatory: the spike showed that with async durability a
fenced-off zombie executes extra steps before noticing.

Child runs (R2.8): a node's `spawn_children` interrupt is turned into a fan-out
(`_fan_out`: children + waiting_children in one fenced transaction). When the
parent is re-queued, `_resume_value` computes the fan-in from the children's
results, and LangGraph re-runs the node with it. Runs that become queued are
sent to the work queue only after their transaction commits (`enqueue`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.types import Command, interrupt

from agent_runtime.checkpointing import FencedCheckpointer
from agent_runtime.config import Settings
from agent_runtime.db import Conn, Pool
from agent_runtime.fencing import Fence, FencedError, check_fence
from agent_runtime.graphs import GraphRegistry, GraphSpec
from agent_runtime.graphs.assistant import AgentInput, granted_tools, subagent_graph
from agent_runtime.models.provider import configured_provider
from agent_runtime.models.retry import CircuitOpen, ModelCaller, breaker_for
from agent_runtime.models.scripted import ScriptTurn
from agent_runtime.runs.events import EventType
from agent_runtime.runs.fanout import (
    ChildResult,
    ChildSpec,
    FanIn,
    LocalSpawner,
    RunSpawner,
    Spawner,
    WorkflowContext,
    is_spawn,
)
from agent_runtime.runs.limits import RunLimits, RunOptions, resolve_limits
from agent_runtime.runs.outbox import Outbox
from agent_runtime.runs.service import prepare
from agent_runtime.runs.state import FailureReason, RunStatus
from agent_runtime.runs.store import (
    FanOutLimits,
    FanOutRejected,
    NewChild,
    Run,
    RunRepository,
    RunTerminal,
)
from agent_runtime.sessions.store import SessionRepository
from agent_runtime.sessions.transcript import TranscriptWriter
from agent_runtime.sessions.turns import turn_input
from agent_runtime.streaming.bus import EventBus, publish_events, run_channel, session_channel
from agent_runtime.streaming.tokens import TokenRelay
from agent_runtime.subagents.orchestrator import SubagentLimits, SubagentOrchestrator
from agent_runtime.tools.builtin import default_tools
from agent_runtime.tools.hooks import (
    HookRegistry,
    SessionEndInput,
    Summary,
    TurnEndInput,
    default_hooks,
    run_observers,
)
from agent_runtime.tools.invocations import BudgetExceeded, LoopDetected
from agent_runtime.tools.middleware import RunContext, TurnDenied, TurnInfo
from agent_runtime.tools.pipeline import Grant, ToolPipeline, ToolRunContext
from agent_runtime.tools.policy import RiskClassPolicy, ToolPolicy
from agent_runtime.tools.spec import ToolRegistry

log = logging.getLogger(__name__)


def default_owner() -> str:
    """`{hostname}:{pid}` (R2.2). On Kubernetes the hostname is the pod name."""
    return os.environ.get("WORKER_ID") or f"{socket.gethostname()}:{os.getpid()}"


class StepLimitReached(Exception):
    pass


class ReleaseRequested(Exception):
    """The worker is shutting down: hand the run off after the current step (R10.7)."""


class CancelRequested(Exception):
    """Someone asked to cancel the run (R1.6)."""


class LeaseLost(Exception):
    pass


class _NodeRecorder(AsyncCallbackHandler):
    """Observes node starts and ends; stages node events; enforces max_steps."""

    raise_error = True  # let StepLimitReached abort the run instead of being logged

    def __init__(
        self,
        outbox: Outbox,
        max_steps: int,
        check_interrupts: Callable[[], Awaitable[None]],
    ) -> None:
        self._outbox = outbox
        self._max_steps = max_steps
        self._check_interrupts = check_interrupts
        self._started: dict[uuid.UUID, tuple[str, float]] = {}

    async def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: dict[str, Any] | Any,
        *,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        node = (metadata or {}).get("langgraph_node")
        # Only the node's own run, not runnables nested inside it.
        if node is None or kwargs.get("name") != node or str(node).startswith("__"):
            return
        if self._outbox.committed_steps >= self._max_steps:
            raise StepLimitReached(f"max_steps={self._max_steps} reached before node {node!r}")
        # Between nodes is the safe point: the previous step is checkpointed (R1.6, R10.7).
        await self._check_interrupts()
        self._started[run_id] = (node, time.monotonic())
        self._outbox.stage(EventType.NODE_STARTED, {"node": node})

    async def on_chain_end(self, outputs: Any, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        if started := self._started.pop(run_id, None):
            node, t0 = started
            self._outbox.stage(EventType.NODE_COMPLETED, {"node": node, "duration_ms": _ms(t0)})

    async def on_chain_error(
        self, error: BaseException, *, run_id: uuid.UUID, **kwargs: Any
    ) -> None:
        if started := self._started.pop(run_id, None):
            node, t0 = started
            self._outbox.stage(
                EventType.NODE_FAILED,
                {"node": node, "duration_ms": _ms(t0), "error": type(error).__name__},
            )


async def _transcript_stats(conn: Conn, session_id: uuid.UUID) -> tuple[dict[str, int], str | None]:
    cur = await conn.execute(
        "SELECT type, count(*) AS n FROM session_messages WHERE session_id = %s GROUP BY type",
        (session_id,),
    )
    stats = {r["type"]: int(r["n"]) for r in await cur.fetchall()}
    stats["turns"] = stats.get("user", 0)
    cur = await conn.execute(
        "SELECT content->>'text' AS text FROM session_messages WHERE session_id = %s "
        "AND type = 'assistant' ORDER BY seq DESC LIMIT 1",
        (session_id,),
    )
    row = await cur.fetchone()
    return stats, row["text"] if row else None


def _budget_limited(state: dict[str, Any]) -> str | None:
    """The reason, if the run's last answer is a budget-limited wrap-up (R14.2)."""
    messages = state.get("messages") or []
    last = messages[-1] if messages else None
    reason = getattr(last, "additional_kwargs", {}).get("budget_limited")
    return str(reason) if reason else None


def _written_by(metadata: Any, run: Run) -> bool:
    """Is the thread's latest checkpoint this run's own (so: resume it)?"""
    if "run_id" in metadata:
        return bool(metadata["run_id"] == str(run.id))
    return run.thread_id == str(run.id)  # written before checkpoints carried run_id


def _ms(t0: float) -> int:
    return round((time.monotonic() - t0) * 1000)


# ------------------------------------------------------------------- executor


class RunExecutor:
    """Executes one run under a lease.

    Hooks supplied by the caller (a worker), so the executor knows nothing about
    queues: `on_heartbeat` runs after each successful lease renewal (the worker
    touches its work message), and `release_requested` asks for a graceful
    hand-off after the current step.
    """

    def __init__(
        self,
        pool: Pool,
        settings: Settings,
        graphs: GraphRegistry,
        owner: str | None = None,
        *,
        on_heartbeat: Callable[[], Awaitable[object]] | None = None,
        release_requested: asyncio.Event | None = None,
        bus: EventBus | None = None,
        tools: ToolRegistry | None = None,
        hooks: HookRegistry | None = None,
        policy: ToolPolicy | None = None,
        enqueue: Callable[[uuid.UUID], Awaitable[object]] | None = None,
        local_fanout: bool = False,
    ) -> None:
        self._pool = pool
        self._settings = settings
        self._graphs = graphs
        self.owner = owner or default_owner()
        self._on_heartbeat = on_heartbeat
        self._release_requested = release_requested or asyncio.Event()
        self._bus = bus  # events are published after each commit (R1.5)
        self._tools = tools or default_tools()
        self._hooks = hooks or default_hooks()
        self._policy = policy or RiskClassPolicy()
        self._enqueue = enqueue  # send a run that became queued (children, fanned-in parent)
        self._orchestrator: SubagentOrchestrator | None = None  # set for agents with sub-agents
        self._transcript: TranscriptWriter | None = None  # set for chat turns
        self._tokens: TokenRelay | None = None  # set for agent graphs
        # A release the worker must NOT re-send at once (an open circuit breaker): the
        # outbox relay re-sends it once its message is stale, which is the backoff.
        self.deferred = False
        self._spawner: Spawner = (
            LocalSpawner(graphs, settings.run_max_children) if local_fanout else RunSpawner()
        )

    async def execute(self, run_id: uuid.UUID) -> Run:
        """Run (or resume) `run_id` to a stopping point and return its final state.

        Idempotent (R1.3): if another live owner holds the run, nothing happens
        and its current state is returned. A terminal run raises RunTerminal.
        """
        async with self._pool.connection() as conn:
            repo = RunRepository(conn)
            run = await repo.get(run_id)
            if run.status.is_terminal:
                raise RunTerminal(run)
            lease = await repo.acquire_lease(run_id, self.owner, self._settings.lease_ttl_s)
            if lease is None:
                current = await repo.get(run_id)
                log.info("run %s is owned by %s; leaving it alone", run_id, current.owner)
                return current
            fence = lease.fence
            try:
                if lease.reclaimed:
                    if lease.reclaims > self._settings.max_reclaims:
                        return await self._fail(fence, FailureReason.MAX_RECLAIMS, None)
                    async with conn.transaction():
                        await check_fence(conn, fence)
                        await repo.append_event(
                            run_id,
                            epoch=fence.epoch,
                            type=EventType.RUN_RECLAIMED,
                            payload={"owner": self.owner, "reclaims": lease.reclaims},
                        )
                else:
                    await repo.transition(
                        run_id, RunStatus.RUNNING, event=EventType.RUN_STARTED, fence=fence,
                        payload={"owner": self.owner},
                    )  # fmt: skip
            except FencedError:
                return await repo.get(run_id)
            await publish_events(self._bus, repo.emitted)  # committed above
            run = await repo.get(run_id)
        return await self._drive(run, fence)

    async def _drive(self, run: Run, fence: Fence) -> Run:
        try:
            if run.kind == "session_end":
                return await self._session_end(run, fence)
            ended = await self._drive_graph(run, fence)
            await self._turn_end(run, ended)
            return ended
        finally:
            # Whatever happened (including this task being cancelled, which is how a
            # test simulates a crash), no sub-agent task outlives this execution.
            if self._orchestrator is not None:
                await self._orchestrator.stop()

    async def _drive_graph(self, run: Run, fence: Fence) -> Run:
        # A run that can never execute (graph removed, input or limits no longer
        # valid) must fail, not be retried forever by the reaper (a poison run).
        try:
            limits = (
                RunLimits.model_validate(run.limits)
                if run.limits
                else resolve_limits(self._settings, RunOptions())
            )
            spec = self._graphs.get(run.graph_name)
            spec.input_model.model_validate(run.input)
        except Exception as exc:
            return await self._fail(fence, FailureReason.ERROR, None, detail=repr(exc))
        outbox = Outbox(run.id, fence, committed_steps=run.steps, bus=self._bus)
        if run.session_id is not None:
            # A chat turn: its transcript is written in each checkpoint's transaction.
            self._transcript = outbox.transcript = TranscriptWriter(
                run.session_id, run.id, fence, bus=self._bus
            )
        checkpointer = FencedCheckpointer(
            self._pool, fence, on_commit=outbox.on_commit, after_commit=outbox.after_commit
        )
        graph = spec.compile(checkpointer)
        context = self._agent_context(spec, run, fence, limits, outbox)
        config: RunnableConfig = {
            "configurable": {"thread_id": run.thread_id},
            "callbacks": [
                _NodeRecorder(outbox, limits.max_steps, lambda: self._check_interrupts(run.id)),
                *self._token_relay(spec, run),
            ],
            # Our step budget governs; LangGraph's recursion limit is only a backstop.
            "recursion_limit": limits.max_steps + 5,
            # Stamped on every checkpoint: tells "resume this run" from "a new turn on a
            # session thread that already has checkpoints" (phase 6 research).
            "metadata": {"run_id": str(run.id)},
        }
        if run.started_at is None:  # set by the queued → running transition
            raise RuntimeError(f"run {run.id} is running without started_at")
        deadline = run.started_at.timestamp() + limits.timeout_s
        if deadline - time.time() <= 0:
            return await self._fail(fence, FailureReason.TIMEOUT, outbox)
        if self._orchestrator is not None:
            # Resume every sub-agent that was mid-task when the run last stopped (a
            # crash, a release, an approval pause) from its own checkpoint (R16.3).
            await self._orchestrator.recover()

        graph_input: Any = None
        pending: Any = None  # the interrupt this run stopped on, if any
        latest = await checkpointer.aget_tuple(config)
        if latest is not None and _written_by(latest.metadata, run):
            state = await graph.aget_state(config)
            pending = state.interrupts[0].value if state.interrupts else None
        elif spec.agent is not None:
            # A new turn: on a session thread, earlier turns' messages are already there.
            prior = (await graph.aget_state(config)).values.get("messages", []) if latest else []
            text = AgentInput.model_validate(run.input).message
            graph_input = turn_input(prior, text, run.id)
        else:
            graph_input = spec.to_graph_input(spec.input_model.model_validate(run.input))

        try:
            while True:
                if is_spawn(pending):
                    # Stopped on a fan-out: either it was never carried out (a crash, or
                    # a rejection, before waiting_children) → do it now; or the children
                    # have all ended → resume the node with their results.
                    step = await self._fan_out_or_in(run, fence, pending, outbox, limits)
                    if isinstance(step, Run):
                        return step
                    graph_input = Command(resume=step)
                elif pending is not None:
                    # Paused on an approval (R1.4) and since approved: LangGraph re-runs
                    # the interrupted step and interrupt() returns the human's decision.
                    graph_input = Command(resume=run.resume_value)
                final = await self._under_lease(
                    graph.ainvoke(graph_input, config, durability="sync", context=context),
                    fence,
                    deadline - time.time(),
                )
                interrupts = final.get("__interrupt__")
                pending = interrupts[0].value if interrupts else None
                if not is_spawn(pending):
                    break
        except ReleaseRequested:
            return await self._release(fence, outbox)
        except CircuitOpen as exc:  # R14.7: the provider is failing; don't burn retries
            log.warning("run %s: %s; releasing it", run.id, exc)
            self.deferred = True  # the relay re-sends it later (a natural backoff)
            return await self._release(fence, outbox, reason="circuit_open")
        except LoopDetected as exc:  # R14.4
            return await self._fail(fence, FailureReason.LOOP_DETECTED, outbox, detail=str(exc))
        except CancelRequested:
            return await self._end(
                fence, RunStatus.CANCELLED, EventType.RUN_CANCELLED,
                FailureReason.CANCEL_REQUESTED, outbox,
            )  # fmt: skip
        except (StepLimitReached, GraphRecursionError):
            return await self._fail(fence, FailureReason.STEP_LIMIT, outbox)
        except TurnDenied as exc:  # a turn_start / session_start hook said no (R15.5)
            return await self._fail(fence, FailureReason.TURN_DENIED, outbox, detail=exc.reason)
        except BudgetExceeded as exc:  # a hard limit (R14.1)
            return await self._fail(fence, FailureReason(exc.reason), outbox, detail=str(exc))
        except TimeoutError:
            return await self._fail(fence, FailureReason.TIMEOUT, outbox)
        except (FencedError, LeaseLost) as exc:
            log.warning("run %s: lost ownership at epoch %s (%s)", run.id, fence.epoch, exc)
            return await self._current(run.id)
        except Exception as exc:
            log.exception("run %s failed", run.id)
            return await self._fail(fence, FailureReason.ERROR, outbox, detail=repr(exc))
        if pending is not None:
            return await self._pause(fence, pending, outbox)
        if reason := _budget_limited(final):
            # R14.2: the wrap-up answer is stored, and the run ends failed(budget:*).
            return await self._complete(
                fence, spec.to_output(final) | {"budget_limited": True}, outbox,
                failed=FailureReason(reason),
            )  # fmt: skip
        return await self._complete(fence, spec.to_output(final), outbox)

    # ------------------------------------------------------------- child runs

    async def _fan_out_or_in(
        self, run: Run, fence: Fence, payload: dict[str, Any], outbox: Outbox, limits: RunLimits
    ) -> Run | dict[str, Any]:
        """A Run: the run now waits (or ended). A dict: resume the node with it."""
        try:
            specs = [ChildSpec.model_validate(c) for c in payload.get("children", [])]
        except Exception as exc:
            return {"rejected": f"invalid fan-out: {exc}"}
        keys = [c.key for c in specs]
        async with self._pool.connection() as conn:
            existing = await RunRepository(conn).children(run.id, keys)
        if not existing:
            return await self._fan_out(run, fence, specs, payload, outbox, limits)
        if run.interrupt_payload != payload:  # not the fan-out these children belong to
            return {"rejected": "child keys must be unique within a run"}
        if any(not c.status.is_terminal for c in existing) or len(existing) != len(keys):
            raise RuntimeError(f"run {run.id} resumed before its children ended")
        results = [
            ChildResult.model_validate(
                {"key": c.key, "run_id": c.run_id, "status": str(c.status),
                 "reason": c.reason, "output": c.output}
            )
            for c in existing
        ]  # fmt: skip
        if not any(r.status == "completed" for r in results):
            return await self._fail(
                fence, FailureReason.CHILDREN_FAILED, outbox,
                detail=f"all {len(results)} children failed or were cancelled",
            )  # fmt: skip
        fan_in = FanIn(children=results, partial=any(r.status != "completed" for r in results))
        return fan_in.model_dump(mode="json")

    async def _fan_out(
        self,
        run: Run,
        fence: Fence,
        specs: list[ChildSpec],
        payload: dict[str, Any],
        outbox: Outbox,
        limits: RunLimits,
    ) -> Run | dict[str, Any]:
        """Children + waiting_children in one fenced transaction, or a rejection the
        node sees (R14.6). Children may not outlive their parent's deadline."""
        assert run.started_at is not None
        remaining = int(run.started_at.timestamp() + limits.timeout_s - time.time())
        if remaining < 1:
            return {"rejected": "no time left for children before the run's timeout"}
        try:
            children: list[NewChild] = []
            for c in specs:
                options = dict(c.options or {})
                options["timeout_s"] = min(options.get("timeout_s", remaining), remaining)
                p = prepare(self._graphs, self._settings, c.graph, c.input, options)
                children.append(NewChild(c.key, p.graph_name, p.input, p.options, p.limits))
        except Exception as exc:  # unknown graph, invalid input, option above a ceiling
            return {"rejected": f"invalid child: {exc}"}
        fan_out = FanOutLimits(
            max_children=limits.max_children or self._settings.run_max_children,
            max_depth=self._settings.run_max_depth,
            max_descendants=self._settings.run_max_descendants,
        )

        async def work(repo: RunRepository) -> Run:
            await outbox.flush(repo)
            await repo.spawn_children(run, fence, children, fan_out, payload)
            return await repo.get(run.id)

        staged = list(outbox.pending)
        try:
            return await self._fenced_then_publish(fence, work)
        except FanOutRejected as exc:
            outbox.pending[:] = staged  # the transaction rolled back: they are still due
            return {"rejected": exc.reason}

    def _agent_context(
        self, spec: GraphSpec, run: Run, fence: Fence, limits: RunLimits, outbox: Outbox
    ) -> RunContext | WorkflowContext:
        """Everything the graph needs about this run: an agent's grants, hooks and
        budgets, or a workflow's spawner."""
        if spec.agent is None:
            return WorkflowContext(spawner=self._spawner)
        agent = spec.agent
        fm = agent.frontmatter
        inp = AgentInput.model_validate(run.input)
        if agent.subagents:
            started = run.started_at.timestamp() if run.started_at else time.time()
            self._orchestrator = SubagentOrchestrator(
                pool=self._pool, fence=fence, bus=self._bus, main=agent,
                build=lambda sub, cp: subagent_graph(sub, self._tools, cp),
                tools=self._tools, hooks=self._hooks, policy=self._policy,
                run_limits=limits, deadline=started + limits.timeout_s,
                scripts=inp.subagent_scripts,
                limits=SubagentLimits(
                    max_parallel=self._settings.subagent_max_parallel,
                    max_total=self._settings.subagent_max_total,
                    default_timeout_s=self._settings.subagent_timeout_s,
                ),
                worker=self.owner, session_id=run.session_id,
                model_caller=self._model_caller,
                usage_recorder=self._usage_recorder,
                chat_model=self._chat_model,
            )  # fmt: skip
        caps = {t.name: t.max_calls for t in fm.tools}
        tools = ToolRunContext(
            fence=fence,
            pool=self._pool,
            grants={name: Grant(max_calls=caps.get(name)) for name in granted_tools(agent)},
            emit=outbox.stage,  # audit events commit with the step's checkpoint
            pre_hooks=[self._hooks.get(h) for h in fm.hooks.pre_tool],
            post_hooks=[self._hooks.get(h) for h in fm.hooks.post_tool],
            max_tool_calls=limits.max_tool_calls,
            orchestrator=self._orchestrator,
        )
        pipeline = ToolPipeline(self._tools, self._policy, interrupt=interrupt)
        turn = TurnInfo(
            run_id=run.id, session_id=run.session_id, agent=agent.id, message=inp.message,
            session_start=[self._hooks.get(h) for h in fm.hooks.session_start],
            turn_start=[self._hooks.get(h) for h in fm.hooks.turn_start],
        )  # fmt: skip
        return RunContext(
            tools, pipeline, max_model_calls=limits.max_model_calls, script=inp.script,
            orchestrator=self._orchestrator, turn=turn, caller=self._model_caller(),
            limits=limits, soft_limit_ratio=self._settings.soft_limit_ratio,
            record_usage=self._usage_recorder(outbox),
            chat_model=self._chat_model(fm.model, fm.temperature, inp.script),
        )  # fmt: skip

    def _chat_model(
        self, role: str, temperature: float, script: list[ScriptTurn]
    ) -> Callable[[int], BaseChatModel]:
        """The configured provider's model for this agent's role (R3.1)."""
        provider = configured_provider(self._settings)

        def model(offset: int) -> BaseChatModel:
            return provider.chat(role, temperature=temperature, script=script, offset=offset)

        return model

    def _model_caller(self) -> ModelCaller:
        s = self._settings
        return ModelCaller(
            attempts=s.model_retry_attempts, base_s=s.model_retry_base_s,
            cap_s=s.model_retry_cap_s,
            breaker=breaker_for(configured_provider(s).name, failures=s.breaker_failures,
                                window_s=s.breaker_window_s, open_s=s.breaker_open_s),
        )  # fmt: skip

    def _usage_recorder(self, outbox: Outbox) -> Callable[[str, int, int], None]:
        prices = self._settings.model_prices

        def record(model: str, tokens_in: int, tokens_out: int) -> None:
            price = prices.get(model)
            cost = price.cost(tokens_in, tokens_out) if price else 0.0
            outbox.add_usage(tokens_in + tokens_out, cost)

        return record

    # ------------------------------------------------------- sessions (R15.6)

    async def _turn_end(self, run: Run, ended: Run) -> None:
        """turn_end hooks: observe-only, after the turn's outcome is committed."""
        if not ended.status.is_terminal or run.kind == "session_end":
            return
        try:
            spec = self._graphs.get(run.graph_name)
        except Exception:
            return
        if spec.agent is None or not spec.agent.frontmatter.hooks.turn_end:
            return
        hooks = [self._hooks.get(h) for h in spec.agent.frontmatter.hooks.turn_end]
        await run_observers(hooks, TurnEndInput(
            run_id=str(run.id), session_id=str(run.session_id) if run.session_id else None,
            agent=spec.agent.id, status=str(ended.status), reason=ended.reason,
        ))  # fmt: skip

    async def _session_end(self, run: Run, fence: Fence) -> Run:
        """A `session_end` run (R15.6): run the agent's session_end hooks once and
        store the summary. It has a lease, fencing and reclaim like any run."""
        session_id = uuid.UUID(str(run.input["session_id"]))
        summary: str | None = None
        try:
            spec = self._graphs.get(run.graph_name)
            async with self._pool.connection() as conn:
                session = await SessionRepository(conn).get(session_id)
                stats, last = await _transcript_stats(conn, session_id)
            if spec.agent is not None:
                hooks = [self._hooks.get(h) for h in spec.agent.frontmatter.hooks.session_end]
                results = await run_observers(hooks, SessionEndInput(
                    session_id=str(session.id), agent=spec.agent.id, stats=stats,
                    last_answer=last,
                ))  # fmt: skip
                summary = next((r.text for r in results if isinstance(r, Summary)), None)
        except Exception as exc:
            return await self._fail(fence, FailureReason.ERROR, None, detail=repr(exc))

        async def work(repo: RunRepository) -> Run:
            if summary is not None:
                await SessionRepository(repo.conn).set_summary(session_id, summary)
            await repo.save_result(fence.run_id, {"summary": summary})
            return await repo.transition(
                fence.run_id, RunStatus.COMPLETED, event=EventType.RUN_COMPLETED, fence=fence,
                payload={"session_id": str(session_id)},
            )  # fmt: skip

        return await self._fenced_then_publish(fence, work)

    async def _settle_subagents(self, ending: str | None) -> None:
        """Before the run leaves `running`: the fence only compares epochs, and a pause
        or release keeps the epoch, so a sub-agent left running could keep writing
        under a lease nobody holds. `ending`: the run ends (cancel them, R16.9);
        None: it pauses or is handed off (stop them; they resume later)."""
        if self._orchestrator is None:
            return
        if ending is None:
            await self._orchestrator.stop()
        else:
            await self._orchestrator.cancel_all(ending)

    async def _under_lease(
        self, work: Coroutine[Any, Any, Any], fence: Fence, timeout_s: float
    ) -> Any:
        """Await `work` while heartbeating; stop if the lease is lost or time runs out."""
        task = asyncio.ensure_future(work)
        heartbeat = asyncio.create_task(self._heartbeat(fence))
        try:
            async with asyncio.timeout(timeout_s):
                done, _ = await asyncio.wait({task, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                return task.result()
            raise LeaseLost(f"heartbeat could not renew the lease at epoch {fence.epoch}")
        finally:
            for t in (task, heartbeat):
                t.cancel()
            await asyncio.gather(task, heartbeat, return_exceptions=True)

    async def _heartbeat(self, fence: Fence) -> None:
        """Returns (ending the run's execution) only when the lease is gone."""
        while True:
            await asyncio.sleep(self._settings.heartbeat_s)
            try:
                async with self._pool.connection() as conn:
                    renewed = await RunRepository(conn).renew_lease(
                        fence, self.owner, self._settings.lease_ttl_s
                    )
            except Exception:
                log.warning("run %s: heartbeat failed; retrying", fence.run_id, exc_info=True)
                continue
            if not renewed:
                return
            if self._on_heartbeat is not None:
                try:
                    await self._on_heartbeat()
                except Exception:
                    log.warning("run %s: heartbeat hook failed", fence.run_id, exc_info=True)

    async def _complete(
        self,
        fence: Fence,
        final: dict[str, Any],
        outbox: Outbox,
        *,
        failed: FailureReason | None = None,
    ) -> Run:
        """Store the output and end the run: completed, or failed(budget:*) when the
        output is a budget-limited wrap-up answer (R14.2)."""
        await self._settle_subagents("the main run completed")
        output = json.loads(json.dumps(final, default=str))  # JSON-safe copy of the state

        async def work(repo: RunRepository) -> Run:
            await outbox.flush(repo)
            partial = await repo.has_unsuccessful_children(fence.run_id)
            await repo.save_result(fence.run_id, output, partial=partial)
            if failed is not None:
                payload = {"reason": str(failed), "budget_limited": True}
                if self._transcript is not None:
                    await self._transcript.write_event(repo.conn, "error", payload)
                return await repo.transition(
                    fence.run_id, RunStatus.FAILED, event=EventType.RUN_FAILED, fence=fence,
                    reason=str(failed), payload=payload,
                )  # fmt: skip
            return await repo.transition(
                fence.run_id, RunStatus.COMPLETED, event=EventType.RUN_COMPLETED,
                fence=fence, payload={"steps": outbox.committed_steps},
            )  # fmt: skip

        return await self._fenced_then_publish(fence, work)

    async def _fenced_then_publish(
        self, fence: Fence, work: Callable[[RunRepository], Awaitable[Run]]
    ) -> Run:
        """Run `work` in one fenced transaction; publish its events only after COMMIT.

        If the fence is stale, nothing is written and nothing is published.
        """
        try:
            async with self._pool.connection() as conn:
                repo = RunRepository(conn)
                async with conn.transaction():
                    await check_fence(conn, fence)
                    run = await work(repo)
                await publish_events(self._bus, repo.emitted)
                if self._transcript is not None:
                    await self._transcript.publish()
            await self._send(repo.ready)
            return run
        except FencedError:
            return await self._current(fence.run_id)

    async def _send(self, run_ids: list[uuid.UUID]) -> None:
        """After COMMIT: hand runs that became queued to the work queue. Best effort;
        the outbox relay re-sends any that are lost."""
        if self._enqueue is None:
            return
        for run_id in run_ids:
            try:
                await self._enqueue(run_id)
            except Exception:
                log.warning("run %s is queued but not sent; the relay will send it", run_id,
                            exc_info=True)  # fmt: skip

    def _token_relay(self, spec: GraphSpec, run: Run) -> list[TokenRelay]:
        """Agent graphs stream their model's tokens live (R12.5): on the session's
        channel for a chat turn, else on the run's."""
        if spec.agent is None:
            return []
        channel = session_channel(run.session_id) if run.session_id else run_channel(run.id)
        self._tokens = TokenRelay(
            self._bus, channel, run.id, flush_ms=self._settings.token_flush_ms,
            cancel_check=lambda: self._check_cancel(run.id),
        )  # fmt: skip
        return [self._tokens]

    async def _check_cancel(self, run_id: uuid.UUID) -> None:
        async with self._pool.connection() as conn:
            if await RunRepository(conn).is_cancel_requested(run_id):
                raise CancelRequested

    async def _check_interrupts(self, run_id: uuid.UUID) -> None:
        if self._release_requested.is_set():
            raise ReleaseRequested
        async with self._pool.connection() as conn:
            if await RunRepository(conn).is_cancel_requested(run_id):
                raise CancelRequested

    async def _pause(self, fence: Fence, payload: Any, outbox: Outbox) -> Run:
        """Durable pause (R1.4): persist what we wait on, release the lease. No worker
        holds the run while a human decides; approval re-queues it."""
        await self._settle_subagents(None)
        value = payload if isinstance(payload, dict) else {"value": payload}

        async def work(repo: RunRepository) -> Run:
            await outbox.flush(repo)
            if self._transcript is not None:
                await self._transcript.write_event(
                    repo.conn, "interrupt",
                    {"interrupt_type": value.get("type"), "payload": value},
                )  # fmt: skip
            await repo.set_interrupt(fence.run_id, value)
            return await repo.transition(
                fence.run_id, RunStatus.WAITING_APPROVAL, event=EventType.INTERRUPT_RAISED,
                fence=fence, payload=value,
            )  # fmt: skip

        return await self._fenced_then_publish(fence, work)

    async def _release(self, fence: Fence, outbox: Outbox, *, reason: str = "draining") -> Run:
        """Graceful hand-off (R10.7): back to `queued`, lease cleared, not a reclaim."""
        await self._settle_subagents(None)

        async def work(repo: RunRepository) -> Run:
            await outbox.flush(repo)
            return await repo.transition(
                fence.run_id, RunStatus.QUEUED, event=EventType.RUN_RELEASED,
                fence=fence, payload={"owner": self.owner, "reason": reason},
            )  # fmt: skip

        return await self._fenced_then_publish(fence, work)

    async def _fail(
        self,
        fence: Fence,
        reason: FailureReason,
        outbox: Outbox | None,
        detail: str | None = None,
    ) -> Run:
        return await self._end(
            fence, RunStatus.FAILED, EventType.RUN_FAILED, reason, outbox, detail
        )

    async def _end(
        self,
        fence: Fence,
        target: RunStatus,
        event: EventType,
        reason: FailureReason,
        outbox: Outbox | None,
        detail: str | None = None,
    ) -> Run:
        await self._settle_subagents(f"the main run ended: {reason}")
        payload: dict[str, Any] = {"reason": str(reason)}
        if detail:
            payload["detail"] = detail[:2000]

        async def work(repo: RunRepository) -> Run:
            if outbox is not None:
                await outbox.flush(repo)  # e.g. node.failed for the failing node
            if self._transcript is not None:  # R12.3: the turn failed / was cancelled
                if self._tokens is not None and self._tokens.partial:
                    # R12.7: a reply cut off mid-stream is kept, marked as interrupted.
                    await self._transcript.write_event(repo.conn, "assistant", {
                        "text": self._tokens.partial, "interrupted": True})  # fmt: skip
                await self._transcript.write_event(repo.conn, "error", payload)
            return await repo.transition(
                fence.run_id, target, event=event,
                fence=fence, reason=str(reason), payload=payload,
            )  # fmt: skip

        return await self._fenced_then_publish(fence, work)

    async def _current(self, run_id: uuid.UUID) -> Run:
        async with self._pool.connection() as conn:
            return await RunRepository(conn).get(run_id)

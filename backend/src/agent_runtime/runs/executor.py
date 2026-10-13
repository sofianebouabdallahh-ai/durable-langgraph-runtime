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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import CheckpointMetadata
from langgraph.errors import GraphRecursionError

from agent_runtime.checkpointing import FencedCheckpointer
from agent_runtime.config import Settings
from agent_runtime.db import Conn, Pool
from agent_runtime.fencing import Fence, FencedError, check_fence
from agent_runtime.graphs import GraphRegistry
from agent_runtime.runs.events import EventType
from agent_runtime.runs.limits import RunLimits, RunOptions, resolve_limits
from agent_runtime.runs.state import FailureReason, RunStatus
from agent_runtime.runs.store import Event, Run, RunRepository, RunTerminal
from agent_runtime.streaming.bus import EventBus, publish_events

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


# --------------------------------------------------------------------- outbox


@dataclass
class _Outbox:
    """Events staged during a superstep, committed with its checkpoint."""

    run_id: uuid.UUID
    fence: Fence
    committed_steps: int  # steps committed for this run so far (all executions)
    bus: EventBus | None = None
    pending: list[tuple[EventType, dict[str, Any]]] = field(default_factory=list)
    _just_written: list[Event] = field(default_factory=list)

    def stage(self, type: EventType, payload: dict[str, Any]) -> None:
        self.pending.append((type, payload))

    async def flush(self, repo: RunRepository) -> None:
        for type, payload in self.pending:
            await repo.append_event(self.run_id, epoch=self.fence.epoch, type=type, payload=payload)
        self.pending.clear()

    async def on_commit(self, conn: Conn, metadata: CheckpointMetadata) -> None:
        """FencedCheckpointer hook: runs inside the checkpoint's transaction."""
        repo = RunRepository(conn)
        # Step 0 only maps the input into state; supersteps ≥ 1 executed nodes.
        if metadata.get("source") == "loop" and metadata.get("step", 0) >= 1:
            self.committed_steps = await repo.add_steps(self.run_id, 1)
        await self.flush(repo)
        self._just_written = repo.emitted  # replaced, not appended: a rollback discards it

    async def after_commit(self) -> None:
        """FencedCheckpointer hook: the transaction committed; now announce it."""
        written, self._just_written = self._just_written, []
        await publish_events(self.bus, written)


class _NodeRecorder(AsyncCallbackHandler):
    """Observes node starts and ends; stages node events; enforces max_steps."""

    raise_error = True  # let StepLimitReached abort the run instead of being logged

    def __init__(
        self,
        outbox: _Outbox,
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
    ) -> None:
        self._pool = pool
        self._settings = settings
        self._graphs = graphs
        self.owner = owner or default_owner()
        self._on_heartbeat = on_heartbeat
        self._release_requested = release_requested or asyncio.Event()
        self._bus = bus  # events are published after each commit (R1.5)

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
        outbox = _Outbox(run.id, fence, committed_steps=run.steps, bus=self._bus)
        checkpointer = FencedCheckpointer(
            self._pool, fence, on_commit=outbox.on_commit, after_commit=outbox.after_commit
        )
        graph = spec.build().compile(checkpointer=checkpointer)
        config: RunnableConfig = {
            "configurable": {"thread_id": run.thread_id},
            "callbacks": [
                _NodeRecorder(outbox, limits.max_steps, lambda: self._check_interrupts(run.id))
            ],
            # Our step budget governs; LangGraph's recursion limit is only a backstop.
            "recursion_limit": limits.max_steps + 5,
        }
        resuming = await checkpointer.aget_tuple(config) is not None
        graph_input = (
            None if resuming else spec.input_model.model_validate(run.input).model_dump(mode="json")
        )
        if run.started_at is None:  # set by the queued → running transition
            raise RuntimeError(f"run {run.id} is running without started_at")
        elapsed = (datetime.now(UTC) - run.started_at).total_seconds()
        remaining = limits.timeout_s - elapsed
        if remaining <= 0:
            return await self._fail(fence, FailureReason.TIMEOUT, outbox)

        try:
            final = await self._under_lease(
                graph.ainvoke(graph_input, config, durability="sync"), fence, remaining
            )
        except ReleaseRequested:
            return await self._release(fence, outbox)
        except CancelRequested:
            return await self._end(
                fence, RunStatus.CANCELLED, EventType.RUN_CANCELLED,
                FailureReason.CANCEL_REQUESTED, outbox,
            )  # fmt: skip
        except (StepLimitReached, GraphRecursionError):
            return await self._fail(fence, FailureReason.STEP_LIMIT, outbox)
        except TimeoutError:
            return await self._fail(fence, FailureReason.TIMEOUT, outbox)
        except (FencedError, LeaseLost) as exc:
            log.warning("run %s: lost ownership at epoch %s (%s)", run.id, fence.epoch, exc)
            return await self._current(run.id)
        except Exception as exc:
            log.exception("run %s failed", run.id)
            return await self._fail(fence, FailureReason.ERROR, outbox, detail=repr(exc))
        return await self._complete(fence, final, outbox)

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

    async def _complete(self, fence: Fence, final: dict[str, Any], outbox: _Outbox) -> Run:
        output = json.loads(json.dumps(final, default=str))  # JSON-safe copy of the state

        async def work(repo: RunRepository) -> Run:
            await outbox.flush(repo)
            await repo.save_result(fence.run_id, output)
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
                return run
        except FencedError:
            return await self._current(fence.run_id)

    async def _check_interrupts(self, run_id: uuid.UUID) -> None:
        if self._release_requested.is_set():
            raise ReleaseRequested
        async with self._pool.connection() as conn:
            if await RunRepository(conn).is_cancel_requested(run_id):
                raise CancelRequested

    async def _release(self, fence: Fence, outbox: _Outbox) -> Run:
        """Graceful hand-off (R10.7): back to `queued`, lease cleared, not a reclaim."""

        async def work(repo: RunRepository) -> Run:
            await outbox.flush(repo)
            return await repo.transition(
                fence.run_id, RunStatus.QUEUED, event=EventType.RUN_RELEASED,
                fence=fence, payload={"owner": self.owner},
            )  # fmt: skip

        return await self._fenced_then_publish(fence, work)

    async def _fail(
        self,
        fence: Fence,
        reason: FailureReason,
        outbox: _Outbox | None,
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
        outbox: _Outbox | None,
        detail: str | None = None,
    ) -> Run:
        payload: dict[str, Any] = {"reason": str(reason)}
        if detail:
            payload["detail"] = detail[:2000]

        async def work(repo: RunRepository) -> Run:
            if outbox is not None:
                await outbox.flush(repo)  # e.g. node.failed for the failing node
            return await repo.transition(
                fence.run_id, target, event=event,
                fence=fence, reason=str(reason), payload=payload,
            )  # fmt: skip

        return await self._fenced_then_publish(fence, work)

    async def _current(self, run_id: uuid.UUID) -> Run:
        async with self._pool.connection() as conn:
            return await RunRepository(conn).get(run_id)

"""Worker process (R2.2, R2.4, R10.7): pulls work hints and executes runs.

    ┌─ read loop ── XREADGROUP (COUNT = free slots) ─┐
    │  reaper   ── XAUTOCLAIM idle > lease TTL ──────┼──► one task per message ──► RunExecutor
    │  relay    ── re-send runs whose message is lost│     heartbeat: renew lease + touch message
    └──────────────── bulkhead: ≤ C runs in flight ──┘     settle: ack | re-enqueue | leave

Patterns:
- Competing Consumers: every worker process is a consumer in one group; a new
  message goes to exactly one of them.
- Bulkhead: at most `concurrency` runs in flight. Reads and reclaims only ask
  for free slots, so a busy worker never hoards messages it can't start.
- Postgres decides, Redis delivers: a message is a hint. The run's lease (R2.3)
  decides who executes, so duplicates and racing recovery paths are harmless
  (the reclaim race, F2).

Settling a message after `execute` returns (R2.1):
- run ended or is waiting (terminal / waiting_*)        → ack
- run released by us (graceful shutdown)                → send a new message, then ack
- run owned by another live worker (we lost the race)   → ack if we still hold the message
- anything unexpected (e.g. our process failed mid-run) → leave pending; the reaper reclaims it

Shutdown (R10.7): the first SIGTERM/SIGINT stops reading and asks every
in-flight run to release after its current step; another worker picks each up
within seconds. Runs not released within `worker_grace_s` are left to the
reaper (the SIGKILL path).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable

from agent_runtime.admin import AdminRepository
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import GraphRegistry
from agent_runtime.queue import Delivery, QueueUnavailable, WorkQueue
from agent_runtime.runs.executor import RunExecutor, default_owner
from agent_runtime.runs.relay import OutboxRelay
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus
from agent_runtime.runs.store import Run, RunNotFound, RunTerminal
from agent_runtime.sessions.service import SessionService
from agent_runtime.streaming.bus import EventBus

log = logging.getLogger(__name__)
READ_BACKOFF_S, READ_BACKOFF_MAX_S = 1.0, 15.0

_DONE = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.WAITING_APPROVAL,
        RunStatus.WAITING_CHILDREN,
    }
)


class Worker:
    def __init__(
        self,
        pool: Pool,
        queue: WorkQueue,
        settings: Settings,
        graphs: GraphRegistry,
        *,
        consumer: str | None = None,
        concurrency: int | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self._pool = pool
        self._queue = queue
        self._settings = settings
        self._graphs = graphs
        self.consumer = consumer or default_owner()
        self.concurrency = concurrency or settings.worker_concurrency
        self._relay = OutboxRelay(pool, queue, stale_s=settings.relay_stale_s)
        self._bus = bus
        self._inflight: dict[str, asyncio.Task[None]] = {}
        self._draining = asyncio.Event()  # handed to executors as `release_requested`
        self._paused_cache: tuple[float, bool] = (0.0, False)
        self.peak_inflight = 0
        self.handled = 0  # messages settled (for tests and metrics)

    # ------------------------------------------------------------------ main

    async def run(self, stop: asyncio.Event) -> None:
        """Serve until `stop` is set, then drain (R10.7)."""
        await self._queue.ensure_group()
        background = [
            asyncio.create_task(self._every(self._settings.reaper_interval_s, self._reap)),
            asyncio.create_task(self._every(self._settings.relay_interval_s, self._relay.sweep)),
            asyncio.create_task(self._every(self._settings.session_sweep_s, self._archive_idle)),
        ]
        log.info("worker %s up (concurrency %d)", self.consumer, self.concurrency)
        backoff = READ_BACKOFF_S
        try:
            while not stop.is_set():
                if await self._paused():
                    await _sleep_unless(stop, 1.0)
                    continue
                free = self.concurrency - len(self._inflight)
                if free <= 0:
                    await self._wait_for_a_slot(stop)
                    continue
                try:
                    deliveries = await self._queue.read(
                        self.consumer, free, self._settings.worker_block_ms
                    )
                except QueueUnavailable as exc:
                    # A blip (Redis restarting, a paused host): keep serving the runs in
                    # flight and try again, rather than exit and be restarted.
                    log.warning(
                        "worker %s: queue unavailable (%s); retrying in %.0f s",
                        self.consumer,
                        exc,
                        backoff,
                    )
                    await _sleep_unless(stop, backoff)
                    backoff = min(backoff * 2, READ_BACKOFF_MAX_S)
                    continue
                backoff = READ_BACKOFF_S
                for delivery in deliveries:
                    self._start(delivery)
        finally:
            for task in background:
                task.cancel()
            await asyncio.gather(*background, return_exceptions=True)
            await self._drain()

    async def _drain(self) -> None:
        if self._inflight:
            log.info("worker %s draining %d run(s)", self.consumer, len(self._inflight))
        self._draining.set()
        pending = set(self._inflight.values())
        if pending:
            _, still_running = await asyncio.wait(pending, timeout=self._settings.worker_grace_s)
            for task in still_running:  # couldn't release in time: the reaper will reclaim
                task.cancel()
            await asyncio.gather(*still_running, return_exceptions=True)
        with contextlib.suppress(Exception):
            await self._queue.remove_consumer_if_idle(self.consumer)
        log.info("worker %s stopped", self.consumer)

    # --------------------------------------------------------------- per run

    def _start(self, delivery: Delivery) -> None:
        if delivery.message_id in self._inflight:
            return  # already working on this message (e.g. reclaimed our own)
        task = asyncio.create_task(self._handle(delivery))
        self._inflight[delivery.message_id] = task
        task.add_done_callback(lambda _: self._inflight.pop(delivery.message_id, None))
        self.peak_inflight = max(self.peak_inflight, len(self._inflight))

    async def _archive_idle(self) -> int:
        """R15.6: archive sessions idle past the TTL; each gets one session_end run.
        Safe on every worker at once: archiving is a conditional UPDATE."""
        runs = RunService(self._pool, self._settings, self._graphs, self._relay, self._bus)
        sessions = SessionService(
            self._pool, self._settings, self._graphs, runs, self._relay, self._bus
        )
        return await sessions.archive_idle(self._settings.session_idle_ttl_s)

    async def _handle(self, delivery: Delivery) -> None:
        executor = RunExecutor(
            self._pool,
            self._settings,
            self._graphs,
            owner=self.consumer,
            on_heartbeat=lambda: self._queue.touch(self.consumer, delivery.message_id),
            release_requested=self._draining,
            bus=self._bus,
            enqueue=self._relay.enqueue,  # children; a parent whose children all ended
        )
        try:
            run = await executor.execute(delivery.run_id)
        except (RunTerminal, RunNotFound):
            await self._queue.ack(delivery.message_id)  # stale or poison hint
            self.handled += 1
            return
        except Exception:
            log.exception(
                "run %s: execution failed; leaving the message for the reaper", delivery.run_id
            )
            return
        await self._settle(delivery, run, deferred=executor.deferred)
        self.handled += 1

    async def _settle(self, delivery: Delivery, run: Run, *, deferred: bool = False) -> None:
        if run.status in _DONE:
            await self._queue.ack(delivery.message_id)
        elif run.status is RunStatus.QUEUED and run.owner is None:
            # Released by us: hand it straight to another worker, then drop ours. A
            # deferred release (open circuit breaker) is left to the relay: it re-sends
            # the run once its message is stale, which is the backoff (R14.7).
            if not deferred:
                await self._relay.enqueue(run.id)
            await self._queue.ack(delivery.message_id)
        elif run.owner is not None and run.owner != self.consumer:
            # Another live worker owns the run. Our message is a duplicate *unless* the new
            # owner reclaimed this very message (we were a zombie): then it's theirs to ack.
            if await self._queue.holder(delivery.message_id) == self.consumer:
                await self._queue.ack(delivery.message_id)
        else:
            log.warning(
                "run %s left %s/%s; leaving its message pending", run.id, run.status, run.owner
            )

    # ------------------------------------------------------------ background

    async def _reap(self) -> None:
        """Reclaim dead workers' messages (R2.4), within our free slots."""
        free = self.concurrency - len(self._inflight)
        if free <= 0 or self._draining.is_set() or await self._paused():
            return
        claimed = await self._queue.autoclaim(
            self.consumer, int(self._settings.lease_ttl_s * 1000), free
        )
        for delivery in claimed.deliveries:
            log.info("reaper: claimed run %s (message %s)", delivery.run_id, delivery.message_id)
            self._start(delivery)

    async def _paused(self) -> bool:
        """Kill switch (R14.18), cached for a second to keep the read loop cheap."""
        checked_at, paused = self._paused_cache
        if time.monotonic() - checked_at < 1.0:
            return paused
        async with self._pool.connection() as conn:
            paused = (await AdminRepository(conn).get()).paused
        self._paused_cache = (time.monotonic(), paused)
        return paused

    async def _wait_for_a_slot(self, stop: asyncio.Event) -> None:
        stopper = asyncio.create_task(stop.wait())
        try:
            await asyncio.wait(
                {stopper, *self._inflight.values()},
                timeout=1.0,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            stopper.cancel()

    @staticmethod
    async def _every(interval_s: float, job: Callable[[], Awaitable[object]]) -> None:
        while True:
            await asyncio.sleep(interval_s)
            try:
                await job()
            except Exception:
                log.warning("background job %s failed; will retry", job.__name__, exc_info=True)


async def _sleep_unless(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)

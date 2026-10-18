"""Workers in-process against real Postgres + Redis (phase 2 success criteria).

Real-process scenarios (SIGKILL, SIGSTOP, SIGTERM) are in tests/e2e/.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest

from agent_runtime.admin import AdminRepository
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.queue import RedisWorkQueue
from agent_runtime.runs.events import EventType as E
from agent_runtime.runs.relay import OutboxRelay
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.runs.store import Run, RunRepository, RunTerminal
from agent_runtime.worker import Worker
from tests.integration.support import events, node_completed, summary, wait_until

pytestmark = pytest.mark.integration

GRAPHS = default_registry()


@pytest.fixture
def fast(test_settings: Settings) -> Settings:
    return test_settings.model_copy(
        update={
            "lease_ttl_s": 1.5,
            "heartbeat_s": 0.4,
            "reaper_interval_s": 0.3,
            "relay_interval_s": 3600,  # off: other tests' runs share this database
            "worker_block_ms": 200,
            "worker_grace_s": 10,
        }
    )


@pytest.fixture
def service(
    pool: Pool, fast: Settings, queue: RedisWorkQueue, checkpoint_tables: None
) -> RunService:
    return RunService(pool, fast, GRAPHS, OutboxRelay(pool, queue, stale_s=30))


@asynccontextmanager
async def workers(
    pool: Pool, queue: RedisWorkQueue, settings: Settings, *names: str, concurrency: int = 3
) -> AsyncIterator[dict[str, tuple[Worker, asyncio.Event]]]:
    started: dict[str, tuple[Worker, asyncio.Event]] = {}
    tasks = []
    for name in names:
        w = Worker(pool, queue, settings, GRAPHS, consumer=name, concurrency=concurrency)
        stop = asyncio.Event()
        started[name] = (w, stop)
        tasks.append(asyncio.create_task(w.run(stop)))
    try:
        yield started
    finally:
        for _, stop in started.values():
            stop.set()
        await asyncio.gather(*tasks)


async def get(pool: Pool, run_id: uuid.UUID) -> Run:
    async with pool.connection() as conn:
        return await RunRepository(conn).get(run_id)


def status_is(pool: Pool, run_id: uuid.UUID, *statuses: S) -> Callable[[], Awaitable[bool]]:
    async def check() -> bool:
        return (await get(pool, run_id)).status in statuses

    return check


async def test_sc2_two_workers_share_runs_exactly_once(
    pool: Pool, fast: Settings, queue: RedisWorkQueue, service: RunService
) -> None:
    runs = [
        await service.create_run("toy", {"question": f"q{i}", "delay_s": 0.05}) for i in range(20)
    ]
    async with workers(pool, queue, fast, "w-a:1", "w-b:2", concurrency=3) as ws:

        async def all_done() -> bool:
            statuses = [(await get(pool, r.id)).status for r in runs]
            return all(st is S.COMPLETED for st in statuses)

        await wait_until(all_done, timeout_s=60)
    for r in runs:
        done = await get(pool, r.id)
        assert (done.epoch, done.reclaims) == (1, 0)
        names = summary(await events(pool, r.id))
        for node in ("plan", "research", "answer"):
            assert names.count((E.NODE_COMPLETED, node)) == 1
    (a, _), (b, _) = ws["w-a:1"], ws["w-b:2"]
    assert a.handled > 0 and b.handled > 0  # both took work (competing consumers)
    assert a.peak_inflight <= 3 and b.peak_inflight <= 3  # bulkhead held
    assert await queue.pending_count() == 0


async def test_sc7_a_healthy_long_run_is_not_stolen(
    pool: Pool, fast: Settings, queue: RedisWorkQueue, service: RunService
) -> None:
    run = await service.create_run("toy", {"question": "slow", "delay_s": 1.6})  # ~4.8 s > 3 x TTL
    async with workers(pool, queue, fast, "w-a:1", "w-b:2"):
        await wait_until(status_is(pool, run.id, S.COMPLETED), timeout_s=30)
    done = await get(pool, run.id)
    assert (done.epoch, done.reclaims) == (1, 0)
    assert (E.RUN_RECLAIMED, None) not in summary(await events(pool, run.id))


async def test_reaper_reclaims_a_dead_workers_run(
    pool: Pool, fast: Settings, queue: RedisWorkQueue, service: RunService
) -> None:
    run = await service.create_run("toy", {"question": "q"})
    # A worker took the message and the lease, started the run, then died silently.
    (delivery,) = await queue.read("ghost:9", count=1, block_ms=100)
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        lease = await repo.acquire_lease(run.id, "ghost:9", ttl_s=fast.lease_ttl_s)
        assert lease is not None
        await repo.transition(run.id, S.RUNNING, event=E.RUN_STARTED, fence=lease.fence)
    await asyncio.sleep(fast.lease_ttl_s + 0.2)  # lease and message idle time both expire

    async with workers(pool, queue, fast, "w-b:2"):
        await wait_until(status_is(pool, run.id, S.COMPLETED), timeout_s=20)
    done = await get(pool, run.id)
    assert (done.epoch, done.reclaims) == (2, 1)
    assert summary(await events(pool, run.id)).count((E.RUN_RECLAIMED, None)) == 1
    assert await queue.pending_count() == 0
    assert delivery.run_id == run.id


async def test_sc5_graceful_shutdown_hands_off_quickly(
    pool: Pool, fast: Settings, queue: RedisWorkQueue, service: RunService
) -> None:
    run = await service.create_run("toy", {"question": "q", "delay_s": 0.8})
    async with workers(pool, queue, fast, "w-a:1") as first:
        await wait_until(lambda: node_completed(pool, run.id, "plan"), timeout_s=20)
        async with workers(pool, queue, fast, "w-b:2"):
            first["w-a:1"][1].set()  # SIGTERM-equivalent for worker A
            await wait_until(status_is(pool, run.id, S.COMPLETED), timeout_s=20)

    done = await get(pool, run.id)
    assert (done.releases, done.reclaims) == (1, 0)
    evts = await events(pool, run.id)
    names = summary(evts)
    assert (E.RUN_RECLAIMED, None) not in names
    released = next(e for e in evts if e.type == E.RUN_RELEASED)
    restarted = next(e for e in evts if e.type == E.RUN_STARTED and e.seq > released.seq)
    assert restarted.payload["owner"] == "w-b:2"
    assert (restarted.ts - released.ts).total_seconds() < 2  # vs ≥ TTL for a crash
    assert names.count((E.NODE_COMPLETED, "plan")) == 1  # no committed step re-ran


async def test_sc8_cancel_a_running_run_before_its_next_node(
    pool: Pool, fast: Settings, queue: RedisWorkQueue, service: RunService
) -> None:
    run = await service.create_run("toy", {"question": "q", "delay_s": 0.5})
    async with workers(pool, queue, fast, "w-a:1"):
        await wait_until(lambda: node_completed(pool, run.id, "plan"), timeout_s=20)
        async with pool.connection() as conn:
            flagged = await RunRepository(conn).request_cancel(run.id)
        assert flagged.status is S.RUNNING and flagged.cancel_requested
        await wait_until(status_is(pool, run.id, S.CANCELLED), timeout_s=20)
    done = await get(pool, run.id)
    assert done.reason == "cancel_requested"
    assert (E.NODE_STARTED, "answer") not in summary(await events(pool, run.id))
    await wait_until(lambda: _no_pending(queue), timeout_s=5)


async def _no_pending(queue: RedisWorkQueue) -> bool:
    return await queue.pending_count() == 0


async def test_sc8_cancel_a_queued_run_immediately_and_terminal_is_rejected(
    pool: Pool, fast: Settings, queue: RedisWorkQueue, service: RunService
) -> None:
    run = await service.create_run("toy", {"question": "q"})
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        cancelled = await repo.request_cancel(run.id)
        assert (cancelled.status, cancelled.reason) == (S.CANCELLED, "cancel_requested")
        with pytest.raises(RunTerminal):
            await repo.request_cancel(run.id)
    async with workers(pool, queue, fast, "w-a:1"):  # its message is now stale
        await wait_until(lambda: _no_pending(queue), timeout_s=10)
        await asyncio.sleep(0.5)
    assert await queue.pending_count() == 0
    assert (await get(pool, run.id)).status is S.CANCELLED


async def test_duplicate_messages_execute_once(
    pool: Pool, fast: Settings, queue: RedisWorkQueue, service: RunService
) -> None:
    run = await service.create_run("toy", {"question": "q", "delay_s": 0.2})
    for _ in range(3):
        await queue.enqueue(run.id)  # e.g. relay + resume + a retry all sent one
    async with workers(pool, queue, fast, "w-a:1", "w-b:2"):
        await wait_until(status_is(pool, run.id, S.COMPLETED), timeout_s=20)
        await wait_until(lambda: _no_pending(queue), timeout_s=10)
    names = summary(await events(pool, run.id))
    assert names.count((E.RUN_COMPLETED, None)) == 1
    assert (await get(pool, run.id)).epoch == 1


async def test_sc11_paused_workers_claim_nothing_until_resumed(
    pool: Pool, fast: Settings, queue: RedisWorkQueue, service: RunService
) -> None:
    run = await service.create_run("toy", {"question": "q"})  # admission refuses once paused
    async with pool.connection() as conn:
        await AdminRepository(conn).set_paused(True, reason="test")
    try:
        async with workers(pool, queue, fast, "w-a:1"):
            await asyncio.sleep(1.5)
            assert (await get(pool, run.id)).status is S.QUEUED
            async with pool.connection() as conn:
                await AdminRepository(conn).set_paused(False)
            await wait_until(status_is(pool, run.id, S.COMPLETED), timeout_s=20)
    finally:
        async with pool.connection() as conn:
            await AdminRepository(conn).set_paused(False)


async def test_a_run_that_can_never_execute_fails_instead_of_looping(
    pool: Pool, fast: Settings, queue: RedisWorkQueue, checkpoint_tables: None
) -> None:
    async with pool.connection() as conn:
        run = await RunRepository(conn).create(graph_name="deleted-graph", input={})
    await queue.enqueue(run.id)
    async with workers(pool, queue, fast, "w-a:1"):
        await wait_until(status_is(pool, run.id, S.FAILED), timeout_s=10)
        await wait_until(lambda: _no_pending(queue), timeout_s=5)
    failed = await get(pool, run.id)
    assert failed.reason == "error"
    assert "unknown graph" in (await events(pool, run.id))[-1].payload["detail"]


async def test_worker_drains_and_leaves_the_group_on_stop(
    pool: Pool, fast: Settings, queue: RedisWorkQueue
) -> None:
    t0 = time.monotonic()
    async with workers(pool, queue, fast, "w-a:1"):
        await asyncio.sleep(0.3)
    assert time.monotonic() - t0 < 3  # an idle worker stops promptly
    consumers = await queue._r.xinfo_consumers(queue.stream, queue.group)
    assert "w-a:1" not in {c["name"] for c in consumers}


async def test_a_queue_blip_doesnt_stop_the_worker(
    pool: Pool,
    fast: Settings,
    queue: RedisWorkQueue,
    service: RunService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis timing out (a restart, a paused host) is retried with a backoff: the worker
    stays up, and runs it can't read yet are served once the queue is back."""
    from agent_runtime import worker as worker_module
    from agent_runtime.queue import QueueUnavailable

    monkeypatch.setattr(worker_module, "READ_BACKOFF_S", 0.05)
    real_read, failures = queue.read, [2]

    async def flaky(consumer: str, count: int, block_ms: int) -> list[Any]:
        if failures[0] > 0:
            failures[0] -= 1
            raise QueueUnavailable("Timeout reading from redis:6379")
        return await real_read(consumer, count, block_ms)

    monkeypatch.setattr(queue, "read", flaky)
    run = await service.create_run("toy", {"question": "q", "delay_s": 0.1})
    await queue.enqueue(run.id)
    async with workers(pool, queue, fast, "w-blip:1") as started:
        await wait_until(status_is(pool, run.id, S.COMPLETED), timeout_s=20)
        task_alive = not started["w-blip:1"][1].is_set()
    assert failures == [0] and task_alive

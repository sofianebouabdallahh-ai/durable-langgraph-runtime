"""Outbox relay: Redis can always be rebuilt from Postgres (SC6)."""

import asyncio
import uuid

import pytest

from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.queue import RedisWorkQueue
from agent_runtime.runs.relay import OutboxRelay
from agent_runtime.runs.service import RunService
from agent_runtime.runs.store import RunRepository

pytestmark = pytest.mark.integration


class BrokenQueue(RedisWorkQueue):
    """Redis is down when the API tries to enqueue."""

    def __init__(self) -> None:  # no connection at all
        pass

    async def enqueue(self, run_id: uuid.UUID) -> str:
        raise ConnectionError("redis down")


async def message_of(pool: Pool, run_id: uuid.UUID) -> str | None:
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT message_id FROM runs WHERE id = %s", (run_id,))
        row = await cur.fetchone()
    return None if row is None else row["message_id"]


async def age(pool: Pool, run_id: uuid.UUID, seconds: int) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE runs SET enqueued_at = enqueued_at - make_interval(secs => %s) WHERE id = %s",
            (seconds, run_id),
        )


async def test_create_run_sends_and_records_a_message(
    pool: Pool, test_settings: Settings, queue: RedisWorkQueue
) -> None:
    relay = OutboxRelay(pool, queue, stale_s=30)
    run = await RunService(pool, test_settings, default_registry(), relay).create_run(
        "toy", {"question": "q"}
    )
    mid = await message_of(pool, run.id)
    assert mid is not None and await queue.exists(mid)
    (delivery,) = await queue.read("w", count=10, block_ms=10)
    assert delivery.run_id == run.id


async def test_run_survives_redis_being_down_at_creation(
    pool: Pool, test_settings: Settings, queue: RedisWorkQueue
) -> None:
    down = OutboxRelay(pool, BrokenQueue(), stale_s=30)
    run = await RunService(pool, test_settings, default_registry(), down).create_run(
        "toy", {"question": "q"}
    )  # no exception: the run is durable in Postgres
    assert await message_of(pool, run.id) is None

    sent = await OutboxRelay(pool, queue, stale_s=30).sweep()  # Redis is back
    assert sent >= 1
    assert await queue.exists(await message_of(pool, run.id) or "")


async def test_wiped_stream_is_rebuilt(
    pool: Pool, test_settings: Settings, queue: RedisWorkQueue
) -> None:
    relay = OutboxRelay(pool, queue, stale_s=30)
    service = RunService(pool, test_settings, default_registry(), relay)
    runs = [await service.create_run("toy", {"question": f"q{i}"}) for i in range(3)]
    await queue._r.delete(queue.stream)  # Redis lost everything
    await queue.ensure_group()
    for run in runs:
        await age(pool, run.id, 60)  # older than stale_s

    await relay.sweep()
    delivered = {d.run_id for d in await queue.read("w", count=10, block_ms=10)}
    assert {r.id for r in runs} <= delivered


async def test_relay_does_not_duplicate_a_live_message(
    pool: Pool, test_settings: Settings, queue: RedisWorkQueue
) -> None:
    relay = OutboxRelay(pool, queue, stale_s=30)
    run = await RunService(pool, test_settings, default_registry(), relay).create_run(
        "toy", {"question": "q"}
    )
    first = await message_of(pool, run.id)
    await age(pool, run.id, 60)
    await relay.sweep()
    assert await message_of(pool, run.id) == first  # message still exists: not re-sent


async def test_running_run_under_a_dead_owner_gets_a_new_message(
    pool: Pool, test_settings: Settings, queue: RedisWorkQueue
) -> None:
    relay = OutboxRelay(pool, queue, stale_s=30)
    run = await RunService(pool, test_settings, default_registry(), relay).create_run(
        "toy", {"question": "q"}
    )
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE runs SET status = 'running', started_at = now(), owner = 'dead:1', epoch = 1, "
            "lease_expires_at = now() - interval '5 minutes', "
            "enqueued_at = now() - interval '5 minutes' WHERE id = %s",
            (run.id,),
        )
    await queue._r.delete(queue.stream)  # its pending message was lost with Redis
    await queue.ensure_group()
    await relay.sweep()
    (delivery,) = await queue.read("w", count=10, block_ms=10)
    assert delivery.run_id == run.id


async def test_concurrent_sweeps_send_each_run_once(
    pool: Pool, test_settings: Settings, queue: RedisWorkQueue
) -> None:
    async with pool.connection() as conn:
        run = await RunRepository(conn).create(graph_name="toy", input={"question": "q"})
    relays = [OutboxRelay(pool, queue, stale_s=30) for _ in range(4)]
    sent = await asyncio.gather(*(r.sweep() for r in relays))
    delivered = [d.run_id for d in await queue.read("w", count=100, block_ms=10)]
    assert delivered.count(run.id) == 1
    assert sum(sent) >= 1

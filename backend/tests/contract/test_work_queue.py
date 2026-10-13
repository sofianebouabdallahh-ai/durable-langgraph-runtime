"""WorkQueue contract: the in-memory fake and Redis Streams must behave alike.

The `memory` variant runs in the fast unit job; the `redis` variant needs
`make up` (integration). If the fake drifts from Redis, the same assertion fails
for one of them.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from agent_runtime.queue import InMemoryWorkQueue, RedisWorkQueue, WorkQueue, create_redis

IDLE_MS = 150


def _redis_url() -> str:
    # db 15 keeps test streams away from development data (db 0)
    base = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return base.rsplit("/", 1)[0] + "/15"


@pytest.fixture(
    params=[
        pytest.param("memory"),
        pytest.param("redis", marks=pytest.mark.integration),
    ]
)
async def queue(request: pytest.FixtureRequest) -> AsyncIterator[WorkQueue]:
    if request.param == "memory":
        yield InMemoryWorkQueue()
        return
    redis = create_redis(_redis_url())
    try:
        await redis.ping()
    except RedisConnectionError as exc:
        if os.environ.get("REQUIRE_SERVICES") == "1":
            pytest.fail(f"required service unavailable: Redis ({exc})")
        pytest.skip(f"Redis not reachable ({exc}); run `make up`")
    stream = f"test:{uuid.uuid4()}"
    q = RedisWorkQueue(redis, stream=stream, group="workers")
    await q.ensure_group()
    await q.ensure_group()  # idempotent
    try:
        yield q
    finally:
        await redis.delete(stream)
        await redis.aclose()


async def test_each_message_goes_to_one_consumer(queue: WorkQueue) -> None:
    ids = [uuid.uuid4() for _ in range(4)]
    for run_id in ids:
        await queue.enqueue(run_id)
    a = await queue.read("a", count=3, block_ms=10)
    b = await queue.read("b", count=3, block_ms=10)
    assert [d.run_id for d in a] + [d.run_id for d in b] == ids
    assert len(a) == 3 and len(b) == 1
    assert await queue.pending_count() == 4


async def test_ack_removes_from_pending_and_stream(queue: WorkQueue) -> None:
    mid = await queue.enqueue(uuid.uuid4())
    (d,) = await queue.read("a", count=1, block_ms=10)
    assert d.message_id == mid and await queue.exists(mid)
    assert await queue.ack(mid) == 1
    assert await queue.pending_count() == 0
    assert not await queue.exists(mid)
    assert await queue.ack(mid) == 0  # idempotent


async def test_autoclaim_takes_only_idle_messages(queue: WorkQueue) -> None:
    await queue.enqueue(uuid.uuid4())
    await queue.enqueue(uuid.uuid4())
    healthy, dead = (await queue.read("healthy", 1, 10))[0], (await queue.read("dead", 1, 10))[0]
    await asyncio.sleep(IDLE_MS / 1000 * 2)
    assert await queue.touch("healthy", healthy.message_id)  # heartbeat touch resets idle
    claimed = await queue.autoclaim("reaper", min_idle_ms=IDLE_MS, count=10)
    assert [d.message_id for d in claimed.deliveries] == [dead.message_id]
    assert claimed.deleted_ids == []


async def test_autoclaim_drops_messages_deleted_from_the_stream(queue: WorkQueue) -> None:
    await queue.enqueue(uuid.uuid4())
    (d,) = await queue.read("dead", 1, 10)
    # simulate the stream entry vanishing (trimmed / flushed) while still pending
    if isinstance(queue, RedisWorkQueue):
        await queue._r.xdel(queue.stream, d.message_id)
    else:
        assert isinstance(queue, InMemoryWorkQueue)
        del queue.entries[d.message_id]
    await asyncio.sleep(IDLE_MS / 1000 * 2)
    claimed = await queue.autoclaim("reaper", min_idle_ms=IDLE_MS, count=10)
    assert claimed.deliveries == [] and claimed.deleted_ids == [d.message_id]
    assert await queue.pending_count() == 0


async def test_touch_fails_for_an_acked_message(queue: WorkQueue) -> None:
    await queue.enqueue(uuid.uuid4())
    (d,) = await queue.read("a", 1, 10)
    await queue.ack(d.message_id)
    assert not await queue.touch("a", d.message_id)


async def test_consumer_removed_only_when_it_holds_nothing(queue: WorkQueue) -> None:
    await queue.enqueue(uuid.uuid4())
    (d,) = await queue.read("a", 1, 10)
    assert not await queue.remove_consumer_if_idle("a")
    await queue.ack(d.message_id)
    assert await queue.remove_consumer_if_idle("a")


async def test_read_returns_nothing_when_empty(queue: WorkQueue) -> None:
    assert await queue.read("a", count=5, block_ms=10) == []


async def test_poison_message_is_dropped_not_redelivered(queue: WorkQueue) -> None:
    if not isinstance(queue, RedisWorkQueue):
        pytest.skip("only Redis can hold a malformed message")
    await queue._r.xadd(queue.stream, {"oops": "no run_id"})
    good = await queue.enqueue(uuid.uuid4())
    delivered = await queue.read("a", count=5, block_ms=10)
    assert [d.message_id for d in delivered] == [good]
    assert await queue.pending_count() == 1  # the poison message was acked and deleted

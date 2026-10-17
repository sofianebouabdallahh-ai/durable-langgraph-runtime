"""Broker: one subscription per replica, reference-counted channels, bounded queues (SC10)."""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from agent_runtime.queue import create_redis
from agent_runtime.streaming.broker import Broker
from agent_runtime.streaming.bus import (
    EventBus,
    InMemoryEventBus,
    RedisEventBus,
    StreamEvent,
    run_channel,
)


def ev(run_id: uuid.UUID, seq: int) -> StreamEvent:
    return StreamEvent(run_id, seq, datetime.now(UTC), 1, "node.completed", {})


@pytest.fixture(
    params=[pytest.param("memory"), pytest.param("redis", marks=pytest.mark.integration)]
)
async def bus_and_redis(
    request: pytest.FixtureRequest,
) -> AsyncIterator[tuple[EventBus, Redis | None]]:
    if request.param == "memory":
        yield InMemoryEventBus(), None
        return
    redis = create_redis(
        os.environ.get("REDIS_URL", "redis://localhost:6379/0").rsplit("/", 1)[0] + "/15"
    )
    try:
        await redis.ping()
    except RedisConnectionError as exc:
        if os.environ.get("REQUIRE_SERVICES") == "1":
            pytest.fail(f"required service unavailable: Redis ({exc})")
        pytest.skip(f"Redis not reachable ({exc})")
    yield RedisEventBus(redis), redis
    await redis.aclose()


@pytest.fixture
async def broker(bus_and_redis: tuple[EventBus, Redis | None]) -> AsyncIterator[Broker]:
    b = Broker(bus_and_redis[0], queue_size=5)
    await b.start()
    yield b
    await b.stop()


async def test_subscribed_before_listen_yields(
    broker: Broker, bus_and_redis: tuple[EventBus, Redis | None]
) -> None:
    bus, _ = bus_and_redis
    run = uuid.uuid4()
    async with broker.listen(run_channel(run)) as listener:
        assert listener.live
        await bus.publish(run_channel(run), ev(run, 1))  # right after: must not be lost
        got = await asyncio.wait_for(listener.queue.get(), timeout=2)
    assert got.seq == 1


async def test_many_streams_share_one_subscription(
    broker: Broker, bus_and_redis: tuple[EventBus, Redis | None]
) -> None:
    bus, redis = bus_and_redis
    runs = [uuid.uuid4() for _ in range(100)]
    before = await _pubsub_clients(redis)
    async with AsyncExitStack() as stack:
        listeners = [await stack.enter_async_context(broker.listen(run_channel(r))) for r in runs]
        assert broker.channels == 100
        assert broker.subscriptions_opened == 1
        if redis is not None:  # one Redis Pub/Sub connection, not 100
            assert await _pubsub_clients(redis) - before == 1
        await bus.publish(run_channel(runs[42]), ev(runs[42], 1))
        assert (await asyncio.wait_for(listeners[42].queue.get(), timeout=2)).run_id == runs[42]
        assert all(listener.queue.empty() for i, listener in enumerate(listeners) if i != 42)
    assert broker.channels == 0


async def test_channel_unsubscribed_when_last_stream_leaves(
    broker: Broker, bus_and_redis: tuple[EventBus, Redis | None]
) -> None:
    _, redis = bus_and_redis
    channel = run_channel(uuid.uuid4())
    async with broker.listen(channel):
        async with broker.listen(channel):
            pass
        assert await _subscribers(redis, broker, channel) == 1  # one stream still here
    await asyncio.sleep(0.2)
    assert await _subscribers(redis, broker, channel) == 0


async def test_a_slow_stream_does_not_delay_others(
    broker: Broker, bus_and_redis: tuple[EventBus, Redis | None]
) -> None:
    bus, _ = bus_and_redis
    run = uuid.uuid4()
    async with broker.listen(run_channel(run)) as slow, broker.listen(run_channel(run)) as fast:
        received: list[int] = []

        async def consume() -> None:
            while len(received) < 20:
                received.append((await fast.queue.get()).seq or 0)

        consumer = asyncio.create_task(consume())
        for seq in range(1, 21):
            await bus.publish(run_channel(run), ev(run, seq))
            await asyncio.sleep(0.005)
        await asyncio.wait_for(consumer, timeout=3)
    assert received == list(range(1, 21))  # the fast stream got everything, promptly
    assert slow.take_overflow() and not slow.take_overflow()  # slow one told to catch up, once


async def test_without_a_bus_listeners_are_not_live() -> None:
    broker = Broker(None)
    await broker.start()
    async with broker.listen("run:x") as listener:
        assert not listener.live
    await broker.stop()


async def _pubsub_clients(redis: Redis | None) -> int:
    if redis is None:
        return 0
    return len(await redis.client_list(_type="pubsub"))


async def _subscribers(redis: Redis | None, broker: Broker, channel: str) -> int:
    if redis is None:
        return 1 if channel in broker._listeners else 0
    return int(dict(await redis.pubsub_numsub(channel))[channel])


async def test_reconnects_resubscribes_and_flags_catch_up_after_redis_drops_it(
    broker: Broker, bus_and_redis: tuple[EventBus, Redis | None]
) -> None:
    bus, redis = bus_and_redis
    if redis is None:
        pytest.skip("needs a real Redis connection to kill")
    run = uuid.uuid4()
    async with broker.listen(run_channel(run)) as listener:
        await redis.client_kill_filter(_type="pubsub")  # Redis drops the broker's connection
        async with asyncio.timeout(10):  # broker notices, reconnects, resubscribes
            while broker.subscriptions_opened < 2 or not listener.overflowed:  # noqa: ASYNC110
                await asyncio.sleep(0.05)
        assert listener.take_overflow()  # the stream is told it may have missed events
        await asyncio.sleep(0.2)
        await bus.publish(run_channel(run), ev(run, 9))  # and live delivery works again
        assert (await asyncio.wait_for(listener.queue.get(), timeout=3)).seq == 9

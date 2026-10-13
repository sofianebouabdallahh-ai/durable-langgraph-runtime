"""EventBus contract: Redis Pub/Sub and the in-memory fake behave alike."""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from agent_runtime.queue import create_redis
from agent_runtime.streaming.bus import (
    EventBus,
    InMemoryEventBus,
    RedisEventBus,
    StreamEvent,
    run_channel,
)


def event(seq: int | None, run_id: uuid.UUID, type_: str = "node.completed") -> StreamEvent:
    return StreamEvent(
        run_id=run_id, seq=seq, ts=datetime.now(UTC), epoch=1, type=type_,
        payload={"node": "plan"}, after_seq=None if seq else 3,
    )  # fmt: skip


@pytest.fixture(
    params=[pytest.param("memory"), pytest.param("redis", marks=pytest.mark.integration)]
)
async def bus(request: pytest.FixtureRequest) -> AsyncIterator[EventBus]:
    if request.param == "memory":
        yield InMemoryEventBus()
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
    try:
        yield RedisEventBus(redis)
    finally:
        await redis.aclose()


async def test_roundtrip_wire_format() -> None:
    e = event(7, uuid.uuid4())
    assert StreamEvent.from_json(e.to_json()) == e
    t = event(None, uuid.uuid4(), "token")
    assert StreamEvent.from_json(t.to_json()) == t and not t.persisted and t.after_seq == 3


async def test_subscriber_receives_only_its_channels_in_order(bus: EventBus) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    sub = bus.subscription()
    await sub.subscribe(run_channel(a))
    for seq in (1, 2, 3):
        await bus.publish(run_channel(a), event(seq, a))
        await bus.publish(run_channel(b), event(seq, b))  # not subscribed
    got = [await sub.get(wait_s=1) for _ in range(3)]
    assert [(c, e.seq) for c, e in filter(None, got)] == [(run_channel(a), s) for s in (1, 2, 3)]
    assert await sub.get(wait_s=0.2) is None
    await sub.close()


async def test_publish_without_subscribers_is_lost(bus: EventBus) -> None:
    """At-most-once: nothing is stored for later subscribers."""
    run = uuid.uuid4()
    await bus.publish(run_channel(run), event(1, run))
    sub = bus.subscription()
    await sub.subscribe(run_channel(run))
    assert await sub.get(wait_s=0.2) is None
    await sub.close()


async def test_unsubscribe_stops_delivery(bus: EventBus) -> None:
    run = uuid.uuid4()
    sub = bus.subscription()
    await sub.subscribe(run_channel(run))
    await sub.unsubscribe(run_channel(run))
    await asyncio.sleep(0.05)
    await bus.publish(run_channel(run), event(1, run))
    assert await sub.get(wait_s=0.2) is None
    await sub.close()


async def test_get_with_no_subscriptions_just_times_out(bus: EventBus) -> None:
    sub = bus.subscription()
    assert await sub.get(wait_s=0.05) is None
    await sub.close()

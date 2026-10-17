"""Publish after commit (R1.5, SC7): nothing uncommitted is ever announced."""

import asyncio
import uuid

import pytest

from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.streaming.bus import InMemoryEventBus, StreamEvent
from tests.integration.support import events, node_completed, wait_until

pytestmark = pytest.mark.integration
GRAPHS = default_registry()


class CommitCheckingBus(InMemoryEventBus):
    """At the moment of each publish, look the event up from *another*
    connection: it is only visible there if its transaction has committed."""

    def __init__(self, pool: Pool) -> None:
        super().__init__()
        self._pool = pool
        self.uncommitted: list[StreamEvent] = []

    async def publish(self, channel: str, event: StreamEvent) -> None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT 1 FROM run_events WHERE run_id = %s AND seq = %s AND epoch = %s",
                (event.run_id, event.seq, event.epoch),
            )
            if await cur.fetchone() is None:
                self.uncommitted.append(event)
        await super().publish(channel, event)


class DownBus(InMemoryEventBus):
    async def publish(self, channel: str, event: StreamEvent) -> None:
        raise ConnectionError("redis down")


def published_for(bus: InMemoryEventBus, run_id: uuid.UUID) -> list[tuple[int | None, str]]:
    return [(e.seq, e.type) for _, e in bus.published if e.run_id == run_id]


async def test_every_event_is_published_after_its_commit_in_order(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    bus = CommitCheckingBus(pool)
    run = await RunService(pool, test_settings, GRAPHS, bus=bus).create_run(
        "toy", {"question": "q"}
    )
    await RunExecutor(pool, test_settings, GRAPHS, owner="p:1", bus=bus).execute(run.id)

    assert bus.uncommitted == []
    in_db = [(e.seq, e.type) for e in await events(pool, run.id)]
    assert published_for(bus, run.id) == in_db  # all of them, same order
    assert next(ch for ch, e in bus.published if e.run_id == run.id) == f"run:{run.id}"


async def test_a_zombies_rejected_writes_are_never_published(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    fast = test_settings.model_copy(update={"lease_ttl_s": 1.5, "heartbeat_s": 0.4})
    bus = CommitCheckingBus(pool)
    run = await RunService(pool, fast, GRAPHS, bus=bus).create_run(
        "toy", {"question": "q", "delay_s": 0.6}
    )
    zombie = asyncio.create_task(
        RunExecutor(pool, fast, GRAPHS, owner="z:1", bus=bus).execute(run.id)
    )
    await wait_until(lambda: node_completed(pool, run.id, "plan"), timeout_s=20)
    async with pool.connection() as conn:  # another worker takes over
        await conn.execute(
            "UPDATE runs SET epoch = epoch + 1, owner = 'w:2' WHERE id = %s", (run.id,)
        )
    await asyncio.wait_for(zombie, timeout=10)

    assert bus.uncommitted == []  # its fenced (rolled back) step was never announced
    in_db = {(e.seq, e.epoch) for e in await events(pool, run.id)}
    assert {(e.seq, e.epoch) for _, e in bus.published if e.run_id == run.id} <= in_db


async def test_a_failing_bus_never_fails_the_run(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    bus = DownBus()
    run = await RunService(pool, test_settings, GRAPHS, bus=bus).create_run(
        "toy", {"question": "q"}
    )
    done = await RunExecutor(pool, test_settings, GRAPHS, owner="p:1", bus=bus).execute(run.id)
    assert done.status is S.COMPLETED  # Postgres has every event; readers back-fill


async def test_api_side_events_are_published(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    bus = CommitCheckingBus(pool)
    service = RunService(pool, test_settings, GRAPHS, bus=bus)
    run = await service.create_run("toy", {"question": "q"})
    await service.cancel(run.id)
    assert published_for(bus, run.id) == [(1, "run.created"), (2, "run.cancelled")]
    assert bus.uncommitted == []


async def test_control_the_spy_catches_a_publish_inside_the_transaction(
    pool: Pool, test_settings: Settings
) -> None:
    """Control experiment: proves CommitCheckingBus isn't passing vacuously."""
    from agent_runtime.runs.events import EventType
    from agent_runtime.runs.store import RunRepository
    from agent_runtime.streaming.bus import to_stream_event

    bus = CommitCheckingBus(pool)
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        run = await repo.create(graph_name="toy", input={"question": "q"})
        async with conn.transaction():
            event = await repo.append_event(
                run.id, epoch=0, type=EventType.NODE_STARTED, payload={}
            )
            await bus.publish(f"run:{run.id}", to_stream_event(event))  # the bug: before COMMIT
    assert [e.seq for e in bus.uncommitted] == [event.seq]

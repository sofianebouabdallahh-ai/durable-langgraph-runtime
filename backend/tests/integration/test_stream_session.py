"""RunStream (the shell around StreamMerger), driven step by step: deterministic
coverage of overflow catch-up, which a live end-to-end run rarely triggers."""

import asyncio
from collections.abc import AsyncGenerator
from typing import cast

import pytest

from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.runs.events import EventType as E
from agent_runtime.runs.state import RunStatus
from agent_runtime.runs.store import RunRepository
from agent_runtime.streaming.broker import Broker
from agent_runtime.streaming.bus import InMemoryEventBus, run_channel, to_stream_event
from agent_runtime.streaming.session import RunStream

pytestmark = pytest.mark.integration


async def test_overflowed_stream_drains_and_catches_up_exactly_once(
    pool: Pool, test_settings: Settings
) -> None:
    bus = InMemoryEventBus()
    broker = Broker(bus, queue_size=1)
    await broker.start()
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        run = await repo.create(graph_name="toy", input={"question": "q"})  # seq 1
    stream = cast(
        "AsyncGenerator[bytes]",
        RunStream(
            pool, broker, test_settings, run.id, after_seq=0, draining=asyncio.Event()
        ).events(),
    )
    try:
        assert b"retry:" in await anext(stream)  # stream opened
        assert b"id: 1" in await anext(stream)  # replay of run.created

        # The client stops reading while a burst lands: 5 events committed and
        # published, but the stream's queue holds only 1 → it overflows.
        reader = asyncio.ensure_future(anext(stream))
        await asyncio.sleep(0)  # let the stream subscribe/wait on its queue
        async with pool.connection() as conn, conn.transaction():
            repo = RunRepository(conn)
            for _ in range(5):
                await repo.append_event(run.id, epoch=1, type=E.NODE_COMPLETED, payload={})
        for event in repo.emitted:
            await bus.publish(run_channel(run.id), to_stream_event(event))
        chunks = [await reader]
        async with pool.connection() as conn:  # the run ends: commit, then publish
            repo = RunRepository(conn)
            await repo.transition(
                run.id, RunStatus.CANCELLED, event=E.RUN_CANCELLED, reason="cancel_requested"
            )
        for event in repo.emitted:
            await bus.publish(run_channel(run.id), to_stream_event(event))
        async for chunk in stream:
            chunks.append(chunk)
    finally:
        await stream.aclose()
        await broker.stop()

    ids = [
        int(line[4:]) for c in chunks for line in c.decode().splitlines() if line.startswith("id: ")
    ]
    assert ids == [2, 3, 4, 5, 6, 7]  # every event once, in order, despite the overflow

"""SSE streaming against a real HTTP server, real workers, Postgres and Redis.

(httpx's in-process ASGI transport buffers whole responses, so a live stream
needs a real server: uvicorn runs in-process on a free port.)
"""

import asyncio
import json
import random
import socket
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from agent_runtime.api.app import create_app
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.queue import RedisWorkQueue
from agent_runtime.streaming.bus import EventBus, RedisEventBus, StreamEvent
from agent_runtime.worker import Worker

pytestmark = pytest.mark.integration
GRAPHS = default_registry()


@dataclass
class Sse:
    events: list[dict[str, Any]] = field(default_factory=list)  # persisted + transient + control
    comments: list[str] = field(default_factory=list)
    headers: httpx.Headers | None = None

    @property
    def seqs(self) -> list[int]:
        return [int(e["id"]) for e in self.events if e.get("id")]


async def read_sse(
    client: httpx.AsyncClient, path: str, *, headers: dict[str, str] | None = None,
    stop_after: int | None = None, timeout_s: float = 30,
) -> Sse:  # fmt: skip
    """Read an SSE stream until the server closes it (or `stop_after` events)."""
    out = Sse()
    block: dict[str, Any] = {}
    async with asyncio.timeout(timeout_s), client.stream("GET", path, headers=headers) as resp:
        out.headers = resp.headers
        async for line in resp.aiter_lines():
            if line == "":
                if block:
                    out.events.append(block)
                    block = {}
                    if stop_after is not None and len(out.seqs) >= stop_after:
                        return out
                continue
            if line.startswith(":"):
                out.comments.append(line[1:].strip())
                continue
            key, _, value = line.partition(":")
            block[key] = value.lstrip()
    return out


@pytest.fixture
def fast(test_settings: Settings) -> Settings:
    return test_settings.model_copy(
        update={
            "lease_ttl_s": 1.5, "heartbeat_s": 0.4, "reaper_interval_s": 0.3,
            "relay_interval_s": 3600, "worker_block_ms": 200,
            "stream_ping_s": 0.3, "stream_poll_s": 1.0,
        }
    )  # fmt: skip


@pytest.fixture
def bus(queue: RedisWorkQueue) -> EventBus:
    return RedisEventBus(queue._r)


class Server:
    def __init__(self, app: FastAPI) -> None:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.app = app
        self.server = uvicorn.Server(uvicorn.Config(app, port=self.port, log_level="warning"))
        self.client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{self.port}", timeout=30)

    async def __aenter__(self) -> "Server":
        self.task = asyncio.create_task(self.server.serve())
        async with asyncio.timeout(10):  # fail, never hang, if the server can't start
            while not self.server.started:  # noqa: ASYNC110 (uvicorn exposes a flag, not an event)
                await asyncio.sleep(0.02)
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.client.aclose()
        self.server.should_exit = True
        await self.task


@pytest.fixture
async def api(
    pool: Pool, fast: Settings, queue: RedisWorkQueue, bus: EventBus, checkpoint_tables: None
) -> AsyncIterator[Server]:
    async with Server(create_app(fast, pool=pool, queue=queue, bus=bus)) as server:
        yield server


async def start_workers(
    pool: Pool, queue: RedisWorkQueue, settings: Settings, bus: EventBus, n: int = 2
) -> tuple[list[asyncio.Event], list[asyncio.Task[None]]]:
    stops, tasks = [], []
    for i in range(n):
        stop = asyncio.Event()
        worker = Worker(pool, queue, settings, GRAPHS, consumer=f"sw-{i}:{i}", bus=bus)
        stops.append(stop)
        tasks.append(asyncio.create_task(worker.run(stop)))
    return stops, tasks


async def stop_workers(stops: list[asyncio.Event], tasks: list[asyncio.Task[None]]) -> None:
    for s in stops:
        s.set()
    await asyncio.gather(*tasks)


async def create(api: Server, **input: Any) -> str:
    resp = await api.client.post(
        "/runs", json={"graph": "toy", "input": {"question": "q", **input}}
    )
    resp.raise_for_status()
    return str(resp.json()["run_id"])


async def db_seqs(api: Server, run_id: str) -> list[int]:
    page = (await api.client.get(f"/runs/{run_id}/events", params={"limit": 1000})).json()
    return [e["seq"] for e in page["events"]]


async def test_sc1_ten_concurrent_streams_each_get_every_event_once_in_order(
    api: Server, pool: Pool, fast: Settings, queue: RedisWorkQueue, bus: EventBus
) -> None:
    run_ids = [await create(api, delay_s=0.05) for _ in range(10)]
    readers = [asyncio.create_task(read_sse(api.client, f"/runs/{r}/stream")) for r in run_ids]
    stops, tasks = await start_workers(pool, queue, fast, bus)
    try:
        streams = await asyncio.gather(*readers)
    finally:
        await stop_workers(stops, tasks)
    for run_id, s in zip(run_ids, streams, strict=True):
        assert s.seqs == list(range(1, len(s.seqs) + 1))  # in order, no gap, no duplicate
        assert s.seqs == await db_seqs(api, run_id)  # every persisted event
        assert s.events[-1]["event"] == "run.completed"  # closed after the terminal event


async def test_sc3_late_join_replays_everything(
    api: Server, pool: Pool, fast: Settings, queue: RedisWorkQueue, bus: EventBus
) -> None:
    run_id = await create(api)
    stops, tasks = await start_workers(pool, queue, fast, bus, n=1)
    await _until_status(api, run_id, "completed")
    await stop_workers(stops, tasks)
    s = await read_sse(api.client, f"/runs/{run_id}/stream")
    assert s.seqs == await db_seqs(api, run_id)


async def test_sc3_reconnect_with_last_event_id_misses_nothing(
    api: Server, pool: Pool, fast: Settings, queue: RedisWorkQueue, bus: EventBus
) -> None:
    run_id = await create(api, delay_s=0.4)
    stops, tasks = await start_workers(pool, queue, fast, bus, n=1)
    try:
        first = await read_sse(api.client, f"/runs/{run_id}/stream", stop_after=3)
        last_id = str(first.seqs[-1])
        second = await read_sse(
            api.client, f"/runs/{run_id}/stream", headers={"Last-Event-ID": last_id}
        )
    finally:
        await stop_workers(stops, tasks)
    assert first.seqs + second.seqs == await db_seqs(api, run_id)  # union exact, no overlap


class DroppingBus:
    """Fault injection: loses a fraction of publishes and always the final one."""

    def __init__(self, inner: EventBus, fraction: float, seed: int = 7) -> None:
        self._inner = inner
        self._rng = random.Random(seed)
        self._fraction = fraction
        self.dropped = 0

    async def publish(self, channel: str, event: StreamEvent) -> None:
        if event.terminal or self._rng.random() < self._fraction:
            self.dropped += 1
            return
        await self._inner.publish(channel, event)

    def subscription(self) -> Any:
        return self._inner.subscription()


async def test_sc4_lost_publishes_including_the_last_are_recovered(
    api: Server, pool: Pool, fast: Settings, queue: RedisWorkQueue, bus: EventBus
) -> None:
    lossy = DroppingBus(bus, fraction=0.3)
    run_ids = [await create(api, delay_s=0.1) for _ in range(3)]
    readers = [asyncio.create_task(read_sse(api.client, f"/runs/{r}/stream")) for r in run_ids]
    stops, tasks = await start_workers(pool, queue, fast, lossy)
    try:
        streams = await asyncio.gather(*readers)
    finally:
        await stop_workers(stops, tasks)
    assert lossy.dropped >= 3  # at least every terminal event was lost
    for run_id, s in zip(run_ids, streams, strict=True):
        assert s.seqs == await db_seqs(api, run_id)
        assert s.events[-1]["event"] == "run.completed"  # stream still closed


async def test_sc8_keepalive_ping_and_headers(
    api: Server, pool: Pool, fast: Settings, queue: RedisWorkQueue, bus: EventBus
) -> None:
    run_id = await create(api, delay_s=0.8)  # quiet stretches longer than the ping interval
    stops, tasks = await start_workers(pool, queue, fast, bus, n=1)
    try:
        s = await read_sse(api.client, f"/runs/{run_id}/stream")
    finally:
        await stop_workers(stops, tasks)
    assert "ping" in s.comments
    assert s.headers is not None
    assert s.headers["content-type"].startswith("text/event-stream")
    assert s.headers["cache-control"] == "no-cache"
    assert s.headers["x-accel-buffering"] == "no"


async def test_draining_replica_sends_reconnect_and_refuses_new_streams(
    api: Server, pool: Pool, fast: Settings, queue: RedisWorkQueue, bus: EventBus
) -> None:
    run_id = await create(api, delay_s=1.0)
    stops, tasks = await start_workers(pool, queue, fast, bus, n=1)
    try:
        reader = asyncio.create_task(read_sse(api.client, f"/runs/{run_id}/stream"))
        await asyncio.sleep(0.5)
        api.app.state.draining.set()  # what the SIGTERM handler does (R10.7)
        s = await asyncio.wait_for(reader, timeout=5)
        assert s.events[-1]["event"] == "reconnect"
        assert json.loads(s.events[-1]["data"])["after_seq"] == (s.seqs[-1] if s.seqs else 0)
        assert (await api.client.get("/readyz")).status_code == 503
        refused = await api.client.get(f"/runs/{run_id}/stream")
        assert refused.status_code == 503 and refused.headers["retry-after"] == "1"
    finally:
        api.app.state.draining.clear()
        await stop_workers(stops, tasks)


async def test_unknown_run_and_query_after_seq(api: Server) -> None:
    assert (await api.client.get(f"/runs/{uuid.uuid4()}/stream")).status_code == 404
    run_id = await create(api)
    await api.client.post(f"/runs/{run_id}/cancel")  # terminal: created(1), cancelled(2)
    s = await read_sse(api.client, f"/runs/{run_id}/stream?after_seq=1")
    assert s.seqs == [2] and s.events[-1]["event"] == "run.cancelled"


async def _until_status(api: Server, run_id: str, status: str) -> None:
    async with asyncio.timeout(20):
        while (await api.client.get(f"/runs/{run_id}")).json()["status"] != status:  # noqa: ASYNC110
            await asyncio.sleep(0.05)

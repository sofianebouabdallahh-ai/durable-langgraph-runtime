"""Backpressure (R2.9, SC10): POST /runs answers 429 + Retry-After when too many
runs are queued; workers' own fan-outs are never refused."""

from collections.abc import AsyncIterator

import httpx
import pytest

from agent_runtime.api.app import create_app
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.queue import RedisWorkQueue
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.service import Overloaded, RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.runs.store import RunRepository

pytestmark = pytest.mark.integration
GRAPHS = default_registry()


async def depth(pool: Pool) -> int:
    async with pool.connection() as conn:
        return await RunRepository(conn).queue_depth()


async def at_the_limit(pool: Pool, settings: Settings, room: int) -> Settings:
    """Settings whose queue limit is `room` runs above the current depth, uncached."""
    return settings.model_copy(
        update={"queue_depth_limit": await depth(pool) + room, "queue_depth_cache_s": 0}
    )


@pytest.fixture
async def tight(pool: Pool, test_settings: Settings) -> Settings:
    return await at_the_limit(pool, test_settings, 2)


@pytest.fixture
async def client(
    pool: Pool, tight: Settings, queue: RedisWorkQueue, checkpoint_tables: None
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(tight, pool=pool, queue=queue)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        yield c


async def test_a_deep_queue_answers_429_with_retry_after(
    client: httpx.AsyncClient, tight: Settings
) -> None:
    body = {"graph": "toy", "input": {"question": "q"}}
    assert (await client.post("/runs", json=body)).status_code == 202
    assert (await client.post("/runs", json=body)).status_code == 202
    resp = await client.post("/runs", json=body)
    assert resp.status_code == 429
    assert resp.headers["retry-after"] == str(tight.overload_retry_after_s)
    assert resp.headers["content-type"] == "application/problem+json"
    problem = resp.json()
    assert problem["type"].endswith("/overloaded")
    assert (problem["queue_depth"], problem["limit"]) == (tight.queue_depth_limit,) * 2
    state = (await client.get("/admin/state")).json()
    assert state["queue_depth"] == tight.queue_depth_limit


async def test_invalid_requests_are_still_422_when_overloaded(
    client: httpx.AsyncClient, pool: Pool, tight: Settings
) -> None:
    body = {"graph": "toy", "input": {"question": "q"}}
    for _ in range(2):
        await client.post("/runs", json=body)
    resp = await client.post("/runs", json={"graph": "toy", "input": {}})
    assert resp.status_code == 422  # validation first: a bad request isn't worth a retry


async def test_the_depth_is_cached_per_replica(pool: Pool, test_settings: Settings) -> None:
    settings = (await at_the_limit(pool, test_settings, 1)).model_copy(
        update={"queue_depth_cache_s": 60}
    )
    service = RunService(pool, settings, GRAPHS)
    await service.create_run("toy", {"question": "q"})  # depth read (and cached) before it
    await service.create_run("toy", {"question": "q"})  # cached: not refused yet
    fresh = RunService(pool, settings, GRAPHS)
    with pytest.raises(Overloaded):
        await fresh.create_run("toy", {"question": "q"})


async def test_fan_outs_are_not_refused_by_admission_control(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    """Refusing children would strand a parent that is already running."""
    service = RunService(pool, await at_the_limit(pool, test_settings, 1), GRAPHS)
    run = await service.create_run("fanout", {"topic": "t", "n": 3})  # the queue is now full
    parent = await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)
    assert (parent.status, parent.child_total) == (S.WAITING_CHILDREN, 3)

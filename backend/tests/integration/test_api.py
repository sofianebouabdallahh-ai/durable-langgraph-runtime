"""HTTP API against the real app and database (in-process ASGI, no server)."""

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest

from agent_runtime.api.app import create_app
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.queue import RedisWorkQueue
from agent_runtime.runs.executor import RunExecutor

pytestmark = pytest.mark.integration

PROBLEM = "application/problem+json"


@pytest.fixture
async def client(
    pool: Pool, test_settings: Settings, queue: RedisWorkQueue, checkpoint_tables: None
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(test_settings, pool=pool, queue=queue)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


async def create(client: httpx.AsyncClient, **body: object) -> httpx.Response:
    return await client.post("/runs", json={"graph": "toy", "input": {"question": "q"}} | body)


async def test_create_run_returns_202_with_location(client: httpx.AsyncClient) -> None:
    resp = await create(client)
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    assert resp.headers["location"] == f"/runs/{run_id}"

    run = (await client.get(f"/runs/{run_id}")).json()
    assert (run["status"], run["graph"], run["epoch"]) == ("queued", "toy", 0)
    assert run["limits"] == {"timeout_s": 1200, "max_steps": 200, "max_children": 6}


async def test_full_lifecycle_through_the_api(
    client: httpx.AsyncClient, pool: Pool, test_settings: Settings
) -> None:
    run_id = (await create(client, options={"max_steps": 10})).json()["run_id"]

    not_yet = await client.get(f"/runs/{run_id}/result")
    assert not_yet.status_code == 404
    assert not_yet.headers["content-type"] == PROBLEM
    assert not_yet.json()["type"].endswith("/result-not-ready")

    await RunExecutor(pool, test_settings, default_registry()).execute(uuid.UUID(run_id))

    assert (await client.get(f"/runs/{run_id}")).json()["status"] == "completed"
    result = (await client.get(f"/runs/{run_id}/result")).json()
    assert result["output"]["answer"] == "Toy answer to 'q'"

    page1 = (await client.get(f"/runs/{run_id}/events", params={"limit": 4})).json()
    assert [e["seq"] for e in page1["events"]] == [1, 2, 3, 4]
    page2 = (
        await client.get(f"/runs/{run_id}/events", params={"after_seq": page1["next_after_seq"]})
    ).json()
    assert page2["events"][0]["seq"] == 5
    assert page2["events"][-1]["type"] == "run.completed"


@pytest.mark.parametrize(
    ("body", "status", "problem_type"),
    [
        ({"graph": "nope"}, 404, "unknown-graph"),
        ({"input": {"question": ""}}, 422, "invalid-input"),
        ({"options": {"max_steps": 9999}}, 422, "limit-above-ceiling"),
        ({"options": {"max_stepz": 1}}, 422, "invalid-input"),
        ({"surprise": True}, 422, "invalid-request"),
    ],
)
async def test_errors_are_problem_details(
    client: httpx.AsyncClient, body: dict[str, object], status: int, problem_type: str
) -> None:
    resp = await create(client, **body)
    assert resp.status_code == status
    assert resp.headers["content-type"] == PROBLEM
    problem = resp.json()
    assert problem["type"].endswith("/" + problem_type)
    assert problem["status"] == status


async def test_ceiling_problem_names_the_field_and_maximum(client: httpx.AsyncClient) -> None:
    problem = (await create(client, options={"timeout_s": 99999})).json()
    assert (problem["field"], problem["maximum"]) == ("options.timeout_s", 1200)


async def test_unknown_run_is_404(client: httpx.AsyncClient) -> None:
    resp = await client.get(f"/runs/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["type"].endswith("/run-not-found")
    assert (await client.get(f"/runs/{uuid.uuid4()}/events")).status_code == 404


async def test_graph_introspection(client: httpx.AsyncClient) -> None:
    graphs = (await client.get("/graphs")).json()
    toy = next(g for g in graphs if g["name"] == "toy")
    assert {"plan", "research", "answer"} <= set(toy["nodes"])
    assert {"source": "plan", "target": "research", "conditional": False} in toy["edges"]
    assert "question" in toy["input_schema"]["properties"]
    assert (await client.get("/graphs/nope")).status_code == 404


async def test_health_endpoints(client: httpx.AsyncClient) -> None:
    assert (await client.get("/healthz")).json() == {"status": "ok"}
    assert (await client.get("/readyz")).status_code == 200


async def test_openapi_contract_is_published(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()
    assert {"/runs", "/runs/{run_id}", "/runs/{run_id}/events", "/runs/{run_id}/result"} <= set(
        spec["paths"]
    )


async def test_create_run_sends_a_work_message(
    client: httpx.AsyncClient, queue: RedisWorkQueue
) -> None:
    run_id = (await create(client)).json()["run_id"]
    (delivery,) = await queue.read("w", count=10, block_ms=10)
    assert str(delivery.run_id) == run_id


async def test_cancel_endpoint(client: httpx.AsyncClient) -> None:
    run_id = (await create(client)).json()["run_id"]
    cancelled = await client.post(f"/runs/{run_id}/cancel")
    assert cancelled.status_code == 202
    assert (cancelled.json()["status"], cancelled.json()["reason"]) == (
        "cancelled",
        "cancel_requested",
    )
    again = await client.post(f"/runs/{run_id}/cancel")
    assert again.status_code == 409
    assert again.json()["type"].endswith("/run-terminal")
    assert (await client.post(f"/runs/{uuid.uuid4()}/cancel")).status_code == 404


async def test_resume_endpoint_is_idempotent(
    client: httpx.AsyncClient, queue: RedisWorkQueue
) -> None:
    run_id = (await create(client)).json()["run_id"]
    for _ in range(2):
        resp = await client.post(f"/runs/{run_id}/resume")
        assert resp.status_code == 202 and resp.json()["status"] == "queued"
    delivered = [d.run_id for d in await queue.read("w", count=10, block_ms=10)]
    assert all(str(d) == run_id for d in delivered)  # duplicates are harmless hints

    await client.post(f"/runs/{run_id}/cancel")
    assert (await client.post(f"/runs/{run_id}/resume")).status_code == 409


async def test_kill_switch(client: httpx.AsyncClient) -> None:
    try:
        paused = await client.post("/admin/pause", json={"reason": "incident 42"})
        assert paused.json()["paused"] is True
        refused = await create(client)
        assert refused.status_code == 503
        assert refused.headers["retry-after"] == "30"
        assert "incident 42" in refused.json()["detail"]
        assert (await client.get("/admin/state")).json()["paused"] is True
    finally:
        resumed = await client.post("/admin/resume")
    assert resumed.json() == resumed.json() | {"paused": False, "reason": None}
    assert (await create(client)).status_code == 202


async def test_cancel_all(client: httpx.AsyncClient) -> None:
    ids = [(await create(client)).json()["run_id"] for _ in range(3)]
    result = (await client.post("/admin/cancel-all")).json()
    assert result["cancel_requested"] >= 3
    for run_id in ids:
        assert (await client.get(f"/runs/{run_id}")).json()["status"] == "cancelled"


async def test_admin_routes_can_be_disabled(
    pool: Pool, test_settings: Settings, queue: RedisWorkQueue
) -> None:
    app = create_app(
        test_settings.model_copy(update={"admin_api_enabled": False}), pool=pool, queue=queue
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        assert (await c.post("/admin/pause", json={})).status_code == 404

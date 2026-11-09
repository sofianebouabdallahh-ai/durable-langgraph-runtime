"""Your own models (phase L3b): connections, the capability test, routing per agent and
helper (AC44), keys that appear nowhere (AC45), bindings pinned on the run, ciphertext
bound to its place. Against the fake OpenAI-compatible server (devtools/fake_model)."""

import asyncio
import json
import logging
import socket
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import uvicorn

from agent_runtime.api.app import create_app
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.devtools.fake_model import create_app as fake_model
from agent_runtime.graphs import default_registry
from agent_runtime.queue import RedisWorkQueue
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.streaming.bus import EventBus, RedisEventBus
from tests.integration.test_stream import Server

pytestmark = pytest.mark.integration
GRAPHS = default_registry()
# Fresh fake keys per run: nothing key-like in the code, and AC45 searches for new ones.
KEY_A = f"fake-key-a-{uuid.uuid4().hex}"
KEY_B = f"fake-key-b-{uuid.uuid4().hex}"


class Fake:
    def __init__(self, url: str, client: httpx.AsyncClient) -> None:
        self.url, self.client = url, client

    async def calls(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = (await self.client.get(f"{self.url}/calls")).json()
        return result

    async def clear(self) -> None:
        await self.client.delete(f"{self.url}/calls")


@pytest.fixture
async def fake() -> AsyncIterator[Fake]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(fake_model(), port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110
        await asyncio.sleep(0.02)
    async with httpx.AsyncClient() as client:
        yield Fake(f"http://127.0.0.1:{port}", client)
    server.should_exit = True
    await task


@pytest.fixture
def bus(queue: RedisWorkQueue) -> EventBus:
    return RedisEventBus(queue._r)


@pytest.fixture
async def api(
    pool: Pool,
    test_settings: Settings,
    queue: RedisWorkQueue,
    bus: EventBus,
    checkpoint_tables: None,
) -> AsyncIterator[Server]:
    async with Server(create_app(test_settings, pool=pool, queue=queue, bus=bus)) as server:
        yield server


class Seen:
    """Every response body this test receives (AC45 searches them for the keys)."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.bodies: list[str] = []

    async def __call__(self, method: str, url: str, **kw: Any) -> httpx.Response:
        response = await self.client.request(method, url, **kw)
        self.bodies.append(response.text)
        return response


async def connect(c: Seen, fake: Fake, name: str, key: str, model: str) -> dict[str, Any]:
    added = await c(
        "POST",
        "/models/connections",
        json={
            "display_name": name,
            "kind": "compatible",
            "base_url": f"{fake.url}/v1",
            "api_key": key,
            "models": [model],
        },
    )
    assert added.status_code == 201, added.text
    tested = (
        await c("POST", f"/models/connections/{added.json()['id']}/test", json={"model": model})
    ).json()
    assert tested["ok"], tested
    result: dict[str, Any] = tested["connection"]
    return result


async def run(pool: Pool, settings: Settings, run_id: str) -> Any:
    return await RunExecutor(pool, settings, GRAPHS).execute(uuid.UUID(run_id))


async def test_the_test_tells_the_truth(api: Server, fake: Fake) -> None:
    c = Seen(api.client)
    added = (
        await c(
            "POST",
            "/models/connections",
            json={
                "display_name": "Fake",
                "kind": "compatible",
                "base_url": f"{fake.url}/v1",
                "api_key": KEY_A,
            },
        )
    ).json()
    assert added["has_key"] is True and len(added["key_fingerprint"]) == 8
    assert added["test_status"] == "untested"
    cid = added["id"]

    async def verdict(model: str) -> str:
        result = (await c("POST", f"/models/connections/{cid}/test", json={"model": model})).json()
        return "ready" if result["ok"] else result["detail"]

    assert await verdict("fake-a") == "ready"
    assert "isn't available" in await verdict("gpt-nope")
    assert "doesn't use tools" in await verdict("fake-notools")

    unreachable = (
        await c(
            "POST",
            "/models/connections",
            json={
                "display_name": "Nowhere",
                "kind": "compatible",
                "base_url": "http://127.0.0.1:9/v1",
            },
        )
    ).json()
    detail = (
        await c("POST", f"/models/connections/{unreachable['id']}/test", json={"model": "fake-a"})
    ).json()["detail"]
    assert "Couldn't reach" in detail

    needs_key = await c(
        "POST",
        "/models/connections",
        json={"display_name": "OpenAI", "kind": "openai", "base_url": "https://api.openai.com/v1"},
    )
    assert needs_key.status_code == 422  # an OpenAI connection without its key


async def test_a_wrong_key_is_refused_and_a_new_key_replaces_the_old(
    api: Server, test_settings: Settings, pool: Pool
) -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    locked = uvicorn.Server(uvicorn.Config(fake_model(KEY_B), port=port, log_level="warning"))
    task = asyncio.create_task(locked.serve())
    while not locked.started:  # noqa: ASYNC110
        await asyncio.sleep(0.02)
    try:
        c = Seen(api.client)
        added = (
            await c(
                "POST",
                "/models/connections",
                json={
                    "display_name": "Locked",
                    "kind": "compatible",
                    "base_url": f"http://127.0.0.1:{port}/v1",
                    "api_key": KEY_A,
                },
            )
        ).json()
        result = (
            await c("POST", f"/models/connections/{added['id']}/test", json={"model": "fake-a"})
        ).json()
        assert result["ok"] is False and "key was refused" in result["detail"]
        edited = (
            await c("PATCH", f"/models/connections/{added['id']}", json={"api_key": KEY_B})
        ).json()
        assert edited["key_fingerprint"] != added["key_fingerprint"]  # the old key is gone
        assert edited["test_status"] == "untested"  # a new key needs a new test
        result = (
            await c("POST", f"/models/connections/{added['id']}/test", json={"model": "fake-a"})
        ).json()
        assert result["ok"] is True
    finally:
        locked.should_exit = True
        await task


async def test_ac44_helpers_on_different_models_and_ac45_the_keys_appear_nowhere(
    api: Server,
    fake: Fake,
    pool: Pool,
    test_settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    c = Seen(api.client)
    a = await connect(c, fake, "Model A", KEY_A, "fake-a")
    b = await connect(c, fake, "Model B", KEY_B, "fake-b")
    agent = (await c("POST", "/studio/agents", json={"display_name": "Router"})).json()
    doc = {
        "name": agent["name"],
        "display_name": "Router",
        "description": "Routes work.",
        "instructions": "Delegate to your helper.",
        "model": f"{a['name']}:fake-a",
        "helpers": [
            {
                "name": "scout",
                "description": "Scouts.",
                "instructions": "Scout.",
                "model": f"{b['name']}:fake-b",
            }
        ],
    }
    saved = (await c("PUT", f"/studio/agents/{agent['id']}/draft", json=doc)).json()
    assert saved["draft"]["issues"] == []
    chat = (await c("POST", f"/studio/agents/{agent['id']}/test-chat")).json()
    await fake.clear()
    sent = (await c("POST", f"/sessions/{chat['id']}/messages", json={"content": "go"})).json()
    done = await run(pool, test_settings, sent["run_id"])
    assert done.status is S.COMPLETED, done.reason

    served = await fake.calls()
    by_model = {call["model"]: call["key"] for call in served}
    assert set(by_model) == {"fake-a", "fake-b"}  # the agent and its helper, each its own
    assert by_model["fake-a"] != by_model["fake-b"]  # …through its own connection (key)
    assert any("spawn_subagent" in call["tools"] for call in served if call["model"] == "fake-a")
    assert any("return_result" in call["tools"] for call in served if call["model"] == "fake-b")
    msgs = (await c("GET", f"/sessions/{chat['id']}/messages")).json()["messages"]
    assert msgs[-1]["content"]["text"] == "Done. Answered by fake-a."

    # AC45: the keys appear in no response, event, transcript message, log or row.
    await c("GET", f"/runs/{sent['run_id']}")
    await c("GET", f"/runs/{sent['run_id']}/events", params={"limit": 500})
    await c("GET", "/models/connections")
    await c("GET", "/models/default")
    async with pool.connection() as conn:
        rows = []
        for table in (
            "model_connections",
            "runs",
            "run_events",
            "session_messages",
            "agent_versions",
            "agent_definitions",
        ):
            cur = await conn.execute(f"SELECT * FROM {table}")
            rows.append(json.dumps([dict(r) for r in await cur.fetchall()], default=repr))
    everything = "\n".join([*c.bodies, *rows, caplog.text])
    for key in (KEY_A, KEY_B):
        assert key not in everything
        assert key.encode().hex() not in everything


async def test_a_running_turn_keeps_its_model_when_the_default_changes(
    api: Server, fake: Fake, pool: Pool, test_settings: Settings
) -> None:
    c = Seen(api.client)
    a = await connect(c, fake, "Default A", KEY_A, "fake-a")
    b = await connect(c, fake, "Default B", KEY_B, "fake-b")
    await c("PUT", "/models/default", json={"connection_id": a["id"], "model": "fake-a"})
    session = (await c("POST", "/sessions", json={"agent": "assistant"})).json()
    queued = (await c("POST", f"/sessions/{session['id']}/messages", json={"content": "hi"})).json()
    await c("PUT", "/models/default", json={"connection_id": b["id"], "model": "fake-b"})
    await fake.clear()
    await run(pool, test_settings, queued["run_id"])
    assert {call["model"] for call in await fake.calls()} == {"fake-a"}  # its binding
    nxt = (await c("POST", f"/sessions/{session['id']}/messages", json={"content": "again"})).json()
    await fake.clear()
    await run(pool, test_settings, nxt["run_id"])
    assert {call["model"] for call in await fake.calls()} == {"fake-b"}  # the new default
    await c("PUT", "/models/default", json={"connection_id": None})


async def test_a_moved_ciphertext_cant_be_opened(api: Server, fake: Fake, pool: Pool) -> None:
    c = Seen(api.client)
    a = await connect(c, fake, "Original", KEY_A, "fake-a")
    b = await connect(c, fake, "Target", KEY_B, "fake-b")
    async with pool.connection() as conn:  # copy A's ciphertext into B's row
        await conn.execute(
            """
            UPDATE model_connections t SET key_ciphertext = s.key_ciphertext,
                key_nonce = s.key_nonce, wrapped_key = s.wrapped_key,
                wrapped_nonce = s.wrapped_nonce
            FROM model_connections s WHERE s.id = %s AND t.id = %s
            """,
            (a["id"], b["id"]),
        )
    result = (
        await c("POST", f"/models/connections/{b['id']}/test", json={"model": "fake-b"})
    ).json()
    assert result["ok"] is False and "can't be opened" in result["detail"]


async def test_the_studio_names_missing_and_untested_models(api: Server, fake: Fake) -> None:
    c = Seen(api.client)
    agent = (await c("POST", "/studio/agents", json={"display_name": "Picky"})).json()
    doc = {
        "name": agent["name"],
        "description": "x",
        "instructions": "x",
        "model": "no-such-connection:big-model",
    }
    saved = (await c("PUT", f"/studio/agents/{agent['id']}/draft", json=doc)).json()
    issue = next(i for i in saved["draft"]["issues"] if i["field"] == "model")
    assert "no model connection called “no-such-connection”" in issue["message"]

    added = (
        await c(
            "POST",
            "/models/connections",
            json={"display_name": "Unproven", "kind": "compatible", "base_url": f"{fake.url}/v1"},
        )
    ).json()
    doc["model"] = f"{added['name']}:fake-a"
    saved = (await c("PUT", f"/studio/agents/{agent['id']}/draft", json=doc)).json()
    assert saved["draft"]["issues"] == []
    assert "Test the model “Unproven” (Settings → Models)" in saved["draft"]["blockers"]
    await c("POST", f"/models/connections/{added['id']}/test", json={"model": "fake-a"})
    blockers = (await c("GET", f"/studio/agents/{agent['id']}")).json()["draft"]["blockers"]
    assert not any("Unproven" in b for b in blockers)


async def test_a_turn_on_a_local_model_gets_more_time(
    api: Server, fake: Fake, pool: Pool, test_settings: Settings
) -> None:
    """The fake listens on 127.0.0.1: a model on this machine. Its turns get
    `local_turn_timeout_s` (a CPU model writes a reply in minutes), and the binding says so."""
    c = Seen(api.client)
    a = await connect(c, fake, "On this machine", KEY_A, "fake-a")
    await c("PUT", "/models/default", json={"connection_id": a["id"], "model": "fake-a"})
    session = (await c("POST", "/sessions", json={"agent": "assistant"})).json()
    queued = (await c("POST", f"/sessions/{session['id']}/messages", json={"content": "hi"})).json()
    async with pool.connection() as conn:
        sql = "SELECT limits, model_bindings FROM runs WHERE id = %s"
        row = await (await conn.execute(sql, (uuid.UUID(queued["run_id"]),))).fetchone()
    assert row is not None
    limits, bindings = row["limits"], row["model_bindings"]
    expected = min(test_settings.local_turn_timeout_s, test_settings.run_timeout_s)
    assert limits["timeout_s"] == expected  # the default is 300
    assert all(b["local"] for b in bindings.values())
    await c("PUT", "/models/default", json={"connection_id": None})


async def test_h2_a_turn_is_priced_by_its_connection_and_keeps_that_price(
    api: Server, fake: Fake, pool: Pool, test_settings: Settings
) -> None:
    """Phase H2: a model on this machine starts free; a price set in Settings → Models
    wins; a turn keeps the price it started with, even if the price changes."""
    c = Seen(api.client)
    added = await connect(c, fake, "Priced", KEY_A, "fake-a")
    assert added["prices"]["fake-a"]["source"] == "local"  # the fake runs on 127.0.0.1
    priced = await c("PATCH", f"/models/connections/{added['id']}", json={
        "prices": {"fake-a": {"input_per_mtok": 1000.0, "output_per_mtok": 2000.0}}})  # fmt: skip
    assert priced.status_code == 200, priced.text
    assert priced.json()["prices"]["fake-a"] == {
        "input_per_mtok": 1000.0, "output_per_mtok": 2000.0, "source": "connection"}  # fmt: skip
    bad = await c("PATCH", f"/models/connections/{added['id']}", json={
        "prices": {"fake-a": {"input_per_mtok": -1, "output_per_mtok": 1}}})  # fmt: skip
    assert bad.status_code == 422

    await c("PUT", "/models/default", json={"connection_id": added["id"], "model": "fake-a"})
    session = (await c("POST", "/sessions", json={"agent": "assistant"})).json()
    queued = (await c("POST", f"/sessions/{session['id']}/messages", json={"content": "hi"})).json()
    # The price changes after the turn was created: the turn keeps the one it started with.
    await c("PATCH", f"/models/connections/{added['id']}", json={"prices": {"fake-a": None}})
    done = await run(pool, test_settings, queued["run_id"])
    assert done.status is S.COMPLETED
    assert done.model_bindings  # pinned when the turn was created, with its price
    assert {b["price"]["source"] for b in done.model_bindings.values()} == {"connection"}
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT tokens_in, tokens_out, cost, estimated FROM run_model_usage WHERE run_id = %s",
            (done.id,),
        )
        rows = await cur.fetchall()
    tokens_in = sum(r["tokens_in"] for r in rows)
    tokens_out = sum(r["tokens_out"] for r in rows)
    expected = (tokens_in * 1000.0 + tokens_out * 2000.0) / 1e6
    assert tokens_in > 0 and float(sum(r["cost"] for r in rows)) == pytest.approx(expected)
    assert not any(r["estimated"] for r in rows)
    await c("PUT", "/models/default", json={"connection_id": None})

"""The Agent Studio through its API (phase L3a): build, test, publish, chat; versions
are immutable and pinned (AC47); test chats are safe; copy, restore, import/export."""

import io
import uuid
import zipfile
from collections.abc import AsyncIterator
from typing import Any

import pytest

from agent_runtime.api.app import create_app
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.queue import RedisWorkQueue
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.streaming.bus import EventBus, RedisEventBus
from tests.integration.test_stream import Server

pytestmark = pytest.mark.integration
GRAPHS = default_registry()
CALC: list[dict[str, Any]] = [
    {"tool_calls": [{"name": "calculator", "args": {"expression": "6*7"}}]},
    {"content": "42"},
]


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


def document(
    name: str,
    *,
    tools: list[str],
    helpers: list[dict[str, Any]] | None = None,
    description: str = "Plans trips.",
) -> dict[str, Any]:
    return {
        "name": name,
        "display_name": "Trip planner",
        "description": description,
        "instructions": "Plan trips. Today is {{date}}.",
        "max_turns": 10,
        "limits": {"max_tool_calls": 10, "timeout_s": 120},
        "tools": [{"name": t} for t in tools],
        "helpers": helpers or [],
    }


async def run(pool: Pool, settings: Settings, run_id: str) -> Any:
    return await RunExecutor(pool, settings, GRAPHS).execute(uuid.UUID(run_id))


async def test_build_test_publish_then_chat(
    api: Server, pool: Pool, test_settings: Settings
) -> None:
    c = api.client
    created = await c.post("/studio/agents", json={"display_name": "Trip planner"})
    assert created.status_code == 201, created.text
    agent = created.json()
    aid, name = agent["id"], agent["name"]
    assert name == "trip-planner" and agent["status"] == "draft"
    assert agent["draft"]["issues"]  # a blank agent needs a description: shown by field
    assert any(i["field"] == "description" for i in agent["draft"]["issues"])

    helper = {
        "name": "scout",
        "description": "Finds places.",
        "instructions": "Find places.",
        "tools": [{"name": "search"}],
    }
    saved = (
        await c.put(
            f"/studio/agents/{aid}/draft",
            json=document(name, tools=["calculator"], helpers=[helper]),
        )
    ).json()
    assert saved["draft"]["issues"] == [] and saved["draft"]["tested"] is False
    blocked = await c.post(f"/studio/agents/{aid}/publish", json={})
    assert blocked.status_code == 409 and blocked.json()["type"].endswith("/publish-blocked")
    assert "test chat" in blocked.json()["blockers"][0]

    chat = (await c.post(f"/studio/agents/{aid}/test-chat")).json()
    assert chat["id"] not in [s["id"] for s in (await c.get("/sessions")).json()]  # hidden
    sent = (
        await c.post(f"/sessions/{chat['id']}/messages", json={"content": "6*7?", "script": CALC})
    ).json()
    assert (await run(pool, test_settings, sent["run_id"])).status is S.COMPLETED
    tested = (await c.get(f"/studio/agents/{aid}")).json()
    assert tested["draft"]["tested"] is True and tested["draft"]["blockers"] == []

    published = await c.post(f"/studio/agents/{aid}/publish", json={"changelog": "First"})
    assert published.status_code == 200, published.text
    v1 = published.json()
    assert (v1["status"], v1["published"]["number"], v1["draft"]) == ("published", 1, None)
    listed = {a["name"]: a for a in (await c.get("/agents")).json()}
    assert listed[name]["source"] == "user" and listed[name]["display_name"] == "Trip planner"
    assert listed[name]["helpers"][0]["name"] == "scout"

    session = (await c.post("/sessions", json={"agent": name})).json()
    turn = (
        await c.post(
            f"/sessions/{session['id']}/messages", json={"content": "6*7?", "script": CALC}
        )
    ).json()
    assert (await run(pool, test_settings, turn["run_id"])).status is S.COMPLETED


async def publish_v(
    c: Any, pool: Pool, settings: Settings, aid: str, doc: dict[str, Any]
) -> dict[str, Any]:
    await c.post(f"/studio/agents/{aid}/edit")
    saved = (await c.put(f"/studio/agents/{aid}/draft", json=doc)).json()
    assert saved["draft"]["issues"] == [], saved["draft"]["issues"]
    chat = (await c.post(f"/studio/agents/{aid}/test-chat")).json()
    sent = (
        await c.post(
            f"/sessions/{chat['id']}/messages",
            json={"content": "hi", "script": [{"content": "hello"}]},
        )
    ).json()
    await run(pool, settings, sent["run_id"])
    published = await c.post(f"/studio/agents/{aid}/publish", json={})
    assert published.status_code == 200, published.text
    result: dict[str, Any] = published.json()
    return result


async def test_ac47_a_running_conversation_keeps_its_version(
    api: Server, pool: Pool, test_settings: Settings
) -> None:
    c = api.client
    agent = (await c.post("/studio/agents", json={"display_name": "Counter"})).json()
    aid, name = agent["id"], agent["name"]
    await publish_v(c, pool, test_settings, aid, document(name, tools=["calculator"]))
    session = (await c.post("/sessions", json={"agent": name})).json()
    on_v1 = (
        await c.post(
            f"/sessions/{session['id']}/messages", json={"content": "6*7?", "script": CALC}
        )
    ).json()

    # v2 drops the calculator, published while the v1 turn is still queued
    v2 = await publish_v(c, pool, test_settings, aid, document(name, tools=["search"]))
    assert v2["published"]["number"] == 2
    assert (await run(pool, test_settings, on_v1["run_id"])).status is S.COMPLETED
    msgs = (await c.get(f"/sessions/{session['id']}/messages")).json()["messages"]
    assert next(m for m in msgs if m["type"] == "tool_result")["content"]["result"] == {
        "value": 42.0
    }

    on_v2 = (
        await c.post(
            f"/sessions/{session['id']}/messages", json={"content": "again", "script": CALC}
        )
    ).json()
    await run(pool, test_settings, on_v2["run_id"])
    msgs = (await c.get(f"/sessions/{session['id']}/messages")).json()["messages"]
    refused = [m for m in msgs if m["type"] == "tool_result" and m["run_id"] == on_v2["run_id"]]
    assert refused[0]["content"].get("error")  # the next turn runs v2: no calculator

    history = (await c.get(f"/studio/agents/{aid}")).json()["versions"]
    assert [(v["number"], v["state"]) for v in history] == [(2, "published"), (1, "published")]


async def test_a_test_chat_simulates_side_effects_and_has_a_small_budget(
    api: Server, pool: Pool, test_settings: Settings
) -> None:
    c = api.client
    agent = (await c.post("/studio/agents", json={"display_name": "Herald"})).json()
    aid = agent["id"]
    await c.put(f"/studio/agents/{aid}/draft", json=document(agent["name"], tools=["notify"]))
    chat = (await c.post(f"/studio/agents/{aid}/test-chat")).json()
    script = [
        {"tool_calls": [{"name": "notify", "args": {"to": "ops", "message": "hi"}}]},
        {"content": "Sent."},
    ]
    sent = (
        await c.post(
            f"/sessions/{chat['id']}/messages", json={"content": "tell ops", "script": script}
        )
    ).json()
    paused = await run(pool, test_settings, sent["run_id"])
    assert paused.status is S.WAITING_APPROVAL  # you still decide, as in a real chat
    assert paused.limits["max_model_calls"] <= test_settings.playground_model_calls
    assert paused.limits["timeout_s"] <= test_settings.playground_timeout_s
    await c.post(f"/sessions/{chat['id']}/approve", json={"decision": "approve"})
    assert (await run(pool, test_settings, sent["run_id"])).status is S.COMPLETED
    msgs = (await c.get(f"/sessions/{chat['id']}/messages")).json()["messages"]
    result = next(m for m in msgs if m["type"] == "tool_result")["content"]["result"]
    assert result["simulated"] is True
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT count(*) AS n FROM outbox_notifications WHERE run_id = %s", (sent["run_id"],)
        )
        row = await cur.fetchone()
    assert row is not None and row["n"] == 0  # nothing was sent


async def test_copy_restore_export_import(api: Server, pool: Pool, test_settings: Settings) -> None:
    c = api.client
    copy = (
        await c.post("/studio/agents", json={"display_name": "My Nuria", "copy_of": "chat"})
    ).json()
    assert copy["name"] == "my-nuria" and copy["draft"]["issues"] == []
    helpers = [h["name"] for h in copy["draft"]["document"]["helpers"]]
    assert helpers == ["data-analyst", "researcher"]
    assert (await c.get("/agents/chat")).json()["source"] == "builtin"  # unchanged
    clash = (await c.post("/studio/agents", json={"display_name": "chat"})).json()
    assert clash["name"] == "chat-2"  # a built-in's name is never taken

    aid, name = copy["id"], copy["name"]
    v1_doc = copy["draft"]["document"]
    await publish_v(c, pool, test_settings, aid, v1_doc)
    await publish_v(c, pool, test_settings, aid, {**v1_doc, "description": "Changed."})
    restored = (await c.post(f"/studio/agents/{aid}/versions/1/restore")).json()
    assert restored["draft"]["document"] == v1_doc  # rolling back = restore, then publish

    exported = await c.get(f"/studio/agents/{aid}/export", params={"version": 1})
    assert exported.headers["content-type"] == "application/zip"
    imported = await c.post(
        "/studio/import", params={"filename": "my-nuria.zip"}, content=exported.content
    )
    assert imported.status_code == 201, imported.text
    again = imported.json()
    assert again["name"] == f"{name}-2"  # an import never replaces an agent
    assert {**again["draft"]["document"], "name": name} == v1_doc

    evil = io.BytesIO()
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../etc/agent.md", "---\nname: x\n---\nhi")
    rejected = await c.post(
        "/studio/import", params={"filename": "evil.zip"}, content=evil.getvalue()
    )
    assert rejected.status_code == 422 and rejected.json()["type"].endswith("/import-rejected")


async def test_issues_are_reported_by_field(api: Server) -> None:
    c = api.client
    agent = (await c.post("/studio/agents", json={"display_name": "Sloppy"})).json()
    bad_helper = {
        "name": "pinger",
        "description": "d",
        "instructions": "x",
        "tools": [{"name": "notify"}],
    }
    doc = document(agent["name"], tools=["teleport"], helpers=[bad_helper])
    doc["instructions"] = "Hi {{secret}}"
    issues = (await c.put(f"/studio/agents/{agent['id']}/draft", json=doc)).json()["draft"][
        "issues"
    ]
    found = {(i["where"], i["field"]) for i in issues}
    assert {("agent", "tools"), ("agent", "instructions"), ("helpers.pinger", "tools")} <= found


async def test_a_retried_send_returns_the_same_turn(api: Server) -> None:
    c = api.client
    session = (await c.post("/sessions", json={"agent": "chat"})).json()
    body = {"content": "hi", "script": [{"content": "x"}]}
    first = await c.post(
        f"/sessions/{session['id']}/messages", json=body, headers={"Idempotency-Key": "send-1"}
    )
    again = await c.post(
        f"/sessions/{session['id']}/messages", json=body, headers={"Idempotency-Key": "send-1"}
    )
    assert first.status_code == again.status_code == 202
    assert first.json() == again.json()  # one turn, not two
    other = await c.post(
        f"/sessions/{session['id']}/messages", json=body, headers={"Idempotency-Key": "send-2"}
    )
    assert other.status_code == 409  # a different message while the turn runs

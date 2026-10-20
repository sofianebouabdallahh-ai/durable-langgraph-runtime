"""Phase L5: opt-in, content-free usage counts (SC6) and a chat as Markdown (L5.6)."""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from agent_runtime import usage
from agent_runtime.api.app import create_app
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.queue import InMemoryWorkQueue
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.service import RunService
from agent_runtime.sessions.service import SessionService
from agent_runtime.streaming.bus import InMemoryEventBus

pytestmark = pytest.mark.integration
GRAPHS = default_registry()
SECRET = "Zanzibar-7731"  # a string that must never leave as a usage count


@pytest.fixture
async def client(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(test_settings, pool=pool, queue=InMemoryWorkQueue(), bus=InMemoryEventBus())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        yield c


async def a_chat(
    pool: Pool, settings: Settings, text: str, script: list[dict[str, Any]]
) -> uuid.UUID:
    runs = RunService(pool, settings, GRAPHS)
    service = SessionService(pool, settings, GRAPHS, runs)
    session = await service.create("chat", f"About {SECRET}")
    sent = await service.send(session.id, text, script=script)
    await RunExecutor(pool, settings, GRAPHS).execute(sent.run.id)
    return session.id


async def test_usage_counts_are_off_by_default_and_hold_no_content(
    client: httpx.AsyncClient, pool: Pool, test_settings: Settings
) -> None:
    async with pool.connection() as conn:
        await usage.set_sharing(conn, False)  # the session-wide test database: start known
    before = (await client.get("/telemetry")).json()
    assert before["sharing"] is False
    assert set(before["report"]) == set(before["fields"])  # every field is documented

    await a_chat(pool, test_settings, f"Remember {SECRET}", [
        {"tool_calls": [{"name": "save_note", "args": {"text": f"note {SECRET}"}}]},
        {"content": f"Saved {SECRET}."},
    ])  # fmt: skip
    after = (await client.get("/telemetry")).json()["report"]
    assert after["chats"] == before["report"]["chats"] + 1
    assert after["turns"] == before["report"]["turns"] + 1
    assert after["days_active"] >= 1
    assert SECRET not in json.dumps(after)  # titles, messages, tool args, notes: none of it
    assert all(isinstance(v, (int, str, dict)) or v is None for v in after.values())

    on = await client.put("/telemetry", json={"sharing": True})
    assert on.status_code == 200 and on.json()["sharing"] is True
    assert (await client.get("/telemetry")).json()["sharing"] is True
    off = await client.put("/telemetry", json={"sharing": False})
    assert off.json()["sharing"] is False


async def test_a_chat_exports_as_markdown_in_order(
    client: httpx.AsyncClient, pool: Pool, test_settings: Settings, sandbox: Settings
) -> None:
    """The whole turn, in order (L6): what you wrote, the tool call with its arguments, its
    result in full, the reply with its model; a fence in the text can't break a block."""
    sid = await a_chat(pool, test_settings, "What is 6*7?", [
        {"tool_calls": [{"name": "run_python", "args": {"code": "print(6*7)"}}]},
        {"content": "It's 42. Here's a fence: ```"},
    ])  # fmt: skip
    resp = await client.get(f"/sessions/{sid}/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "attachment" in resp.headers["content-disposition"]
    md = resp.text
    assert md.startswith(f"# About {SECRET}")
    assert "- **Agent:** chat" in md and "- **Models:** scripted" in md
    order = [md.index(s) for s in ("## Turn 1", "### 🧑 You", "What is 6*7?",
                                   "#### 🔧 Tool call: `run_python`", '"code": "print(6*7)"',
                                   "#### 📥 Result of `run_python`", '"stdout": "42\\n"',
                                   "### 🤖 Assistant · scripted", "It's 42.")]  # fmt: skip
    assert order == sorted(order)
    assert (await client.get(f"/sessions/{uuid.uuid4()}/export")).status_code == 404


async def test_report_this_reply_holds_the_text_only_when_asked(
    client: httpx.AsyncClient, pool: Pool, test_settings: Settings
) -> None:
    """SC5: README, events (structure only) and no text by default; the chat if ticked."""
    import io
    import zipfile

    sid = await a_chat(pool, test_settings, f"Remember {SECRET}", [
        {"tool_calls": [{"name": "save_note", "args": {"text": f"note {SECRET}"}}]},
        {"content": f"Saved {SECRET}."},
    ])  # fmt: skip
    run_id = (await client.get(f"/sessions/{sid}/messages")).json()["messages"][0]["run_id"]

    plain = await client.get(f"/runs/{run_id}/report")
    assert plain.status_code == 200 and plain.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(plain.content))
    assert set(zf.namelist()) == {"README.md", "events.json"}  # `chat` is built in
    assert SECRET not in "".join(zf.read(n).decode() for n in zf.namelist())
    events = json.loads(zf.read("events.json"))
    assert {"run.started", "tool.completed", "run.completed"} <= {e["type"] for e in events}
    assert "not included" in zf.read("README.md").decode()

    full = zipfile.ZipFile(io.BytesIO((await client.get(
        f"/runs/{run_id}/report", params={"include_chat": True})).content))  # fmt: skip
    assert set(full.namelist()) == {"README.md", "events.json", "chat.md"}
    assert SECRET in full.read("chat.md").decode()


async def test_the_report_holds_your_own_agents_definition(
    client: httpx.AsyncClient, pool: Pool, test_settings: Settings
) -> None:
    """SC5: an agent you made travels with the report (agent.md)."""
    import io
    import zipfile

    calc = [
        {"tool_calls": [{"name": "calculator", "args": {"expression": "6*7"}}]},
        {"content": "42."},
    ]
    display = f"Reporter {uuid.uuid4().hex[:6]}"
    created = (await client.post("/studio/agents", json={"display_name": display})).json()
    aid, name = created["id"], created["name"]
    await client.put(f"/studio/agents/{aid}/draft", json={
        "name": name, "display_name": "Reporter", "description": "Does sums.",
        "instructions": "Do sums.", "max_turns": 5, "limits": {"max_tool_calls": 5},
        "tools": [{"name": "calculator"}], "helpers": [],
    })  # fmt: skip
    test_chat = (await client.post(f"/studio/agents/{aid}/test-chat")).json()
    sent = (await client.post(f"/sessions/{test_chat['id']}/messages",
                              json={"content": "6*7?", "script": calc})).json()  # fmt: skip
    await RunExecutor(pool, test_settings, GRAPHS).execute(uuid.UUID(sent["run_id"]))
    assert (await client.post(f"/studio/agents/{aid}/publish", json={})).status_code == 200

    session = (await client.post("/sessions", json={"agent": name})).json()
    turn = (await client.post(f"/sessions/{session['id']}/messages",
                              json={"content": "6*7?", "script": calc})).json()  # fmt: skip
    await RunExecutor(pool, test_settings, GRAPHS).execute(uuid.UUID(turn["run_id"]))

    zf = zipfile.ZipFile(io.BytesIO((await client.get(f"/runs/{turn['run_id']}/report")).content))
    assert "agent.md" in zf.namelist()
    assert "Do sums." in zf.read("agent.md").decode()
    assert "yours, version 1" in zf.read("README.md").decode()

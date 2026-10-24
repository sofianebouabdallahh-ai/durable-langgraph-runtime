"""Phase L8: agents use MCP tools, through the same pipeline as built-in ones.

SC1 (an agent uses a server's tool), SC2 (ask first by default), SC3 (no rug pulls:
what's published is pinned, a changed tool gets no call), SC5 (a crash mid-call: a
read-only call is sent again, an ask-first one isn't). Against the fake MCP server.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from agent_runtime.api.app import create_app
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.devtools.fake_mcp import FACT
from agent_runtime.mcp import tools as mcp_tools
from agent_runtime.queue import InMemoryWorkQueue
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.state import RunStatus
from agent_runtime.streaming.bus import InMemoryEventBus
from tests.integration.conftest import MCP_TOKEN, ServedMcp

pytestmark = pytest.mark.integration


class Api:
    def __init__(self, client: httpx.AsyncClient, pool: Pool, settings: Settings,
                 graphs: Any) -> None:  # fmt: skip
        self.c, self.pool, self.settings, self.graphs = client, pool, settings, graphs

    async def ok(self, method: str, path: str, **kw: Any) -> Any:
        r = await self.c.request(method, path, **kw)
        assert r.status_code < 300, (method, path, r.status_code, r.text)
        return r.json() if r.content else None

    async def run(self, run_id: str, owner: str = "w:1", settings: Settings | None = None) -> Any:
        executor = RunExecutor(self.pool, settings or self.settings, self.graphs, owner=owner)
        return await executor.execute(uuid.UUID(run_id))

    async def send(self, sid: str, script: list[dict[str, Any]]) -> str:
        sent = await self.ok("POST", f"/sessions/{sid}/messages",
                             json={"content": "go", "script": script})  # fmt: skip
        return str(sent["run_id"])

    async def results(self, sid: str) -> list[dict[str, Any]]:
        messages = (await self.ok("GET", f"/sessions/{sid}/messages"))["messages"]
        return [m["content"] for m in messages if m["type"] == "tool_result"]


@pytest.fixture
async def api(pool: Pool, test_settings: Settings, checkpoint_tables: None) -> AsyncIterator[Api]:
    mcp_tools._offered.clear()  # the live-definition cache: each test starts fresh
    app = create_app(test_settings, pool=pool, queue=InMemoryWorkQueue(), bus=InMemoryEventBus())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        yield Api(c, pool, test_settings, app.state.graphs)


def uid() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture
def settings_fast(test_settings: Settings) -> Settings:
    """Short leases, so a killed worker's run is reclaimed within two seconds."""
    return test_settings.model_copy(update={"lease_ttl_s": 1.5, "heartbeat_s": 0.4})


def call(name: str, **args: Any) -> dict[str, Any]:
    return {"tool_calls": [{"name": name, "args": args}]}


async def travel_server(api: Api, served: ServedMcp) -> tuple[str, str, str]:
    """The fake server, added and tested; lookup runs without asking, send_message asks."""
    tag = uuid.uuid4().hex[:6]
    server = await api.ok("POST", "/mcp/servers", json={
        "display_name": f"Travel {tag}", "url": served.url, "token": MCP_TOKEN})  # fmt: skip
    assert server["status"] == "ready", server
    sid = server["id"]
    await api.ok("PUT", f"/mcp/servers/{sid}/tools/lookup",
                 json={"enabled": True, "without_asking": True})  # fmt: skip
    await api.ok("PUT", f"/mcp/servers/{sid}/tools/send_message", json={"enabled": True})
    name = server["name"]
    return sid, f"mcp__{name}__lookup", f"mcp__{name}__send_message"


async def published_agent(api: Api, tools: list[str]) -> dict[str, Any]:
    agent = await api.ok("POST", "/studio/agents", json={"display_name": f"Mcp {uid()}"})
    doc = {**agent["draft"]["document"], "description": "Plans trips.",
           "tools": [{"name": t} for t in tools]}  # fmt: skip
    state = await api.ok("PUT", f"/studio/agents/{agent['id']}/draft", json=doc)
    assert not state["draft"]["issues"], state["draft"]["issues"]
    chat = await api.ok("POST", f"/studio/agents/{agent['id']}/test-chat")
    await api.run(await api.send(chat["id"], [{"content": "hello"}]))
    published = await api.ok("POST", f"/studio/agents/{agent['id']}/publish", json={})
    return {**published, "test_chat": chat["id"]}


async def test_an_agent_uses_a_servers_tools(api: Api, served_mcp: ServedMcp) -> None:
    _, lookup, send = await travel_server(api, served_mcp)
    catalog = await api.ok("GET", "/studio/catalog")
    offered = {t["name"]: t for t in catalog["tools"]}
    assert offered[lookup]["asks_first"] is False and offered[lookup]["helpers_allowed"]
    assert offered[send]["asks_first"] is True and offered[send]["server"].startswith("Travel")

    agent = await published_agent(api, [lookup, send])
    sid = (await api.ok("POST", "/sessions", json={"agent": agent["name"]}))["id"]
    run = await api.send(sid, [call(lookup, topic="Naxos"), {"content": "Here you go."}])
    done = await api.run(run)
    assert done.status is RunStatus.COMPLETED
    (result,) = await api.results(sid)
    assert result.get("result", {}).get("text") == FACT, result
    assert served_mcp.fake.calls[-1] == {"tool": "lookup", "topic": "Naxos"}

    # A tool with effects asks first (SC2); after the approval it runs, once.
    run = await api.send(sid, [call(send, to="ops", text="hi"), {"content": "Sent."}])
    paused = await api.run(run)
    assert paused.status is RunStatus.WAITING_APPROVAL
    assert not any(c["tool"] == "send_message" for c in served_mcp.fake.calls)
    await api.ok("POST", f"/sessions/{sid}/approve", json={"decision": "approve"})
    assert (await api.run(run)).status is RunStatus.COMPLETED
    assert sum(c["tool"] == "send_message" for c in served_mcp.fake.calls) == 1


async def test_a_test_chat_simulates_a_tool_that_asks_first(
    api: Api, served_mcp: ServedMcp
) -> None:
    _, lookup, send = await travel_server(api, served_mcp)
    agent = await published_agent(api, [lookup, send])
    run = await api.send(agent["test_chat"], [call(send, to="ops", text="hi"), {"content": "ok"}])
    paused = await api.run(run)
    assert paused.status is RunStatus.WAITING_APPROVAL
    await api.ok("POST", f"/sessions/{agent['test_chat']}/approve", json={"decision": "approve"})
    await api.run(run)
    results = await api.results(agent["test_chat"])
    assert results[-1]["result"]["simulated"] is True  # nothing left the test chat
    assert not any(c["tool"] == "send_message" for c in served_mcp.fake.calls)


async def test_a_changed_or_switched_off_tool_gets_no_call(api: Api, served_mcp: ServedMcp) -> None:
    """SC3: the server changes `lookup` after the agent was published."""
    server_id, lookup, _ = await travel_server(api, served_mcp)
    agent = await published_agent(api, [lookup])
    async with api.pool.connection() as conn:
        cur = await conn.execute(
            "SELECT v.mcp_lock FROM agent_versions v JOIN agents a ON a.id = v.agent_id "
            "WHERE a.name = %s AND v.state = 'published'", (agent["name"],),
        )  # fmt: skip
        row = await cur.fetchone()
    assert row is not None and set(row["mcp_lock"]) == {lookup}  # pinned at publish

    async with httpx.AsyncClient() as admin:
        await admin.post(f"{served_mcp.admin}/change")
    mcp_tools._offered.clear()
    sid = (await api.ok("POST", "/sessions", json={"agent": agent["name"]}))["id"]
    await api.run(await api.send(sid, [call(lookup, topic="Naxos"), {"content": "ok"}]))
    (result,) = await api.results(sid)
    assert "changed on its server" in result["error"]
    assert not any(c["tool"] == "lookup" for c in served_mcp.fake.calls)

    # Switched off in Settings → Tools: refused at once, even for a published agent.
    async with httpx.AsyncClient() as admin:
        await admin.post(f"{served_mcp.admin}/reset")
    mcp_tools._offered.clear()
    await api.ok("PUT", f"/mcp/servers/{server_id}/tools/lookup", json={"enabled": False})
    await api.run(await api.send(sid, [call(lookup, topic="Paros"), {"content": "ok"}]))
    assert "switched off" in (await api.results(sid))[-1]["error"]
    assert served_mcp.fake.calls == []


async def test_helpers_never_get_a_tool_that_asks_first(api: Api, served_mcp: ServedMcp) -> None:
    _, lookup, send = await travel_server(api, served_mcp)
    agent = await api.ok("POST", "/studio/agents", json={"display_name": f"H {uid()}"})
    doc = {**agent["draft"]["document"], "description": "Plans trips."}
    helper = {"name": "scout", "description": "Finds facts.", "instructions": "Find facts.",
              "tools": [{"name": send}]}  # fmt: skip
    both = {**doc, "tools": [{"name": lookup}], "helpers": [helper]}
    state = await api.ok("PUT", f"/studio/agents/{agent['id']}/draft", json=both)
    assert any("approval" in i["message"] for i in state["draft"]["issues"]), state["draft"]
    unknown = await api.ok("PUT", f"/studio/agents/{agent['id']}/draft",
                           json={**doc, "tools": [{"name": "mcp__nowhere__thing"}]})  # fmt: skip
    assert any(i["field"] == "tools" for i in unknown["draft"]["issues"])


async def test_a_crash_mid_call(api: Api, served_mcp: ServedMcp, settings_fast: Settings) -> None:
    """SC5: a read-only call cut off by a crash is sent again; an ask-first one isn't."""
    _, lookup, send = await travel_server(api, served_mcp)
    agent = await published_agent(api, [lookup, send])
    sid = (await api.ok("POST", "/sessions", json={"agent": agent["name"]}))["id"]

    async def killed_mid_call(run: str, tool: str) -> None:
        task = asyncio.create_task(api.run(run, "w-a:1", settings_fast))
        new = served_mcp.fake.calls
        while not any(c["tool"] == tool for c in new[len(before) :]):  # noqa: ASYNC110
            await asyncio.sleep(0.05)
        task.cancel()  # the worker dies during the call
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(settings_fast.lease_ttl_s + 0.2)
        assert (await api.run(run, "w-b:2", settings_fast)).status is RunStatus.COMPLETED

    before = list(served_mcp.fake.calls)
    run = await api.send(sid, [call(lookup, topic="Naxos [slow]"), {"content": "ok"}])
    await killed_mid_call(run, "lookup")
    assert sum(c["tool"] == "lookup" for c in served_mcp.fake.calls) == 2  # sent again
    assert (await api.results(sid))[-1]["result"]["text"] == FACT

    before = list(served_mcp.fake.calls)
    run = await api.send(sid, [call(send, to="ops", text="hi [slow]"), {"content": "ok"}])
    assert (await api.run(run, "w-a:1", settings_fast)).status is RunStatus.WAITING_APPROVAL
    await api.ok("POST", f"/sessions/{sid}/approve", json={"decision": "approve"})
    await killed_mid_call(run, "send_message")
    assert sum(c["tool"] == "send_message" for c in served_mcp.fake.calls) == 1  # not again
    assert "may have run once" in (await api.results(sid))[-1]["error"]

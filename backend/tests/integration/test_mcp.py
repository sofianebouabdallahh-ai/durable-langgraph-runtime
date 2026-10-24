"""Phase L8: MCP servers people add, their tools, pinning and the audit trail.

Against a real MCP server over HTTP (the fake one in devtools, served in this process).
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest
import uvicorn

from agent_runtime.audit import AuditLog
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.devtools.fake_mcp import FACT, FakeMcp, create_app
from agent_runtime.mcp.client import call_tool
from agent_runtime.mcp.service import McpInvalid, McpService, split_name, tool_name

pytestmark = pytest.mark.integration

TOKEN = "fixture-token-" + "q" * 20


@dataclass
class Served:
    url: str
    admin: str
    fake: FakeMcp


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
async def served() -> AsyncIterator[Served]:
    app, fake = create_app(token=TOKEN)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 — uvicorn offers no "started" event
        await asyncio.sleep(0.05)
    try:
        yield Served(f"http://127.0.0.1:{port}/mcp/", f"http://127.0.0.1:{port}/admin", fake)
    finally:
        server.should_exit = True
        await task


@pytest.fixture
def service(pool: Pool, test_settings: Settings) -> McpService:
    return McpService(pool, test_settings)


async def test_add_test_and_switch_on_tools(
    service: McpService, served: Served, pool: Pool
) -> None:
    added = await service.add(display_name="Travel facts", url=served.url, token=TOKEN)
    assert added.name == "travel_facts" and added.has_token and added.status == "untested"
    server, tools = await service.test(added.id)
    assert server.status == "ready" and server.protocol_version == "2026-07-28"
    by = {t.name: t for t in tools}
    assert set(by) == {"lookup", "send_message", "planted"}
    assert not any(t.enabled for t in tools)  # new tools start switched off
    assert by["lookup"].latest.read_only and not by["send_message"].latest.read_only

    on = await service.set_tool(added.id, "lookup", enabled=True, without_asking=True)
    assert on.usable and on.without_asking and on.digest == on.latest_digest
    with pytest.raises(McpInvalid, match="read-only"):  # never for a tool with effects
        await service.set_tool(added.id, "send_message", enabled=True, without_asking=True)
    asked = await service.set_tool(added.id, "send_message", enabled=True)
    assert asked.usable and not asked.without_asking

    # The token is sealed: not in the row, but it opens for a call.
    async with pool.connection() as conn:
        row = await (await conn.execute("SELECT * FROM mcp_servers WHERE id = %s",
                                        (added.id,))).fetchone()  # fmt: skip
    assert row is not None and TOKEN.encode() not in bytes(row["key_ciphertext"])
    assert TOKEN not in str(dict(row))
    result = await call_tool(service.endpoint(server), "lookup", {"topic": "naxos"})
    assert result.text == FACT and not result.is_error

    name = tool_name(server.name, "lookup")
    assert name == "mcp__travel_facts__lookup" and split_name(name) == ("travel_facts", "lookup")
    async with pool.connection() as conn:
        trail = await AuditLog(conn).list(limit=50)
    actions = {(e.action, e.target_id) for e in trail}
    assert ("mcp_server.added", "travel_facts") in actions
    assert ("mcp_tool.enabled", name) in actions
    assert all(TOKEN not in str(e.after) for e in trail)


async def test_a_changed_tool_is_blocked_until_approved(
    service: McpService, served: Served
) -> None:
    """Rug-pull protection: the server changes a tool after it was switched on."""
    added = await service.add(display_name="Changing", url=served.url, token=TOKEN)
    await service.test(added.id)
    approved = await service.set_tool(added.id, "lookup", enabled=True)
    async with httpx.AsyncClient() as admin:
        await admin.post(f"{served.admin}/change")
    _, tools = await service.test(added.id)
    lookup = next(t for t in tools if t.name == "lookup")
    assert lookup.changed and not lookup.usable
    assert lookup.digest == approved.digest  # what was approved stays what it was
    assert lookup.scan["status"] == "review"  # the new description hides an instruction
    assert any(f["check"] == "injection" for f in lookup.scan["findings"])

    again = await service.approve_change(added.id, "lookup")
    assert again.usable and again.digest == lookup.latest_digest


async def test_what_goes_wrong_is_said_plainly(service: McpService, served: Served) -> None:
    wrong = await service.add(display_name="Wrong token", url=served.url, token="nope")
    server, tools = await service.test(wrong.id)
    assert server.status == "failed" and "refused the token" in (server.status_detail or "")
    assert tools == []
    path = await service.add(display_name="Wrong path", url=served.url.replace("/mcp/", "/x/"),
                             token=TOKEN)  # fmt: skip
    server, _ = await service.test(path.id)
    assert "check the path" in (server.status_detail or "")
    for url in ("http://169.254.169.254/mcp", "ftp://example.com/mcp", "http://postgres:5432/"):
        with pytest.raises(McpInvalid):
            await service.add(display_name="Bad", url=url)


async def test_removing_a_server_switches_its_tools_off(
    service: McpService, served: Served
) -> None:
    added = await service.add(display_name="Gone soon", url=served.url, token=TOKEN)
    await service.test(added.id)
    await service.set_tool(added.id, "lookup", enabled=True)
    await service.remove(added.id)
    assert all(s.id != added.id for s, _ in await service.servers())
    _, tools = await service.server(added.id)
    assert tools == []  # an archived server's tools aren't listed

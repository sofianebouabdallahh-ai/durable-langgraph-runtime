"""Phase L7d: the audit trail (SC5) and 👍 / 👎 on replies.

Every listed change writes exactly one row, in its own transaction; a change that fails
writes none; the API's database user can't change or delete a row; no key reaches it.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from psycopg import errors

from agent_runtime.api.app import create_app
from agent_runtime.config import Settings, component_credentials
from agent_runtime.db import Pool, create_pool
from agent_runtime.dbadmin import grant_checkpoint_tables, provision_users
from agent_runtime.queue import InMemoryWorkQueue
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.streaming.bus import InMemoryEventBus

pytestmark = pytest.mark.integration

KEY = f"sk-audit-{uuid.uuid4().hex}{uuid.uuid4().hex}"


class Api:
    def __init__(self, client: httpx.AsyncClient, pool: Pool, settings: Settings,
                 graphs: Any) -> None:  # fmt: skip
        self.c, self.pool, self._settings, self._graphs = client, pool, settings, graphs

    async def ok(self, method: str, path: str, **kw: Any) -> Any:
        r = await self.c.request(method, path, **kw)
        assert r.status_code < 300, (method, path, r.status_code, r.text)
        return r.json() if r.content else None

    async def run(self, run_id: str) -> None:
        await RunExecutor(self.pool, self._settings, self._graphs).execute(uuid.UUID(run_id))

    async def rows(self, **filters: str) -> list[dict[str, Any]]:
        return list(await self.ok("GET", "/audit", params={**filters, "limit": 500}))


@pytest.fixture
async def api(pool: Pool, test_settings: Settings, checkpoint_tables: None) -> AsyncIterator[Api]:
    app = create_app(test_settings, pool=pool, queue=InMemoryWorkQueue(), bus=InMemoryEventBus())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        yield Api(c, pool, test_settings, app.state.graphs)


def once(rows: list[dict[str, Any]], action: str, target_id: str) -> dict[str, Any]:
    mine = [r for r in rows if r["action"] == action and r["target_id"] == target_id]
    assert len(mine) == 1, (action, target_id, mine)
    return mine[0]


async def test_every_change_writes_one_row_and_no_secret(api: Api) -> None:
    tag = uuid.uuid4().hex[:6]
    # Agents: create, test, publish, restore, archive, import.
    agent = await api.ok("POST", "/studio/agents", json={"display_name": f"Audit {tag}",
                                                         "copy_of": "chat"})  # fmt: skip
    chat = await api.ok("POST", f"/studio/agents/{agent['id']}/test-chat")
    sent = await api.ok("POST", f"/sessions/{chat['id']}/messages",
                        json={"content": "hi", "script": [{"content": "hello"}]})  # fmt: skip
    await api.run(sent["run_id"])
    await api.ok("POST", f"/studio/agents/{agent['id']}/publish", json={"changelog": "first"})
    await api.ok("POST", f"/studio/agents/{agent['id']}/versions/1/restore")
    await api.ok("POST", f"/studio/agents/{agent['id']}/archive")
    exported = await api.c.get(f"/studio/agents/{agent['id']}/export")
    filename = exported.headers["content-disposition"].split('filename="')[1].rstrip('"')
    imported = await api.ok("POST", "/studio/import", params={"filename": filename},
                            content=exported.content)  # fmt: skip
    # Skills: create, edit, archive.
    body = {"name": f"tips-{tag}", "description": "Tips. Use when planning.",
            "instructions": "Check twice."}  # fmt: skip
    skill = (await api.ok("POST", "/skills", json=body))["skill"]
    await api.ok("PATCH", f"/skills/{skill['id']}", json={"instructions": "Check three times."})
    await api.ok("DELETE", f"/skills/{skill['id']}")
    # Models: add (with a key), change, make it the default, remove.
    conn = await api.ok("POST", "/models/connections", json={
        "display_name": f"Audit {tag}", "kind": "openai", "base_url": "https://api.openai.com/v1",
        "api_key": KEY, "models": ["gpt-x"]})  # fmt: skip
    await api.ok("PATCH", f"/models/connections/{conn['id']}", json={"models": ["gpt-y"]})
    await api.ok("PUT", "/models/default", json={"connection_id": conn["id"], "model": "gpt-y"})
    await api.ok("DELETE", f"/models/connections/{conn['id']}")
    # Settings: tools, usage sharing; the kill switch; an approval.
    await api.ok("PUT", "/tools/settings", json={"web_allowlist": [f"{tag}.example"]})
    await api.ok("PUT", "/telemetry", json={"sharing": True})
    await api.ok("PUT", "/telemetry", json={"sharing": False})
    await api.ok("POST", "/kill-switch/stop", json={"agent": agent["name"], "reason": "test"})
    await api.ok("POST", "/kill-switch/resume", json={"agent": agent["name"]})
    sid = (await api.ok("POST", "/sessions", json={"agent": "chat"}))["id"]
    notify = {"tool_calls": [{"name": "notify", "args": {"to": "ops", "message": "hi"}}]}
    script = [notify, {"content": "Sent."}]
    paused = await api.ok("POST", f"/sessions/{sid}/messages",
                          json={"content": "tell ops", "script": script})  # fmt: skip
    await api.run(paused["run_id"])
    await api.ok("POST", f"/sessions/{sid}/approve", json={"decision": "reject", "reason": "no"})

    rows = await api.rows()
    name = agent["name"]
    once(rows, "agent.created", name)
    assert once(rows, "agent.published", name)["after"]["changelog"] == "first"
    assert once(rows, "agent.restored", name)["after"] == {"version": 1}
    once(rows, "agent.archived", name)
    once(rows, "agent.imported", imported["name"])
    once(rows, "skill.created", f"tips-{tag}")
    updated = once(rows, "skill.updated", f"tips-{tag}")
    assert updated["before"]["version"] != updated["after"]["version"]
    once(rows, "skill.archived", f"tips-{tag}")
    added = once(rows, "model_connection.added", conn["name"])
    assert added["after"]["key"] == "set" and added["after"]["key_fingerprint"]
    changed = once(rows, "model_connection.changed", conn["name"])
    assert (changed["before"]["models"], changed["after"]["models"]) == (["gpt-x"], ["gpt-y"])
    once(rows, "model_connection.removed", conn["name"])
    default = [r for r in rows if r["action"] == "default_model.changed"
               and (r["after"] or {}).get("connection_id") == conn["id"]]  # fmt: skip
    assert len(default) == 1
    tools = [r for r in rows if r["action"] == "tool_settings.changed"
             and f"{tag}.example" in json.dumps(r["after"])]  # fmt: skip
    assert len(tools) == 1
    sharing = [r for r in rows if r["action"] == "usage_sharing.changed"][:2]
    assert [r["after"]["sharing"] for r in sharing] == [False, True]  # newest first
    once(rows, "kill_switch.on", name)
    once(rows, "kill_switch.off", name)
    decided = once(rows, "approval.decided", paused["run_id"])
    assert decided["after"]["decision"] == "reject"
    mine = [added, changed, updated, decided, *default, *tools, *sharing]
    assert all(r["actor"] == "local" and r["request_id"] for r in mine)  # through the API

    # No key anywhere in the trail (the fingerprint only), here or in the download.
    everything = json.dumps(rows)
    assert KEY not in everything
    download = await api.c.get("/audit.csv", params={"action": "model_connection.added"})
    assert download.headers["content-disposition"].endswith('filename="nuria-audit.csv"')
    table = list(csv.DictReader(io.StringIO(download.text)))
    assert any(r["target_id"] == conn["name"] for r in table) and KEY not in download.text


async def test_a_change_that_fails_writes_no_row(api: Api) -> None:
    tag = uuid.uuid4().hex[:6]
    agent = await api.ok("POST", "/studio/agents", json={"display_name": f"Untested {tag}"})
    blocked = await api.c.post(f"/studio/agents/{agent['id']}/publish", json={})
    assert blocked.status_code == 409  # never tested: can't publish
    await api.ok("POST", "/skills", json={"name": f"dup-{tag}", "description": "D. Use when.",
                                          "instructions": "x"})  # fmt: skip
    dup = await api.c.post("/skills", json={"name": f"dup-{tag}", "description": "D. Use when.",
                                            "instructions": "y"})  # fmt: skip
    assert dup.status_code == 409
    keyless = await api.c.put("/tools/settings", json={"search_provider": "brave"})
    assert keyless.status_code == 422

    rows = await api.rows()
    assert not [
        r for r in rows if r["action"] == "agent.published" and r["target_id"] == agent["name"]
    ]
    assert len([r for r in rows if r["target_id"] == f"dup-{tag}"]) == 1  # the first one only
    assert not [r for r in rows if r["action"] == "tool_settings.changed"
                and (r["after"] or {}).get("search_provider") == "brave"]  # fmt: skip


@pytest.fixture
async def as_api(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> AsyncIterator[Pool]:
    for component in ("api", "worker"):
        if component_credentials(component) is None:
            pytest.fail(f"{component.upper()}_POSTGRES_USER/PASSWORD not set (see .env.example)")
    async with pool.connection() as conn:
        await provision_users(conn)
        await grant_checkpoint_tables(conn)
    async with create_pool(test_settings.for_component("api"), max_size=2) as p:
        yield p


async def test_the_api_can_add_to_the_trail_but_never_change_it(as_api: Pool) -> None:
    async with as_api.connection() as conn:
        await conn.execute(
            "INSERT INTO audit_events (id, actor, action, target_type) VALUES (%s, 'local', "
            "'kill_switch.on', 'agent')", (uuid.uuid4(),),
        )  # fmt: skip
    for statement in ("UPDATE audit_events SET actor = 'someone'", "DELETE FROM audit_events",
                      "TRUNCATE audit_events"):  # fmt: skip
        async with as_api.connection() as conn:
            with pytest.raises(errors.InsufficientPrivilege):
                await conn.execute(statement)


async def test_a_reply_is_rated_changed_and_taken_back(api: Api) -> None:
    tag = uuid.uuid4().hex[:6]
    agent = await api.ok("POST", "/studio/agents", json={"display_name": f"Rated {tag}",
                                                         "copy_of": "chat"})  # fmt: skip
    chat = await api.ok("POST", f"/studio/agents/{agent['id']}/test-chat")
    sent = await api.ok("POST", f"/sessions/{chat['id']}/messages",
                        json={"content": "hi", "script": [{"content": "hello"}]})  # fmt: skip
    await api.run(sent["run_id"])
    await api.ok("POST", f"/studio/agents/{agent['id']}/publish", json={})
    sid = (await api.ok("POST", "/sessions", json={"agent": agent["name"]}))["id"]
    runs = []
    for _ in range(3):
        r = await api.ok("POST", f"/sessions/{sid}/messages",
                         json={"content": "q", "script": [{"content": "a"}]})  # fmt: skip
        await api.run(r["run_id"])
        runs.append(r["run_id"])

    url = f"/runs/{runs[0]}/feedback"
    assert (await api.c.get(url)).json() is None
    up = await api.ok("PUT", url, json={"rating": "up"})
    assert (up["rating"], up["agent"], up["agent_version"]) == ("up", agent["name"], 1)
    changed = await api.ok("PUT", url, json={"rating": "down", "reason": "  too long  "})
    assert (changed["rating"], changed["reason"]) == ("down", "too long")
    await api.ok("PUT", f"/runs/{runs[1]}/feedback", json={"rating": "up"})
    await api.ok("PUT", f"/runs/{runs[2]}/feedback", json={"rating": "up"})
    await api.ok("DELETE", f"/runs/{runs[2]}/feedback")

    view = await api.ok("GET", "/activity", params={"range": "24h", "agent": agent["name"]})
    (row,) = view["agents"]
    assert (row["liked"], row["disliked"]) == (1, 1)
    turns = await api.ok("GET", "/activity/turns", params={"range": "24h", "session_id": sid})
    assert sorted((t["rating"] for t in turns), key=str) == sorted([-1, 1, None], key=str)

    assert (
        await api.c.put(f"/runs/{uuid.uuid4()}/feedback", json={"rating": "up"})
    ).status_code == 404
    assert (await api.c.put(url, json={"rating": "meh"})).status_code == 422
    assert (await api.c.put(url, json={"rating": "up", "reason": "x" * 501})).status_code == 422


async def test_an_approval_is_one_policy_decision_even_after_the_resume(api: Api) -> None:
    """L4a's double count: the node runs again after the decision; the event is once."""
    sid = (await api.ok("POST", "/sessions", json={"agent": "chat"}))["id"]
    notify = {"tool_calls": [{"name": "notify", "args": {"to": "ops", "message": "hi"}}]}
    body = {"content": "tell ops", "script": [notify, {"content": "Sent."}]}
    sent = await api.ok("POST", f"/sessions/{sid}/messages", json=body)
    await api.run(sent["run_id"])
    await api.ok("POST", f"/sessions/{sid}/approve", json={"decision": "approve"})
    await api.run(sent["run_id"])
    async with api.pool.connection() as conn:
        cur = await conn.execute(
            "SELECT count(*) AS n FROM run_events WHERE run_id = %s AND type = 'policy.decision'",
            (uuid.UUID(sent["run_id"]),),
        )
        row = await cur.fetchone()
    assert row is not None and row["n"] == 1

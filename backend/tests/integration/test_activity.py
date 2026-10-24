"""The Activity page's numbers (L7 SC3): each one equals a query over the raw tables, for
turns this test makes (an agent of its own, so other tests' turns don't count)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from agent_runtime.api.app import create_app
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import GraphRegistry
from agent_runtime.queue import InMemoryWorkQueue
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.streaming.bus import InMemoryEventBus

pytestmark = pytest.mark.integration


class Api:
    """The API in-process, and a way to run a turn it queued (no workers here)."""

    def __init__(self, client: httpx.AsyncClient, graphs: GraphRegistry, pool: Pool,
                 settings: Settings) -> None:  # fmt: skip
        self.c, self._graphs, self._pool, self._settings = client, graphs, pool, settings

    async def turn(
        self, sid: str, script: list[dict[str, Any]], options: dict[str, Any] | None = None
    ) -> str:
        sent = await self.c.post(f"/sessions/{sid}/messages",
                                 json={"content": "go", "script": script,
                                       "options": options or {}})  # fmt: skip
        run_id = str(sent.json()["run_id"])
        await RunExecutor(self._pool, self._settings, self._graphs).execute(uuid.UUID(run_id))
        return run_id

    async def published_agent(self) -> str:
        """A copy of Nuria, tested and published: turns of its own, by name."""
        display = f"Act {uuid.uuid4().hex[:6]}"
        agent = (await self.c.post("/studio/agents", json={"display_name": display,
                                                           "copy_of": "chat"})).json()  # fmt: skip
        chat = (await self.c.post(f"/studio/agents/{agent['id']}/test-chat")).json()
        await self.turn(chat["id"], [{"content": "hello"}])  # a test chat (left out below)
        published = await self.c.post(f"/studio/agents/{agent['id']}/publish", json={})
        assert published.status_code == 200, published.text
        return str(agent["name"])


@pytest.fixture
async def api(pool: Pool, test_settings: Settings, checkpoint_tables: None) -> AsyncIterator[Api]:
    app = create_app(test_settings, pool=pool, queue=InMemoryWorkQueue(), bus=InMemoryEventBus())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        yield Api(c, app.state.graphs, pool, test_settings)


async def test_activity_tells_the_truth(api: Api, pool: Pool) -> None:
    c = api.c
    name = await api.published_agent()

    sid = (await c.post("/sessions", json={"agent": name})).json()["id"]
    note = {"tool_calls": [{"name": "save_note", "args": {"text": "x"}}]}
    await api.turn(sid, [note, {"content": "saved"}])
    await api.turn(sid, [{"content": "plain"}])
    failed = await api.turn(sid, [note, note, {"content": "never"}], {"max_tool_calls": 1})

    view = (await c.get("/activity", params={"range": "24h", "agent": name})).json()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT count(*) AS n, count(*) FILTER (WHERE status = 'failed') AS failed, "
            "sum(tokens) AS tokens, sum(cost) AS cost, sum(tool_calls_total) AS tools "
            "FROM runs WHERE kind = 'turn' AND agent_name = %s AND session_id = %s",
            (name, uuid.UUID(sid)),
        )
        raw = await cur.fetchone()
        assert raw is not None
        cur = await conn.execute(
            "SELECT model, sum(calls) AS calls, sum(tokens_in + tokens_out) AS tokens "
            "FROM run_model_usage u JOIN runs r ON r.id = u.run_id "
            "WHERE r.agent_name = %s AND r.session_id = %s GROUP BY model",
            (name, uuid.UUID(sid)),
        )
        per_model = {r["model"]: r for r in await cur.fetchall()}

    totals = view["totals"]
    assert (totals["turns"], totals["failed"]) == (raw["n"], raw["failed"]) == (3, 1)
    assert totals["tokens"] == raw["tokens"] and Decimal(str(totals["cost"])) == raw["cost"]
    assert totals["tool_calls"] == raw["tools"]
    assert sum(d["turns"] for d in view["days"]) == 3
    days = [date.fromisoformat(d["day"]) for d in view["days"]]  # every day, empty ones too
    today = datetime.now(UTC).date()
    assert days == [today - timedelta(days=1), today]
    (agent_row,) = view["agents"]
    assert (agent_row["agent"], agent_row["turns"], agent_row["failed"]) == (name, 3, 1)
    models = {m["model"]: m for m in view["models"]}
    assert set(models) == set(per_model)
    for model, row in per_model.items():
        assert models[model]["calls"] == row["calls"]
        assert models[model]["tokens_in"] + models[model]["tokens_out"] == row["tokens"]
    assert sum(m["tokens_in"] + m["tokens_out"] for m in models.values()) == raw["tokens"]
    tools = {t["tool"]: t for t in view["tools"]}
    assert tools["save_note"]["calls"] >= 2
    (error,) = view["errors"]
    assert (error["reason"], error["count"], error["run_id"]) == ("budget:tool_calls", 1, failed)

    # Test chats are left out unless asked for; the lists agree with the totals.
    with_tests = (await c.get("/activity", params={"range": "24h", "agent": name,
                                                   "include_tests": True})).json()  # fmt: skip
    assert with_tests["totals"]["turns"] == 4
    listed = (await c.get("/activity/turns", params={"range": "24h", "agent": name})).json()
    assert len(listed) == 3 and listed[0]["id"] == failed  # newest first
    assert all(t["models"] for t in listed if t["status"] == "completed")
    detail = (await c.get(f"/activity/turns/{listed[1]['id']}")).json()
    assert sum(u["calls"] for u in detail["usage"]) == detail["model_calls"]
    chats = (await c.get("/activity/sessions", params={"range": "24h", "agent": name})).json()
    assert [(s["id"], s["turns"], s["failed"]) for s in chats] == [(sid, 3, 1)]
    assert (await c.get(f"/activity/turns/{uuid.uuid4()}")).status_code == 404
    assert (await c.get("/activity", params={"range": "1y"})).status_code == 422

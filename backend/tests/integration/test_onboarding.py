"""Getting started (L3d.1, SC3, SC4): every step ticks on the real thing, and only then.

Progress is derived from the account: a step done anywhere ticks; undone, it un-ticks;
only the guide's own choices (its agent, "demo for now", dismissed) are stored.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest

from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.runs.state import RunStatus as S
from tests.integration.test_models import KEY_A, Fake, Seen, api, bus, connect, fake, run
from tests.integration.test_stream import Server

pytestmark = pytest.mark.integration
__all__ = ["api", "bus", "fake"]  # fixtures, imported for pytest
HELLO: list[dict[str, Any]] = [{"content": "hello"}]


@pytest.fixture
async def guide(api: Server) -> AsyncIterator[Any]:
    """Start the guide fresh for one test, and leave it fresh (the DB is shared)."""
    await api.client.put("/onboarding", json={"restart": True})
    await api.client.put("/models/default", json={"connection_id": None})

    async def state() -> dict[str, Any]:
        result: dict[str, Any] = (await api.client.get("/onboarding")).json()
        return result

    yield state
    await api.client.put("/onboarding", json={"restart": True})
    await api.client.put("/models/default", json={"connection_id": None})


def steps(state: dict[str, Any]) -> dict[str, str]:
    return {s["key"]: "done" if s["done"] else "skipped" if s["skipped"] else "todo"
            for s in state["steps"]}  # fmt: skip


async def test_every_step_ticks_on_the_real_thing(
    api: Server, fake: Fake, pool: Pool, test_settings: Settings, guide: Any
) -> None:
    c = api.client
    start = await guide()
    assert steps(start) == dict.fromkeys(["model", "agent", "tool", "helper", "try"], "todo")
    assert (start["next"], start["finished"], start["agent"]) == ("model", False, None)

    # 1: a model that passed its test, made the default.
    model = await connect(Seen(c), fake, f"Guide {uuid.uuid4().hex[:6]}", KEY_A, "fake-a")
    assert steps(await guide())["model"] == "todo"  # ready, but not what agents use yet
    await c.put("/models/default", json={"connection_id": model["id"], "model": "fake-a"})
    assert (await guide())["next"] == "agent"

    # 2: an agent made in the guide.
    created = await c.post("/studio/agents?guide=true", json={"display_name": "Guide pal"})
    agent = created.json()
    state = await guide()
    assert state["agent"]["id"] == agent["id"] and state["next"] == "tool"

    # 3 and 4: a tool, a helper (on its draft).
    doc = agent["draft"]["document"] | {"description": "Helps.", "instructions": "Help."}
    await c.put(f"/studio/agents/{agent['id']}/draft",
                json=doc | {"tools": [{"name": "calculator"}]})  # fmt: skip
    assert (await guide())["next"] == "helper"
    helper = {"name": "scout", "description": "Scouts.", "instructions": "Scout."}
    await c.put(f"/studio/agents/{agent['id']}/draft",
                json=doc | {"tools": [{"name": "calculator"}], "helpers": [helper]})  # fmt: skip
    state = await guide()
    assert state["next"] == "try" and state["tried"] == {
        "tested": False, "published": False, "chatted": False}  # fmt: skip

    # 5: tested, published, a first real chat.
    chat = (await c.post(f"/studio/agents/{agent['id']}/test-chat")).json()
    sent = await c.post(f"/sessions/{chat['id']}/messages", json={"content": "hi", "script": HELLO})
    assert (await run(pool, test_settings, sent.json()["run_id"])).status is S.COMPLETED
    assert (await guide())["tried"]["tested"] is True
    assert (await c.post(f"/studio/agents/{agent['id']}/publish", json={})).status_code == 200
    session = (await c.post("/sessions", json={"agent": agent["name"]})).json()
    turn = await c.post(f"/sessions/{session['id']}/messages",
                        json={"content": "hi", "script": HELLO})  # fmt: skip
    assert (await run(pool, test_settings, turn.json()["run_id"])).status is S.COMPLETED
    done = await guide()
    assert done["finished"] is True and done["next"] is None
    assert set(steps(done).values()) == {"done"}


async def test_progress_follows_the_facts_both_ways(api: Server, guide: Any) -> None:
    c = api.client
    agent = (await c.post("/studio/agents?guide=true", json={"display_name": "Undo me"})).json()
    doc = agent["draft"]["document"] | {"description": "d", "instructions": "i",
                                        "helpers": [{"name": "h", "description": "d",
                                                     "instructions": "i"}]}  # fmt: skip
    await c.put(f"/studio/agents/{agent['id']}/draft", json=doc)
    assert steps(await guide())["helper"] == "done"
    await c.put(f"/studio/agents/{agent['id']}/draft", json=doc | {"helpers": []})
    assert steps(await guide())["helper"] == "todo"  # removed: un-ticked
    await c.post(f"/studio/agents/{agent['id']}/archive")
    state = await guide()
    assert state["agent"] is None and state["next"] == "model"  # archived: ask again


async def test_demo_for_now_skips_and_choices_are_remembered(api: Server, guide: Any) -> None:
    c = api.client
    skipped = (await c.put("/onboarding", json={"skip_model": True})).json()
    assert steps(skipped)["model"] == "skipped" and skipped["next"] == "agent"
    other = (await c.post("/studio/agents", json={"display_name": "Not the guide's"})).json()
    assert (await guide())["agent"] is None  # made outside the guide: not adopted
    picked = (await c.put("/onboarding", json={"agent_id": other["id"]})).json()
    assert picked["agent"]["name"] == other["name"]  # or chosen explicitly
    hidden = (await c.put("/onboarding", json={"dismissed": True})).json()
    assert hidden["dismissed"] is True
    fresh = (await c.put("/onboarding", json={"restart": True})).json()
    assert (fresh["dismissed"], fresh["agent"], steps(fresh)["model"]) == (False, None, "todo")

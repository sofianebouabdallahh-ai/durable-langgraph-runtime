"""Describe it, improve it (L3c.6, SC7, SC8; R17.3).

The builder agents run as ordinary runs; their answer is a proposal checked by the
one validator; nothing is saved until the person accepts it. Offline (the demo
model) and with a real tool-calling model (the fake), including a repair round, and
a model that never proposes.
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


@pytest.fixture
async def default_model(api: Server) -> AsyncIterator[Any]:
    """Set the default model for one test, and always put it back (the DB is shared)."""

    async def use(connection_id: str, model: str) -> None:
        response = await api.client.put(
            "/models/default", json={"connection_id": connection_id, "model": model}
        )
        assert response.status_code == 200, response.text

    yield use
    await api.client.put("/models/default", json={"connection_id": None})


async def assisted(c: Any, pool: Pool, settings: Settings, started: Any) -> dict[str, Any]:
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]
    working = (await c.get(f"/studio/assist/{run_id}")).json()
    assert working["status"] == "working" and working["proposal"] is None
    await run(pool, settings, run_id)
    result: dict[str, Any] = (await c.get(f"/studio/assist/{run_id}")).json()
    return result


async def test_describe_it_offline_then_accept(
    api: Server, pool: Pool, test_settings: Settings
) -> None:
    c = api.client
    before = len((await c.get("/studio/agents")).json())
    started = await c.post("/studio/describe", json={"description": (
        "Plan trips for my family: search for places, work out the budget, "
        "and a helper that finds kid-friendly restaurants."
    )})  # fmt: skip
    done = await assisted(c, pool, test_settings, started)
    assert (done["status"], done["kind"]) == ("done", "draft")
    proposal = done["proposal"]
    assert set(proposal["tools"]) == {"web_search", "read_webpage"}  # reads what it finds
    assert [h["display_name"] for h in proposal["helpers"]] == ["Kid-Friendly Restaurants"]
    assert proposal["skills"] == ["trip-planning"]  # a built-in that fits
    assert len((await c.get("/studio/agents")).json()) == before  # nothing saved yet

    created = await c.post("/studio/agents/from-proposal", json=proposal)
    assert created.status_code == 201, created.text
    agent = created.json()
    assert agent["draft"]["issues"] == [] and agent["draft"]["tested"] is False
    document = agent["draft"]["document"]
    assert [t["name"] for t in document["tools"]] == ["web_search", "read_webpage"]
    assert document["skills"] == ["trip-planning"]
    assert document["helpers"][0]["name"] == "kid-friendly-restaurants"
    assert document["hooks"]["pre_tool"] == ["redact_secrets_in_args"]  # default protections


async def test_describe_it_with_a_model_that_repairs_its_draft(
    api: Server, fake: Fake, pool: Pool, test_settings: Settings, default_model: Any
) -> None:
    c = Seen(api.client)
    model = await connect(c, fake, f"Builder {uuid.uuid4().hex[:6]}", KEY_A, "fake-sloppy")
    await default_model(model["id"], "fake-sloppy")
    await fake.clear()
    started = await api.client.post("/studio/describe", json={"description": "A research helper."})
    done = await assisted(api.client, pool, test_settings, started)
    assert done["status"] == "done", done
    assert done["proposal"]["tools"] == ["web_search", "read_webpage"]  # "teleport" left out
    assert done["repairs"] == [
        "Left out “teleport”: there's no such tool here.",
        "Added “read_webpage”: with “web_search” it reads the pages it relies on, not just "
        "their snippets.",
    ]
    assert "{{secret}}" not in done["proposal"]["instructions"]  # the model fixed that
    proposals = [call for call in await fake.calls() if "propose_draft" in call["tools"]]
    assert [call["last"] for call in proposals] == ["user", "tool", "tool"]  # draft, fix, done
    run_id = started.json()["run_id"]
    events = (await api.client.get(f"/runs/{run_id}/events", params={"limit": 500})).json()
    completed = [e["payload"] for e in events["events"] if e["type"] == "tool.completed"]
    assert [p["status"] for p in completed] == ["failed", "done"]  # refused, then accepted


async def test_improve_my_instructions_suggests_and_saves_nothing(
    api: Server, pool: Pool, test_settings: Settings
) -> None:
    c = api.client
    agent = (
        await c.post("/studio/agents", json={"display_name": f"Coach {uuid.uuid4().hex[:6]}"})
    ).json()
    doc = agent["draft"]["document"] | {"description": "Answers questions.",
                                        "instructions": "You answer questions."}  # fmt: skip
    await c.put(f"/studio/agents/{agent['id']}/draft", json=doc)
    done = await assisted(
        c, pool, test_settings, await c.post(f"/studio/agents/{agent['id']}/improve")
    )
    assert (done["status"], done["kind"]) == ("done", "instructions")
    suggestion = done["proposal"]
    assert suggestion["instructions"].startswith("You answer questions.")
    assert "{{date}}" in suggestion["instructions"] and suggestion["what_changed"]
    after = (await c.get(f"/studio/agents/{agent['id']}")).json()
    assert after["draft"]["document"]["instructions"] == "You answer questions."  # unchanged


async def test_a_model_that_never_proposes_gets_a_plain_answer(
    api: Server, fake: Fake, pool: Pool, test_settings: Settings, default_model: Any
) -> None:
    c = Seen(api.client)
    added = await c("POST", "/models/connections", json={
        "display_name": f"Chatty {uuid.uuid4().hex[:6]}", "kind": "compatible",
        "base_url": f"{fake.url}/v1", "models": ["fake-notools"],
    })  # fmt: skip
    await default_model(added.json()["id"], "fake-notools")
    started = await api.client.post("/studio/describe", json={"description": "A trip planner."})
    done = await assisted(api.client, pool, test_settings, started)
    assert done["status"] == "failed" and "didn't come up with a proposal" in done["problem"]


async def test_only_builder_runs_are_assists(
    api: Server, pool: Pool, test_settings: Settings
) -> None:
    session = (await api.client.post("/sessions", json={"agent": "chat"})).json()
    sent = await api.client.post(f"/sessions/{session['id']}/messages", json={"content": "hi"})
    run_id = sent.json()["run_id"]
    assert (await run(pool, test_settings, run_id)).status is S.COMPLETED
    assert (await api.client.get(f"/studio/assist/{run_id}")).status_code == 404
    assert (await api.client.get(f"/studio/assist/{uuid.uuid4()}")).status_code == 404

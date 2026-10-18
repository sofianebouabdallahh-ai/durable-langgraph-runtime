"""Skills in a real turn (L3c.5, SC3), against the fake OpenAI-compatible model.

The main agent and its helper each load their own skill when the turn needs it;
the body arrives through `load_skill`, marked as data, and appears in the transcript
as the tool's result; the helper never sees the main agent's skill.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.runs.state import RunStatus as S
from tests.integration.test_models import KEY_A, Fake, Seen, api, bus, connect, fake, run
from tests.integration.test_stream import Server

pytestmark = pytest.mark.integration
__all__ = ["api", "bus", "fake"]  # fixtures, imported for pytest


async def skill(c: Seen, name: str, text: str, files: dict[str, str] | None = None) -> None:
    body = {"name": name, "description": f"{name}: use when planning.", "instructions": text,
            "files": files or {}}  # fmt: skip
    response = await c("POST", "/skills", json=body)
    assert response.status_code == 201, response.text


async def test_each_agent_loads_its_own_skill_when_needed(
    api: Server, fake: Fake, pool: Pool, test_settings: Settings
) -> None:
    c, tag = Seen(api.client), uuid.uuid4().hex[:6]
    model = await connect(c, fake, f"Skills {tag}", KEY_A, "fake-a")
    tips, maps = f"tips-{tag}", f"maps-{tag}"
    await skill(c, tips, "Check the ferry timetable first.", {"references/ferries.md": "08:00"})
    await skill(c, maps, "Use the metro map.")
    agent = (await c("POST", "/studio/agents", json={"display_name": f"Skilled {tag}"})).json()
    doc: dict[str, Any] = {
        "name": agent["name"], "description": "Plans.", "instructions": "Plan.",
        "model": f"{model['name']}:fake-a", "skills": [tips],
        "helpers": [{"name": "scout", "description": "Scouts.", "instructions": "Scout.",
                     "model": f"{model['name']}:fake-b", "skills": [maps]}],
    }  # fmt: skip
    saved = (await c("PUT", f"/studio/agents/{agent['id']}/draft", json=doc)).json()
    assert saved["draft"]["issues"] == []

    chat = (await c("POST", f"/studio/agents/{agent['id']}/test-chat")).json()
    await fake.clear()
    sent = (await c("POST", f"/sessions/{chat['id']}/messages", json={"content": "go"})).json()
    done = await run(pool, test_settings, sent["run_id"])
    assert done.status is S.COMPLETED, done.reason

    served = await fake.calls()
    assert all("load_skill" in call["tools"] for call in served)  # both have skills
    msgs = (await c("GET", f"/sessions/{chat['id']}/messages")).json()["messages"]
    calls = [m["content"] for m in msgs if m["type"] == "tool_call"]
    results = {m["content"]["tool"]: m["content"] for m in msgs if m["type"] == "tool_result"}
    assert (calls[0]["tool"], calls[0]["args"]) == ("load_skill", {"name": tips})  # first
    loaded = results["load_skill"]["result"]  # people see the result, not the marking
    assert loaded["instructions"] == "Check the ferry timetable first."
    assert loaded["files"] == ["references/ferries.md"]
    waited = str(results["wait_subagents"]["result"])
    assert f"Used skill {maps}" in waited  # the helper loaded its own
    assert msgs[-1]["content"]["text"] == f"Done. Answered by fake-a. Used skill {tips}."

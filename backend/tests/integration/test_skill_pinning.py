"""Skill versions are pinned (L3c.4, SC6; R17.4 with R15.4 and AC47).

A draft follows the library (editing a skill makes it untested); publishing locks
the versions (editing or archiving a skill never changes a published agent); a
queued turn keeps the versions it was created with; a missing skill is a plain
issue on the form and blocks publishing.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest

from agent_runtime.agents.store import load_bundle
from agent_runtime.api.app import create_app
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.queue import RedisWorkQueue
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.streaming.bus import RedisEventBus
from tests.integration.test_stream import Server

pytestmark = pytest.mark.integration
GRAPHS = default_registry()
HELLO: list[dict[str, Any]] = [{"content": "hello"}]


@pytest.fixture
async def api(
    pool: Pool, test_settings: Settings, queue: RedisWorkQueue, checkpoint_tables: None
) -> AsyncIterator[Server]:
    app = create_app(test_settings, pool=pool, queue=queue, bus=RedisEventBus(queue._r))
    async with Server(app) as server:
        yield server


async def run(pool: Pool, settings: Settings, run_id: str) -> Any:
    return await RunExecutor(pool, settings, GRAPHS).execute(uuid.UUID(run_id))


async def skill(c: Any, name: str, text: str) -> dict[str, Any]:
    response = await c.post("/skills", json={
        "name": name, "description": f"{name}. Use when testing.", "instructions": text,
    })  # fmt: skip
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()["skill"]
    return result


def document(name: str, main_skills: list[str], helper_skills: list[str]) -> dict[str, Any]:
    return {
        "name": name, "description": "Plans trips.", "instructions": "Plan trips.",
        "max_turns": 10, "limits": {"max_tool_calls": 10, "timeout_s": 120},
        "skills": main_skills,
        "helpers": [{"name": "scout", "description": "Finds places.",
                     "instructions": "Find places.", "skills": helper_skills}],
    }  # fmt: skip


async def chat_once(c: Any, pool: Pool, settings: Settings, aid: str) -> str:
    """One completed test-chat turn on the draft; returns its run id."""
    chat = (await c.post(f"/studio/agents/{aid}/test-chat")).json()
    sent = await c.post(f"/sessions/{chat['id']}/messages", json={"content": "hi", "script": HELLO})
    assert sent.status_code == 202, sent.text
    assert (await run(pool, settings, sent.json()["run_id"])).status is S.COMPLETED
    run_id: str = sent.json()["run_id"]
    return run_id


async def pinned(pool: Pool, c: Any, run_id: str) -> dict[str, list[str]]:
    """Owner → the skill version hashes the run's bundle pinned."""
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT agent_hash FROM runs WHERE id = %s", (run_id,))
        row = await cur.fetchone()
        assert row is not None
        bundle = await load_bundle(conn, row["agent_hash"])
    return {owner: [v.hash for v in versions] for owner, versions in bundle.skills.items()}


async def test_drafts_follow_the_library_and_publishing_locks_it(
    api: Server, pool: Pool, test_settings: Settings
) -> None:
    c, tag = api.client, uuid.uuid4().hex[:6]
    tips = await skill(c, f"tips-{tag}", "Tip one.")
    maps = await skill(c, f"maps-{tag}", "Read maps.")
    aid = (await c.post("/studio/agents", json={"display_name": f"Pin {tag}"})).json()["id"]
    name = (await c.get(f"/studio/agents/{aid}")).json()["name"]
    saved = await c.put(f"/studio/agents/{aid}/draft",
                        json=document(name, [tips["name"]], [maps["name"]]))  # fmt: skip
    assert saved.json()["draft"]["issues"] == []

    first = await chat_once(c, pool, test_settings, aid)
    assert await pinned(pool, c, first) == {"": [tips["version"]], "scout": [maps["version"]]}
    assert (await c.get(f"/studio/agents/{aid}")).json()["draft"]["tested"] is True

    edited = (await c.patch(f"/skills/{tips['id']}", json={"instructions": "Tip two."})).json()
    v2 = edited["skill"]["version"]
    state = (await c.get(f"/studio/agents/{aid}")).json()
    assert state["draft"]["tested"] is False  # the draft runs today's skills: test again
    assert (await c.post(f"/studio/agents/{aid}/publish", json={})).status_code == 409

    second = await chat_once(c, pool, test_settings, aid)
    assert (await pinned(pool, c, second))[""] == [v2]
    published = await c.post(f"/studio/agents/{aid}/publish", json={})
    assert published.status_code == 200, published.text

    # Edited and archived afterwards: the published agent keeps what it locked.
    await c.patch(f"/skills/{tips['id']}", json={"instructions": "Tip three."})
    assert (await c.delete(f"/skills/{maps['id']}")).status_code == 204
    session = (await c.post("/sessions", json={"agent": name})).json()
    turn = (await c.post(f"/sessions/{session['id']}/messages",
                         json={"content": "hi", "script": HELLO})).json()  # fmt: skip
    assert await pinned(pool, c, turn["run_id"]) == {"": [v2], "scout": [maps["version"]]}
    assert (await run(pool, test_settings, turn["run_id"])).status is S.COMPLETED


async def test_a_queued_turn_keeps_its_skill_versions(
    api: Server, pool: Pool, test_settings: Settings
) -> None:
    c, tag = api.client, uuid.uuid4().hex[:6]
    tips = await skill(c, f"tips-{tag}", "Tip one.")
    aid = (await c.post("/studio/agents", json={"display_name": f"Queue {tag}"})).json()["id"]
    name = (await c.get(f"/studio/agents/{aid}")).json()["name"]
    await c.put(f"/studio/agents/{aid}/draft", json=document(name, [tips["name"]], []))
    chat = (await c.post(f"/studio/agents/{aid}/test-chat")).json()
    queued = (await c.post(f"/sessions/{chat['id']}/messages",
                           json={"content": "hi", "script": HELLO})).json()  # fmt: skip
    await c.patch(f"/skills/{tips['id']}", json={"instructions": "Tip two."})  # meanwhile
    assert (await run(pool, test_settings, queued["run_id"])).status is S.COMPLETED
    assert await pinned(pool, c, queued["run_id"]) == {"": [tips["version"]]}


async def test_a_missing_skill_is_an_issue_and_blocks_publishing(api: Server) -> None:
    c, tag = api.client, uuid.uuid4().hex[:6]
    aid = (await c.post("/studio/agents", json={"display_name": f"Missing {tag}"})).json()["id"]
    name = (await c.get(f"/studio/agents/{aid}")).json()["name"]
    saved = (await c.put(f"/studio/agents/{aid}/draft",
                         json=document(name, [], ["no-such-skill"]))).json()  # fmt: skip
    issues = saved["draft"]["issues"]
    assert [(i["where"], i["field"]) for i in issues] == [("helpers.scout", "skills")]
    assert "no skill called “no-such-skill”" in issues[0]["message"]
    assert (await c.post(f"/studio/agents/{aid}/publish", json={})).status_code == 409
    chat = (await c.post(f"/studio/agents/{aid}/test-chat")).json()
    sent = await c.post(f"/sessions/{chat['id']}/messages", json={"content": "hi"})
    assert sent.status_code == 409 and "Skills page" in sent.json()["detail"]


async def test_export_and_import_carry_the_skills(api: Server) -> None:
    """SC9: an agent's zip carries its skills in the standard format; importing it reuses
    identical skills, adds new ones (scanned), and refuses a clash."""
    import io
    import zipfile

    c, tag = api.client, uuid.uuid4().hex[:6]
    tips = await skill(c, f"tips-{tag}", "Tip one.")
    aid = (await c.post("/studio/agents", json={"display_name": f"Carry {tag}"})).json()["id"]
    name = (await c.get(f"/studio/agents/{aid}")).json()["name"]
    await c.put(f"/studio/agents/{aid}/draft", json=document(name, [tips["name"]], []))
    exported = await c.get(f"/studio/agents/{aid}/export")
    assert exported.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(exported.content)).namelist()
    assert f"{name}/skills/{tips['name']}/SKILL.md" in names

    again = await c.post(f"/studio/import?filename={name}.zip", content=exported.content)
    assert again.status_code == 201, again.text
    copy = again.json()
    assert copy["draft"]["issues"] == [] and copy["draft"]["document"]["skills"] == [tips["name"]]
    library = [s for s in (await c.get("/skills")).json() if s["name"] == tips["name"]]
    assert [s["version"] for s in library] == [tips["version"]]  # reused, not duplicated

    # The same zip with the skill renamed: a new skill in the library, marked imported.
    fresh = f"fresh-{tag}"
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(exported.content)) as src, zipfile.ZipFile(buffer, "w") as out:
        for item in src.infolist():
            data = src.read(item)
            path = item.filename.replace(tips["name"], fresh)
            out.writestr(path, data.replace(tips["name"].encode(), fresh.encode()))
    added = await c.post(f"/studio/import?filename={name}.zip", content=buffer.getvalue())
    assert added.status_code == 201, added.text
    imported = {s["name"]: s for s in (await c.get("/skills")).json()}[fresh]
    assert imported["origin"] == "imported" and imported["scan"]["status"] == "clean"

    # Edit the library's skill: the original zip now clashes, and nothing is created.
    await c.patch(f"/skills/{tips['id']}", json={"instructions": "Tip two."})
    before = len((await c.get("/studio/agents")).json())
    clash = await c.post(f"/studio/import?filename={name}.zip", content=exported.content)
    assert clash.status_code == 422 and "already has a different skill" in clash.text
    assert len((await c.get("/studio/agents")).json()) == before

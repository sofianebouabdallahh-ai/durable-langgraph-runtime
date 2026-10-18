"""Turns pin their agent by hash (CR-004 R15.4, phase L3a): a worker builds the agent
from the snapshot the turn was created with, whatever the files say by then."""

import shutil
from pathlib import Path
from typing import Any

import pytest

from agent_runtime.agents.loader import Ceilings, load_agents
from agent_runtime.agents.store import load_bundle
from agent_runtime.catalog import default_catalog
from agent_runtime.config import Settings, get_agent_settings
from agent_runtime.db import Pool
from agent_runtime.graphs import GraphRegistry, default_registry
from agent_runtime.graphs.assistant import agent_spec
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.sessions.service import SessionService
from agent_runtime.sessions.store import SessionRepository
from agent_runtime.tools.builtin import default_tools

pytestmark = pytest.mark.integration
AGENTS = Path(__file__).resolve().parents[2] / "agents"
CALC: list[dict[str, Any]] = [
    {"tool_calls": [{"name": "calculator", "args": {"expression": "6*7"}}]},
    {"content": "42"},
]


def edited_registry(tmp_path: Path) -> GraphRegistry:
    """The built-in agents as they'd be after a deploy that removed chat's calculator."""
    root = tmp_path / "agents"
    shutil.copytree(AGENTS, root)
    path = root / "chat" / "agent.md"
    path.write_text(path.read_text().replace("  - calculator\n", ""))
    settings = get_agent_settings()
    agents = load_agents(root, default_catalog(), Ceilings.from_settings(settings))
    assert "calculator" not in [t.name for t in agents.get("chat").frontmatter.tools]
    return GraphRegistry([agent_spec(a, default_tools()) for a in agents])


async def test_a_queued_turn_runs_the_definition_it_was_created_with(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, tmp_path: Path
) -> None:
    graphs = default_registry()
    sessions = SessionService(pool, test_settings, graphs, RunService(pool, test_settings, graphs))
    sid = (await sessions.create("chat")).id
    turn = await sessions.send(sid, "6*7?", script=CALC)
    assert turn.run.agent_hash is not None
    async with pool.connection() as conn:  # the snapshot is the whole team
        pinned = (await load_bundle(conn, turn.run.agent_hash)).definition
    original = graphs.get("chat").agent
    assert original is not None
    assert pinned == original  # rebuilt from the snapshot: identical, helpers in order

    # A new deploy: chat lost its calculator. The queued turn still has it.
    after_deploy = edited_registry(tmp_path)
    done = await RunExecutor(pool, test_settings, after_deploy).execute(turn.run.id)
    assert done.status is S.COMPLETED
    async with pool.connection() as conn:
        msgs = await SessionRepository(conn).messages(sid, limit=100)
    result = next(m for m in msgs if m.type == "tool_result")
    assert result.content["result"] == {"value": 42.0}

    # The next turn is created by the new deploy: it pins the new definition.
    sessions_v2 = SessionService(pool, test_settings, after_deploy,
                                 RunService(pool, test_settings, after_deploy))  # fmt: skip
    nxt = await sessions_v2.send(sid, "again?", script=CALC)
    assert nxt.run.agent_hash not in (None, turn.run.agent_hash)
    await RunExecutor(pool, test_settings, after_deploy).execute(nxt.run.id)
    async with pool.connection() as conn:
        msgs = await SessionRepository(conn).messages(sid, limit=100)
    refused = [m for m in msgs if m.type == "tool_result" and m.run_id == nxt.run.id]
    assert refused and refused[0].content.get("error")  # not granted any more


async def test_the_same_definition_pins_the_same_hash(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    graphs = default_registry()
    sessions = SessionService(pool, test_settings, graphs, RunService(pool, test_settings, graphs))
    a = await sessions.send((await sessions.create("chat")).id, "hi", script=[{"content": "x"}])
    b = await sessions.send((await sessions.create("chat")).id, "hi", script=[{"content": "x"}])
    assert a.run.agent_hash == b.run.agent_hash  # content-addressed: no duplicate snapshots

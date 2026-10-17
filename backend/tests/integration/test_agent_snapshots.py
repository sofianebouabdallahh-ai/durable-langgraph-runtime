from pathlib import Path

import pytest

from agent_runtime.agents.loader import Ceilings, load_agents
from agent_runtime.agents.store import AgentDefinitionRepository
from agent_runtime.catalog import default_catalog
from agent_runtime.db import Pool

pytestmark = pytest.mark.integration

AGENTS = Path(__file__).resolve().parents[2] / "agents"
CEILINGS = Ceilings(model_calls=100, tool_calls=100, tokens=1_000_000, cost_usd=2.0, timeout_s=1200)


async def test_snapshot_is_content_addressed_and_idempotent(pool: Pool) -> None:
    example = load_agents(AGENTS, default_catalog(), CEILINGS).get("example")
    async with pool.connection() as conn:
        repo = AgentDefinitionRepository(conn)
        first = await repo.snapshot(example)
        second = await repo.snapshot(example)
        sub = await repo.snapshot(example.subagents[0])
        cur = await conn.execute(
            "SELECT name, kind, content->'frontmatter'->>'max_turns' AS max_turns "
            "FROM agent_definitions WHERE hash = ANY(%s) ORDER BY name",
            ([first, sub],),
        )
        rows = await cur.fetchall()
    assert first == second and len(first) == 64
    assert rows == [
        {"name": "example", "kind": "main", "max_turns": "10"},
        {"name": "example/summarizer", "kind": "sub", "max_turns": "3"},
    ]

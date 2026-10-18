"""R14.15 gate: planted instructions change nothing the harness enforces.

Each case in `evals/cases/injection/` plants text in a tool result and assumes the
worst model: one that obeys it. The planted text must reach the model marked as
data (it can't close the block), and the obeying call must still be stopped by
the harness: an un-granted tool is denied and never runs, an approval-gated tool
waits for a person (and a refusal sends nothing), a budget stays a budget.
0 policy violations is the pass mark.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ConfigDict

from agent_runtime.db import Pool
from agent_runtime.fencing import Fence
from agent_runtime.runs.events import EventType as E
from agent_runtime.runs.state import RunStatus
from agent_runtime.runs.store import RunRepository
from agent_runtime.tools.builtin import NotifyArgs, notify
from agent_runtime.tools.invocations import BudgetExceeded
from agent_runtime.tools.pipeline import Grant, ToolCall, ToolPipeline, ToolRunContext
from agent_runtime.tools.policy import RiskClassPolicy
from agent_runtime.tools.spec import ToolArgs, ToolContext, ToolRegistry

pytestmark = pytest.mark.integration

CASES = Path(__file__).parents[2] / "evals" / "cases" / "injection"


def _cases() -> list[Any]:
    found = sorted(CASES.glob("*.yaml"))
    assert len(found) >= 10, "R14.15 asks for at least 10 injection cases"
    return [pytest.param(yaml.safe_load(p.read_text()), id=p.stem) for p in found]


class Text(ToolArgs):
    text: str = ""


class Anything(ToolArgs):
    model_config = ConfigDict(extra="allow")


class Lab:
    """Tools a swayed model might reach for, each counting its executions."""

    def __init__(self) -> None:
        self.ran: Counter[str] = Counter()
        self.asked: list[dict[str, Any]] = []
        self.registry = ToolRegistry()

        @self.registry.tool("fetch_page", args=Text, risk_class="read", side_effect=False)
        async def fetch_page(args: Text, ctx: ToolContext) -> str:
            return self.planted

        @self.registry.tool("echo", args=Text, risk_class="read", side_effect=False)
        async def echo(args: Text, ctx: ToolContext) -> str:
            self.ran["echo"] += 1
            return args.text

        for name in ("run_python", "fetch_secrets"):  # exist, but this agent isn't granted them
            self.registry.tool(name, args=Anything, risk_class="read", side_effect=False)(
                self._spy(name)
            )
        self.registry.tool(
            "notify", args=NotifyArgs, risk_class="external_side_effect", side_effect=True
        )(notify)
        self.planted = ""

    def _spy(self, name: str) -> Any:
        async def spy(args: Anything, ctx: ToolContext) -> str:
            self.ran[name] += 1
            return "ran"

        return spy

    def interrupt(self, payload: dict[str, Any]) -> Any:
        self.asked.append(payload)
        return {"decision": "reject", "reason": "not what I asked for"}  # the person says no

    def pipeline(self) -> ToolPipeline:
        return ToolPipeline(self.registry, RiskClassPolicy(), interrupt=self.interrupt)

    def ctx(self, fence: Fence, pool: Pool) -> ToolRunContext:
        grants = {n: Grant() for n in ("fetch_page", "echo", "notify")}
        return ToolRunContext(
            fence=fence, pool=pool, grants=grants, emit=lambda *_: None, max_tool_calls=3
        )


@pytest.fixture
async def fence(pool: Pool) -> Fence:
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        run = await repo.create(graph_name="assistant", input={})
        lease = await repo.acquire_lease(run.id, "inject:1", ttl_s=60)
        assert lease is not None
        await repo.transition(run.id, RunStatus.RUNNING, event=E.RUN_STARTED, fence=lease.fence)
    return lease.fence


@pytest.mark.parametrize("case", _cases())
async def test_planted_instructions_change_nothing(
    case: dict[str, Any], pool: Pool, fence: Fence
) -> None:
    lab = Lab()
    lab.planted = case["planted"]
    pipeline, ctx = lab.pipeline(), lab.ctx(fence, pool)

    seen = await pipeline.run(ToolCall(id="c0", name="fetch_page", args={}, index=0), ctx)
    inner = seen.content.removeprefix('<data source="fetch_page">\n').removesuffix("\n</data>")
    assert seen.content.startswith('<data source="fetch_page">') and seen.content.endswith(
        "</data>"
    )
    assert "</data" not in inner.lower() and "<data" not in inner.lower()

    tool, args = case["obeys"]["tool"], case["obeys"]["args"]
    obey = ToolCall(id="c1", name=tool, args=args, index=1)
    expect = case["expect"]
    if expect == "not_granted":
        result = await pipeline.run(obey, ctx)
        assert result.status == "error" and "Deny(not_granted)" in result.content
        assert lab.ran[tool] == 0
    elif expect == "approval":
        result = await pipeline.run(obey, ctx)
        assert [a["type"] for a in lab.asked] == ["tool_approval"]  # a person decides
        assert result.status == "error"
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT count(*) AS n FROM outbox_notifications WHERE run_id = %s", (fence.run_id,)
            )
            assert (await cur.fetchone() or {}).get("n") == 0  # refused: nothing sent
    elif expect == "over_limit":
        await pipeline.run(obey, ctx)
        await pipeline.run(ToolCall(id="c2", name=tool, args={"text": "more"}, index=2), ctx)
        with pytest.raises(BudgetExceeded, match="max_tool_calls=3"):
            await pipeline.run(ToolCall(id="c3", name=tool, args={"text": "x"}, index=3), ctx)
        assert lab.ran[tool] == 2
    else:
        pytest.fail(f"unknown expectation {expect!r}")

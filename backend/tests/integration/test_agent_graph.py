"""The `assistant` agent graph end to end: create_agent + RuntimeMiddleware +
ToolPipeline + executor, driven by the scripted model (R14.20)."""

from typing import Any

import pytest

from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.runs.events import EventType as E
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.runs.store import Run, RunRepository
from tests.integration.support import events

pytestmark = pytest.mark.integration
GRAPHS = default_registry()


def turn(content: str = "", **tool_calls: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": content,
        "tool_calls": [{"name": n, "args": a} for n, a in tool_calls.items()],
    }


async def run_assistant(
    pool: Pool,
    settings: Settings,
    script: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
) -> Run:
    service = RunService(pool, settings, GRAPHS)
    run = await service.create_run("assistant", {"message": "hi", "script": script}, options)
    return await RunExecutor(pool, settings, GRAPHS, owner="agent:1").execute(run.id)


async def test_agent_calls_tools_through_the_pipeline_and_answers(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    script = [
        turn(calculator={"expression": "6*7"}),
        turn(save_note={"text": "the answer is 42"}),
        turn("The answer is 42; noted."),
    ]
    done = await run_assistant(pool, test_settings, script)
    assert done.status is S.COMPLETED
    async with pool.connection() as conn:
        result = await RunRepository(conn).get_result(done.id)
        cur = await conn.execute(
            "SELECT model_calls, tool_calls_total, tool_calls FROM runs WHERE id = %s", (done.id,)
        )
        counters = await cur.fetchone()
        cur = await conn.execute("SELECT text FROM notes WHERE run_id = %s", (done.id,))
        notes = await cur.fetchall()
    assert result is not None and result["output"]["answer"] == "The answer is 42; noted."
    assert counters == {
        "model_calls": 3,
        "tool_calls_total": 2,
        "tool_calls": {"calculator": 1, "save_note": 1},
    }
    assert notes == [{"text": "the answer is 42"}]
    types = [e.type for e in await events(pool, done.id)]
    assert types.count(E.TOOL_CALLED) == 2 and types.count(E.TOOL_COMPLETED) == 2


async def test_hallucinated_and_ungranted_tools_are_denied_and_the_run_continues(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    script = [turn(teleport={"to": "mars"}), turn("I can't do that.")]
    done = await run_assistant(pool, test_settings, script)
    assert done.status is S.COMPLETED
    decisions = [e.payload for e in await events(pool, done.id) if e.type == E.POLICY_DECISION]
    assert decisions[0]["kind"] == "not_granted" and decisions[0]["tool"] == "teleport"


async def test_invalid_args_then_a_corrected_retry(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    script = [
        turn(calculator={"expr": "1+1"}),  # wrong field name
        turn(calculator={"expression": "1+1"}),
        turn("2"),
    ]
    done = await run_assistant(pool, test_settings, script)
    assert done.status is S.COMPLETED
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT tool_calls_total FROM runs WHERE id = %s", (done.id,))
        row = await cur.fetchone()
    assert row == {"tool_calls_total": 1}  # the invalid call never reached the ledger


async def test_model_call_budget_fails_the_run(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    script = [turn(calculator={"expression": "1"}), turn(calculator={"expression": "2"}), turn("x")]
    done = await run_assistant(pool, test_settings, script, {"max_model_calls": 2})
    assert (done.status, done.reason) == (S.FAILED, "budget:model_calls")


async def test_tool_call_budget_fails_the_run(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    script = [
        turn(calculator={"expression": "1"}),
        turn(calculator={"expression": "2"}),
        turn("x"),
    ]
    done = await run_assistant(pool, test_settings, script, {"max_tool_calls": 1})
    assert (done.status, done.reason) == (S.FAILED, "budget:tool_calls")


async def test_agent_limits_come_from_the_definition(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    run = await RunService(pool, test_settings, GRAPHS).create_run(
        "assistant", {"message": "hi"}, {"max_tool_calls": 3}
    )
    # max_turns 10 → max_model_calls; options tighten max_tool_calls 10 → 3; timeout 300
    assert run.limits == {
        "timeout_s": 300, "max_steps": 200, "max_model_calls": 10, "max_tool_calls": 3,
        "max_tokens": 1_000_000, "max_cost_usd": 2.0, "max_children": 6,  # server ceilings
    }  # fmt: skip


async def test_parallel_tool_calls_in_one_turn_do_not_deadlock(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    """Regression (found in phase 5b): LangGraph runs a turn's tool calls concurrently.
    Each ledger transaction used to take the run row FOR SHARE (check_fence) and then
    upgrade it, so two of them deadlocked. check_fence now takes FOR NO KEY UPDATE."""
    script = [
        {
            "tool_calls": [
                {"name": "calculator", "args": {"expression": f"{i}*2"}} for i in range(4)
            ]
        },
        turn("done"),
    ]
    done = await run_assistant(pool, test_settings, script)
    assert done.status is S.COMPLETED
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT tool_calls_total FROM runs WHERE id = %s", (done.id,))
        assert await cur.fetchone() == {"tool_calls_total": 4}

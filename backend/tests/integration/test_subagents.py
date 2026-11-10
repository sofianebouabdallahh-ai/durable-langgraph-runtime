"""Sub-agents (CR-005, phase 5b): the `delegator` agent and its leaf sub-agents
`scribe` (save_note), `mathematician` (calculator) and `napper` (2 s timeout),
driven by scripted models. SC12-SC19."""

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.fencing import Fence, FencedError
from agent_runtime.graphs import default_registry
from agent_runtime.models.scripted import ScriptedChatModel
from agent_runtime.runs.events import EventType as E
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.runs.store import Run, RunRepository
from agent_runtime.subagents.store import Invocation, SubagentRepository
from agent_runtime.tools.hooks import Ask, Continue, HookDecision, HookRegistry, ToolHookInput
from tests.integration.support import events

pytestmark = pytest.mark.integration
GRAPHS = default_registry()


# ------------------------------------------------------------------ scripting


def call(name: str, **args: Any) -> dict[str, Any]:
    return {"name": name, "args": args}


def turn(*calls: dict[str, Any], content: str = "") -> dict[str, Any]:
    return {"content": content, "tool_calls": list(calls)}


def handle(i: int) -> str:
    """The i-th spawn's handle, resolved by the scripted model from its result."""
    return f"${{spawn_subagent[{i}].handle}}"


def spawn(agent: str, task: str = "do it", **kw: Any) -> dict[str, Any]:
    return call("spawn_subagent", agent=agent, task=task, **kw)


def wait(*i: int, timeout_s: int = 30) -> dict[str, Any]:
    return call("wait_subagents", handles=[handle(n) for n in i], timeout_s=timeout_s)


def say(text: str) -> dict[str, Any]:
    return turn(content=text)


RETURN = turn(call("return_result", summary="done"))


async def create(
    pool: Pool,
    settings: Settings,
    script: list[dict[str, Any]],
    subs: dict[str, list[dict[str, Any]]],
    options: dict[str, Any] | None = None,
) -> Run:
    inp = {"message": "go", "script": script, "subagent_scripts": subs}
    return await RunService(pool, settings, GRAPHS).create_run("delegator", inp, options)


async def run_delegator(
    pool: Pool, settings: Settings, script: list[dict[str, Any]],
    subs: dict[str, list[dict[str, Any]]], options: dict[str, Any] | None = None, **kw: Any,
) -> tuple[Run, RunExecutor]:  # fmt: skip
    run = await create(pool, settings, script, subs, options)
    executor = RunExecutor(pool, settings, GRAPHS, owner="w:1", **kw)
    return await executor.execute(run.id), executor


async def invocations(pool: Pool, run_id: uuid.UUID) -> list[Invocation]:
    async with pool.connection() as conn:
        return await SubagentRepository(conn).list(run_id)


async def tool_results(pool: Pool, run_id: uuid.UUID, tool: str) -> list[Any]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT result FROM tool_invocations WHERE run_id = %s AND tool = %s "
            "ORDER BY created_at",
            (run_id, tool),
        )
        return [r["result"] for r in await cur.fetchall()]


async def counters(pool: Pool, run_id: uuid.UUID) -> tuple[int, int]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT model_calls, tool_calls_total FROM runs WHERE id = %s", (run_id,)
        )
        row = await cur.fetchone()
    assert row is not None
    return row["model_calls"], row["tool_calls_total"]


@pytest.fixture
def requests(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[list[BaseMessage]]]:
    """Every message list a scripted model was called with (main and sub-agents)."""
    seen: list[list[BaseMessage]] = []
    real = ScriptedChatModel._agenerate

    async def spy(self: ScriptedChatModel, messages: list[BaseMessage], *a: Any, **kw: Any) -> Any:
        seen.append(list(messages))
        return await real(self, messages, *a, **kw)

    monkeypatch.setattr(ScriptedChatModel, "_agenerate", spy)
    yield seen


def system_of(messages: list[BaseMessage]) -> str:
    return next((str(m.content) for m in messages if isinstance(m, SystemMessage)), "")


# ---------------------------------------------------------------- happy path


async def test_two_subagents_run_in_parallel_and_their_usage_rolls_up(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    script = [
        turn(spawn("scribe", "keep: alpha"), spawn("mathematician", "6*7")),
        turn(wait(0, 1)),
        say("Kept alpha; 6*7 = 42."),
    ]
    subs = {
        "scribe": [
            turn(call("save_note", text="alpha", linger_s=0.5)),
            turn(call("report_progress", message="saved alpha", percent=100)),
            RETURN,
        ],
        "mathematician": [
            turn(call("calculator", expression="6*7")),
            turn(call("return_result", summary="42", result={"value": 42})),
        ],
    }
    done, executor = await run_delegator(pool, test_settings, script, subs)
    assert done.status is S.COMPLETED
    assert executor._orchestrator is not None
    assert executor._orchestrator.max_running_seen == 2  # SC12: concurrently, same worker
    invs = {i.name: i for i in await invocations(pool, done.id)}
    assert {n: i.status for n, i in invs.items()} == {
        "scribe": "completed",
        "mathematician": "completed",
    }
    assert invs["mathematician"].result == {
        "status": "success",
        "summary": "42",
        "result": {"value": 42},
    }
    assert invs["scribe"].progress["message"] == "saved alpha"

    waited = (await tool_results(pool, done.id, "wait_subagents"))[0]
    assert sorted(c["agent"] for c in waited["completed"]) == ["mathematician", "scribe"]
    assert waited["pending"] == []
    types = [e.type for e in await events(pool, done.id)]
    assert types.count(E.SUBAGENT_SPAWNED) == 2 and types.count(E.SUBAGENT_COMPLETED) == 2
    assert types.count(E.SUBAGENT_PROGRESS) == 1
    # R16.8 / AC42: usage rolls up. Main: 3 model + 3 tool calls; scribe 3 + 3; maths 2 + 2.
    assert await counters(pool, done.id) == (8, 8)
    assert invs["scribe"].usage["model_calls"] == 3 and invs["scribe"].usage["tool_calls"] == 3
    # The sub-agents' steps don't count toward the main run's max_steps
    assert done.steps == 6  # before_agent (turn hooks), model, tools, model, tools, model


async def test_spawn_errors_are_tool_errors_the_model_sees(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    settings = test_settings.model_copy(update={"subagent_max_total": 1})
    script = [
        turn(spawn("ghost")),
        turn(spawn("mathematician", "1+1")),
        turn(spawn("scribe")),  # the 2nd sub-agent: over max_total=1
        turn(wait(0)),
        say("ok"),
    ]
    subs = {"mathematician": [RETURN]}
    done, _ = await run_delegator(pool, settings, script, subs)
    assert done.status is S.COMPLETED
    errors = [
        r["error"] for r in await tool_results(pool, done.id, "spawn_subagent") if "error" in r
    ]
    assert errors == [
        "SubagentToolError: unknown sub-agent 'ghost'; available: mathematician, napper, scribe",
        "SubagentToolError: at most 1 sub-agents per run",
    ]


# ------------------------------------------------------ isolation & privilege


async def test_a_subagent_sees_only_its_prompt_and_task_and_only_its_tools(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    requests: list[list[BaseMessage]],
) -> None:  # fmt: skip
    script = [
        turn(spawn("mathematician", "compute 2+2", context="the user likes round numbers")),
        turn(wait(0)),
        say("4"),
    ]
    subs = {"mathematician": [turn(call("save_note", text="sneaky")), RETURN]}  # not its tool
    done, _ = await run_delegator(pool, test_settings, script, subs)
    assert done.status is S.COMPLETED
    first = next(m for m in requests if "You compute." in system_of(m))
    assert [type(m) for m in first] == [SystemMessage, HumanMessage]  # SC13 / R16.6
    assert first[1].content == "compute 2+2\n\nContext:\nthe user likes round numbers"
    assert "go" not in str(first[1].content)  # the main conversation never leaks in
    denied = [e.payload for e in await events(pool, done.id) if e.type == E.POLICY_DECISION]
    assert denied[0]["tool"] == "save_note" and denied[0]["kind"] == "not_granted"
    assert "subagent" in denied[0]  # audited with the sub-agent's handle
    assert await tool_results(pool, done.id, "save_note") == []


async def test_a_hook_asking_for_approval_in_a_subagent_is_a_deny_not_a_pause(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    hooks = HookRegistry()

    @hooks.hook("redact_secrets_in_args", point="pre_tool")
    async def ask_for_notes(inp: ToolHookInput) -> HookDecision:
        return Ask({"why": "test"}) if inp.tool == "save_note" else Continue()

    @hooks.hook("redact_secrets_in_result", point="post_tool")
    async def nothing(inp: ToolHookInput) -> HookDecision:
        return Continue()

    script = [turn(spawn("scribe")), turn(wait(0)), say("ok")]
    subs = {"scribe": [turn(call("save_note", text="x")), RETURN]}
    done, _ = await run_delegator(pool, test_settings, script, subs, hooks=hooks)
    assert done.status is S.COMPLETED  # never waiting_approval (R16.7)
    kinds = [
        e.payload.get("kind") for e in await events(pool, done.id) if e.type == E.POLICY_DECISION
    ]
    assert kinds == ["approval_unavailable"]


# --------------------------------------------- status, return, cancel, timeout


async def test_progress_partial_results_and_the_rate_limit(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    script = [turn(spawn("scribe")), turn(wait(0)), turn(call("subagent_status")), say("ok")]
    subs = {
        "scribe": [
            turn(call("report_progress", message="halfway", percent=50)),
            turn(call("report_progress", message="too soon")),  # < 2 s later: dropped
            turn(call("return_result", summary="half of it", status="partial")),
        ]
    }
    done, _ = await run_delegator(pool, test_settings, script, subs)
    assert done.status is S.COMPLETED
    progress = await tool_results(pool, done.id, "report_progress")
    assert progress[0] == {"accepted": True}
    assert progress[1]["accepted"] is False and "per 2s" in progress[1]["note"]
    waited = (await tool_results(pool, done.id, "wait_subagents"))[0]["completed"][0]
    assert (waited["status"], waited["summary"]) == ("partial", "half of it")  # AC40
    status = (await tool_results(pool, done.id, "subagent_status"))[0][0]
    assert (status["agent"], status["progress"], status["percent"]) == ("scribe", "halfway", 50)


async def test_cancel_stops_a_subagent_between_steps(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    # The main agent waits 1 s first, so the scribe is inside its first (slow) tool call
    # when the cancel arrives. (Cancelling right after the spawn raced the scribe's
    # start: under coverage tracing the cancel could land before its first step, which
    # is correct behaviour but not what this test is about.)
    script = [
        turn(spawn("scribe")),
        turn(wait(0, timeout_s=1)),
        turn(call("cancel_subagent", handle=handle(0), reason="not needed")),
        turn(wait(0)),
        say("ok"),
    ]
    subs = {
        "scribe": [
            turn(call("save_note", text="first", linger_s=3.0)),  # cancelled meanwhile
            turn(call("save_note", text="second")),
            RETURN,
        ]
    }
    done, _ = await run_delegator(pool, test_settings, script, subs)
    assert done.status is S.COMPLETED
    (inv,) = await invocations(pool, done.id)
    assert inv.status == "cancelled" and inv.result is not None
    assert inv.result["reason"] == "cancelled: not needed"
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT text FROM notes WHERE run_id = %s", (done.id,))
        assert await cur.fetchall() == [{"text": "first"}]  # stopped before its next step


async def test_a_subagent_past_its_timeout_fails_with_timeout(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    script = [turn(spawn("napper")), turn(wait(0)), say("ok")]
    subs = {"napper": [turn(call("save_note", text="zz", linger_s=5)), RETURN]}
    done, _ = await run_delegator(pool, test_settings, script, subs)
    assert done.status is S.COMPLETED
    (inv,) = await invocations(pool, done.id)
    assert inv.status == "timed_out"
    assert inv.result == {"status": "failed", "summary": "", "reason": "timeout"}  # AC40


# ---------------------------------------------------------------- turn guard


async def test_the_main_agent_cannot_finish_while_a_subagent_runs(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    requests: list[list[BaseMessage]],
) -> None:  # fmt: skip
    script = [
        turn(spawn("scribe")),
        say("Done already!"),  # answers while the scribe still works
        say("Now really done, with the scribe's notes."),
    ]
    subs = {"scribe": [turn(call("save_note", text="slow", linger_s=1.0)), RETURN]}
    done, _ = await run_delegator(pool, test_settings, script, subs)
    assert done.status is S.COMPLETED  # SC15 / R16.9
    async with pool.connection() as conn:
        result = await RunRepository(conn).get_result(done.id)
    assert result is not None
    assert result["output"]["answer"] == "Now really done, with the scribe's notes."
    guard = requests[-1][-1]
    assert isinstance(guard, HumanMessage) and "were still running" in str(guard.content)
    assert '"summary": "done"' in str(guard.content)  # the result is in the extra call
    # The helpers' words are data, like wait_subagents' output (H4, finding 14).
    assert '<data source="subagents">' in str(guard.content)
    assert str(guard.content).rstrip().endswith("</data>")
    seqs = {e.type: e.seq for e in await events(pool, done.id)}
    assert seqs[E.SUBAGENT_COMPLETED] < seqs[E.RUN_COMPLETED]


# ---------------------------------------------------------- crash & recovery


async def test_a_crashed_run_resumes_its_unfinished_subagent_and_never_reruns_a_finished_one(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    """AC41 in-process: worker A dies while the scribe is mid-task (the mathematician
    already finished). Worker B resumes the main agent and only the scribe."""
    fast = test_settings.model_copy(update={"lease_ttl_s": 1.0, "heartbeat_s": 0.3})
    script = [turn(spawn("scribe"), spawn("mathematician", "1+1")), turn(wait(0, 1)), say("ok")]
    subs = {
        "scribe": [turn(call("save_note", text="kept", linger_s=1.5)), RETURN],
        "mathematician": [turn(call("calculator", expression="1+1")), RETURN],
    }
    run = await create(pool, fast, script, subs)
    worker_a = asyncio.create_task(RunExecutor(pool, fast, GRAPHS, owner="w-a:1").execute(run.id))

    async def scribe_mid_task() -> bool:
        invs = {i.name: i for i in await invocations(pool, run.id)}
        async with pool.connection() as conn:
            cur = await conn.execute("SELECT 1 FROM notes WHERE run_id = %s", (run.id,))
            noted = await cur.fetchone() is not None
        return (
            noted and invs.get("mathematician") is not None and not invs["mathematician"].is_running
        )

    from tests.integration.support import wait_until

    await wait_until(scribe_mid_task, timeout_s=15)
    worker_a.cancel()  # the worker dies: its sub-agent tasks die with it
    await asyncio.gather(worker_a, return_exceptions=True)
    await asyncio.sleep(fast.lease_ttl_s + 0.2)

    done = await RunExecutor(pool, fast, GRAPHS, owner="w-b:2").execute(run.id)
    assert done.status is S.COMPLETED and done.epoch == 2
    invs = await invocations(pool, run.id)
    assert sorted((i.name, i.status) for i in invs) == [
        ("mathematician", "completed"),
        ("scribe", "completed"),
    ]
    evts = await events(pool, run.id)
    assert sum(e.type == E.SUBAGENT_SPAWNED for e in evts) == 2  # no double spawn
    assert sum(e.type == E.SUBAGENT_COMPLETED for e in evts) == 2  # one result per handle
    calc = [e for e in evts if e.type == E.TOOL_CALLED and e.payload["tool"] == "calculator"]
    assert len(calc) == 1 and calc[0].epoch == 1  # the finished sub-agent never re-ran
    # The scribe resumed from ITS checkpoint: its first model call isn't repeated, and
    # the tool call it was in the middle of is taken over under the new epoch.
    scribe = next(i for i in invs if i.name == "scribe")
    assert scribe.usage["model_calls"] == 2
    note = [e for e in evts if e.type == E.TOOL_CALLED and e.payload["tool"] == "save_note"]
    assert [(e.epoch, e.payload["taken_over"]) for e in note] == [(2, True)]
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT count(*) AS n FROM notes WHERE run_id = %s", (run.id,))
        assert await cur.fetchone() == {"n": 1}


async def test_an_approval_pause_stops_subagents_and_the_resume_recovers_them(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    """The main run must not leave `running` with sub-agents still writing."""
    script = [
        turn(spawn("scribe")),
        turn(call("notify", to="ops", message="heads up")),  # needs approval: pause
        turn(wait(0)),
        say("ok"),
    ]
    subs = {"scribe": [turn(call("save_note", text="n", linger_s=1.0)), RETURN]}
    # notify isn't granted to the delegator: grant it for this test via a copy
    from agent_runtime.agents.schema import ToolGrant
    from agent_runtime.graphs import GraphRegistry
    from agent_runtime.graphs.assistant import agent_spec
    from agent_runtime.tools.builtin import default_tools

    base = GRAPHS.get("delegator").agent
    assert base is not None
    fm = base.frontmatter.model_copy(update={"tools": [ToolGrant(name="notify")]})
    graphs = GraphRegistry(
        [agent_spec(base.model_copy(update={"frontmatter": fm}), default_tools())]
    )
    run = await RunService(pool, test_settings, graphs).create_run(
        "delegator", {"message": "go", "script": script, "subagent_scripts": subs}
    )
    paused = await RunExecutor(pool, test_settings, graphs).execute(run.id)
    assert paused.status is S.WAITING_APPROVAL
    (inv,) = await invocations(pool, run.id)
    assert inv.status == "running"  # stopped, not ended: it resumes with the run
    await RunService(pool, test_settings, graphs).decide_approval(run.id, "approve")
    done = await RunExecutor(pool, test_settings, graphs).execute(run.id)
    assert done.status is S.COMPLETED
    (inv,) = await invocations(pool, run.id)
    assert inv.status == "completed"


# ------------------------------------------------------------------- budgets


async def test_the_runs_budget_bounds_its_subagents_soft_then_hard(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    requests: list[list[BaseMessage]],
) -> None:  # fmt: skip
    """AC42: max_model_calls=6 for the whole run. At 80 % the scribe is asked to wrap
    up; at 6 the run's hard limit stops it. The main agent still gets its one wrap-up
    call past the limit (H2), so the run ends failed(budget) WITH an answer."""
    script = [turn(spawn("scribe")), turn(wait(0)), say("ok")]
    subs = {"scribe": [turn(call("report_progress", message="started"))]
            + [turn(call("save_note", text=f"n{i}")) for i in range(6)]}  # fmt: skip
    done, _ = await run_delegator(pool, test_settings, script, subs, {"max_model_calls": 6})
    assert (done.status, done.reason) == (S.FAILED, "budget:model_calls")
    model_calls, _ = await counters(pool, done.id)
    # The limit across main + sub-agent, plus the main agent's one wrap-up call (H2).
    assert model_calls == 6 + 1
    async with pool.connection() as conn:
        output = await RunRepository(conn).get_result(done.id)
    assert output is not None and output["output"]["budget_limited"] is True  # an answer
    # The main agent spends 2 calls (spawn, wait) and then blocks in wait_subagents
    # until the scribe ends, so the scribe is always the one that hits the limit:
    # its 5th call would be the run's 7th.
    (inv,) = await invocations(pool, done.id)
    assert inv.status == "failed"
    assert inv.result == {"status": "partial", "summary": "started", "reason": "budget:model_calls"}
    assert inv.usage["model_calls"] == 4
    scribe_calls = [m for m in requests if "You keep notes" in system_of(m)]
    noted = ["budget is nearly used up" in str(m[-1].content) for m in scribe_calls]
    assert noted == [False, False, True, True]  # the run's 5th and 6th calls are ≥ 80 %


# --------------------------------------------------------- fencing & the API


async def test_a_stale_owner_cannot_write_subagent_state(pool: Pool) -> None:
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        run = await repo.create(graph_name="toy", input={"question": "q"})
        lease = await repo.acquire_lease(run.id, "w:1", 60)
        assert lease is not None
        await repo.transition(run.id, S.RUNNING, event=E.RUN_STARTED, fence=lease.fence)
        subs = SubagentRepository(conn)
        inv, created = await subs.spawn(lease.fence, key="a" * 64, agent="x/y", task="t",
                                        context=None, max_total=10)  # fmt: skip
        again, created_again = await subs.spawn(lease.fence, key="a" * 64, agent="x/y",
                                                task="t", context=None, max_total=10)  # fmt: skip
        assert created and not created_again and again.handle == inv.handle  # idempotent
        newer = await conn.execute(
            "UPDATE runs SET epoch = epoch + 1 WHERE id = %s RETURNING epoch", (run.id,)
        )
        assert (await newer.fetchone()) is not None
        stale = lease.fence
        for write in (
            subs.report_progress(stale, inv.handle, "x", None),
            subs.finish(stale, inv.handle, "completed", {}),
            subs.request_cancel(stale, inv.handle, "x"),
        ):
            with pytest.raises(FencedError):
                await write
        assert stale == Fence(run.id, lease.fence.epoch)


async def test_the_api_lists_a_runs_subagents(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    import httpx

    from agent_runtime.api.app import create_app

    script = [turn(spawn("mathematician", "2*2")), turn(wait(0)), say("4")]
    done, _ = await run_delegator(pool, test_settings, script, {"mathematician": [RETURN]})
    app = create_app(test_settings, pool=pool)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client,
    ):
        view = (await client.get(f"/runs/{done.id}")).json()
    (sub,) = view["subagents"]  # SC19
    assert (sub["agent"], sub["status"]) == ("mathematician", "completed")
    assert sub["result"]["summary"] == "done" and sub["usage"]["model_calls"] == 1

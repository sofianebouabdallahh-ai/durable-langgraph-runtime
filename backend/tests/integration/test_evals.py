"""Phase H6: agents have tests. The built-in suites pass; a regression fails them; a
Studio draft with tests publishes only once every test passed on exactly that draft."""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from agent_runtime.api.app import create_app
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.evals.runner import report, run_suite, suites
from agent_runtime.graphs import default_registry
from agent_runtime.queue import RedisWorkQueue
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.streaming.bus import EventBus, RedisEventBus
from agent_runtime.tools.policy import Allow, PolicyDecision
from tests.integration.test_stream import Server

pytestmark = pytest.mark.integration
GRAPHS = default_registry()
AGENTS = Path(__file__).resolve().parents[2] / "agents"
CALC = [{"tool_calls": [{"name": "calculator", "args": {"expression": "6*7"}}]},
        {"content": "It is 42."}]  # fmt: skip


@pytest.mark.parametrize("agent", sorted(suites(AGENTS)))
async def test_the_built_in_suites_pass(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, agent: str
) -> None:
    outcomes = await run_suite(pool, test_settings, GRAPHS, agent, suites(AGENTS)[agent])
    text, ok = report(agent, outcomes)
    assert ok, text
    assert len(outcomes) >= 3


class AllowEverything:
    """A harness regression: the policy no longer asks before anything."""

    async def check(self, tool: Any, args: Any, ctx: Any = None) -> PolicyDecision:
        return Allow()


async def test_a_regression_that_skips_an_approval_fails_the_suite(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    cases = [c for c in suites(AGENTS)["assistant"] if c[0] == "notify-asks-first"]
    (outcome,) = await run_suite(pool, test_settings, GRAPHS, "assistant", cases,
                                 policy=AllowEverything())  # fmt: skip
    assert outcome.status == "failed"
    failed = {c["check"]: c["detail"] for c in outcome.checks if not c["ok"]}
    assert failed == {"asked before notify": "notify ran without asking"}


async def test_a_regression_that_drops_a_tool_fails_the_suite(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    from agent_runtime.graphs import GraphRegistry
    from agent_runtime.graphs.assistant import agent_spec
    from agent_runtime.tools.builtin import default_tools

    base = GRAPHS.get("assistant").agent
    assert base is not None
    fm = base.frontmatter.model_copy(update={
        "tools": [t for t in base.frontmatter.tools if t.name != "calculator"]})  # fmt: skip
    graphs = GraphRegistry([agent_spec(base.model_copy(update={"frontmatter": fm}),
                                       default_tools())])  # fmt: skip
    cases = [c for c in suites(AGENTS)["assistant"] if c[0] == "uses-the-calculator"]
    (outcome,) = await run_suite(pool, test_settings, graphs, "assistant", cases)
    assert outcome.status == "failed"
    assert any(c["check"] == "called calculator" and not c["ok"] for c in outcome.checks)


# ---------------------------------------------------------- Studio: the gate


@pytest.fixture
async def api(
    pool: Pool, test_settings: Settings, queue: RedisWorkQueue, checkpoint_tables: None
) -> AsyncIterator[Server]:
    bus: EventBus = RedisEventBus(queue._r)
    async with Server(create_app(test_settings, pool=pool, queue=queue, bus=bus)) as server:
        yield server


def document(name: str, tools: list[str]) -> dict[str, Any]:
    return {"name": name, "display_name": "Calc", "description": "Does sums.",
            "instructions": "Do sums.", "max_turns": 10,
            "limits": {"max_tool_calls": 10, "timeout_s": 120},
            "tools": [{"name": t} for t in tools], "helpers": []}  # fmt: skip


async def run_batch(pool: Pool, settings: Settings, batch: str) -> None:
    """What the workers do: execute each test turn until it ends (graded on the way)."""
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT run_id FROM eval_runs WHERE batch = %s", (batch,))
        runs = [r["run_id"] for r in await cur.fetchall()]
    for run_id in runs:
        for _ in range(5):
            if (await RunExecutor(pool, settings, GRAPHS).execute(run_id)).status.is_terminal:
                break


async def test_a_draft_with_tests_publishes_only_once_they_pass_on_it(
    api: Server, pool: Pool, test_settings: Settings
) -> None:
    c = api.client
    agent = (await c.post("/studio/agents", json={"display_name": "Calc"})).json()
    aid, name = agent["id"], agent["name"]
    await c.put(f"/studio/agents/{aid}/draft", json=document(name, ["calculator"]))
    case = {"name": "does the sum", "message": "6*7?", "script": CALC,
            "expect": {"tools": ["calculator"], "answer_contains": ["42"]}}  # fmt: skip
    added = await c.post(f"/studio/agents/{aid}/tests", json=case)
    assert added.status_code == 201, added.text
    # A test chat completing is no longer enough: its tests are the gate.
    state = (await c.get(f"/studio/agents/{aid}")).json()
    assert state["draft"]["tests"] == 1 and state["draft"]["tests_failing"] == ["does the sum"]
    blocked = await c.post(f"/studio/agents/{aid}/publish", json={})
    assert blocked.status_code == 409 and "passed on this draft" in blocked.text

    started = (await c.post(f"/studio/agents/{aid}/tests/run")).json()
    assert started["cases"] == 1
    await run_batch(pool, test_settings, started["batch"])
    tests = (await c.get(f"/studio/agents/{aid}/tests")).json()
    (view,) = tests["cases"]
    assert (view["result"]["status"], view["result"]["current"]) == ("passed", True)
    assert tests["passing"] == 1
    published = await c.post(f"/studio/agents/{aid}/publish", json={"changelog": "Tested"})
    assert published.status_code == 200, published.text

    # A new draft: the old result was on another bundle, so it doesn't count.
    changed = {**document(name, ["calculator"]), "description": "Does sums, fast."}
    await c.put(f"/studio/agents/{aid}/draft", json=changed)
    again = await c.post(f"/studio/agents/{aid}/publish", json={})
    assert again.status_code == 409
    tests = (await c.get(f"/studio/agents/{aid}/tests")).json()
    assert tests["cases"][0]["result"]["current"] is False and tests["passing"] == 0


async def test_a_failing_test_says_why_and_editing_the_case_makes_it_stale(
    api: Server, pool: Pool, test_settings: Settings
) -> None:
    c = api.client
    agent = (await c.post("/studio/agents", json={"display_name": "Calc"})).json()
    aid, name = agent["id"], agent["name"]
    await c.put(f"/studio/agents/{aid}/draft", json=document(name, ["calculator"]))
    case = {"name": "wants 43", "message": "6*7?", "script": CALC,
            "expect": {"answer_contains": ["43"], "not_tools": ["calculator"]}}  # fmt: skip
    case_id = (await c.post(f"/studio/agents/{aid}/tests", json=case)).json()["id"]
    started = (await c.post(f"/studio/agents/{aid}/tests/run")).json()
    await run_batch(pool, test_settings, started["batch"])
    (view,) = (await c.get(f"/studio/agents/{aid}/tests")).json()["cases"]
    assert view["result"]["status"] == "failed"
    failed = {x["check"]: x["detail"] for x in view["result"]["checks"] if not x["ok"]}
    assert failed["answer says '43'"].startswith("the answer: “It is 42.")
    assert failed["never called calculator"] == "it called calculator"
    assert view["result"]["session_id"]  # its test chat, to see what happened
    fixed = {**case, "expect": {"answer_contains": ["42"]}}
    await c.put(f"/studio/agents/{aid}/tests/{case_id}", json=fixed)
    (view,) = (await c.get(f"/studio/agents/{aid}/tests")).json()["cases"]
    assert view["result"]["current"] is False  # the case changed since


async def test_a_judge_needs_a_real_model(api: Server, pool: Pool, test_settings: Settings) -> None:
    c = api.client
    agent = (await c.post("/studio/agents", json={"display_name": "Calc"})).json()
    aid, name = agent["id"], agent["name"]
    await c.put(f"/studio/agents/{aid}/draft", json=document(name, ["calculator"]))
    case = {"name": "polite", "message": "6*7?", "script": CALC,
            "expect": {"judge": "Answers politely"}}  # fmt: skip
    await c.post(f"/studio/agents/{aid}/tests", json=case)
    started = (await c.post(f"/studio/agents/{aid}/tests/run")).json()
    await run_batch(pool, test_settings, started["batch"])
    (view,) = (await c.get(f"/studio/agents/{aid}/tests")).json()["cases"]
    assert view["result"]["status"] == "error"
    judged = next(x for x in view["result"]["checks"] if x["check"].startswith("judge"))
    assert "needs a real model" in judged["detail"]


async def test_a_thumbs_down_becomes_a_test(
    api: Server, pool: Pool, test_settings: Settings
) -> None:
    c = api.client
    agent = (await c.post("/studio/agents", json={"display_name": "Calc"})).json()
    aid, name = agent["id"], agent["name"]
    await c.put(f"/studio/agents/{aid}/draft", json=document(name, ["calculator"]))
    chat = (await c.post(f"/studio/agents/{aid}/test-chat")).json()
    sent = (await c.post(f"/sessions/{chat['id']}/messages",
                         json={"content": "6*7?", "script": CALC})).json()  # fmt: skip
    await RunExecutor(pool, test_settings, GRAPHS).execute(uuid.UUID(sent["run_id"]))
    await c.put(f"/runs/{sent['run_id']}/feedback",
                json={"rating": "down", "reason": "show the working"})  # fmt: skip
    made = await c.post(f"/runs/{sent['run_id']}/make-test")
    assert made.status_code == 201, made.text
    case = made.json()["case"]
    assert case["message"] == "6*7?" and "show the working" in case["expect"]["judge"]
    assert "It is 42." in case["expect"]["judge"]
    assert made.json()["from_run"] == sent["run_id"]
    tests = (await c.get(f"/studio/agents/{aid}/tests")).json()
    assert [x["case"]["name"] for x in tests["cases"]] == ["From a 👎: 6*7?"]


async def test_a_built_in_agents_reply_has_no_studio_tests(
    api: Server, pool: Pool, test_settings: Settings
) -> None:
    c = api.client
    session = (await c.post("/sessions", json={"agent": "assistant"})).json()
    sent = (await c.post(f"/sessions/{session['id']}/messages",
                         json={"content": "6*7?", "script": CALC})).json()  # fmt: skip
    done = await RunExecutor(pool, test_settings, GRAPHS).execute(uuid.UUID(sent["run_id"]))
    assert done.status is S.COMPLETED
    refused = await c.post(f"/runs/{sent['run_id']}/make-test")
    assert refused.status_code == 409 and refused.json()["type"].endswith("/not-a-studio-agent")


# ------------------------------------------------- from the review of the change


async def test_runtime_evals_send_nothing_and_keep_their_notes_to_themselves(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    """A test turn simulates side effects like a Studio test chat, and its notes (even a
    planted instruction) never reach a real chat's recall_notes."""
    before = await _count(pool, "SELECT count(*) AS n FROM outbox_notifications")
    for agent in ("assistant", "chat"):
        await run_suite(pool, test_settings, GRAPHS, agent, suites(AGENTS)[agent])
    assert await _count(pool, "SELECT count(*) AS n FROM outbox_notifications") == before
    from agent_runtime.runs.service import RunService
    from agent_runtime.sessions.service import SessionService

    sessions = SessionService(pool, test_settings, GRAPHS, RunService(pool, test_settings, GRAPHS))
    sid = (await sessions.create("chat")).id
    sent = await sessions.send(sid, "my notes?", script=[
        {"tool_calls": [{"name": "recall_notes", "args": {"query": "locker"}}]},
        {"content": "ok"}])  # fmt: skip
    await RunExecutor(pool, test_settings, GRAPHS).execute(sent.run.id)
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT result FROM tool_invocations WHERE run_id = %s AND tool = 'recall_notes'",
            (sent.run.id,),
        )
        row = await cur.fetchone()
    assert row is not None and row["result"]["count"] == 0  # the test's note stayed in its chat


async def _count(pool: Pool, query: str) -> int:
    async with pool.connection() as conn:
        cur = await conn.execute(query)
        row = await cur.fetchone()
    return int(row["n"]) if row else 0


async def test_the_sweep_answers_an_unanswered_approval_and_grades_a_cancelled_test(
    pool: Pool, test_settings: Settings, queue: RedisWorkQueue, checkpoint_tables: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    from agent_runtime.evals import grader
    from agent_runtime.evals.cases import Case
    from agent_runtime.evals.store import EvalStore
    from agent_runtime.ids import new_id
    from agent_runtime.runs.service import RunService
    from agent_runtime.sessions.service import SessionService
    from agent_runtime.worker import Worker

    sessions = SessionService(pool, test_settings, GRAPHS, RunService(pool, test_settings, GRAPHS))
    ((_, case),) = [c for c in suites(AGENTS)["assistant"] if c[0] == "notify-asks-first"]
    batch = new_id()

    async def send(c: Case) -> uuid.UUID:
        chat = await sessions.create("assistant", "test")

        async def known(conn: Any, run: Any) -> None:
            await EvalStore(conn).record(
                run.id,
                agent="assistant",
                agent_id=None,
                case_key="t",
                case=c,
                bundle_hash=None,
                batch=batch,
            )

        script = [t.model_dump(mode="json") for t in c.script]
        turn = await sessions.send(chat.id, c.message, on_created=known, script=script)
        return turn.run.id

    # 1. The worker died right after the pause: nobody answered the case's approval.
    real = grader.answer_approvals

    async def dies(*a: Any, **kw: Any) -> Any:
        raise ConnectionError("the worker died here")

    monkeypatch.setattr(grader, "answer_approvals", dies)
    waiting = await send(case)
    with pytest.raises(ConnectionError):
        await RunExecutor(pool, test_settings, GRAPHS).execute(waiting)
    monkeypatch.setattr(grader, "answer_approvals", real)
    # 2. A test turn cancelled through the API: it ended with no executor to grade it.
    cancelled = await send(case)
    await RunService(pool, test_settings, GRAPHS).cancel(cancelled)

    worker = Worker(pool, queue, test_settings, GRAPHS)
    assert await worker._settle_tests() == 2
    for _ in range(3):
        if (await RunExecutor(pool, test_settings, GRAPHS).execute(waiting)).status.is_terminal:
            break
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT run_id, status FROM eval_runs WHERE run_id = ANY(%s)", ([waiting, cancelled],)
        )
        status = {r["run_id"]: r["status"] for r in await cur.fetchall()}
        cur = await conn.execute(
            "SELECT count(*) AS n FROM session_messages WHERE run_id = %s AND type = 'approval'",
            (waiting,),
        )
        decided = (await cur.fetchone() or {}).get("n")
    assert status == {waiting: "passed", cancelled: "failed"}  # answered, then graded
    assert decided == 1  # the test chat shows the test's decision, like a person's


async def test_the_trajectory_comes_from_the_ledger_not_only_the_events(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    from agent_runtime.evals.trajectory import read

    ((_, case),) = [c for c in suites(AGENTS)["assistant"] if c[0] == "uses-the-calculator"]
    (outcome,) = await run_suite(pool, test_settings, GRAPHS, "assistant",
                                 [("uses-the-calculator", case)])  # fmt: skip
    async with pool.connection() as conn:  # a crash lost the step's events (re-run: cached)
        await conn.execute("DELETE FROM run_events WHERE run_id = %s AND type = 'tool.called'",
                           (outcome.run_id,))  # fmt: skip
        t = await read(conn, outcome.run_id)
    assert t.tools == {"calculator"}

"""Chat sessions (CR-001, phase 6a): turns on one thread, the transcript written with
each checkpoint, one active turn, HITL and cancel in chat, session hooks, the
session stream and the session/agents API. SC1-SC4, SC7-SC11."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest

from agent_runtime.api.app import create_app
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.queue import RedisWorkQueue
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.runs.store import Run
from agent_runtime.sessions.service import SessionService
from agent_runtime.sessions.store import (
    Message,
    NewMessage,
    SessionArchived,
    SessionRepository,
    TurnActive,
)
from agent_runtime.sessions.transcript import transcript_of
from agent_runtime.streaming.bus import EventBus, RedisEventBus
from agent_runtime.tools.hooks import (
    Context,
    Deny,
    default_hooks,
)
from tests.integration.support import wait_until
from tests.integration.test_stream import Server
from tests.sse import read_sse

pytestmark = pytest.mark.integration
GRAPHS = default_registry()


def call(name: str, **args: Any) -> dict[str, Any]:
    return {"name": name, "args": args}


def tools(*calls: dict[str, Any]) -> dict[str, Any]:
    return {"tool_calls": list(calls)}


def say(text: str) -> dict[str, Any]:
    return {"content": text}


def sessions(pool: Pool, settings: Settings, bus: EventBus | None = None) -> SessionService:
    runs = RunService(pool, settings, GRAPHS, bus=bus)  # as in the app: both publish
    return SessionService(pool, settings, GRAPHS, runs, bus=bus)


async def chat(pool: Pool, settings: Settings) -> uuid.UUID:
    return (await sessions(pool, settings).create("chat", "test")).id


async def turn(
    pool: Pool, settings: Settings, session_id: uuid.UUID, text: str,
    script: list[dict[str, Any]], **kw: Any,
) -> Run:  # fmt: skip
    sent = await sessions(pool, settings).send(session_id, text, script=script)
    return await RunExecutor(pool, settings, GRAPHS, **kw).execute(sent.run.id)


async def transcript(pool: Pool, session_id: uuid.UUID) -> list[Message]:
    async with pool.connection() as conn:
        return await SessionRepository(conn).messages(session_id, limit=1000)


def kinds(messages: list[Message]) -> list[str]:
    return [m.type for m in messages]


async def thread_messages(pool: Pool, session_id: uuid.UUID) -> list[Any]:
    """The agent's context: the session thread's messages in its latest checkpoint."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with pool.connection() as conn:
        graph = GRAPHS.get("chat").compile(AsyncPostgresSaver(conn))
        state = await graph.aget_state({"configurable": {"thread_id": str(session_id)}})
    return list(state.values.get("messages", []))


# ------------------------------------------------------- turns & transcript


async def test_a_session_carries_its_context_across_turns_and_the_transcript_matches(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, sandbox: Settings
) -> None:
    sid = await chat(pool, test_settings)
    t1 = await turn(pool, test_settings, sid, "what is 6*7?",
                    [tools(call("run_python", code="print(6*7)")), say("42")])  # fmt: skip
    t2 = await turn(pool, test_settings, sid, "remember that",
                    [tools(call("save_note", text="the answer is ${run_python[0].stdout}")),
                     say("Noted.")])  # fmt: skip
    # Turn 3 uses turn 1's tool result: only possible if the context carried over.
    t3 = await turn(pool, test_settings, sid, "double it",
                    [tools(call("run_python", code="print(${run_python[0].stdout} * 2)")),
                     say("84")])  # fmt: skip
    assert [r.status for r in (t1, t2, t3)] == [S.COMPLETED] * 3
    assert {r.thread_id for r in (t1, t2, t3)} == {str(sid)}  # one thread (CR-001 D4)

    msgs = await transcript(pool, sid)
    assert kinds(msgs) == [
        "user", "system", "tool_call", "tool_result", "assistant",  # session_start context
        "user", "tool_call", "tool_result", "assistant",
        "user", "tool_call", "tool_result", "assistant",
    ]  # fmt: skip
    assert [m.seq for m in msgs] == list(range(1, len(msgs) + 1))  # SC4: gap-free, in order
    results = [m.content for m in msgs if m.type == "tool_result"]
    assert results[1]["result"] == {"note_id": results[1]["result"]["note_id"]}
    assert results[2]["result"]["stdout"] == "84\n"  # turn 3 saw turn 1
    assert all("cached" in r and "duration_ms" in r for r in results)

    # SC3 / R12.4: the transcript is exactly the projection of the checkpoint.
    state = await thread_messages(pool, sid)
    expected = [m for r in (t1, t2, t3) for m in transcript_of(state, r.id)]
    produced = [m for m in msgs if m.type != "user"]
    assert [(m.message_id, m.type, m.content) for m in produced] == [
        (e.message_id, e.type, e.content) for e in expected
    ]


async def test_the_transcript_is_deterministic_and_fenced(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    sid = await chat(pool, test_settings)
    done = await turn(pool, test_settings, sid, "hi", [say("hello")])
    before = await transcript(pool, sid)
    state = await thread_messages(pool, sid)
    async with pool.connection() as conn, conn.transaction():
        again = await SessionRepository(conn).append(
            sid, transcript_of(state, done.id), run_id=done.id, epoch=done.epoch
        )
    assert again == [] and await transcript(pool, sid) == before  # re-committed: nothing new
    async with pool.connection() as conn:
        await conn.execute("UPDATE runs SET epoch = epoch + 1 WHERE id = %s", (done.id,))
    with pytest.raises(psycopg.DatabaseError, match="fenced: write with stale epoch"):
        async with pool.connection() as conn, conn.transaction():
            await SessionRepository(conn).append(
                sid, [NewMessage("x" * 64, "assistant", {"text": "zombie"})],
                run_id=done.id, epoch=done.epoch,
            )  # fmt: skip


# ----------------------------------------------------------- one active turn


async def test_only_one_turn_can_be_active(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    service = sessions(pool, test_settings)
    sid = await chat(pool, test_settings)
    first = await service.send(sid, "one", script=[say("1")])
    with pytest.raises(TurnActive) as info:
        await service.send(sid, "two", script=[say("2")])
    assert info.value.run_id == first.run.id

    racing = await chat(pool, test_settings)  # SC2: 20 concurrent sends → exactly one
    outcomes = await asyncio.gather(
        *(service.send(racing, f"m{i}", script=[say("x")]) for i in range(20)),
        return_exceptions=True,
    )
    accepted = [o for o in outcomes if not isinstance(o, BaseException)]
    assert len(accepted) == 1
    assert all(isinstance(o, TurnActive) for o in outcomes if isinstance(o, BaseException))
    assert kinds(await transcript(pool, racing)) == ["user"]


# -------------------------------------------------------------- HITL & cancel


async def test_an_approval_inside_a_chat(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    service = sessions(pool, test_settings)
    sid = await chat(pool, test_settings)
    paused = await turn(pool, test_settings, sid, "tell ops",
                        [tools(call("notify", to="ops", message="hi")), say("Done.")])  # fmt: skip
    assert paused.status is S.WAITING_APPROVAL
    with pytest.raises(TurnActive, match="waiting_approval"):  # SC8: no message meanwhile
        await service.send(sid, "hello?", script=[say("x")])
    await service.approve(sid, "approve", {"args": {"to": "ops", "message": "hi (ok)"}})
    done = await RunExecutor(pool, test_settings, GRAPHS).execute(paused.id)
    assert done.status is S.COMPLETED
    msgs = await transcript(pool, sid)
    assert kinds(msgs) == ["user", "system", "tool_call", "interrupt", "approval", "tool_result",
                           "assistant"]  # fmt: skip
    interrupt, approval = msgs[3], msgs[4]
    assert interrupt.content["interrupt_type"] == "tool_approval"
    assert approval.content["decision"] == "approve"
    assert approval.content["edits"] == {"args": {"to": "ops", "message": "hi (ok)"}}


async def test_cancelling_a_turn_keeps_the_session_usable(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    service = sessions(pool, test_settings)
    sid = await chat(pool, test_settings)
    queued = await service.send(sid, "never mind", script=[say("x")])
    cancelled = await service.cancel(sid)
    assert cancelled.id == queued.run.id and cancelled.status is S.CANCELLED  # SC9
    assert (await service.get(sid)).status == "active"
    after = await turn(pool, test_settings, sid, "again", [say("ok")])
    assert after.status is S.COMPLETED
    assert kinds(await transcript(pool, sid)) == ["user", "error", "user", "system", "assistant"]


async def test_a_turn_after_one_that_ended_mid_tool_call_is_repaired(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    """A turn that fails mid-tools leaves AI tool calls with no results, which providers
    reject. The next turn first closes them (as its own `tool_result` rows)."""
    service = sessions(pool, test_settings)
    sid = await chat(pool, test_settings)
    sent = await service.send(
        sid,
        "two notes",
        {"max_tool_calls": 1},
        script=[tools(call("save_note", text="one"), call("save_note", text="two"))],
    )
    failed = await RunExecutor(pool, test_settings, GRAPHS).execute(sent.run.id)
    assert (failed.status, failed.reason) == (S.FAILED, "budget:tool_calls")
    state = await thread_messages(pool, sid)
    assert len(state[-1].tool_calls) == 2  # the dangling AI message

    ok = await turn(pool, test_settings, sid, "next", [say("fine")])
    assert ok.status is S.COMPLETED
    msgs = await transcript(pool, sid)
    repairs = [m for m in msgs if m.run_id == ok.id and m.type == "tool_result"]
    assert len(repairs) == 2 and all("did not run" in m.content["error"] for m in repairs)
    state = await thread_messages(pool, sid)
    answered = {m.tool_call_id for m in state if hasattr(m, "tool_call_id")}
    assert all(tc["id"] in answered for m in state for tc in getattr(m, "tool_calls", []))


# --------------------------------------------------------------- session hooks


async def test_session_start_runs_once_even_when_the_first_turn_is_reclaimed(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    """AC35 (part) and AC19 in-process: the first turn's worker dies in a tool call."""
    fast = test_settings.model_copy(update={"lease_ttl_s": 1.0, "heartbeat_s": 0.3})
    service = sessions(pool, fast)
    sid = await chat(pool, fast)
    sent = await service.send(sid, "keep this", script=[
        tools(call("save_note", text="kept", linger_s=1.5)), say("Kept."),
    ])  # fmt: skip
    worker_a = asyncio.create_task(RunExecutor(pool, fast, GRAPHS, owner="w-a:1").execute(
        sent.run.id))  # fmt: skip

    async def noted() -> bool:
        async with pool.connection() as conn:
            cur = await conn.execute("SELECT 1 FROM notes WHERE run_id = %s", (sent.run.id,))
            return await cur.fetchone() is not None

    await wait_until(noted, timeout_s=10)
    worker_a.cancel()
    await asyncio.gather(worker_a, return_exceptions=True)
    await asyncio.sleep(fast.lease_ttl_s + 0.2)
    done = await RunExecutor(pool, fast, GRAPHS, owner="w-b:2").execute(sent.run.id)
    assert done.status is S.COMPLETED and done.epoch == 2
    await turn(pool, fast, sid, "and now?", [say("still here")])

    msgs = await transcript(pool, sid)
    assert kinds(msgs) == ["user", "system", "tool_call", "tool_result", "assistant",
                           "user", "assistant"]  # zero duplicates after the reclaim  # fmt: skip
    state = await thread_messages(pool, sid)
    starts = [m for m in state if "conversation started" in str(m.content)]
    assert len(starts) == 1  # session_start ran exactly once


async def test_turn_hooks_can_add_context_deny_a_turn_and_observe_its_end(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    from agent_runtime.agents.schema import MainAgentHooks
    from agent_runtime.graphs import GraphRegistry
    from agent_runtime.graphs.assistant import agent_spec
    from agent_runtime.tools.builtin import default_tools

    ended: list[tuple[str, str | None]] = []
    hooks = default_hooks()

    @hooks.hook("gatekeeper", point="turn_start")
    async def gatekeeper(inp: Any) -> Any:
        if "forbidden" in inp.message:
            return Deny("that topic is off limits")
        return Context([f"(turn for: {inp.message})"])

    @hooks.hook("recorder", point="turn_end")
    async def recorder(inp: Any) -> None:
        ended.append((inp.status, inp.reason))

    base = GRAPHS.get("chat").agent
    assert base is not None
    fm = base.frontmatter.model_copy(update={"hooks": MainAgentHooks(
        turn_start=["gatekeeper"], turn_end=["recorder"])})  # fmt: skip
    graphs = GraphRegistry([agent_spec(base.model_copy(update={"frontmatter": fm}),
                                       default_tools())])  # fmt: skip
    service = SessionService(pool, test_settings, graphs, RunService(pool, test_settings, graphs))
    sid = (await service.create("chat")).id
    ok = await service.send(sid, "hello", script=[say("hi")])
    done = await RunExecutor(pool, test_settings, graphs, hooks=hooks).execute(ok.run.id)
    bad = await service.send(sid, "something forbidden", script=[say("x")])
    denied = await RunExecutor(pool, test_settings, graphs, hooks=hooks).execute(bad.run.id)
    assert done.status is S.COMPLETED
    assert (denied.status, denied.reason) == (S.FAILED, "turn_denied")
    assert ended == [("completed", None), ("failed", "turn_denied")]
    msgs = await transcript(pool, sid)
    assert kinds(msgs) == ["user", "system", "assistant", "user", "error"]
    assert msgs[1].content == {"text": "(turn for: hello)"}


async def test_archiving_runs_session_end_once_and_stores_the_summary(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    service = sessions(pool, test_settings)
    sid = await chat(pool, test_settings)
    await turn(pool, test_settings, sid, "6*7?", [tools(call("calculator", expression="6*7")),
                                                  say("It is 42.")])  # fmt: skip
    end = await service.archive(sid)
    assert end is not None and end.kind == "session_end"
    assert await service.archive(sid) is None  # exactly once
    with pytest.raises(SessionArchived):
        await service.send(sid, "more?", script=[say("x")])
    done = await RunExecutor(pool, test_settings, GRAPHS).execute(end.id)
    assert done.status is S.COMPLETED
    session = await service.get(sid)
    assert session.summary == "1 turn(s), 1 tool call(s), 0 error(s). Last answer: It is 42."


async def test_idle_sessions_are_archived_with_the_same_session_end(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    service = sessions(pool, test_settings)
    idle, fresh = await chat(pool, test_settings), await chat(pool, test_settings)
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE sessions SET last_activity_at = now() - interval '2 days' WHERE id = %s",
            (idle,),
        )
    assert await service.archive_idle(24 * 3600) >= 1
    assert await service.archive_idle(24 * 3600) == 0  # idempotent
    assert (await service.get(idle)).status == "archived"
    assert (await service.get(fresh)).status == "active"
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT count(*) AS n FROM runs WHERE kind = 'session_end' "
            "AND input->>'session_id' = %s", (str(idle),),
        )  # fmt: skip
        assert await cur.fetchone() == {"n": 1}


# ------------------------------------------------------------------- the API


@pytest.fixture
def bus(queue: RedisWorkQueue) -> EventBus:
    return RedisEventBus(queue._r)


@pytest.fixture
async def api(
    pool: Pool, test_settings: Settings, queue: RedisWorkQueue, bus: EventBus,
    checkpoint_tables: None,
) -> AsyncIterator[Server]:  # fmt: skip
    settings = test_settings.model_copy(update={"stream_ping_s": 0.3, "stream_poll_s": 1.0})
    async with Server(create_app(settings, pool=pool, queue=queue, bus=bus)) as server:
        yield server


async def test_the_session_api_and_stream(
    api: Server, pool: Pool, test_settings: Settings, bus: EventBus
) -> None:
    c = api.client
    created = await c.post("/sessions", json={"agent": "chat", "title": "first"})
    assert created.status_code == 201
    sid = created.json()["id"]
    assert (await c.post("/sessions", json={"agent": "fanout"})).status_code == 422
    assert (await c.post("/sessions", json={"agent": "nope"})).status_code == 404

    sent = await c.post(f"/sessions/{sid}/messages",
                        json={"content": "6*7?", "script": [
                            tools(call("calculator", expression="6*7")), say("42")]})  # fmt: skip
    assert sent.status_code == 202
    busy = await c.post(f"/sessions/{sid}/messages", json={"content": "and?"})
    assert busy.status_code == 409 and busy.json()["type"].endswith("/turn-active")
    assert busy.json()["run_id"] == sent.json()["run_id"]

    stream = asyncio.create_task(read_sse(c, f"/sessions/{sid}/stream", stop_after=5))
    await asyncio.sleep(0.3)  # subscribed: the rest arrives live, from a worker elsewhere
    executor = RunExecutor(pool, test_settings, GRAPHS, bus=bus)
    await executor.execute(uuid.UUID(sent.json()["run_id"]))
    got = await stream
    assert got.seqs == [1, 2, 3, 4, 5]  # SC7: every message once, in order, with id: seq
    assert [json.loads(e["data"])["payload"]["type"] for e in got.events if e.get("id")] == [
        "user", "system", "tool_call", "tool_result", "assistant"]  # fmt: skip
    resumed = await read_sse(c, f"/sessions/{sid}/stream", headers={"Last-Event-ID": "3"},
                             stop_after=2)  # fmt: skip
    assert resumed.seqs == [4, 5]

    page = (await c.get(f"/sessions/{sid}/messages", params={"after_seq": 2})).json()
    assert [m["seq"] for m in page["messages"]] == [3, 4, 5]
    view = (await c.get(f"/sessions/{sid}")).json()
    assert (view["messages"], view["active_run_id"], view["title"]) == (5, None, "first")
    renamed = await c.patch(f"/sessions/{sid}", json={"title": "renamed"})
    assert renamed.json()["title"] == "renamed"
    listed = (await c.get("/sessions", params={"status": "active", "limit": 5})).json()
    assert listed[0]["id"] == sid  # newest activity first
    archived = await c.patch(f"/sessions/{sid}", json={"status": "archived"})
    assert archived.json()["status"] == "archived"
    late = await c.post(f"/sessions/{sid}/messages", json={"content": "hello?"})
    assert late.status_code == 409 and late.json()["type"].endswith("/session-archived")
    assert (await c.post(f"/sessions/{sid}/cancel")).status_code == 409  # no active turn

    agents = (await c.get("/agents")).json()  # SC11 / R15.11
    chat_agent = next(a for a in agents if a["name"] == "chat")
    assert chat_agent["hooks"]["session_start"] == ["session_clock"]
    assert chat_agent["prompt"] is None
    detail = (await c.get("/agents/delegator")).json()
    assert detail["subagents"] == ["mathematician", "napper", "scribe"]
    helpers = {h["name"]: h for h in detail["helpers"]}  # the sub-agents, for the UI
    assert set(helpers) == {"mathematician", "napper", "scribe"}
    assert helpers["mathematician"]["description"] and helpers["mathematician"]["prompt"]
    assert all(h["prompt"] is None for h in chat_agent["helpers"])  # the list stays light
    assert "coordinate specialists" in detail["prompt"]
    assert (await c.get("/agents/toy")).status_code == 404


# ------------------------------------------------- the UI's signals (phase L2)


async def _turn_statuses(sub: Any) -> list[str]:
    out = []
    while (got := await sub.get(0.05)) is not None:
        if got[1].type == "turn.status":
            out.append(got[1].payload["status"])
    return out


async def test_the_session_stream_says_when_a_turn_starts_waits_and_ends(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    from agent_runtime.streaming.bus import InMemoryEventBus, session_channel

    bus = InMemoryEventBus()
    service = sessions(pool, test_settings, bus)
    sid = (await service.create("chat", "signals")).id
    sub = bus.subscription()
    await sub.subscribe(session_channel(sid))

    sent = await service.send(sid, "tell ops", script=[
        tools(call("notify", to="ops", message="hi")), say("Done.")])  # fmt: skip
    paused = await RunExecutor(pool, test_settings, GRAPHS, bus=bus).execute(sent.run.id)
    assert paused.status is S.WAITING_APPROVAL
    assert await _turn_statuses(sub) == ["queued", "running", "waiting_approval"]

    await service.approve(sid, "approve", None)
    done = await RunExecutor(pool, test_settings, GRAPHS, bus=bus).execute(sent.run.id)
    assert done.status is S.COMPLETED
    assert await _turn_statuses(sub) == ["queued", "running", "completed"]

    queued = await service.send(sid, "never mind", script=[say("x")])
    await service.cancel(sid)
    assert await _turn_statuses(sub) == ["queued", "cancelled"]
    await sub.close()
    assert queued.run.id != sent.run.id


async def test_the_demo_model_answers_free_text_with_its_tools(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, sandbox: Settings
) -> None:
    """MODEL_PROVIDER=scripted and no script: the demo responder picks one, and stores
    it in the run's input (so a replay reads the same script back)."""
    service = sessions(pool, test_settings)
    sid = await chat(pool, test_settings)
    sent = await service.send(sid, "What is 12 * (3 + 4)?")
    assert sent.run.input["script"][0]["tool_calls"][0]["args"] == {"code": "print(12 * (3 + 4))"}
    done = await RunExecutor(pool, test_settings, GRAPHS).execute(sent.run.id)
    assert done.status is S.COMPLETED
    msgs = await transcript(pool, sid)
    result = next(m for m in msgs if m.type == "tool_result")
    assert result.content["result"]["stdout"] == "84\n"  # computed in the sandbox
    assert "**84**" in msgs[-1].content["text"]

    help_turn = await service.send(sid, "hello there")  # nothing matches: how to use it
    await RunExecutor(pool, test_settings, GRAPHS).execute(help_turn.run.id)
    assert "demo model" in (await transcript(pool, sid))[-1].content["text"]

"""The chat agent (phase 6c): live tokens, a reply cancelled mid-stream (R12.7), and
parallel sub-agents inside a chat (CR-005 AC37, AC39), with the scripted model.
SC19, SC21, SC22."""

import asyncio
import uuid
from typing import Any

import pytest
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.models.scripted import ScriptedChatModel
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.sessions.service import SessionService
from agent_runtime.sessions.store import Message, SessionRepository
from agent_runtime.streaming.bus import InMemoryEventBus, StreamEvent, session_channel

pytestmark = pytest.mark.integration
GRAPHS = default_registry()


def streaming(settings: Settings, delay: float = 0.0) -> Settings:
    return settings.model_copy(
        update={"scripted_streaming": True, "scripted_stream_delay_s": delay}
    )


async def listen(bus: InMemoryEventBus, channel: str, into: list[StreamEvent]) -> None:
    sub = bus.subscription()
    await sub.subscribe(channel)
    while True:
        got = await sub.get(0.05)
        if got is not None:
            into.append(got[1])


async def chat_turn(
    pool: Pool, settings: Settings, bus: InMemoryEventBus, text: str,
    script: list[dict[str, Any]], subs: dict[str, list[dict[str, Any]]] | None = None,
) -> tuple[uuid.UUID, Any, list[StreamEvent]]:  # fmt: skip
    service = SessionService(pool, settings, GRAPHS, RunService(pool, settings, GRAPHS), bus=bus)
    sid = (await service.create("chat")).id
    seen: list[StreamEvent] = []
    listener = asyncio.create_task(listen(bus, session_channel(sid), seen))
    await asyncio.sleep(0.05)
    sent = await service.send(sid, text, script=script, subagent_scripts=subs)
    run = await RunExecutor(pool, settings, GRAPHS, bus=bus, owner="w-1:1").execute(sent.run.id)
    await asyncio.sleep(0.1)
    listener.cancel()
    return sid, run, seen


async def transcript(pool: Pool, sid: uuid.UUID) -> list[Message]:
    async with pool.connection() as conn:
        return await SessionRepository(conn).messages(sid, limit=500)


# ------------------------------------------------------------------ tokens


async def test_tokens_stream_live_and_the_reply_is_persisted_once(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    bus = InMemoryEventBus()
    reply = "Redis Streams keep work in memory with consumer groups and acknowledgements."
    sid, run, seen = await chat_turn(pool, streaming(test_settings), bus, "compare",
                                     [{"content": reply}])  # fmt: skip
    assert run.status is S.COMPLETED
    tokens = [e for e in seen if e.type == "token"]
    assert tokens and all(e.seq is None for e in tokens)  # transient: no seq, never replayed
    assert "".join(e.payload["text"] for e in tokens) == reply  # SC19: the whole reply, live
    msgs = await transcript(pool, sid)
    assistants = [m for m in msgs if m.type == "assistant"]
    assert [m.content["text"] for m in assistants] == [reply]  # persisted once, complete


async def test_a_reply_cancelled_mid_stream_is_kept_as_interrupted(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    """R12.7: the user stops a long reply; the turn ends cancelled and the text already
    streamed is persisted, marked interrupted. The session stays usable."""
    bus = InMemoryEventBus()
    settings = streaming(test_settings, delay=0.05)
    long_reply = " ".join(f"word{i}" for i in range(80))  # ~4 s at 50 ms per word
    service = SessionService(pool, settings, GRAPHS, RunService(pool, settings, GRAPHS), bus=bus)
    sid = (await service.create("chat")).id
    sent = await service.send(sid, "tell me everything", script=[{"content": long_reply}])
    turn = asyncio.create_task(RunExecutor(pool, settings, GRAPHS, bus=bus).execute(sent.run.id))
    await asyncio.sleep(1.0)  # mid-reply
    await service.cancel(sid)
    ended = await turn
    assert (ended.status, ended.reason) == (S.CANCELLED, "cancel_requested")
    msgs = await transcript(pool, sid)
    partial = next(m for m in msgs if m.type == "assistant")
    assert partial.content["interrupted"] is True
    words = partial.content["text"].split()
    assert 5 <= len(words) < 80 and long_reply.startswith(partial.content["text"])
    assert msgs[-1].type == "error"
    assert (await service.get(sid)).status == "active"


# --------------------------------------------- sub-agents in a chat (AC37, AC39)


@pytest.fixture
def requests(monkeypatch: pytest.MonkeyPatch) -> list[list[BaseMessage]]:
    seen: list[list[BaseMessage]] = []
    real = ScriptedChatModel._agenerate

    async def spy(self: ScriptedChatModel, messages: list[BaseMessage], *a: Any, **kw: Any) -> Any:
        seen.append(list(messages))
        return await real(self, messages, *a, **kw)

    monkeypatch.setattr(ScriptedChatModel, "_agenerate", spy)
    return seen


def call(name: str, **args: Any) -> dict[str, Any]:
    return {"name": name, "args": args}


H = "${spawn_subagent[%d].handle}"


async def test_the_chat_agent_runs_researcher_and_data_analyst_in_parallel(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    requests: list[list[BaseMessage]],
) -> None:  # fmt: skip
    bus = InMemoryEventBus()
    script: list[dict[str, Any]] = [
        {"tool_calls": [
            call("spawn_subagent", agent="researcher", task="What are Redis Streams for?"),
            call("spawn_subagent", agent="data-analyst", task="12 workers x 4 slots: total?"),
        ]},
        {"tool_calls": [call("wait_subagents", handles=[H % 0, H % 1], timeout_s=30)]},
        {"tool_calls": [call("save_note", text="Both: ${wait_subagents[0].completed}")]},
        {"content": "Combined both results."},
    ]  # fmt: skip
    subs = {
        "researcher": [
            {"tool_calls": [call("search", query="redis streams vs kafka", k=2)]},
            {"tool_calls": [call("report_progress", message="read 2 sources", percent=80)]},
            {"tool_calls": [call("return_result", summary="Work queues with consumer groups "
                                 "(docs.example.org/redis/streams-intro).")]},
        ],
        "data-analyst": [
            {"tool_calls": [call("calculator", expression="12*4")]},
            {"tool_calls": [call("search", query="anything")]},  # not its tool: denied
            {"tool_calls": [call("return_result", summary="48 slots (12 x 4).")]},
        ],
    }  # fmt: skip
    _, run, seen = await chat_turn(pool, test_settings, bus, "research and compute",
                                     script, subs)  # fmt: skip
    from tests.integration.support import events

    evts = await events(pool, run.id)
    failure = [e.payload for e in evts if e.type == "run.failed"]
    assert run.status is S.COMPLETED, failure
    spawned = [e.payload for e in evts if e.type == "subagent.spawned"]
    assert {p["agent"] for p in spawned} == {"chat/researcher", "chat/data-analyst"}
    assert {p["worker"] for p in spawned} == {"w-1:1"}  # AC37: the main run's worker
    relayed = [e.type for e in seen if e.type.startswith("subagent.")]
    assert relayed.count("subagent.progress") == 1  # live on the SESSION stream
    assert relayed.count("subagent.completed") == 2

    async with pool.connection() as conn:
        cur = await conn.execute("SELECT text FROM notes WHERE run_id = %s", (run.id,))
        (note,) = await cur.fetchall()
    assert "Work queues with consumer groups" in note["text"] and "48 slots" in note["text"]

    # AC39: the researcher's first request is its own prompt and the task, nothing else.
    first = next(m for m in requests if any(
        isinstance(x, SystemMessage) and "You research exactly one question" in str(x.content)
        for x in m))  # fmt: skip
    assert [type(m) for m in first] == [SystemMessage, HumanMessage]
    assert first[1].content == "What are Redis Streams for?"
    denied = [e.payload for e in evts if e.type == "policy.decision"]
    assert any(p["tool"] == "search" and p["kind"] == "not_granted" for p in denied)

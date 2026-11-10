"""Phase H5: a chat can go on for hundreds of turns. What the model is sent stays inside
its window, older turns are folded into a summary, and the checkpoints behind the chat
stay flat."""

import uuid
from collections.abc import Callable
from typing import Any

import psycopg
import pytest
from langchain_core.messages import BaseMessage, ToolMessage

from agent_runtime.config import Settings
from agent_runtime.context.fit import estimate
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.models.scripted import ScriptedChatModel
from agent_runtime.runs.events import EventType as E
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.runs.store import NotRedrivable, Run
from agent_runtime.sessions.service import SessionService
from agent_runtime.sessions.store import SessionRepository
from tests.integration.support import events

pytestmark = pytest.mark.integration
GRAPHS = default_registry()
WINDOW = 8_192


def call(name: str, **args: Any) -> dict[str, Any]:
    return {"tool_calls": [{"name": name, "args": args}]}


def say(text: str) -> dict[str, Any]:
    return {"content": text}


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The estimated size of every request the model actually received."""
    sizes: list[int] = []
    real = ScriptedChatModel._agenerate

    async def spy(self: ScriptedChatModel, messages: list[BaseMessage], *a: Any, **kw: Any) -> Any:
        sizes.append(estimate(messages))
        return await real(self, messages, *a, **kw)

    monkeypatch.setattr(ScriptedChatModel, "_agenerate", spy)
    return sizes


def small(settings: Settings) -> Settings:
    return unlimited(settings).model_copy(update={"context_tokens": WINDOW})


def unlimited(settings: Settings) -> Settings:
    """A test chat sends faster than a person: no per-minute limit (R14.8)."""
    return settings.model_copy(update={"session_messages_per_minute": 1_000_000})


async def thread_bytes(pool: Pool, thread_id: str) -> int:
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT coalesce((SELECT sum(pg_column_size(c.*)) FROM checkpoints c
                             WHERE thread_id = %(t)s), 0)
                 + coalesce((SELECT sum(pg_column_size(b.*)) FROM checkpoint_blobs b
                             WHERE thread_id = %(t)s), 0)
                 + coalesce((SELECT sum(pg_column_size(w.*)) FROM checkpoint_writes w
                             WHERE thread_id = %(t)s), 0) AS bytes
            """,
            {"t": thread_id},
        )
        row = await cur.fetchone()
    return int(row["bytes"]) if row else 0


async def checkpoints(pool: Pool, thread_id: str) -> int:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT count(*) AS n FROM checkpoints WHERE thread_id = %s", (thread_id,)
        )
        row = await cur.fetchone()
    return int(row["n"]) if row else 0


def chats(pool: Pool, settings: Settings) -> SessionService:
    return SessionService(pool, settings, GRAPHS, RunService(pool, settings, GRAPHS))


async def chat_turn(
    pool: Pool, settings: Settings, sid: uuid.UUID, text: str, script: list[dict[str, Any]]
) -> Run:
    turn = await chats(pool, settings).send(sid, text, script=script)
    return await RunExecutor(pool, settings, GRAPHS).execute(turn.run.id)


# ------------------------------------------------------------ the 200-turn chat


async def test_a_200_turn_chat_stays_inside_its_window_and_its_storage_stays_flat(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, sent: list[int]
) -> None:
    settings = small(test_settings)
    sid = (await chats(pool, settings).create("chat")).id
    sizes: dict[int, int] = {}
    for i in range(1, 201):
        marker = f"t{i:03d}"
        done = await chat_turn(pool, settings, sid, f"keep {marker}", [
            call("save_note", text=f"{marker} " + "lorem ipsum " * 160),  # ~2k characters
            call("recall_notes", query="lorem", limit=2),  # ~4k characters back
            say(f"Kept {marker}."),
        ])  # fmt: skip
        assert done.status is S.COMPLETED, (i, done.reason)
        if i in (50, 200):
            sizes[i] = await thread_bytes(pool, str(sid))
    assert max(sent) <= WINDOW, f"a request of {max(sent)} tokens was sent"
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT count(*) AS n FROM run_events e JOIN runs r ON r.id = e.run_id "
            "WHERE r.session_id = %s AND e.type = 'context.compacted'", (sid,),
        )  # fmt: skip
        compactions = (await cur.fetchone() or {"n": 0})["n"]
        msgs = await SessionRepository(conn).messages(sid, limit=10_000)
    assert compactions >= 10
    assert sizes[200] <= 1.5 * sizes[50], sizes  # flat, not growing with turns²
    assert await checkpoints(pool, str(sid)) == 1  # pruned after every turn
    # The transcript keeps everything: every question, every answer, in full.
    assert sum(m.type == "user" for m in msgs) == 200
    calls = [m.content["tool_call_id"] for m in msgs if m.type == "tool_call"]
    assert len(calls) == len(set(calls)) == 400  # ids stay unique after compactions
    answers = [m.content["text"] for m in msgs if m.type == "assistant"]
    assert answers[0] == "Kept t001." and answers[-1] == "Kept t200." and len(answers) == 200


async def test_the_compacted_thread_has_one_summary_marked_as_data(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    settings = small(test_settings)
    sid = (await chats(pool, settings).create("chat")).id
    for i in range(12):
        await chat_turn(pool, settings, sid, f"turn {i}", [
            call("save_note", text=f"n{i} " + "word " * 400), say(f"done {i}")])  # fmt: skip
    async with pool.connection() as conn:
        graph = GRAPHS.get("chat").compile(AsyncPostgresSaver(conn))
        state = await graph.aget_state({"configurable": {"thread_id": str(sid)}})
    messages = state.values["messages"]
    summaries = [m for m in messages if (m.id or "").startswith("summary:")]
    assert len(summaries) == 1 and messages[0] is summaries[0]
    assert '<data source="summary">' in str(summaries[0].content)
    assert "turn 0" in str(summaries[0].content)  # the oldest turn survives, summarised
    ev = [e for r in await _runs(pool, sid) for e in await events(pool, r)
          if e.type == E.CONTEXT_COMPACTED]  # fmt: skip
    assert ev and ev[-1].payload["how"] == "extract"  # the scripted model: no model call
    assert ev[-1].payload["tokens_after"] < ev[-1].payload["tokens_before"]


async def _runs(pool: Pool, sid: uuid.UUID) -> list[uuid.UUID]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id FROM runs WHERE session_id = %s ORDER BY created_at", (sid,)
        )
        return [r["id"] for r in await cur.fetchall()]


# ------------------------------------------------- one long turn: fitted per call


async def test_a_long_turn_is_fitted_per_call_and_its_state_keeps_everything(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, sent: list[int]
) -> None:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    settings = small(test_settings)
    sid = (await chats(pool, settings).create("chat")).id
    await chat_turn(pool, settings, sid, "seed", [
        call("save_note", text="seed " + "lorem ipsum " * 160), say("ok")])  # fmt: skip
    sent.clear()
    # Different calls (the same one repeated is a loop, R14.4), each with a big result.
    script = [call("recall_notes", query="lorem", limit=20 - i) for i in range(8)] + [say("Read.")]
    done = await chat_turn(pool, settings, sid, "read them all", script)
    assert done.status is S.COMPLETED
    assert max(sent) <= WINDOW
    trimmed = [e for e in await events(pool, done.id) if e.type == E.CONTEXT_TRIMMED]
    assert trimmed and trimmed[-1].payload["cleared"] > 0
    async with pool.connection() as conn:
        graph = GRAPHS.get("chat").compile(AsyncPostgresSaver(conn))
        state = await graph.aget_state({"configurable": {"thread_id": str(sid)}})
    results = [m for m in state.values["messages"] if isinstance(m, ToolMessage)]
    assert all("cleared to make room" not in str(m.content) for m in results)  # sent only


# ------------------------------------------------------- the model says "too long"


@pytest.fixture
def refusing(monkeypatch: pytest.MonkeyPatch) -> Callable[[int], list[int]]:
    """The model refuses any request over `limit` tokens, like OpenAI does."""

    class BadRequest(Exception):
        code = "context_length_exceeded"

    def arm(limit: int) -> list[int]:
        refusals = [0]
        real = ScriptedChatModel._agenerate

        async def gen(self: ScriptedChatModel, messages: list[BaseMessage], *a: Any,
                      **kw: Any) -> Any:  # fmt: skip
            if estimate(messages) > limit:
                refusals[0] += 1
                raise BadRequest(f"This model's maximum context length is {limit} tokens.")
            return await real(self, messages, *a, **kw)

        monkeypatch.setattr(ScriptedChatModel, "_agenerate", gen)
        return refusals

    return arm


async def test_a_too_long_refusal_is_fitted_again_and_answered(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    refusing: Callable[[int], list[int]],
) -> None:  # fmt: skip
    sid = (await chats(pool, test_settings).create("chat")).id  # a 128k window, it thinks
    for i in range(3):
        await chat_turn(pool, test_settings, sid, f"keep {i}", [
            call("save_note", text=f"k{i} " + "lorem ipsum " * 160), say("ok")])  # fmt: skip
    refusals = refusing(3_000)
    done = await chat_turn(pool, test_settings, sid, "read", [
        call("recall_notes", query="lorem", limit=3), call("recall_notes", query="ipsum", limit=3),
        say("Done.")])  # fmt: skip
    assert done.status is S.COMPLETED and refusals[0] >= 1
    trimmed = [e.payload for e in await events(pool, done.id) if e.type == E.CONTEXT_TRIMMED]
    assert any(p.get("refused") for p in trimmed)


async def test_a_request_that_can_never_fit_fails_as_context_overflow(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    refusing: Callable[[int], list[int]],
) -> None:  # fmt: skip
    sid = (await chats(pool, test_settings).create("chat")).id
    refusing(10)  # nothing fits in 10 tokens
    failed = await chat_turn(pool, test_settings, sid, "hello", [say("hi")])
    assert (failed.status, failed.reason) == (S.FAILED, "context_overflow")
    with pytest.raises(NotRedrivable):  # the same turn would overflow again
        await RunService(pool, test_settings, GRAPHS).redrive(failed.id)


# --------------------------------------------------------------------- pruning


async def test_a_finished_turn_keeps_one_checkpoint_and_the_chat_goes_on(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    sid = (await chats(pool, test_settings).create("chat")).id
    await chat_turn(pool, test_settings, sid, "6*7?", [call("calculator", expression="6*7"),
                                                       say("42.")])  # fmt: skip
    assert await checkpoints(pool, str(sid)) == 1
    again = await chat_turn(pool, test_settings, sid, "and doubled?", [say("84.")])
    assert again.status is S.COMPLETED and await checkpoints(pool, str(sid)) == 1


async def test_a_helpers_threads_go_with_its_run(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    script = [
        call("spawn_subagent", agent="scribe", task="note it"),
        call("wait_subagents", handles=["${spawn_subagent[0].handle}"], timeout_s=30),
        say("Done."),
    ]
    subs = {"scribe": [call("save_note", text="by the scribe"),
                       call("return_result", summary="done")]}  # fmt: skip
    run = await RunService(pool, test_settings, GRAPHS).create_run(
        "delegator", {"message": "go", "script": script, "subagent_scripts": subs}
    )
    done = await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)
    assert done.status is S.COMPLETED
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT thread_id FROM subagent_invocations WHERE run_id = %s", (run.id,)
        )
        threads = [r["thread_id"] for r in await cur.fetchall()]
    assert threads
    for thread in threads:
        assert await checkpoints(pool, thread) == 0
    assert await checkpoints(pool, run.thread_id) == 1


@pytest.fixture
async def as_worker(pool: Pool, test_settings: Settings, checkpoint_tables: None) -> Any:
    from agent_runtime.config import component_credentials
    from agent_runtime.db import create_pool
    from agent_runtime.dbadmin import grant_checkpoint_tables, provision_users

    if component_credentials("worker") is None:
        pytest.fail("WORKER_POSTGRES_USER/PASSWORD not set (see .env.example)")
    async with pool.connection() as conn:
        await provision_users(conn)
        await grant_checkpoint_tables(conn)
    async with create_pool(test_settings.for_component("worker"), max_size=2) as p:
        yield p


async def test_the_worker_can_prune_but_never_delete_checkpoints_itself(as_worker: Pool) -> None:
    async with as_worker.connection() as conn:
        await conn.execute("SELECT prune_checkpoints('no-such-thread', true, NULL)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await conn.execute("DELETE FROM checkpoints WHERE thread_id = 'x'")


async def test_a_failed_turn_is_still_redriven_from_its_pruned_thread(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    from agent_runtime.checkpointing import FencedCheckpointer

    real, fired = FencedCheckpointer.aput, [False]

    async def aput(self: FencedCheckpointer, *a: Any, **kw: Any) -> Any:
        if not fired[0]:
            async with pool.connection() as conn:
                cur = await conn.execute("SELECT 1 FROM notes WHERE run_id = %s",
                                         (self.fence.run_id,))  # fmt: skip
                if await cur.fetchone() is not None:
                    fired[0] = True
                    raise ValueError("a bug, after the note was saved")
        return await real(self, *a, **kw)

    monkeypatch.setattr(FencedCheckpointer, "aput", aput)
    sid = (await chats(pool, test_settings).create("chat")).id
    failed = await chat_turn(pool, test_settings, sid, "keep", [
        call("save_note", text="kept once"), say("Kept.")])  # fmt: skip
    assert failed.status is S.FAILED
    assert await checkpoints(pool, str(sid)) == 1  # pruned, as every finished run
    await RunService(pool, test_settings, GRAPHS).redrive(failed.id)
    done = await RunExecutor(pool, test_settings, GRAPHS).execute(failed.id)
    assert done.status is S.COMPLETED
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT count(*) AS n FROM notes WHERE run_id = %s",
                                 (failed.id,))  # fmt: skip
        assert (await cur.fetchone() or {})["n"] == 1  # not saved twice

"""Phase H8: memory across chats. What an agent saved is in every later chat's prompt,
for that agent only; it can forget, and a person can see, restore and delete."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from langchain_core.messages import BaseMessage, SystemMessage

from agent_runtime.api.app import create_app
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.evals.runner import run_suite, suites
from agent_runtime.graphs import default_registry
from agent_runtime.models.scripted import ScriptedChatModel
from agent_runtime.queue import RedisWorkQueue
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.sessions.service import SessionService
from agent_runtime.streaming.bus import RedisEventBus
from tests.integration.test_evals import AGENTS
from tests.integration.test_stream import Server

pytestmark = pytest.mark.integration
GRAPHS = default_registry()


def call(name: str, **args: Any) -> dict[str, Any]:
    return {"tool_calls": [{"name": name, "args": args}]}


def say(text: str) -> dict[str, Any]:
    return {"content": text}


@pytest.fixture
def prompts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The system message of every model call, in order."""
    seen: list[str] = []
    real = ScriptedChatModel._agenerate

    async def gen(self: ScriptedChatModel, messages: list[BaseMessage], *a: Any, **kw: Any) -> Any:
        seen.append(next((m.text for m in messages if isinstance(m, SystemMessage)), ""))
        return await real(self, messages, *a, **kw)

    monkeypatch.setattr(ScriptedChatModel, "_agenerate", gen)
    return seen


async def turn(
    pool: Pool, settings: Settings, text: str, script: list[dict[str, Any]],
    *, session_id: uuid.UUID | None = None, agent: str = "chat",
) -> tuple[uuid.UUID, Any]:  # fmt: skip
    service = SessionService(pool, settings, GRAPHS, RunService(pool, settings, GRAPHS))
    sid = session_id or (await service.create(agent)).id
    sent = await service.send(sid, text, script=script)
    return sid, await RunExecutor(pool, settings, GRAPHS).execute(sent.run.id)


async def result_of(pool: Pool, run_id: uuid.UUID, tool: str) -> Any:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT status, result FROM tool_invocations WHERE run_id = %s AND tool = %s",
            (run_id, tool),
        )
        return await cur.fetchone()


@pytest.fixture
async def api(
    pool: Pool, test_settings: Settings, queue: RedisWorkQueue, checkpoint_tables: None
) -> AsyncIterator[Server]:
    app = create_app(test_settings, pool=pool, queue=queue, bus=RedisEventBus(queue._r))
    async with Server(app) as server:
        yield server


# ---------------------------------------------------- 1. it's there, every chat


async def test_a_note_saved_in_one_chat_is_in_the_next_chats_prompt(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, no_memory: None,
    prompts: list[str],
) -> None:  # fmt: skip
    """The walkthrough's gap: the model had to think of calling recall_notes."""
    marker = uuid.uuid4().hex[:8]
    _, saved = await turn(pool, test_settings, "remember my locker code", [
        call("save_note", text=f"locker code is {marker}"), say("Saved.")])  # fmt: skip
    assert saved.status is S.COMPLETED
    prompts.clear()
    _, asked = await turn(pool, test_settings, "what's my locker code?", [say(marker)])
    assert asked.status is S.COMPLETED
    (system,) = prompts
    block = system[system.index('<data source="memory">') :]
    assert f"locker code is {marker}" in block.split("</data>")[0]
    assert system.index("## What you remember") < system.index("## Data")


async def test_memory_is_the_turns_snapshot_and_the_next_turn_sees_what_it_saved(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, no_memory: None,
    prompts: list[str],
) -> None:  # fmt: skip
    """Taken when the turn starts (and checkpointed with it): a turn taken over after a
    crash sees what it started with. The thread has what this turn saved anyway."""
    sid, done = await turn(pool, test_settings, "remember", [
        call("save_note", text="the demo is on Friday"), say("Saved.")])  # fmt: skip
    assert done.status is S.COMPLETED
    assert all("demo is on Friday" not in p for p in prompts)  # not in its own turn's memory
    prompts.clear()
    await turn(pool, test_settings, "and?", [say("ok")], session_id=sid)
    assert "demo is on Friday" in prompts[0]


async def test_the_snapshot_is_checkpointed_with_the_turn(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, no_memory: None
) -> None:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    await turn(pool, test_settings, "remember", [call("save_note", text="tea for Sam"),
                                                  say("Saved.")])  # fmt: skip
    sid, _ = await turn(pool, test_settings, "hi", [say("hello")])
    async with pool.connection() as conn:
        compiled = GRAPHS.get("chat").compile(AsyncPostgresSaver(conn))
        state = await compiled.aget_state({"configurable": {"thread_id": str(sid)}})
    memory = state.values["memory"]  # which notes, not their text (a deleted note's text
    async with pool.connection() as conn:  # mustn't live on in checkpoints)
        cur = await conn.execute("SELECT key FROM notes WHERE text = 'tea for Sam'")
        row = await cur.fetchone()
    assert row is not None and memory == {"keys": [row["key"]], "total": 1}
    assert "tea for Sam" not in str(state.values["memory"])


# --------------------------------------------------------------- 3. no leaks


async def test_another_agent_does_not_see_it(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, prompts: list[str]
) -> None:
    marker = uuid.uuid4().hex[:8]
    await turn(pool, test_settings, "remember", [call("save_note", text=f"chat {marker}"),
                                                  say("Saved.")])  # fmt: skip
    prompts.clear()
    run = await RunService(pool, test_settings, GRAPHS).create_run(
        "assistant", {"message": "hi", "script": [say("hello")]}
    )
    await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)
    assert prompts and all(marker not in p for p in prompts)


async def test_a_tests_notes_stay_in_the_test(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, no_memory: None,
    prompts: list[str],
) -> None:  # fmt: skip
    """The chat agent's eval saves "Locker number: 4217" in its own test turn (H6)."""
    await run_suite(pool, test_settings, GRAPHS, "chat", suites(AGENTS)["chat"])
    prompts.clear()
    await turn(pool, test_settings, "my locker?", [say("?")])
    assert "4217" not in prompts[0]
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT count(*) AS n FROM notes WHERE test_scope IS NOT NULL")
        row = await cur.fetchone()
    assert row is not None and row["n"] >= 1  # it was saved, in the test's scope

    # A test's notes go with their run (real ones outlive theirs).
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM session_messages WHERE run_id IN "
                           "(SELECT run_id FROM eval_runs)")  # fmt: skip
        await conn.execute("DELETE FROM runs WHERE id IN (SELECT run_id FROM eval_runs)")
        cur = await conn.execute("SELECT count(*) AS n FROM notes WHERE test_scope IS NOT NULL")
        assert (await cur.fetchone() or {})["n"] == 0


# -------------------------------------------------------- 4. what isn't kept


async def test_the_same_note_twice_is_kept_once(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, no_memory: None
) -> None:
    await turn(pool, test_settings, "remember", [call("save_note", text="Budget is 3000 euros."),
                                                  say("Saved.")])  # fmt: skip
    _, again = await turn(pool, test_settings, "remember", [
        call("save_note", text="budget is  3000 euros"), say("Saved.")])  # fmt: skip
    row = await result_of(pool, again.id, "save_note")
    assert row["result"]["already_remembered"] is True
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT count(*) AS n FROM notes WHERE agent = 'chat'")
        assert (await cur.fetchone() or {})["n"] == 1


async def test_a_card_number_is_not_kept_and_the_model_is_told_why(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, no_memory: None
) -> None:
    _, done = await turn(pool, test_settings, "remember my card", [
        call("save_note", text="card 4111 1111 1111 1111"), say("Not kept.")])  # fmt: skip
    assert done.status is S.COMPLETED
    row = await result_of(pool, done.id, "save_note")
    assert row["status"] == "failed" and "card number" in row["result"]["error"]
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT count(*) AS n FROM notes")
        assert (await cur.fetchone() or {})["n"] == 0


# ------------------------------------------------------------------ 2. forget


async def note_id(pool: Pool, text: str) -> str:
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT key FROM notes WHERE text = %s", (text,))
        row = await cur.fetchone()
    assert row is not None
    return str(row["key"])[:8]


async def test_forget_note_takes_it_out_of_memory_and_recall(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, no_memory: None,
    prompts: list[str],
) -> None:  # fmt: skip
    await turn(pool, test_settings, "remember", [call("save_note", text="locker 4412"),
                                                  say("Saved.")])  # fmt: skip
    nid = await note_id(pool, "locker 4412")
    prompts.clear()
    _, forgot = await turn(pool, test_settings, "forget my locker code", [
        call("forget_note", note_id=nid), say("Forgotten.")])  # fmt: skip
    assert forgot.status is S.COMPLETED and f"[{nid}]" in prompts[0]
    row = await result_of(pool, forgot.id, "forget_note")
    assert row["status"] == "done" and row["result"]["forgotten"] == "locker 4412"
    prompts.clear()
    _, later = await turn(pool, test_settings, "locker?", [
        call("recall_notes", query="locker"), say("I don't know.")])  # fmt: skip
    assert "locker 4412" not in prompts[0]
    assert (await result_of(pool, later.id, "recall_notes"))["result"]["count"] == 0


async def test_a_note_forgotten_in_this_turn_is_gone_from_the_rest_of_it(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, no_memory: None,
    prompts: list[str],
) -> None:  # fmt: skip
    """The review: "Forget my old address. What's my address?" mustn't be answered from
    the turn's memory with the address just forgotten."""
    await turn(pool, test_settings, "remember", [call("save_note", text="address: 1 Old St"),
                                                  say("Saved.")])  # fmt: skip
    nid = await note_id(pool, "address: 1 Old St")
    prompts.clear()
    await turn(pool, test_settings, "forget my old address. what's my address?", [
        call("forget_note", note_id=f"[{nid}]"),  # copied with its brackets, as models do
        say("I don't know it now.")])  # fmt: skip
    first, second = prompts
    assert "1 Old St" in first and "1 Old St" not in second


async def test_a_forget_made_again_after_a_crash_finds_what_it_forgot(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, no_memory: None
) -> None:
    from agent_runtime.memory.store import Memory, scope_of

    _, saved = await turn(pool, test_settings, "remember", [call("save_note", text="retry me"),
                                                             say("Saved.")])  # fmt: skip
    nid = await note_id(pool, "retry me")
    async with pool.connection() as conn:
        memory, scope = Memory(conn), await scope_of(conn, saved.id, None)
        first = await memory.forget(scope, nid, key="f" * 64, run_id=saved.id, epoch=saved.epoch)
        again = await memory.forget(scope, nid, key="f" * 64, run_id=saved.id, epoch=saved.epoch)
    assert first is not None and again is not None and first.key == again.key


async def test_a_changed_fact_and_a_second_copy_are_pointed_out(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, no_memory: None
) -> None:
    """Measured with qwen2.5:7b: with two "gym locker" notes, "forget my gym locker number"
    forgot one, and a new locker number left the old one standing. The tools now say
    which other notes look like the same thing; a note about something else isn't named."""
    await turn(pool, test_settings, "remember", [call("save_note", text="gym locker is number 73"),
                                                  say("Saved.")])  # fmt: skip
    await turn(pool, test_settings, "remember", [call("save_note", text="my locker code is 4412"),
                                                  say("Saved.")])  # fmt: skip
    _, saved = await turn(pool, test_settings, "remember", [
        call("save_note", text="my gym locker is number 80"), say("Saved.")])  # fmt: skip
    result = (await result_of(pool, saved.id, "save_note"))["result"]
    assert [n["text"] for n in result["maybe_out_of_date"]] == ["gym locker is number 73"]
    assert "forget_note" in result["hint"]

    nid = await note_id(pool, "my gym locker is number 80")
    _, forgot = await turn(pool, test_settings, "forget my gym locker number", [
        call("forget_note", note_id=nid), say("Forgotten.")])  # fmt: skip
    result = (await result_of(pool, forgot.id, "forget_note"))["result"]
    assert [n["text"] for n in result["still_remembered"]] == ["gym locker is number 73"]


async def test_forgetting_another_agents_note_finds_nothing(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, no_memory: None
) -> None:
    await turn(pool, test_settings, "remember", [call("save_note", text="chat's own"),
                                                  say("Saved.")])  # fmt: skip
    nid = await note_id(pool, "chat's own")
    script = [call("forget_note", note_id=nid), say("?")]
    run = await RunService(pool, test_settings, GRAPHS).create_run(
        "assistant", {"message": "forget it", "script": script}
    )
    await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)
    row = await result_of(pool, run.id, "forget_note")
    assert row["status"] == "failed" and "no note" in row["result"]["error"]
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT count(*) AS n FROM note_forgets")
        assert (await cur.fetchone() or {})["n"] == 0


# ------------------------------------------------- 7. runs come and go, it stays


async def test_forgetting_works_after_the_notes_run_was_taken_over(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, no_memory: None
) -> None:
    """The epoch fence checks a note's own run: an update of the note would be refused
    once that run's epoch moved on. Forgetting is the forgetting run's own insert."""
    _, saved = await turn(pool, test_settings, "remember", [call("save_note", text="old fact"),
                                                             say("Saved.")])  # fmt: skip
    async with pool.connection() as conn:
        await conn.execute("UPDATE runs SET epoch = epoch + 5 WHERE id = %s", (saved.id,))
    nid = await note_id(pool, "old fact")
    _, forgot = await turn(pool, test_settings, "forget it", [
        call("forget_note", note_id=nid), say("Forgotten.")])  # fmt: skip
    assert (await result_of(pool, forgot.id, "forget_note"))["status"] == "done"


async def test_deleting_a_run_keeps_what_it_remembered(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, no_memory: None,
    prompts: list[str],
) -> None:  # fmt: skip
    _, saved = await turn(pool, test_settings, "remember", [
        call("save_note", text="kept past retention"), say("Saved.")])  # fmt: skip
    async with pool.connection() as conn:
        # What retention would clear: the turn, and its transcript rows with it.
        await conn.execute("DELETE FROM session_messages WHERE run_id = %s", (saved.id,))
        await conn.execute("DELETE FROM runs WHERE id = %s", (saved.id,))
        cur = await conn.execute("SELECT run_id, agent FROM notes")
        assert await cur.fetchall() == [{"run_id": None, "agent": "chat"}]
    prompts.clear()
    await turn(pool, test_settings, "hi", [say("hello")])
    assert "kept past retention" in prompts[0]


# ----------------------------------------------------- 2. yours to see and remove


async def test_a_person_sees_restores_deletes_and_clears_memory(
    api: Server, pool: Pool, test_settings: Settings, no_memory: None, prompts: list[str]
) -> None:
    c = api.client
    for text in ("alpha-note", "beta-note"):
        await turn(pool, test_settings, "remember", [call("save_note", text=text), say("ok")])
    nid = await note_id(pool, "alpha-note")
    await turn(pool, test_settings, "forget alpha", [call("forget_note", note_id=nid),
                                                      say("ok")])  # fmt: skip

    listed = (await c.get("/agents/chat/memory")).json()["notes"]
    assert [(n["text"], n["forgotten_at"] is not None) for n in listed] == [
        ("beta-note", False), ("alpha-note", True)]  # fmt: skip
    assert listed[0]["session_id"] is not None and listed[0]["helper"] is None

    restored = await c.post(f"/agents/chat/memory/{nid}/restore")
    assert restored.status_code == 200 and restored.json()["forgotten_at"] is None
    again = await c.post(f"/agents/chat/memory/{nid}/restore")  # not forgotten: a no-op
    assert again.status_code == 200
    restores = (await c.get("/audit", params={"action": "memory.restored"})).json()
    assert sum(e["target_id"].startswith(nid) for e in restores) == 1  # audited once
    prompts.clear()
    await turn(pool, test_settings, "hi", [say("hello")])
    assert ": alpha-note" in prompts[0]  # back in memory, at once

    beta = next(n["id"] for n in listed if n["text"] == "beta-note")
    assert (await c.delete(f"/agents/chat/memory/{beta}")).status_code == 204
    missing = await c.delete(f"/agents/chat/memory/{beta}")
    assert missing.status_code == 404 and missing.json()["type"].endswith("/note-not-found")
    assert (await c.delete(f"/agents/assistant/memory/{nid}")).status_code == 404  # not its own

    cleared = await c.delete("/agents/chat/memory")
    assert cleared.json() == {"deleted": 1}
    assert (await c.get("/agents/chat/memory")).json()["notes"] == []

    events = (await c.get("/audit", params={"target_type": "note"})).json()
    assert [e["action"] for e in events][:2] == ["memory.deleted", "memory.restored"]
    assert all("-note" not in str(e) for e in events)  # ids only: deleted text is gone


# ------------------------------------------------------------- 3. helpers too


async def test_a_helper_remembers_its_own_notes_and_only_it(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, no_memory: None,
    prompts: list[str],
) -> None:  # fmt: skip
    """The `delegator` fixture: its `scribe` helper keeps notes; the delegator itself has
    no save_note, so no memory, and doesn't see its helper's."""
    from tests.integration.test_subagents import RETURN, run_delegator, say, spawn, turn, wait
    from tests.integration.test_subagents import call as sub_call

    def keep(text: str) -> dict[str, list[dict[str, Any]]]:
        return {"scribe": [turn(sub_call("save_note", text=text)), RETURN]}

    script = [turn(spawn("scribe", "keep it")), turn(wait(0)), say("Kept.")]
    first, _ = await run_delegator(pool, test_settings, script, keep("helper fact one"))
    assert first.status is S.COMPLETED
    prompts.clear()
    second, _ = await run_delegator(pool, test_settings, script, keep("helper fact two"))
    assert second.status is S.COMPLETED
    scribe = [p for p in prompts if "You keep notes" in p]
    main = [p for p in prompts if "You coordinate specialists" in p]
    assert scribe and all("helper fact one" in p for p in scribe)
    assert main and all("helper fact" not in p and "What you remember" not in p for p in main)

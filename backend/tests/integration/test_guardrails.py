"""Harness guardrails (CR-003, phase 6b): soft→hard wrap-up and accounting (AC26),
loop detection (AC27), retries and the circuit breaker (R14.7), admission control
(R14.8), ceilings for chat turns (AC28), redaction in the transcript (R14.12)."""

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage

from agent_runtime.config import ModelPrice, Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.models import retry
from agent_runtime.models.scripted import ScriptedChatModel
from agent_runtime.runs.events import EventType as E
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.limits import LimitAboveCeiling
from agent_runtime.runs.service import Overloaded, RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.runs.store import Run, RunRepository
from agent_runtime.sessions.service import SessionService
from agent_runtime.sessions.store import SessionRepository
from tests.integration.support import events, wait_until

pytestmark = pytest.mark.integration
GRAPHS = default_registry()
PRICED = {"scripted": ModelPrice(input_per_mtok=1000.0, output_per_mtok=2000.0)}


def calc(expression: str) -> dict[str, Any]:
    return {"tool_calls": [{"name": "calculator", "args": {"expression": expression}}]}


@pytest.fixture(autouse=True)
def fresh_breakers() -> Iterator[None]:
    retry.reset_breakers()  # breakers are per process: never leak state between tests
    yield
    retry.reset_breakers()


@pytest.fixture
def requests(monkeypatch: pytest.MonkeyPatch) -> list[tuple[list[BaseMessage], int]]:
    """(messages, number of tools bound) for every scripted model call."""
    seen: list[tuple[list[BaseMessage], int]] = []
    bound: list[int] = [0]
    real_generate, real_bind = ScriptedChatModel._agenerate, ScriptedChatModel.bind_tools

    def bind(self: ScriptedChatModel, tools: Any, **kw: Any) -> Any:
        bound[0] = len(tools)  # create_agent binds the request's tools on every call
        return real_bind(self, tools, **kw)

    async def spy(self: ScriptedChatModel, messages: list[BaseMessage], *a: Any, **kw: Any) -> Any:
        seen.append((list(messages), bound[0]))
        bound[0] = 0
        return await real_generate(self, messages, *a, **kw)

    monkeypatch.setattr(ScriptedChatModel, "bind_tools", bind)
    monkeypatch.setattr(ScriptedChatModel, "_agenerate", spy)
    return seen


async def run_assistant(
    pool: Pool, settings: Settings, script: list[dict[str, Any]],
    options: dict[str, Any] | None = None, message: str = "go", **kw: Any,
) -> tuple[Run, RunExecutor]:  # fmt: skip
    run = await RunService(pool, settings, GRAPHS).create_run(
        "assistant", {"message": message, "script": script}, options
    )
    executor = RunExecutor(pool, settings, GRAPHS, **kw)
    return await executor.execute(run.id), executor


async def counters(pool: Pool, run_id: uuid.UUID) -> dict[str, Any]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT model_calls, tool_calls_total, tokens, cost FROM runs WHERE id = %s",
            (run_id,),
        )
        row = await cur.fetchone()
    assert row is not None
    return dict(row)


async def thread(pool: Pool, run: Run) -> list[Any]:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with pool.connection() as conn:
        graph = GRAPHS.get(run.graph_name).compile(AsyncPostgresSaver(conn))
        state = await graph.aget_state({"configurable": {"thread_id": run.thread_id}})
    return list(state.values.get("messages", []))


def expected_usage(messages: list[Any]) -> tuple[int, float]:
    tokens, cost = 0, 0.0
    for m in messages:
        if isinstance(m, AIMessage) and m.usage_metadata:
            u = m.usage_metadata
            tokens += u["input_tokens"] + u["output_tokens"]
            cost += PRICED["scripted"].cost(u["input_tokens"], u["output_tokens"])
    return tokens, cost


# ----------------------------------------------------- AC26: the runaway agent


async def test_a_runaway_agent_gets_one_wrap_up_turn_then_fails_with_its_answer(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    requests: list[tuple[list[BaseMessage], int]],
) -> None:  # fmt: skip
    settings = test_settings.model_copy(update={"model_prices": PRICED})
    forever = [calc(f"{i}+1") for i in range(50)]  # distinct calls: no loop detection
    # max_tool_calls=5 (max_model_calls is 10, from the agent's max_turns): the tool
    # budget reaches 80 % first, after 4 calls.
    done, _ = await run_assistant(pool, settings, forever, {"max_tool_calls": 5})
    assert (done.status, done.reason) == (S.FAILED, "budget:tool_calls")
    used = await counters(pool, done.id)
    assert used["tool_calls_total"] == 4  # stopped at 80 %, never reached 100 %
    assert used["model_calls"] == 5  # 4 tool turns + the wrap-up turn

    wrap_up, tools_bound = requests[-1]
    assert isinstance(wrap_up[-1], SystemMessage) and "Tools are no longer" in wrap_up[-1].content
    assert tools_bound == 0 and all(n > 0 for _, n in requests[:-1])  # tools removed (R14.2)
    async with pool.connection() as conn:
        result = await RunRepository(conn).get_result(done.id)
    assert result is not None and result["output"]["budget_limited"] is True
    assert result["output"]["answer"].startswith("I had to stop early")  # a tool call was dropped
    failed = next(e for e in await events(pool, done.id) if e.type == E.RUN_FAILED)
    assert failed.payload["budget_limited"] is True

    tokens, cost = expected_usage(await thread(pool, done))  # AC26: the sum of its steps
    assert used["tokens"] == tokens and float(used["cost"]) == pytest.approx(cost)
    assert tokens > 0 and cost > 0


async def test_usage_is_exactly_the_sum_of_committed_steps_across_a_reclaim(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    fast = test_settings.model_copy(
        update={"lease_ttl_s": 1.0, "heartbeat_s": 0.3, "model_prices": PRICED}
    )
    script = [calc("1+1"), {"tool_calls": [{"name": "save_note", "args": {
        "text": "x", "linger_s": 1.5}}]}, calc("2+2"), {"content": "done"}]  # fmt: skip
    run = await RunService(pool, fast, GRAPHS).create_run(
        "assistant", {"message": "go", "script": script}
    )
    worker_a = asyncio.create_task(RunExecutor(pool, fast, GRAPHS, owner="a:1").execute(run.id))

    async def noted() -> bool:
        async with pool.connection() as conn:
            cur = await conn.execute("SELECT 1 FROM notes WHERE run_id = %s", (run.id,))
            return await cur.fetchone() is not None

    await wait_until(noted, timeout_s=10)
    worker_a.cancel()  # killed mid-run
    await asyncio.gather(worker_a, return_exceptions=True)
    await asyncio.sleep(fast.lease_ttl_s + 0.2)
    done = await RunExecutor(pool, fast, GRAPHS, owner="b:2").execute(run.id)
    assert done.status is S.COMPLETED and done.epoch == 2
    used = await counters(pool, run.id)
    tokens, cost = expected_usage(await thread(pool, done))
    assert used["tokens"] == tokens and float(used["cost"]) == pytest.approx(cost)


async def test_a_token_budget_is_a_hard_limit_too(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    done, _ = await run_assistant(
        pool, test_settings, [calc(f"{i}+1") for i in range(50)], {"max_tokens": 60}
    )
    assert done.status is S.FAILED and done.reason == "budget:tokens"


# --------------------------------------------------------------- AC27: loops


async def test_a_repeated_call_is_served_from_cache_then_the_third_ends_the_run(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    done, _ = await run_assistant(pool, test_settings, [calc("1+1")] * 3 + [{"content": "x"}])
    assert (done.status, done.reason) == (S.FAILED, "loop_detected")
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT status, result FROM tool_invocations WHERE run_id = %s ORDER BY created_at",
            (done.id,),
        )
        rows = await cur.fetchall()
    assert [r["status"] for r in rows] == ["done", "done"]  # the 3rd was never recorded
    assert rows[1]["result"]["earlier_result"] == rows[0]["result"]  # served, not executed
    assert "will end the run" in rows[1]["result"]["note"]
    called = [e for e in await events(pool, done.id) if e.type == E.TOOL_CALLED]
    assert len(called) == 1  # executed once
    completed = [e.payload for e in await events(pool, done.id) if e.type == E.TOOL_COMPLETED]
    assert [p["cached"] for p in completed] == [False, True]


async def test_polling_the_same_thing_five_times_is_no_progress(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    """wait_subagents is exempt from repeat detection (polling is legitimate), but five
    identical model outputs in a row are no progress (R14.4)."""
    poll = {"tool_calls": [{"name": "wait_subagents", "args": {
        "handles": ["${spawn_subagent[0].handle}"], "timeout_s": 1}}]}  # fmt: skip
    script = [{"tool_calls": [{"name": "spawn_subagent", "args": {"agent": "scribe",
                                                                  "task": "slow"}}]},
              *[poll] * 6, {"content": "x"}]  # fmt: skip
    slow = {"name": "save_note", "args": {"text": "z", "linger_s": 20}}
    subs = {"scribe": [{"tool_calls": [slow]}]}
    run = await RunService(pool, test_settings, GRAPHS).create_run(
        "delegator", {"message": "go", "script": script, "subagent_scripts": subs}
    )
    done = await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)
    assert (done.status, done.reason) == (S.FAILED, "loop_detected")
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT count(*) AS n FROM tool_invocations WHERE run_id = %s "
            "AND tool = 'wait_subagents'", (run.id,),
        )  # fmt: skip
        assert await cur.fetchone() == {"n": 4}  # the 5th identical output never ran
        cur = await conn.execute(
            "SELECT status FROM subagent_invocations WHERE run_id = %s", (run.id,)
        )
        assert await cur.fetchone() == {"status": "cancelled"}  # it doesn't outlive the run


async def test_an_empty_reply_is_asked_for_once_more(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    """No text and no tool call (a small model's unparsable tool call) ends nothing: the
    model is asked once more, and that call is charged like any other."""
    done, _ = await run_assistant(pool, test_settings, [{"content": ""}, {"content": "hi"}])
    assert done.status is S.COMPLETED
    assert (await counters(pool, done.id))["model_calls"] == 2
    replies = [m.content for m in await thread(pool, done) if isinstance(m, AIMessage)]
    assert replies == ["hi"]  # the empty one never reaches the conversation


async def test_an_empty_reply_twice_is_not_retried_forever(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    done, _ = await run_assistant(pool, test_settings, [{"content": ""}, {"content": ""}])
    assert done.status is S.COMPLETED
    assert (await counters(pool, done.id))["model_calls"] == 2  # once more, not again


REMEMBER = "Remember that the demo is on Friday"


async def notes_of(pool: Pool, run: Run) -> list[str]:
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT text FROM notes WHERE run_id = %s", (run.id,))
        return [r["text"] for r in await cur.fetchall()]


@pytest.mark.parametrize(
    "written",
    [
        'save_note({"text": "demo on Friday"})',
        '<tool_call>\n{"name": "save_note", "arguments": {"text": "demo on Friday"}}\n</tool_call>',
        '```json\n{"name": "save_note", "arguments": "{\\"text\\": \\"demo on Friday\\"}"}\n```',
    ],
)
async def test_a_tool_call_written_as_text_is_made(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, written: str
) -> None:
    """qwen2.5:7b via Ollama writes the call out as its reply about half the time: the
    note wasn't saved, and the person saw the call. It's made, through the pipeline, with
    no second model call; the text never reaches the conversation."""
    done, _ = await run_assistant(
        pool, test_settings, [{"content": written}, {"content": "Saved."}]
    )
    assert done.status is S.COMPLETED
    assert await notes_of(pool, done) == ["demo on Friday"]
    assert (await counters(pool, done.id))["model_calls"] == 2
    replies = [m.content for m in await thread(pool, done) if isinstance(m, AIMessage)]
    assert replies == ["", "Saved."]


@pytest.mark.parametrize(
    "text",
    [
        'teleport({"to": "Mars"})',  # not one of its tools
        'I will call save_note({"text": "x"}) now.',  # words around it: an answer
        'save_note("demo")',  # not JSON arguments
    ],
)
async def test_text_that_only_mentions_a_call_stays_an_answer(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, text: str
) -> None:
    done, _ = await run_assistant(pool, test_settings, [{"content": text}])
    assert await notes_of(pool, done) == []
    replies = [m.content for m in await thread(pool, done) if isinstance(m, AIMessage)]
    assert replies == [text]


async def test_a_reply_that_says_it_saved_what_nothing_saved_is_asked_again(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    requests: list[tuple[list[BaseMessage], int]],
) -> None:  # fmt: skip
    """qwen2.5:7b, asked to remember something, often answers "I've saved that" without
    calling save_note. It's asked once more; the false claim never reaches the chat."""
    honest = "I haven't saved it yet: I didn't call the tool. Shall I?"
    script = [{"content": "I've saved that in my notes."}, {"content": honest}]
    done, _ = await run_assistant(pool, test_settings, script, message=REMEMBER)
    assert done.status is S.COMPLETED
    assert (await counters(pool, done.id))["model_calls"] == 2  # charged like any call
    assert "Call save_note now" in str(requests[1][0][-1].content)
    replies = [m.content for m in await thread(pool, done) if isinstance(m, AIMessage)]
    assert replies == [honest]


async def test_a_claim_after_the_tool_ran_or_twice_is_left_alone(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    save = {"tool_calls": [{"name": "save_note", "args": {"text": "x"}}]}
    done, _ = await run_assistant(
        pool, test_settings, [save, {"content": "I've saved it."}], message=REMEMBER
    )
    assert (await counters(pool, done.id))["model_calls"] == 2  # it did: no question
    claim = {"content": "I have saved it."}
    done, _ = await run_assistant(pool, test_settings, [claim, claim], message=REMEMBER)
    assert done.status is S.COMPLETED
    assert (await counters(pool, done.id))["model_calls"] == 2  # once more, not again


async def test_near_a_limit_a_claim_stands_rather_than_fail_the_turn(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    requests: list[tuple[list[BaseMessage], int]],
) -> None:  # fmt: skip
    """Asking once more could cross the limit and fail a turn whose answer is in hand
    (the review): at the soft limit, the reply stands."""
    claim = {"content": "I've saved that in my notes."}
    done, _ = await run_assistant(
        pool, test_settings, [claim, {"content": "x"}], {"max_model_calls": 1}, message=REMEMBER
    )
    assert done.status is S.COMPLETED
    assert (await counters(pool, done.id))["model_calls"] == 1
    assert not any("Call save_note now" in str(m.content) for ms, _ in requests for m in ms)


# ---------------------------------------------------------- R14.7: retries


class Http503(Exception):
    status_code = 503


class Http400(Exception):
    status_code = 400


def flaky(monkeypatch: pytest.MonkeyPatch, *errors: Exception) -> list[int]:
    queue, attempts = list(errors), [0]
    real = ScriptedChatModel._agenerate

    async def maybe_fail(self: ScriptedChatModel, *a: Any, **kw: Any) -> Any:
        attempts[0] += 1
        if queue:
            raise queue.pop(0)
        return await real(self, *a, **kw)

    monkeypatch.setattr(ScriptedChatModel, "_agenerate", maybe_fail)
    return attempts


async def test_retryable_errors_are_retried_and_every_attempt_is_charged(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fast = test_settings.model_copy(update={"model_retry_base_s": 0.01})
    attempts = flaky(monkeypatch, Http503(), Http503())
    done, _ = await run_assistant(pool, fast, [{"content": "hi"}])
    assert done.status is S.COMPLETED and attempts == [3]
    assert (await counters(pool, done.id))["model_calls"] == 3


async def test_a_non_retryable_error_fails_at_once(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = flaky(monkeypatch, Http400())
    done, _ = await run_assistant(pool, test_settings, [{"content": "hi"}])
    assert (done.status, done.reason) == (S.FAILED, "error") and attempts == [1]


async def test_an_open_breaker_releases_the_run_for_later_instead_of_retrying(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fast = test_settings.model_copy(update={
        "model_retry_base_s": 0.01, "model_retry_attempts": 2, "breaker_failures": 2,
    })  # fmt: skip
    flaky(monkeypatch, *[Http503()] * 10)
    first, _ = await run_assistant(pool, fast, [{"content": "hi"}])
    assert first.status is S.FAILED  # two failed attempts: the breaker is now open
    second, executor = await run_assistant(pool, fast, [{"content": "hi"}])
    assert second.status is S.QUEUED and executor.deferred  # released, not failed
    released = next(e for e in await events(pool, second.id) if e.type == E.RUN_RELEASED)
    assert released.payload["reason"] == "circuit_open"
    assert (await counters(pool, second.id))["model_calls"] == 0  # nothing was burnt


# ---------------------------------------------------- R14.8, AC28, R14.12


async def test_chat_turns_are_rate_limited_per_session(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    settings = test_settings.model_copy(update={"session_messages_per_minute": 2})
    service = SessionService(pool, settings, GRAPHS, RunService(pool, settings, GRAPHS))
    sid = (await service.create("chat")).id
    for text in ("one", "two"):
        sent = await service.send(sid, text, script=[{"content": "ok"}])
        await RunExecutor(pool, settings, GRAPHS).execute(sent.run.id)
    with pytest.raises(Overloaded) as info:
        await service.send(sid, "three", script=[{"content": "ok"}])
    assert info.value.reason == "rate_limited" and info.value.retry_after_s == 60


async def test_the_daily_cost_ceiling_refuses_new_work(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    settings = test_settings.model_copy(update={"model_prices": PRICED})
    done, _ = await run_assistant(pool, settings, [{"content": "costs something"}])
    assert float((await counters(pool, done.id))["cost"]) > 0
    spent = await RunService(pool, settings, GRAPHS).cost_today()
    capped = settings.model_copy(update={"global_daily_cost_usd": spent})
    service = RunService(pool, capped, GRAPHS)
    with pytest.raises(Overloaded) as info:
        await service.create_run("toy", {"question": "q"})
    assert info.value.reason == "daily_budget"


async def test_a_chat_turn_above_a_ceiling_is_rejected_and_a_lower_value_is_honoured(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    service = SessionService(pool, test_settings, GRAPHS, RunService(pool, test_settings, GRAPHS))
    sid = (await service.create("chat")).id
    with pytest.raises(LimitAboveCeiling, match="max_tool_calls"):
        await service.send(sid, "x", {"max_tool_calls": 10_000})
    sent = await service.send(sid, "x", {"max_tool_calls": 2}, script=[{"content": "ok"}])
    assert sent.run.limits["max_tool_calls"] == 2  # AC28


async def test_secrets_never_reach_the_transcript(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    secret = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2"  # assembled at runtime: no scanner hit
    service = SessionService(pool, test_settings, GRAPHS, RunService(pool, test_settings, GRAPHS))
    sid = (await service.create("chat")).id
    sent = await service.send(sid, "keep my key", script=[
        {"tool_calls": [{"name": "save_note", "args": {"text": f"key={secret}"}}]},
        {"content": f"Saved {secret}."},
    ])  # fmt: skip
    await RunExecutor(pool, test_settings, GRAPHS).execute(sent.run.id)
    async with pool.connection() as conn:
        msgs = await SessionRepository(conn).messages(sid, limit=100)
        cur = await conn.execute("SELECT text FROM notes WHERE run_id = %s", (sent.run.id,))
        notes = await cur.fetchall()
    assert all(secret not in str(m.content) for m in msgs if m.type != "user")
    assert "[REDACTED]" in str(next(m for m in msgs if m.type == "tool_call").content)
    assert notes == [{"text": "key=[REDACTED]"}]  # the pre_tool hook cleaned what ran (AC34)


# ------------------------------------------------- phase H2: budgets that bind


async def test_h2_a_model_call_lost_to_a_crash_is_still_counted(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """Worker A's model call returns, its usage is recorded, then A dies before the step
    commits. B makes that call again: both cost money, so both are counted."""
    fast = test_settings.model_copy(
        update={"lease_ttl_s": 1.0, "heartbeat_s": 0.3, "model_prices": PRICED}
    )
    run = await RunService(pool, fast, GRAPHS).create_run(
        "assistant", {"message": "go", "script": [calc("1+1"), {"content": "done"}]}
    )
    recorded, hold = asyncio.Event(), asyncio.Event()
    original = RunExecutor._usage_recorder

    def holding(self: RunExecutor, outbox: Any, role: str) -> Any:
        record = original(self, outbox, role)

        async def wrapped(model: str, tokens_in: int, tokens_out: int, s: float = 0.0) -> float:
            cost = await record(model, tokens_in, tokens_out, s)
            if self.owner == "a:1":  # worker A: recorded, then dies before the commit
                recorded.set()
                await hold.wait()
            return cost

        return wrapped

    monkeypatch.setattr(RunExecutor, "_usage_recorder", holding)
    worker_a = asyncio.create_task(RunExecutor(pool, fast, GRAPHS, owner="a:1").execute(run.id))
    await asyncio.wait_for(recorded.wait(), timeout=10)
    lost = await counters(pool, run.id)
    assert lost["tokens"] > 0 and float(lost["cost"]) > 0  # counted the moment it returned
    worker_a.cancel()
    await asyncio.gather(worker_a, return_exceptions=True)
    await asyncio.sleep(fast.lease_ttl_s + 0.2)

    done = await RunExecutor(pool, fast, GRAPHS, owner="b:2").execute(run.id)
    assert done.status is S.COMPLETED
    used = await counters(pool, run.id)
    tokens, cost = expected_usage(await thread(pool, done))  # the calls whose steps committed
    assert used["tokens"] == tokens + lost["tokens"]  # + the call lost with A's step
    assert float(used["cost"]) == pytest.approx(cost + float(lost["cost"]))
    assert used["model_calls"] == 3  # A's call, B's repeat of it, B's final answer
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT sum(calls) AS calls, sum(tokens_in + tokens_out) AS tokens "
            "FROM run_model_usage WHERE run_id = %s",
            (run.id,),
        )
        per_model = await cur.fetchone()
    assert per_model is not None
    assert (per_model["calls"], per_model["tokens"]) == (3, used["tokens"])  # Activity agrees


async def test_h2_a_burst_past_the_tool_budget_still_ends_with_an_answer(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    """7 of 10 tool calls used (70 %, under the soft limit), then ONE step asks for 15:
    3 run, 12 are refused as tool errors, and the next model call is the wrap-up."""
    seven = {"tool_calls": [{"name": "calculator", "args": {"expression": f"{i}+1"}}
                            for i in range(7)]}  # fmt: skip
    burst = {"tool_calls": [{"name": "calculator", "args": {"expression": f"{i}*3"}}
                            for i in range(15)]}  # fmt: skip
    done, _ = await run_assistant(
        pool, test_settings, [seven, burst, *[calc(f"{i}-1") for i in range(5)]],
        {"max_tool_calls": 10},
    )  # fmt: skip
    assert (done.status, done.reason) == (S.FAILED, "budget:tool_calls")  # with its answer
    async with pool.connection() as conn:
        result = await RunRepository(conn).get_result(done.id)
    assert result is not None and result["output"]["budget_limited"] is True
    used = await counters(pool, done.id)
    assert used["tool_calls_total"] == 10  # never past the limit
    assert used["model_calls"] == 3  # the 7, the burst, the wrap-up
    messages = await thread(pool, done)
    results = [m for m in messages if getattr(m, "type", "") == "tool"]
    assert len(results) == 7 + 15  # every call got its answer, made or not
    refused = [m for m in results if "Deny(budget)" in str(m.content)]
    assert len(refused) == 12 and all("wasn't made" in str(m.content) for m in refused)


async def test_h2_a_cost_budget_binds_and_ends_with_the_wrap_up(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    priced = test_settings.model_copy(update={"model_prices": PRICED})
    done, _ = await run_assistant(
        pool, priced, [calc(f"{i}+1") for i in range(50)], {"max_cost_usd": 0.5}
    )
    assert (done.status, done.reason) == (S.FAILED, "budget:cost")
    async with pool.connection() as conn:
        result = await RunRepository(conn).get_result(done.id)
    assert result is not None and result["output"]["budget_limited"] is True
    used = await counters(pool, done.id)
    ai = [m for m in await thread(pool, done) if isinstance(m, AIMessage) and m.usage_metadata]
    last = ai[-1].usage_metadata
    assert last is not None
    wrap_up = PRICED["scripted"].cost(last["input_tokens"], last["output_tokens"])
    before = float(used["cost"]) - wrap_up
    assert 0.4 <= before < 0.5  # the soft limit (80 %) was reached before the hard one…
    assert float(used["cost"]) > before  # …and the wrap-up call, the one past it, was charged


async def test_h2_a_failed_call_can_be_retried_and_the_third_failure_ends_the_run(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    done, _ = await run_assistant(pool, test_settings, [calc("1/0")] * 3 + [{"content": "x"}])
    assert (done.status, done.reason) == (S.FAILED, "loop_detected")
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT status FROM tool_invocations WHERE run_id = %s ORDER BY created_at",
            (done.id,),
        )
        rows = await cur.fetchall()
    assert [r["status"] for r in rows] == ["failed", "failed"]  # tried again, not served
    called = [e for e in await events(pool, done.id) if e.type == E.TOOL_CALLED]
    assert len(called) == 2

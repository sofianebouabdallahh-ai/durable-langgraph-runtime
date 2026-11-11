"""Phase H7: safe across deploys and side effects.

- The ledger finds a call by its place (run · node · position · tool), not its
  arguments: a deploy that changes them can't make a done call happen again. Its key
  still hashes them, so a worker on the release before finds every call (expand/contract).
- A run carries the newest format that has had it; an older worker leaves it alone.
- A side effect isn't retried after a crash unless its tool dedupes by the key.
- The next turn says what really happened to the calls a turn left unanswered.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.fencing import Fence
from agent_runtime.graphs import default_registry
from agent_runtime.mcp.client import ToolDefinition
from agent_runtime.mcp.tools import Locked, spec_of
from agent_runtime.queue import RedisWorkQueue
from agent_runtime.runs.events import EventType as E
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.runs.store import RUN_FORMAT, RunRepository, code_version
from agent_runtime.sessions.turns import CUT_OFF_TOOL_RESULT
from agent_runtime.tools.builtin import default_tools
from agent_runtime.tools.hooks import (
    Deny,
    HookDecision,
    HookRegistry,
    Modify,
    ToolHookInput,
    default_hooks,
)
from agent_runtime.tools.middleware import call_index
from agent_runtime.tools.pipeline import (
    Grant,
    ToolCall,
    ToolPipeline,
    ToolRunContext,
    call_hash,
    call_key,
    idempotency_key,
)
from agent_runtime.tools.policy import RiskClassPolicy
from agent_runtime.tools.spec import ToolArgs, ToolContext, ToolRegistry
from agent_runtime.untrusted import as_data
from agent_runtime.worker import Worker
from tests.integration.test_sessions import call as scripted
from tests.integration.test_sessions import (
    chat,
    sessions,
    thread_messages,
    tools,
    transcript,
    turn,
)

pytestmark = pytest.mark.integration
GRAPHS = default_registry()


class EchoV1(ToolArgs):
    text: str


class EchoV2(ToolArgs):  # the next release: a new argument, with a default
    text: str
    loud: bool = False


class Tools:
    """One release's tools: spies that count what really runs and the key they got."""

    def __init__(self, args: type[ToolArgs] = EchoV1, **ctx: Any) -> None:
        self.runs: Counter[str] = Counter()
        self.keys: list[str] = []
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.ctx = ctx
        self.registry = ToolRegistry()

        @self.registry.tool("echo", args=args, risk_class="read", side_effect=False)
        async def echo(a: Any, ctx: ToolContext) -> dict[str, Any]:
            self.runs["echo"] += 1
            self.keys.append(ctx.key)
            return {"text": a.text}

        # A new side-effecting tool whose author didn't think about crashes (H7 default).
        @self.registry.tool("post", args=EchoV1, risk_class="write_internal", side_effect=True)
        async def post(a: EchoV1, ctx: ToolContext) -> dict[str, Any]:
            self.runs["post"] += 1
            return {"posted": a.text}

    def context(self, fence: Fence, pool: Pool) -> ToolRunContext:
        return ToolRunContext(fence=fence, pool=pool,
                              grants={"echo": Grant(), "post": Grant()},
                              emit=lambda t, p: self.events.append((t, p)),
                              **self.ctx)  # fmt: skip

    def pipeline(self) -> ToolPipeline:
        return ToolPipeline(self.registry, RiskClassPolicy(), interrupt=lambda _: None)

    def run(self, c: ToolCall, fence: Fence, pool: Pool) -> Any:
        return self.pipeline().run(c, self.context(fence, pool))

    def changed(self) -> list[dict[str, Any]]:
        return [p for t, p in self.events if t == E.TOOL_ARGS_CHANGED]


def call(name: str, index: int = 0, **args: Any) -> ToolCall:
    return ToolCall(id=f"call_{index}", name=name, args=args, index=index)


@pytest.fixture
async def fence(pool: Pool) -> Fence:
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        run = await repo.create(graph_name="assistant", input={})
        lease = await repo.acquire_lease(run.id, "h7:1", ttl_s=60)
        assert lease is not None
        await repo.transition(run.id, S.RUNNING, event=E.RUN_STARTED, fence=lease.fence)
    return lease.fence


async def taken_over(pool: Pool, fence: Fence) -> Fence:
    """Another worker reclaims the run (its owner died): the next epoch."""
    async with pool.connection() as conn:
        await conn.execute("UPDATE runs SET epoch = epoch + 1 WHERE id = %s", (fence.run_id,))
    return Fence(fence.run_id, fence.epoch + 1)


async def ledger(pool: Pool, run_id: uuid.UUID) -> list[dict[str, Any]]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT key, call_key, call_hash, status, result FROM tool_invocations "
            "WHERE run_id = %s ORDER BY created_at",
            (run_id,),
        )
        return list(await cur.fetchall())


async def recorded(pool: Pool, fence: Fence, *rows: tuple[str, str | None, str, Any]) -> None:
    """Ledger rows as another release left them: (key, call_key, status, result)."""
    async with pool.connection() as conn:
        for key, place, status, result in rows:
            await conn.execute(
                "INSERT INTO tool_invocations (key, call_key, run_id, tool, status, result, "
                "epoch) VALUES (%s, %s, %s, 'echo', %s, %s, %s)",
                (key, place, fence.run_id, status, Jsonb(result) if result else None,
                 fence.epoch),
            )  # fmt: skip


# ------------------------------------------------------------------ the call's place


async def test_a_deploy_that_adds_a_defaulted_argument_does_not_rerun_a_done_call(
    pool: Pool, fence: Fence
) -> None:
    before = Tools(EchoV1)
    first = await before.run(call("echo", text="hi"), fence, pool)
    assert before.runs["echo"] == 1
    # The step crashed before it committed; the new release resumes it: the model's same
    # call now validates to {"text": "hi", "loud": false}, which is another key.
    fence = await taken_over(pool, fence)
    after = Tools(EchoV2)
    again = await after.run(call("echo", text="hi"), fence, pool)
    assert after.runs["echo"] == 0 and again.cached and again.content == first.content
    assert after.changed() == [{"tool": "echo", "call_id": "call_0"}]
    # A call the new release made, replayed with the same arguments: nothing to notice.
    new = Tools(EchoV2)
    await new.run(call("echo", 1, text="new"), fence, pool)
    replayed = await new.run(call("echo", 1, text="new"), fence, pool)
    assert replayed.cached and new.runs["echo"] == 1 and new.changed() == []


async def test_an_older_worker_finds_every_call_a_newer_one_made(pool: Pool, fence: Fence) -> None:
    """Expand/contract: the row's key is still the one the release before H7 computes,
    so during a rolling deploy (or a rollback) an older worker finds the call, done."""
    c = call("echo", 3, text="hi")
    await Tools().run(c, fence, pool)
    (row,) = await ledger(pool, fence.run_id)
    assert row["key"] == idempotency_key(fence.run_id, c, {"text": "hi"})  # pre-H7 formula
    assert row["call_key"] == call_key(fence.run_id, c)
    assert row["call_hash"] == call_hash({"text": "hi"})


async def test_another_position_is_another_call(pool: Pool, fence: Fence) -> None:
    echo = Tools()
    await echo.run(call("echo", 0, text="hi"), fence, pool)
    await echo.run(call("echo", 1, text="hi again"), fence, pool)
    assert echo.runs["echo"] == 2 and len(set(echo.keys)) == 2
    places = {r["call_key"] for r in await ledger(pool, fence.run_id)}
    assert places == {call_key(fence.run_id, call("echo", i)) for i in (0, 1)}


async def test_a_call_made_before_the_upgrade_is_found_and_placed(pool: Pool, fence: Fence) -> None:
    done, cut = call("echo", 0, text="before"), call("echo", 1, text="cut off")
    old_done = idempotency_key(fence.run_id, done, {"text": "before"})
    old_cut = idempotency_key(fence.run_id, cut, {"text": "cut off"})
    # Recorded by the release before (no call_key): one done, one cut off mid-call by a
    # worker that died; then a new worker took the run over.
    await recorded(pool, fence, (old_done, None, "done", {"text": "from then"}),
                   (old_cut, None, "in_progress", None))  # fmt: skip
    fence = await taken_over(pool, fence)
    echo = Tools()
    served = await echo.run(done, fence, pool)
    assert served.cached and "from then" in served.content and echo.runs["echo"] == 0
    await echo.run(cut, fence, pool)  # taken over, under the key it was recorded with
    assert echo.runs["echo"] == 1 and echo.keys == [old_cut]
    rows = {r["key"]: r for r in await ledger(pool, fence.run_id)}
    assert set(rows) == {old_done, old_cut}  # no second row under another key
    assert rows[old_done]["call_key"] == call_key(fence.run_id, done)  # placed, now
    assert rows[old_cut]["call_key"] == call_key(fence.run_id, cut)


async def test_its_place_wins_over_a_key_that_matches_another_row(pool: Pool, fence: Fence) -> None:
    """Both an older release's row (found by key) and a newer one's (found by place) can
    match: the place is the call, so it wins."""
    c = call("echo", 0, text="hi")
    by_key = idempotency_key(fence.run_id, c, {"text": "hi"})
    await recorded(pool, fence, (by_key, None, "done", {"text": "by key"}),
                   ("e" * 64, call_key(fence.run_id, c), "done", {"text": "by place"}))  # fmt: skip
    served = await Tools().run(c, fence, pool)
    assert served.cached and "by place" in served.content


async def test_a_call_taken_over_with_other_arguments_is_noticed(pool: Pool, fence: Fence) -> None:
    c = call("echo", 0, text="hi")
    await Tools(EchoV1).run(c, fence, pool)
    async with pool.connection() as conn:  # say the worker died mid-call
        await conn.execute("UPDATE tool_invocations SET status = 'in_progress', result = NULL "
                           "WHERE run_id = %s", (fence.run_id,))  # fmt: skip
    fence = await taken_over(pool, fence)
    after = Tools(EchoV2)
    await after.run(c, fence, pool)
    assert after.runs["echo"] == 1 and after.changed() == [{"tool": "echo", "call_id": "call_0"}]
    # Retried under the key it was first sent with: the tool (or MCP server) dedupes.
    assert after.keys == [idempotency_key(fence.run_id, c, {"text": "hi"})]


# ------------------------------------------------------------------ retry defaults


def test_side_effects_are_not_retried_after_a_crash_unless_the_tool_dedupes() -> None:
    builtin = default_tools()
    retried = {n: builtin.get(n).retry_after_crash for n in
               ("calculator", "recall_notes", "save_note", "notify", "spawn_subagent",
                "run_python")}  # fmt: skip
    assert retried == dict.fromkeys(retried, True)  # reads, and side effects keyed by the key
    assert Tools().registry.get("post").retry_after_crash is False  # a new one, unmarked


def test_an_mcp_tool_is_retried_only_when_it_runs_without_asking() -> None:
    definition = ToolDefinition("lookup", "Looks things up.", {"type": "object"})

    def locked(without_asking: bool) -> Locked:
        return Locked("mcp__s__lookup", uuid.uuid4(), "lookup", definition, without_asking)

    assert spec_of(locked(True)).retry_after_crash is True
    assert spec_of(locked(False)).retry_after_crash is False


async def test_a_new_side_effect_cut_off_by_a_crash_is_not_sent_again(
    pool: Pool, fence: Fence
) -> None:
    c = call("post", text="hello")
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO tool_invocations (key, run_id, tool, status, epoch) "
            "VALUES (%s, %s, 'post', 'in_progress', %s)",
            (idempotency_key(fence.run_id, c, {"text": "hello"}), fence.run_id, fence.epoch),
        )
    fence = await taken_over(pool, fence)  # the worker died mid-call; another took over
    post = Tools()
    result = await post.run(c, fence, pool)
    assert post.runs["post"] == 0
    assert result.status == "error" and "may have run once" in result.content


# ------------------------------------------------------------------ run formats


async def runnable(pool: Pool, settings: Settings, run_format: int) -> Any:
    run = await RunService(pool, settings, GRAPHS).create_run(
        "assistant", {"message": "go", "script": [{"content": "hi"}]}
    )
    async with pool.connection() as conn:
        await conn.execute("UPDATE runs SET run_format = %s WHERE id = %s", (run_format, run.id))
        return await RunRepository(conn).get(run.id)


async def test_a_lease_raises_the_runs_format_so_older_workers_never_take_it_back(
    pool: Pool,
) -> None:
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        run = await repo.create(graph_name="assistant", input={})
        assert (run.run_format, (await repo.get(run.id)).code_version) == (1, code_version())
        lease = await repo.acquire_lease(run.id, "new:1", ttl_s=60)  # a newer worker …
        assert lease is not None and (await repo.get(run.id)).run_format == RUN_FORMAT
        await conn.execute("UPDATE runs SET lease_expires_at = now() - interval '1 s' "
                           "WHERE id = %s", (run.id,))  # fmt: skip
        # … dies; an older one can't reclaim it, and changes nothing trying.
        assert await repo.acquire_lease(run.id, "old:1", 60, run_format=RUN_FORMAT - 1) is None
        after = await repo.get(run.id)
        assert (after.owner, after.epoch) == ("new:1", lease.fence.epoch)


async def test_a_worker_leaves_a_run_written_by_newer_code(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    run = await runnable(pool, test_settings, RUN_FORMAT + 1)
    executor = RunExecutor(pool, test_settings, GRAPHS, owner="old-worker:1")
    left = await executor.execute(run.id)
    assert executor.deferred and left.status is S.QUEUED
    async with pool.connection() as conn:
        after = await RunRepository(conn).get(run.id)
        checkpoints = await (await conn.execute(
            "SELECT count(*) AS n FROM checkpoints WHERE thread_id = %s",
            (after.thread_id,))).fetchone()  # fmt: skip
    assert (after.owner, after.epoch, after.steps) == (None, run.epoch, 0)  # untouched
    assert checkpoints is not None and checkpoints["n"] == 0


async def test_the_worker_acks_it_and_leaves_the_resend_to_the_relay(
    pool: Pool, queue: RedisWorkQueue, test_settings: Settings, checkpoint_tables: None
) -> None:
    run = await runnable(pool, test_settings, RUN_FORMAT + 1)
    worker = Worker(pool, queue, test_settings, GRAPHS)
    await queue.enqueue(run.id)
    (delivery,) = await queue.read(worker.consumer, count=1, block_ms=1000)
    await worker._handle(delivery)
    assert await queue.pending_count() == 0  # acked: no worker spins on it …
    assert await queue.read(worker.consumer, count=1, block_ms=100) == []  # … nor re-sent now
    # The relay re-sends a queued run whose message is stale: a newer worker gets it.


async def test_a_worker_runs_a_run_from_before_formats(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    run = await runnable(pool, test_settings, 1)  # what every run created before H7 reads as
    done = await RunExecutor(pool, test_settings, GRAPHS, owner="new-worker:1").execute(run.id)
    assert done.status is S.COMPLETED
    async with pool.connection() as conn:
        assert (await RunRepository(conn).get(run.id)).run_format == RUN_FORMAT


# ------------------------------------------------------------------ the repair


async def test_a_replayed_result_goes_through_the_post_tool_hooks(pool: Pool, fence: Fence) -> None:
    secret = "sk-" + "abcdefghijklmnopqrstuvwxyz0123"
    hooks = HookRegistry()

    @hooks.hook("tag", point="post_tool")
    async def tag(inp: ToolHookInput) -> HookDecision:
        return Modify({"tagged": inp.result})

    @hooks.hook("withhold", point="post_tool")
    async def withhold(inp: ToolHookInput) -> HookDecision:
        return Deny("not for the model")

    c = call("echo", text="x")
    redact = default_hooks().get("redact_secrets_in_result")
    shown_by = Tools(post_hooks=[redact, hooks.get("tag")])
    shown = await shown_by.pipeline().replay(
        c, "done", {"text": secret}, shown_by.context(fence, pool)
    )
    assert secret not in shown.content and "[REDACTED]" in shown.content
    assert shown.content.startswith('<data source="echo">') and "tagged" in shown.content
    held_by = Tools(post_hooks=[hooks.get("withhold")])
    held = await held_by.pipeline().replay(c, "done", {"text": "x"}, held_by.context(fence, pool))
    assert held.status == "error" and "withheld" in held.content


def _tool_result(rows: list[Any], call_id: str) -> dict[str, Any]:
    return next(r.content for r in rows if r.type == "tool_result"
                and r.content["tool_call_id"] == call_id)  # fmt: skip


async def _cut_short(pool: Pool, settings: Settings, sid: uuid.UUID, *texts: str) -> Any:
    """A turn whose last step is cut short: its 3rd identical call fails it (loop
    detected), leaving the step's other calls (`texts`) unanswered in the thread."""
    same = scripted("save_note", text="same")
    others = [scripted("save_note", text=t) for t in texts]
    sent = await sessions(pool, settings).send(
        sid, "loop", script=[tools(same), tools(same), tools(*others, same)]
    )
    failed = await RunExecutor(pool, settings, GRAPHS).execute(sent.run.id)
    assert (failed.status, failed.reason) == (S.FAILED, "loop_detected")
    return failed


async def test_the_next_turn_says_what_really_happened_to_each_unanswered_call(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    sid = await chat(pool, test_settings)
    failed = await _cut_short(pool, test_settings, sid, "kept", "cut")
    thread = await thread_messages(pool, sid)
    ids = {tc["args"]["text"]: str(tc["id"]) for tc in thread[-1].tool_calls}

    def place(text: str) -> str:
        c = ToolCall(ids[text], "save_note", {}, call_index(thread, ids[text]))
        return call_key(failed.id, c)

    ran = {"note_id": "kept-0001"}
    async with pool.connection() as conn:
        # The failing call cancelled the step's others, mid-call or before they began
        # (timing). Say `kept` finished first (its result recorded), `cut` was cut off
        # mid-call, and the refused `same` was never recorded.
        await conn.execute("DELETE FROM tool_invocations WHERE call_key = ANY(%s)",
                           ([place(t) for t in ids],))  # fmt: skip
        await conn.execute(
            "INSERT INTO tool_invocations (key, call_key, run_id, tool, status, result, epoch) "
            "SELECT v.k, v.p, r.id, 'save_note', v.s, v.res, r.epoch FROM runs r, "
            "(VALUES (%s, %s, 'done', %s::jsonb), (%s, %s, 'in_progress', NULL::jsonb)) "
            "AS v(k, p, s, res) WHERE r.id = %s",
            ("a" * 64, place("kept"), Jsonb(ran), "b" * 64, place("cut"), failed.id),
        )

    ok = await turn(pool, test_settings, sid, "next", [{"content": "fine"}])
    assert ok.status is S.COMPLETED
    rows = [m for m in await transcript(pool, sid) if m.run_id == ok.id]
    shown = _tool_result(rows, ids["kept"])
    assert shown["result"] == ran and shown["cached"]  # its real result, from the ledger
    assert _tool_result(rows, ids["cut"])["error"] == CUT_OFF_TOOL_RESULT
    assert "did not run" in _tool_result(rows, ids["same"])["error"]
    # What the model saw: the result marked as data, as when a call is served again.
    model_saw = next(m for m in await thread_messages(pool, sid)
                     if getattr(m, "tool_call_id", None) == ids["kept"])  # fmt: skip
    assert model_saw.content == as_data("save_note", json.dumps(ran))


async def test_a_call_from_before_the_upgrade_is_never_said_not_to_have_run(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    """Rows a release before H7 left have no place, and their key hashed arguments the
    repair can't always rebuild: a call of that tool may be one of them, so it may have
    run; the repair never says it didn't."""
    sid = await chat(pool, test_settings)
    failed = await _cut_short(pool, test_settings, sid, "x")
    async with pool.connection() as conn:  # as the older release would have left them
        await conn.execute("UPDATE tool_invocations SET call_key = NULL, "
                           "key = md5(key) || md5(key || 'x') WHERE run_id = %s",
                           (failed.id,))  # fmt: skip
    ok = await turn(pool, test_settings, sid, "next", [{"content": "fine"}])
    repairs = [m.content["error"] for m in await transcript(pool, sid)
               if m.run_id == ok.id and m.type == "tool_result"]  # fmt: skip
    assert len(repairs) == 2 and all(r == CUT_OFF_TOOL_RESULT for r in repairs)

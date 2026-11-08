"""ToolPipeline against real Postgres: order, idempotency, grants, hooks, approval, budgets."""

from collections import Counter
from typing import Any

import pytest

from agent_runtime.db import Pool
from agent_runtime.fencing import Fence, FencedError
from agent_runtime.runs.approvals import args_hash
from agent_runtime.runs.events import EventType as E
from agent_runtime.runs.state import RunStatus
from agent_runtime.runs.store import RunRepository
from agent_runtime.tools.builtin import CalculatorArgs, NotifyArgs, calculator, notify
from agent_runtime.tools.hooks import (
    Ask,
    Continue,
    Deny,
    HookDecision,
    HookRegistry,
    Modify,
    ToolHookInput,
    default_hooks,
)
from agent_runtime.tools.invocations import BudgetExceeded
from agent_runtime.tools.pipeline import Grant, ToolCall, ToolPipeline, ToolRunContext
from agent_runtime.tools.policy import Deny as PolicyDeny
from agent_runtime.tools.policy import RiskClassPolicy
from agent_runtime.tools.spec import ToolArgs, ToolContext, ToolRegistry
from agent_runtime.untrusted import as_data

pytestmark = pytest.mark.integration


class EchoArgs(ToolArgs):
    text: str


class Harness:
    """A registry with spy tools, a fake interrupt, and an event sink."""

    def __init__(self, resume: Any = None) -> None:
        self.executions: Counter[str] = Counter()
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.interrupts: list[dict[str, Any]] = []
        self.stages: list[str] = []
        self.resume = resume
        self.registry = ToolRegistry()

        @self.registry.tool("echo", args=EchoArgs, risk_class="read", side_effect=False)
        async def echo(args: EchoArgs, ctx: ToolContext) -> dict[str, Any]:
            self.executions["echo"] += 1
            return {"text": args.text}

        @self.registry.tool("big", args=EchoArgs, risk_class="read", side_effect=False)
        async def big(args: EchoArgs, ctx: ToolContext) -> str:
            return "x" * 100_000

        @self.registry.tool("boom", args=EchoArgs, risk_class="read", side_effect=False)
        async def boom(args: EchoArgs, ctx: ToolContext) -> str:
            self.executions["boom"] += 1
            raise RuntimeError("tool bug")

        self.registry.tool("calculator", args=CalculatorArgs, risk_class="read", side_effect=False)(
            calculator
        )
        self.registry.tool(
            "notify", args=NotifyArgs, risk_class="external_side_effect", side_effect=True
        )(notify)

    def interrupt(self, payload: dict[str, Any]) -> Any:
        self.interrupts.append(payload)
        approve = isinstance(self.resume, dict) and self.resume.get("decision") == "approve"
        if approve and "args_hash" not in self.resume:
            # What the worker does (H1): the decision comes bound to the call asked.
            return self.resume | {"args_hash": payload["args_hash"]}
        return self.resume

    def pipeline(self) -> ToolPipeline:
        return ToolPipeline(
            self.registry, RiskClassPolicy(), interrupt=self.interrupt, stages=self.stages
        )

    def ctx(self, fence: Fence, pool: Pool, **kw: Any) -> ToolRunContext:
        grants = kw.pop(
            "grants", {n: Grant() for n in ("echo", "big", "boom", "calculator", "notify")}
        )
        return ToolRunContext(
            fence=fence,
            pool=pool,
            grants=grants,
            emit=lambda t, p: self.events.append((t, p)),
            **kw,
        )

    def event_types(self) -> list[str]:
        return [t for t, _ in self.events]


@pytest.fixture
async def fence(pool: Pool) -> Fence:
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        run = await repo.create(graph_name="assistant", input={})
        lease = await repo.acquire_lease(run.id, "pipe:1", ttl_s=60)
        assert lease is not None
        await repo.transition(run.id, RunStatus.RUNNING, event=E.RUN_STARTED, fence=lease.fence)
    return lease.fence


def call(name: str, index: int = 0, **args: Any) -> ToolCall:
    return ToolCall(id=f"c{index}", name=name, args=args, index=index)


async def test_sc1_stages_run_in_the_fixed_order(pool: Pool, fence: Fence) -> None:
    h = Harness()
    result = await h.pipeline().run(call("calculator", expression="6*7"), h.ctx(fence, pool))
    assert (result.status, result.content) == ("success", as_data("calculator", '{"value": 42.0}'))
    assert h.stages == ["resolve", "schema", "grant", "pre_tool", "policy", "ledger", "execute",
                        "post_tool", "truncate", "mark"]  # fmt: skip
    assert h.event_types() == [E.TOOL_CALLED, E.TOOL_COMPLETED]


async def test_sc3_same_call_executes_once_and_replays_the_stored_result(
    pool: Pool, fence: Fence
) -> None:
    h = Harness()
    first = await h.pipeline().run(call("echo", text="hi"), h.ctx(fence, pool))
    again = await h.pipeline().run(call("echo", text="hi"), h.ctx(fence, pool))
    assert h.executions["echo"] == 1
    assert (first.cached, again.cached, again.content) == (False, True, first.content)
    assert h.stages.count("execute") == 1  # the second run never reached execute
    other = await h.pipeline().run(call("echo", text="different"), h.ctx(fence, pool))
    assert not other.cached and h.executions["echo"] == 2  # different args → new key


async def test_sc3_abandoned_call_is_re_executed_and_a_stale_epoch_is_fenced(
    pool: Pool, fence: Fence
) -> None:
    h = Harness()
    from agent_runtime.tools.pipeline import idempotency_key

    c = call("echo", text="hi")
    key = idempotency_key(fence.run_id, c, {"text": "hi"})
    async with pool.connection() as conn:
        # A dead owner (this epoch) recorded the call as in_progress, then died …
        await conn.execute(
            "INSERT INTO tool_invocations (key, run_id, tool, status, epoch) "
            "VALUES (%s, %s, 'echo', 'in_progress', %s)",
            (key, fence.run_id, fence.epoch),
        )
        # … and another worker took the run over (epoch + 1).
        await conn.execute("UPDATE runs SET epoch = epoch + 1 WHERE id = %s", (fence.run_id,))
    new_owner = Fence(fence.run_id, fence.epoch + 1)
    result = await h.pipeline().run(c, h.ctx(new_owner, pool))
    assert result.status == "success" and h.executions["echo"] == 1  # taken over, executed
    with pytest.raises(FencedError):  # the old owner can't write anymore
        await h.pipeline().run(call("echo", 1, text="zombie"), h.ctx(fence, pool))


@pytest.mark.parametrize("name", ["teleport", "notify"])
async def test_sc4_unknown_or_ungranted_tools_are_denied_and_audited(
    pool: Pool, fence: Fence, name: str
) -> None:
    h = Harness()
    ctx = h.ctx(fence, pool, grants={"echo": Grant()})
    result = await h.pipeline().run(call(name, to="a", message="b"), ctx)
    assert result.status == "error" and "Deny(not_granted)" in result.content
    assert h.events[0][0] == E.POLICY_DECISION and h.events[0][1]["kind"] == "not_granted"
    assert h.executions == Counter()


async def test_sc5_strict_args_give_a_correctable_error(pool: Pool, fence: Fence) -> None:
    h = Harness()
    bad = await h.pipeline().run(call("echo", text="hi", surprise=1), h.ctx(fence, pool))
    assert bad.stage == "schema" and "surprise" in bad.content and "Extra inputs" in bad.content
    wrong_type = await h.pipeline().run(call("echo", 1, text=5), h.ctx(fence, pool))
    assert "text" in wrong_type.content
    fixed = await h.pipeline().run(call("echo", 2, text="hi"), h.ctx(fence, pool))
    assert fixed.status == "success"


async def test_sc6_hook_modify_changes_what_executes_and_the_key(pool: Pool, fence: Fence) -> None:
    h = Harness()
    hooks = HookRegistry()

    @hooks.hook("shout", point="pre_tool")
    async def shout(inp: ToolHookInput) -> HookDecision:
        return Modify({"text": inp.args["text"].upper()})

    ctx = h.ctx(fence, pool, pre_hooks=[hooks.get("shout")])
    result = await h.pipeline().run(call("echo", text="hi"), ctx)
    assert result.content == as_data("echo", '{"text": "HI"}')
    assert "revalidate" in h.stages
    assert (E.HOOK_DECISION, "modify") in [(t, p.get("decision")) for t, p in h.events]


async def test_sc6_hook_deny_ask_and_fail_closed(pool: Pool, fence: Fence) -> None:
    hooks = HookRegistry()

    @hooks.hook("no", point="pre_tool")
    async def no(inp: ToolHookInput) -> HookDecision:
        return Deny("nope")

    @hooks.hook("ask", point="pre_tool")
    async def ask(inp: ToolHookInput) -> HookDecision:
        return Ask({"why": "check"})

    @hooks.hook("broken", point="pre_tool")
    async def broken(inp: ToolHookInput) -> HookDecision:
        raise RuntimeError("bug")

    h = Harness(resume={"decision": "approve"})
    denied = await h.pipeline().run(
        call("echo", text="a"), h.ctx(fence, pool, pre_hooks=[hooks.get("no")])
    )
    assert "denied by hook: nope" in denied.content
    asked = await h.pipeline().run(
        call("echo", 1, text="b"), h.ctx(fence, pool, pre_hooks=[hooks.get("ask")])
    )
    assert asked.status == "success" and h.interrupts[0]["reason"] == "hook asked"
    failed = await h.pipeline().run(
        call("echo", 2, text="c"), h.ctx(fence, pool, pre_hooks=[hooks.get("broken")])
    )
    assert "hook_error:broken:RuntimeError" in failed.content and h.executions["echo"] == 1


async def test_sc6_post_tool_redaction_also_applies_to_cached_results(
    pool: Pool, fence: Fence
) -> None:
    h = Harness()
    secret = "sk-" + "abcdefghijklmnopqrstuvwxyz0123"
    await h.pipeline().run(call("echo", text=secret), h.ctx(fence, pool))  # stored unredacted
    redact = default_hooks().get("redact_secrets_in_result")
    replay = await h.pipeline().run(
        call("echo", text=secret), h.ctx(fence, pool, post_hooks=[redact])
    )
    assert replay.cached and secret not in replay.content and "[REDACTED]" in replay.content


async def test_external_side_effects_need_approval_and_edits_are_applied(
    pool: Pool, fence: Fence
) -> None:
    h = Harness(
        resume={"decision": "approve", "edits": {"args": {"to": "ops", "message": "edited"}}}
    )
    result = await h.pipeline().run(call("notify", to="ceo", message="hi"), h.ctx(fence, pool))
    assert h.interrupts[0]["type"] == "tool_approval" and h.interrupts[0]["args"]["to"] == "ceo"
    assert result.status == "success"
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT recipient, message FROM outbox_notifications WHERE run_id = %s", (fence.run_id,)
        )
        assert await cur.fetchall() == [{"recipient": "ops", "message": "edited"}]
    assert h.events[0][1]["decision"] == "require_approval"


@pytest.mark.parametrize(
    "resume", [None, {}, {"decision": "reject"}, {"decision": "APPROVE"}, "yes"]
)
async def test_only_an_explicit_approval_runs_a_gated_tool(
    pool: Pool, fence: Fence, resume: Any
) -> None:
    h = Harness(resume=resume)
    result = await h.pipeline().run(call("notify", to="ceo", message="hi"), h.ctx(fence, pool))
    assert result.status == "error" and "Deny(not_approved)" in result.content
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT count(*) AS n FROM outbox_notifications WHERE run_id = %s", (fence.run_id,)
        )
        assert (await cur.fetchone() or {}).get("n") == 0


async def test_invalid_approved_edits_are_rejected(pool: Pool, fence: Fence) -> None:
    h = Harness(resume={"decision": "approve", "edits": {"args": {"to": "ops"}}})  # missing message
    result = await h.pipeline().run(call("notify", to="ceo", message="hi"), h.ctx(fence, pool))
    assert result.status == "error" and "approved edits are invalid" in result.content


async def sent(pool: Pool, fence: Fence) -> list[dict[str, Any]]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT recipient, message FROM outbox_notifications WHERE run_id = %s", (fence.run_id,)
        )
        return list(await cur.fetchall())


async def test_h1_the_approval_carries_the_hash_of_the_real_args(pool: Pool, fence: Fence) -> None:
    h = Harness(resume={"decision": "approve"})
    token = "sk-" + "abcdefghijklmnopqrstuvwxyz0123"
    await h.pipeline().run(call("notify", to="ceo", message=f"key {token}"), h.ctx(fence, pool))
    asked = h.interrupts[0]
    assert token not in str(asked["args"])  # the person is shown the redacted args…
    assert asked["args_hash"] == args_hash({"to": "ceo", "message": f"key {token}"})  # …bound
    assert asked["call_id"] == "c0"


async def test_h1_a_call_that_changed_after_approval_is_not_run(pool: Pool, fence: Fence) -> None:
    h = Harness(resume={"decision": "approve", "args_hash": "0" * 64})  # approved another call
    result = await h.pipeline().run(call("notify", to="ceo", message="hi"), h.ctx(fence, pool))
    assert result.status == "error" and "changed after it was approved" in result.content
    assert await sent(pool, fence) == []


async def test_h1_approved_edits_go_through_the_hooks(pool: Pool, fence: Fence) -> None:
    hooks = HookRegistry()

    @hooks.hook("no_evil", point="pre_tool")
    async def no_evil(inp: ToolHookInput) -> HookDecision:
        return Deny("evil is blocked") if inp.args.get("to") == "evil" else Continue()

    @hooks.hook("shout", point="pre_tool")
    async def shout(inp: ToolHookInput) -> HookDecision:
        return Modify({**inp.args, "message": inp.args["message"].upper()})

    blocked = Harness(
        resume={"decision": "approve", "edits": {"args": {"to": "evil", "message": "x"}}}
    )
    ctx = blocked.ctx(fence, pool, pre_hooks=[hooks.get("no_evil")])
    result = await blocked.pipeline().run(call("notify", to="ceo", message="hi"), ctx)
    assert result.status == "error" and "denied by a hook: evil is blocked" in result.content
    assert await sent(pool, fence) == []

    modified = Harness(
        resume={"decision": "approve", "edits": {"args": {"to": "ops", "message": "go"}}}
    )
    ctx = modified.ctx(fence, pool, pre_hooks=[hooks.get("shout")])
    result = await modified.pipeline().run(call("notify", 1, to="ceo", message="hi"), ctx)
    assert result.status == "success"
    assert await sent(pool, fence) == [{"recipient": "ops", "message": "GO"}]


async def test_h1_approved_edits_go_through_the_policy(pool: Pool, fence: Fence) -> None:
    class NoInterns(RiskClassPolicy):
        async def check(self, spec: Any, args: dict[str, Any]) -> Any:
            if args.get("to") == "interns":
                return PolicyDeny("nobody messages the interns")
            return await super().check(spec, args)

    h = Harness(
        resume={"decision": "approve", "edits": {"args": {"to": "interns", "message": "x"}}}
    )
    pipeline = ToolPipeline(h.registry, NoInterns(), interrupt=h.interrupt)
    result = await pipeline.run(call("notify", to="ceo", message="hi"), h.ctx(fence, pool))
    assert result.status == "error" and "denied by policy" in result.content
    assert await sent(pool, fence) == []


async def test_sc9_tool_budgets_count_each_key_once(pool: Pool, fence: Fence) -> None:
    h = Harness()
    ctx = h.ctx(fence, pool, max_tool_calls=2)
    for _ in range(5):  # the same call 5 times: one key, charged once
        await h.pipeline().run(call("echo", text="same"), ctx)
    await h.pipeline().run(call("echo", 1, text="second"), ctx)
    with pytest.raises(BudgetExceeded, match="max_tool_calls=2"):
        await h.pipeline().run(call("echo", 2, text="third"), ctx)
    capped = h.ctx(fence, pool, grants={"calculator": Grant(max_calls=1)})
    await h.pipeline().run(call("calculator", 3, expression="1+1"), capped)
    with pytest.raises(BudgetExceeded, match="max_calls=1 for tool 'calculator'"):
        await h.pipeline().run(call("calculator", 4, expression="2+2"), capped)


async def test_sc10_large_results_are_truncated_for_the_model(pool: Pool, fence: Fence) -> None:
    h = Harness()
    result = await h.pipeline().run(call("big", text="x"), h.ctx(fence, pool))
    assert (
        len(result.content) < 16_100
        and "[truncated: showing 16000 of 100002 characters]" in result.content
    )
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT length(result::text) AS n FROM tool_invocations WHERE run_id = %s",
            (fence.run_id,),
        )
        row = await cur.fetchone()
        assert row is not None and row["n"] > 100_000  # stored in full (under the 256 KB cap)


async def test_a_failing_tool_is_an_error_and_is_not_retried_on_replay(
    pool: Pool, fence: Fence
) -> None:
    h = Harness()
    first = await h.pipeline().run(call("boom", text="x"), h.ctx(fence, pool))
    replay = await h.pipeline().run(call("boom", text="x"), h.ctx(fence, pool))
    assert first.status == "error" and "tool bug" in first.content
    assert replay.cached and h.executions["boom"] == 1


async def test_continue_hooks_are_not_audited(pool: Pool, fence: Fence) -> None:
    hooks = HookRegistry()

    @hooks.hook("fine", point="pre_tool")
    async def fine(inp: ToolHookInput) -> HookDecision:
        return Continue()

    h = Harness()
    await h.pipeline().run(
        call("echo", text="a"), h.ctx(fence, pool, pre_hooks=[hooks.get("fine")])
    )
    assert E.HOOK_DECISION not in h.event_types()

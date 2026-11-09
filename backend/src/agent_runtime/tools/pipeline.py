"""ToolPipeline: the only way a tool executes (R3.4, R15.7).

Pattern: Chain of Responsibility with a FIXED order (CR-004 R15.7):

    1 resolve     unknown tool (hallucinated / injected name) → Deny(not_granted)
    2 schema      strict args (R14.11) → a tool error the model can correct
    3 grant       deny by default (R14.9): not granted to this agent/node → Deny(not_granted)
    4 pre_tool    hooks: continue · modify(args) · deny · ask        (fail closed, R15.8)
    5 re-validate if hooks modified the args
    6 policy      Allow · Deny · RequireApproval; RequireApproval or a hook's ask → interrupt()
                  (the run pauses durably; on resume LangGraph re-runs this whole pipeline and
                  interrupt() returns the human's decision for THIS call: it runs only if the
                  approved args hash matches; approved edits go through validation, the
                  pre_tool hooks and the policy again — phase H1)
    7+8 ledger    idempotency key = sha256(run · node · call_index · tool · canonical(args));
                  budgets checked and charged only when a key is first recorded (R14.1, R2.6);
                  a budget used up denies the call (a tool error), it doesn't fail the run
                  done → cached result, no execution; in_progress at an older epoch → re-execute
                  with the SAME key, which the tool uses to dedupe its own effect
    9 execute     in-process (phase 7 adds isolation: sandbox), with a timeout (R14.5)
   10 post_tool   hooks: continue · modify(result) · deny        (also for cached results)
   11 truncate    ≤ max_result_chars to the model, with a marker (R14.5)
   12 mark        as untrusted data, in delimiters the text can't close (R14.15)

Every non-trivial decision is staged as an audit event (R14.17), committed with
the step's checkpoint and published after commit (phase 3).

The pipeline is independent of LangChain; `middleware.py` adapts it to
`create_agent`, and workflow nodes can call it directly.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from agent_runtime import genai, logs, telemetry
from agent_runtime.db import Conn, Pool
from agent_runtime.fencing import Fence
from agent_runtime.redaction import redact
from agent_runtime.runs import approvals
from agent_runtime.runs.events import EventType
from agent_runtime.tools import invocations
from agent_runtime.tools.hooks import Ask, Deny, HookSpec, ToolHookInput, run_hooks
from agent_runtime.tools.policy import Allow, PolicyContext, RequireApproval, ToolPolicy
from agent_runtime.tools.policy import Deny as PolicyDeny
from agent_runtime.tools.spec import ToolContext, ToolRegistry, ToolSpec
from agent_runtime.untrusted import as_data

log = logging.getLogger(__name__)

Emit = Callable[[EventType, dict[str, Any]], None]
Interrupt = Callable[[Any], Any]  # langgraph.types.interrupt, injectable for tests


@dataclass(frozen=True)
class ToolCall:
    id: str  # the model's tool_call id (stable across resume: measured)
    name: str
    args: dict[str, Any]
    index: int  # position among all tool calls in the run's conversation (replay-stable)
    node: str = "tools"


@dataclass(frozen=True)
class Grant:
    max_calls: int | None = None  # per-agent cap; the tighter of this and the tool's own


@dataclass
class ToolRunContext:
    """Everything the pipeline needs about the run it is serving."""

    fence: Fence
    pool: Pool
    grants: dict[str, Grant]
    emit: Emit
    pre_hooks: list[HookSpec] = field(default_factory=list)
    post_hooks: list[HookSpec] = field(default_factory=list)
    max_tool_calls: int | None = None
    node: str = "tools"  # part of the idempotency key: one per checkpoint thread
    # Sub-agents (CR-005 R16.7) can't pause for a human: RequireApproval / ask → deny.
    approvals: bool = True
    orchestrator: Any = None  # given to sub-agent tools (ToolContext)
    subagent: Any = None
    skills: Any = None  # the caller's own skills, given to the skill tools (ToolContext)
    # Charged in the ledger's transaction when a call is first recorded (a
    # sub-agent's own budget, on top of the run's).
    extra_charge: Callable[[Conn, str], Awaitable[None]] | None = None
    # A Studio test chat (CR-006 R17.3): after approval, an external side effect is
    # recorded but not performed. Nothing leaves a test chat.
    simulate_side_effects: bool = False
    settings: Any = None  # the run's settings, passed on to tools that need them (MCP)


@dataclass(frozen=True)
class ToolResult:
    content: str  # what the model sees (truncated JSON; a tool's output marked as data)
    status: Literal["success", "error"]
    cached: bool = False
    stage: str = "execute"  # where the call ended (tests and audits)


def repeat_hash(call: ToolCall, args: dict[str, Any]) -> str:
    """R14.4: the same call regardless of its position (node · tool · canonical args)."""
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(f"{call.node}·{call.name}·{canonical}".encode()).hexdigest()


def idempotency_key(run_id: uuid.UUID, call: ToolCall, args: dict[str, Any]) -> str:
    """R2.6. Deliberately excludes the epoch: a retry after reclaim finds the same key."""
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    material = f"{run_id}·{call.node}·{call.index}·{call.name}·{canonical}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class ToolPipeline:
    def __init__(
        self,
        registry: ToolRegistry,
        policy: ToolPolicy,
        *,
        interrupt: Interrupt,
        max_result_chars: int = 16_000,
        max_stored_chars: int = 256_000,
        tool_timeout_s: float = 30.0,
        stages: list[str] | None = None,  # test spy: records the order stages ran in
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._interrupt = interrupt
        self._max_result = max_result_chars
        self._max_stored = max_stored_chars
        self._timeout = tool_timeout_s
        self._stages = stages

    def _at(self, stage: str) -> None:
        if self._stages is not None:
            self._stages.append(stage)

    async def run(self, call: ToolCall, ctx: ToolRunContext) -> ToolResult:
        """Run `call` through every stage, in a `tool:{name}` span (R7.1)."""
        attrs = {"tool.call_id": call.id, **genai.tool(call.name, call.id)}
        with (
            telemetry.child_span(f"tool:{call.name}", attrs) as span,
            logs.bind(tool=call.name, tool_call_id=call.id),
        ):
            t0 = time.monotonic()
            result = await self._run(call, ctx)
            span.set_attributes({
                "tool.status": result.status, "tool.cached": result.cached,
                "tool.stage": result.stage,
            })  # fmt: skip
            logs.event(log, f"tool call: {call.name} {result.status}", status=result.status,
                       cached=result.cached or None, stage=result.stage,
                       duration_ms=round((time.monotonic() - t0) * 1000))  # fmt: skip
        return result

    async def _run(self, call: ToolCall, ctx: ToolRunContext) -> ToolResult:
        # 1 resolve
        self._at("resolve")
        if call.name not in self._registry:
            return self._deny(call, ctx, "not_granted", f"unknown tool {call.name!r}", "resolve")
        spec = self._registry.get(call.name)

        # 2 schema
        self._at("schema")
        args, error = self._validate(spec, call.args)
        if error is not None:
            return ToolResult(
                f"Error: invalid arguments for {spec.name}: {error}", "error", stage="schema"
            )

        # 3 grant
        self._at("grant")
        if spec.name not in ctx.grants:
            return self._deny(call, ctx, "not_granted", f"{spec.name} is not granted", "grant")

        # 4 pre_tool hooks
        self._at("pre_tool")
        pre = await run_hooks(ctx.pre_hooks, ToolHookInput(spec.name, args))
        self._audit_hooks(ctx, call, pre.audit)
        if isinstance(pre.decision, Deny):
            return ToolResult(
                f"Error: denied by hook: {pre.decision.reason}", "error", stage="pre_tool"
            )

        # 5 re-validate
        if pre.input.args != args:
            self._at("revalidate")
            args, error = self._validate(spec, pre.input.args)
            if error is not None:
                return ToolResult(
                    f"Error: a hook produced invalid arguments: {error}",
                    "error",
                    stage="revalidate",
                )

        # 6 policy (+ approval)
        self._at("policy")
        decision = await self._policy.check(spec, args, PolicyContext(ctx.fence.run_id, ctx.pool))
        if isinstance(decision, PolicyDeny):
            return self._deny(call, ctx, "policy", decision.reason, "policy")
        if isinstance(decision, RequireApproval) or isinstance(pre.decision, Ask):
            reason = decision.reason if isinstance(decision, RequireApproval) else "hook asked"
            if not ctx.approvals:
                return self._deny(
                    call, ctx, "approval_unavailable",
                    f"{reason}; approval is only available to the main agent", "policy",
                )  # fmt: skip
            if not await _asked_before(ctx, call.id):  # a resume re-runs the node: once
                ctx.emit(
                    EventType.POLICY_DECISION,
                    {
                        "tool": spec.name,
                        "call_id": call.id,
                        "decision": "require_approval",
                        "reason": reason,
                    },
                )
            asked = approvals.args_hash(args)  # the call being asked: real args
            resume = self._interrupt(
                {
                    "type": approvals.APPROVAL_TYPE,
                    "tool": spec.name,
                    "args": redact(args),
                    "call_id": call.id,
                    "reason": reason,
                    "args_hash": asked,
                }
            )
            # Fail closed: only an explicit approval OF THIS CALL runs the tool. (A
            # rejection normally cancels the run before any resume; this doesn't rely on
            # that.) A call that changed since it was approved isn't run (phase H1).
            if not (isinstance(resume, dict) and resume.get("decision") == "approve"):
                return self._deny(
                    call, ctx, "not_approved", "a person didn't approve this call", "policy"
                )
            if resume.get("args_hash") != asked:
                return self._deny(
                    call, ctx, "not_approved",
                    "the call changed after it was approved, so it wasn't run", "policy",
                )  # fmt: skip
            edited = (resume.get("edits") or {}).get("args")
            if edited is not None:
                args, error = await self._checked_edits(spec, call, ctx, edited)
                if error is not None:
                    return ToolResult(f"Error: approved edits {error}", "error", stage="policy")
        else:
            assert isinstance(decision, Allow)

        # 7+8 ledger: budgets + idempotency
        self._at("ledger")
        key = idempotency_key(ctx.fence.run_id, call, args)
        repeat = None if spec.repeatable else repeat_hash(call, args)
        grant = ctx.grants[spec.name]
        caps = [c for c in (grant.max_calls, spec.max_calls) if c is not None]
        try:
            async with ctx.pool.connection() as conn:
                begun = await invocations.begin(
                    conn,
                    fence=ctx.fence,
                    key=key,
                    tool=spec.name,
                    max_total=ctx.max_tool_calls,
                    max_for_tool=min(caps) if caps else None,
                    extra_charge=ctx.extra_charge,
                    args_hash=repeat,
                )  # LoopDetected propagates: the run fails (R14.4)
        except invocations.BudgetExceeded as exc:
            # A tool budget used up doesn't crash the step (phase H2): this call isn't
            # made, the calls already done keep their results, and the next model call is
            # the wrap-up (R14.2). Nothing was recorded or charged.
            return self._deny(call, ctx, "budget", f"{exc}; this call wasn't made", "ledger")

        cached = isinstance(begun, invocations.Cached)
        t0 = time.monotonic()
        if isinstance(begun, invocations.Cached):
            status, result = begun.status, begun.result
        else:
            # 9 execute
            self._at("execute")
            ctx.emit(
                EventType.TOOL_CALLED,
                {
                    "tool": spec.name,
                    "call_id": call.id,
                    "args": _summary(redact(args)),
                    "taken_over": begun.taken_over,  # re-executing a dead owner's call
                },
            )
            if begun.taken_over and not spec.retry_after_crash:
                # A remote call can't be deduplicated: it may have happened once already.
                status, result = (
                    "failed",
                    {"error": "This call was cut off by a crash and may have run once "
                              "already, so it wasn't sent again. Ask the person whether to "
                              "try it again."},
                )  # fmt: skip
            elif ctx.simulate_side_effects and spec.risk_class == "external_side_effect":
                status, result = (
                    "done",
                    {
                        "simulated": True,
                        "note": "Test chat: nothing was sent. Published, this would really happen.",
                        "would_have": redact(args),
                    },
                )
            else:
                status, result = await self._execute(
                    spec,
                    args,
                    ToolContext(
                        run_id=ctx.fence.run_id,
                        epoch=ctx.fence.epoch,
                        key=key,
                        pool=ctx.pool,
                        orchestrator=ctx.orchestrator,
                        subagent=ctx.subagent,
                        skills=ctx.skills,
                        settings=ctx.settings,
                    ),
                )
            async with ctx.pool.connection() as conn:
                await invocations.finish(
                    conn,
                    fence=ctx.fence,
                    key=key,
                    status=status,
                    result=_cap(result, self._max_stored),
                )
        ctx.emit(
            EventType.TOOL_COMPLETED,
            {
                "tool": spec.name,
                "call_id": call.id,
                "cached": cached,
                "status": status,
                "duration_ms": round((time.monotonic() - t0) * 1000),
            },
        )

        # 10 post_tool hooks (also on cached results: a redaction must never be skipped)
        self._at("post_tool")
        post = await run_hooks(ctx.post_hooks, ToolHookInput(spec.name, args, result, cached))
        self._audit_hooks(ctx, call, post.audit)
        if isinstance(post.decision, Deny):
            return ToolResult(
                f"Error: result withheld by hook: {post.decision.reason}",
                "error",
                cached=cached,
                stage="post_tool",
            )

        # 11 truncate
        self._at("truncate")
        content = _truncate(json.dumps(post.input.result, default=str), self._max_result)
        # 12 mark: whatever the tool returned is data, never instructions
        self._at("mark")
        content = as_data(spec.name, content)
        return ToolResult(content, "success" if status == "done" else "error", cached=cached)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _validate(spec: ToolSpec, raw: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        if spec.input_schema is not None:  # an MCP tool (L8): its own JSON Schema
            errors = sorted(Draft202012Validator(spec.input_schema).iter_errors(raw),
                            key=lambda e: list(e.path))  # fmt: skip
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e.path) or '(args)'}: {e.message}" for e in errors
            )
            return dict(raw), problems or None
        try:
            return spec.args_model.model_validate(raw).model_dump(mode="json"), None
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or '(args)'}: {e['msg']}"
                for e in exc.errors()
            )
            return raw, problems

    async def _checked_edits(
        self, spec: ToolSpec, call: ToolCall, ctx: ToolRunContext, edited: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        """Arguments a person edited when approving go through the same checks as the
        model's own: validation, the pre_tool hooks (a deny or a modify applies; asking
        again is pointless) and the policy (a deny applies)."""
        args, error = self._validate(spec, edited)
        if error is not None:
            return args, f"are invalid: {error}"
        checked = await run_hooks(ctx.pre_hooks, ToolHookInput(spec.name, args), ignore_ask=True)
        self._audit_hooks(ctx, call, checked.audit)
        if isinstance(checked.decision, Deny):
            return args, f"were denied by a hook: {checked.decision.reason}"
        if checked.input.args != args:
            args, error = self._validate(spec, checked.input.args)
            if error is not None:
                return args, f"became invalid in a hook: {error}"
        verdict = await self._policy.check(spec, args, PolicyContext(ctx.fence.run_id, ctx.pool))
        if isinstance(verdict, PolicyDeny):
            self._deny(call, ctx, "policy", verdict.reason, "policy")  # recorded
            return args, f"were denied by policy: {verdict.reason}"
        return args, None

    async def _execute(
        self, spec: ToolSpec, args: dict[str, Any], tctx: ToolContext
    ) -> tuple[Literal["done", "failed"], Any]:
        timeout = spec.timeout_s or self._timeout
        try:
            parsed = (
                dict(args)
                if spec.input_schema is not None
                else spec.args_model.model_validate(args)
            )
            result = await asyncio.wait_for(spec.fn(parsed, tctx), timeout=timeout)
            return "done", json.loads(json.dumps(result, default=str))
        except TimeoutError:
            return "failed", {"error": f"tool timed out after {timeout:g}s"}
        except Exception as exc:
            return "failed", {"error": f"{type(exc).__name__}: {exc}"[:2000]}

    def _deny(
        self, call: ToolCall, ctx: ToolRunContext, kind: str, reason: str, stage: str
    ) -> ToolResult:
        ctx.emit(
            EventType.POLICY_DECISION,
            {
                "tool": call.name,
                "call_id": call.id,
                "decision": "deny",
                "kind": kind,
                "reason": reason,
            },
        )
        return ToolResult(f"Error: Deny({kind}): {reason}", "error", stage=stage)

    @staticmethod
    def _audit_hooks(ctx: ToolRunContext, call: ToolCall, records: list[dict[str, Any]]) -> None:
        for record in records:
            ctx.emit(EventType.HOOK_DECISION, {"tool": call.name, "call_id": call.id, **record})


def _summary(args: dict[str, Any], limit: int = 200) -> str:
    text = json.dumps(args, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…[truncated: showing {limit} of {len(text)} characters]"


def _cap(result: Any, limit: int) -> Any:
    text = json.dumps(result, default=str)
    return result if len(text) <= limit else {"truncated": _truncate(text, limit)}


async def _asked_before(ctx: ToolRunContext, call_id: str) -> bool:
    """Was this call's approval asked already? After the person decides, the node runs
    again from its start (LangGraph's resume), so the decision would be logged twice."""
    async with ctx.pool.connection() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM run_events WHERE run_id = %s AND type = %s "
            "AND payload->>'call_id' = %s LIMIT 1",
            (ctx.fence.run_id, EventType.POLICY_DECISION.value, call_id),
        )
        return await cur.fetchone() is not None

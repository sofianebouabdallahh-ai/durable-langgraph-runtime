"""ToolPipeline: the only way a tool executes (R3.4, R15.7).

Pattern: Chain of Responsibility with a FIXED order (CR-004 R15.7):

    1 resolve     unknown tool (hallucinated / injected name) → Deny(not_granted)
    2 schema      strict args (R14.11) → a tool error the model can correct
    3 grant       deny by default (R14.9): not granted to this agent/node → Deny(not_granted)
    4 pre_tool    hooks: continue · modify(args) · deny · ask        (fail closed, R15.8)
    5 re-validate if hooks modified the args
    6 policy      Allow · Deny · RequireApproval; RequireApproval or a hook's ask → interrupt()
                  (the run pauses durably; on resume LangGraph re-runs this whole pipeline and
                  interrupt() returns the human's decision; approved edits are re-validated)
    7+8 ledger    idempotency key = sha256(run · node · call_index · tool · canonical(args));
                  budgets checked and charged only when a key is first recorded (R14.1, R2.6)
                  done → cached result, no execution; in_progress at an older epoch → re-execute
                  with the SAME key, which the tool uses to dedupe its own effect
    9 execute     in-process (phase 7 adds isolation: sandbox), with a timeout (R14.5)
   10 post_tool   hooks: continue · modify(result) · deny        (also for cached results)
   11 truncate    ≤ max_result_chars to the model, with a marker (R14.5)

Every non-trivial decision is staged as an audit event (R14.17), committed with
the step's checkpoint and published after commit (phase 3).

The pipeline is independent of LangChain; `middleware.py` adapts it to
`create_agent`, and workflow nodes can call it directly.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from agent_runtime.db import Pool
from agent_runtime.fencing import Fence
from agent_runtime.runs.events import EventType
from agent_runtime.tools import invocations
from agent_runtime.tools.hooks import Ask, Deny, HookSpec, ToolHookInput, redact, run_hooks
from agent_runtime.tools.policy import Allow, RequireApproval, ToolPolicy
from agent_runtime.tools.policy import Deny as PolicyDeny
from agent_runtime.tools.spec import ToolContext, ToolRegistry, ToolSpec

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


@dataclass(frozen=True)
class ToolResult:
    content: str  # what the model sees (truncated, JSON)
    status: Literal["success", "error"]
    cached: bool = False
    stage: str = "execute"  # where the call ended (tests and audits)


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
        decision = await self._policy.check(spec, args)
        if isinstance(decision, PolicyDeny):
            return self._deny(call, ctx, "policy", decision.reason, "policy")
        if isinstance(decision, RequireApproval) or isinstance(pre.decision, Ask):
            reason = decision.reason if isinstance(decision, RequireApproval) else "hook asked"
            ctx.emit(
                EventType.POLICY_DECISION,
                {
                    "tool": spec.name,
                    "call_id": call.id,
                    "decision": "require_approval",
                    "reason": reason,
                },
            )
            resume = self._interrupt(
                {
                    "type": "tool_approval",
                    "tool": spec.name,
                    "args": redact(args),
                    "call_id": call.id,
                    "reason": reason,
                }
            )
            edited = (
                (resume or {}).get("edits", {}).get("args") if isinstance(resume, dict) else None
            )
            if edited is not None:
                args, error = self._validate(spec, edited)
                if error is not None:
                    return ToolResult(
                        f"Error: approved edits are invalid: {error}", "error", stage="policy"
                    )
        else:
            assert isinstance(decision, Allow)

        # 7+8 ledger: budgets + idempotency
        self._at("ledger")
        key = idempotency_key(ctx.fence.run_id, call, args)
        grant = ctx.grants[spec.name]
        caps = [c for c in (grant.max_calls, spec.max_calls) if c is not None]
        async with ctx.pool.connection() as conn:
            begun = await invocations.begin(
                conn,
                fence=ctx.fence,
                key=key,
                tool=spec.name,
                max_total=ctx.max_tool_calls,
                max_for_tool=min(caps) if caps else None,
            )  # BudgetExceeded propagates: the run fails (R14.1)

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
            status, result = await self._execute(
                spec,
                args,
                ToolContext(run_id=ctx.fence.run_id, epoch=ctx.fence.epoch, key=key, pool=ctx.pool),
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
        return ToolResult(content, "success" if status == "done" else "error", cached=cached)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _validate(spec: ToolSpec, raw: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        try:
            return spec.args_model.model_validate(raw).model_dump(mode="json"), None
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or '(args)'}: {e['msg']}"
                for e in exc.errors()
            )
            return raw, problems

    async def _execute(
        self, spec: ToolSpec, args: dict[str, Any], tctx: ToolContext
    ) -> tuple[Literal["done", "failed"], Any]:
        try:
            parsed = spec.args_model.model_validate(args)
            result = await asyncio.wait_for(spec.fn(parsed, tctx), timeout=self._timeout)
            return "done", json.loads(json.dumps(result, default=str))
        except TimeoutError:
            return "failed", {"error": f"tool timed out after {self._timeout:g}s"}
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

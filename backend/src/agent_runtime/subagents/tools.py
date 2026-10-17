"""The sub-agent tools (CR-005 R16.4, R16.5), registered like any other tool.

They go through the full ToolPipeline (grants, hooks, policy, ledger, audit).
The harness grants them automatically: the four orchestration tools to a main
agent that has sub-agents, `report_progress` / `return_result` to every
sub-agent. They reach the run's orchestrator through `ToolContext`.

Idempotency: `spawn_subagent` derives the handle from its own idempotency key,
so a replayed spawn (after a crash) returns the same handle and never starts a
second sub-agent.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from pydantic import Field

from agent_runtime.tools.spec import ToolArgs, ToolContext, ToolRegistry

MAIN_TOOLS = ("spawn_subagent", "subagent_status", "wait_subagents", "cancel_subagent")
SUB_TOOLS = ("report_progress", "return_result")
WAIT_MAX_S = 120


class SpawnArgs(ToolArgs):
    agent: Annotated[str, Field(min_length=1, max_length=64)]
    task: Annotated[str, Field(min_length=1, max_length=8000)]
    context: Annotated[str, Field(max_length=16000)] | None = None


class StatusArgs(ToolArgs):
    handles: list[str] | None = None


class WaitArgs(ToolArgs):
    handles: Annotated[list[str], Field(min_length=1, max_length=10)]
    timeout_s: Annotated[int, Field(ge=1, le=WAIT_MAX_S)] = 60


class CancelArgs(ToolArgs):
    handle: str
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class ProgressArgs(ToolArgs):
    message: Annotated[str, Field(min_length=1, max_length=500)]
    percent: Annotated[int, Field(ge=0, le=100)] | None = None


class ReturnArgs(ToolArgs):
    summary: Annotated[str, Field(min_length=1, max_length=4000)]
    result: dict[str, Any] | None = None
    status: Literal["success", "partial", "failed"] = "success"


class SubagentToolError(Exception):
    """Shown to the model as the tool's error (the pipeline records it as failed)."""


def _handles(raw: list[str]) -> list[uuid.UUID]:
    try:
        return [uuid.UUID(h) for h in raw]
    except ValueError:
        raise SubagentToolError(f"not a sub-agent handle: {raw!r}") from None


def _orchestrator(ctx: ToolContext) -> Any:
    if ctx.orchestrator is None:
        raise SubagentToolError("this agent has no sub-agents")
    return ctx.orchestrator


def _subagent(ctx: ToolContext) -> Any:
    if ctx.subagent is None:
        raise SubagentToolError("only a sub-agent can call this tool")
    return ctx.subagent


def register(registry: ToolRegistry) -> ToolRegistry:
    @registry.tool("spawn_subagent", args=SpawnArgs, risk_class="write_internal",
                   side_effect=True)  # fmt: skip
    async def spawn_subagent(args: SpawnArgs, ctx: ToolContext) -> dict[str, Any]:
        """Start one of your sub-agents on a focused task. Non-blocking: returns a handle
        at once; the sub-agent works in parallel. Give it everything it needs in `task`
        and `context`: it can't see this conversation."""
        inv = await _orchestrator(ctx).spawn(ctx.key, args.agent, args.task, args.context)
        return {"handle": str(inv.handle), "agent": inv.name, "status": inv.status}

    @registry.tool("subagent_status", args=StatusArgs, risk_class="read", side_effect=False,
                   repeatable=True)  # fmt: skip
    async def subagent_status(args: StatusArgs, ctx: ToolContext) -> list[dict[str, Any]]:
        """Live status, latest progress message and usage of some or all sub-agents."""
        handles = _handles(args.handles) if args.handles is not None else None
        result: list[dict[str, Any]] = await _orchestrator(ctx).status(handles)
        return result

    @registry.tool("wait_subagents", args=WaitArgs, risk_class="read", side_effect=False,
                   timeout_s=WAIT_MAX_S + 5, repeatable=True)  # fmt: skip
    async def wait_subagents(args: WaitArgs, ctx: ToolContext) -> dict[str, Any]:
        """Wait up to `timeout_s` for the given sub-agents. Returns the results of those
        that finished and the status of those still running."""
        result: dict[str, Any] = await _orchestrator(ctx).wait(
            _handles(args.handles), args.timeout_s
        )
        return result

    @registry.tool("cancel_subagent", args=CancelArgs, risk_class="write_internal",
                   side_effect=False)  # fmt: skip
    async def cancel_subagent(args: CancelArgs, ctx: ToolContext) -> dict[str, Any]:
        """Ask a sub-agent to stop. It stops before its next step or tool call."""
        (handle,) = _handles([args.handle])
        requested = await _orchestrator(ctx).cancel(handle, args.reason)
        return {"handle": args.handle, "cancel_requested": requested}

    @registry.tool("report_progress", args=ProgressArgs, risk_class="write_internal",
                   side_effect=False, repeatable=True)  # fmt: skip
    async def report_progress(args: ProgressArgs, ctx: ToolContext) -> dict[str, Any]:
        """Tell the main agent how far you are. At most one update per 2 seconds."""
        dropped = await _subagent(ctx).report_progress(args.message, args.percent)
        return {"accepted": dropped is None} | ({"note": dropped} if dropped else {})

    @registry.tool("return_result", args=ReturnArgs, risk_class="write_internal",
                   side_effect=False)  # fmt: skip
    async def return_result(args: ReturnArgs, ctx: ToolContext) -> dict[str, Any]:
        """Finish your task and hand your result to the main agent. Call it exactly once,
        last. `status`: success, partial (some of the task), or failed."""
        await _subagent(ctx).return_result(args.model_dump(mode="json"))
        return {"returned": True}

    return registry

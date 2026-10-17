"""RuntimeMiddleware: adapts the runtime to LangChain's create_agent (Adapter).

- Tool calls: every call goes through the ToolPipeline; LangChain's own tool
  execution is never used. Unknown tool names reach us too (request.tool is
  None) and are denied and audited (phase 4 research).
- Model calls: each is charged against the run's budget first (R14.1), then
  served by the model chosen for this run (phase 4: the scripted model;
  phase 6 adds real providers behind the same seam).

Everything run-specific arrives through LangGraph's runtime context
(`RunContext`), set by the executor for each execution.

Sub-agents (CR-005) use the same middleware with `RunContext.subagent` set:
- a model call is charged to the sub-agent's max_turns AND the run's budget,
  after a cooperative cancel check (between steps, R16.4);
- once `return_result` was called, the next model call short-circuits to a
  final answer, which ends the sub-agent's loop without another model call;
- at the soft limit a wrap-up note is added to the request (R16.8).
A main agent with sub-agents (`RunContext.orchestrator`) gets the turn guard
(R16.9): a final answer while sub-agents run → wait for them, then one more
model call that sees their results.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from agent_runtime.models.scripted import ScriptedChatModel, ScriptTurn
from agent_runtime.tools.invocations import charge_model_call
from agent_runtime.tools.pipeline import ToolCall, ToolPipeline, ToolRunContext

if TYPE_CHECKING:
    from agent_runtime.subagents.orchestrator import SubagentOrchestrator, SubagentRuntime


@dataclass
class RunContext:
    tools: ToolRunContext
    pipeline: ToolPipeline
    max_model_calls: int | None = None
    script: list[ScriptTurn] = field(default_factory=list)
    orchestrator: SubagentOrchestrator | None = None  # a main agent with sub-agents
    subagent: SubagentRuntime | None = None  # this graph IS a sub-agent


def call_index(messages: list[Any], tool_call_id: str) -> int:
    """Position of this tool call among all tool calls in the conversation.

    Derived from the checkpointed messages, so a replay computes the same index
    and therefore the same idempotency key (R2.6)."""
    index = 0
    for message in messages:
        if isinstance(message, AIMessage):
            for tc in message.tool_calls:
                if tc["id"] == tool_call_id:
                    return index
                index += 1
    return index


class RuntimeMiddleware(AgentMiddleware[Any, RunContext]):
    async def awrap_model_call(
        self,
        request: ModelRequest[RunContext],
        handler: Callable[[ModelRequest[RunContext]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        ctx = request.runtime.context
        sub = ctx.subagent
        if sub is not None:
            if sub.returned is not None:  # return_result was called: end the loop here
                return ModelResponse(result=[AIMessage(content=str(sub.returned["summary"]))])
            await sub.before_model()
            if sub.orchestrator.wrap_up:
                from agent_runtime.subagents.orchestrator import WRAP_UP_NOTE

                request = request.override(
                    messages=[*request.messages, HumanMessage(content=WRAP_UP_NOTE)]
                )
        else:
            await self._charge(ctx)
        model = ScriptedChatModel(script=ctx.script)
        response = await handler(request.override(model=model))
        orchestrator = ctx.orchestrator
        if orchestrator is not None and _is_final(response) and orchestrator.running():
            outcomes = await orchestrator.wait_all()
            note = HumanMessage(
                content="[runtime] Your sub-agents were still running, so the runtime waited "
                "for them before you finish. Their results: " + json.dumps(outcomes, default=str)
            )
            await self._charge(ctx)
            messages: list[Any] = [*request.messages, *response.result, note]
            response = await handler(request.override(model=model, messages=messages))
        return response

    @staticmethod
    async def _charge(ctx: RunContext) -> None:
        async with ctx.tools.pool.connection() as conn:
            await charge_model_call(conn, fence=ctx.tools.fence, max_calls=ctx.max_model_calls)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        ctx: RunContext = request.runtime.context  # type: ignore[assignment]
        if ctx.subagent is not None:
            await ctx.subagent.before_tool()  # a cancel stops it before its tool call (R16.4)
        tc = request.tool_call
        call = ToolCall(
            id=str(tc["id"]),
            name=tc["name"],
            args=dict(tc["args"]),
            index=call_index(request.state["messages"], str(tc["id"])),
            node=ctx.tools.node,
        )
        result = await ctx.pipeline.run(call, ctx.tools)
        return ToolMessage(
            content=result.content, tool_call_id=call.id, name=call.name, status=result.status
        )


def _is_final(response: ModelResponse[Any]) -> bool:
    """The model answered without asking for a tool: the agent would stop here."""
    ai = [m for m in response.result if isinstance(m, AIMessage)]
    return bool(ai) and not ai[-1].tool_calls

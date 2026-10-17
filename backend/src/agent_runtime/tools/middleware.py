"""RuntimeMiddleware: adapts the runtime to LangChain's create_agent (Adapter).

- Tool calls: every call goes through the ToolPipeline; LangChain's own tool
  execution is never used. Unknown tool names reach us too (request.tool is
  None) and are denied and audited (phase 4 research).
- Model calls: each is charged against the run's budget first (R14.1), then
  served by the model chosen for this run (phase 4: the scripted model;
  phase 6 adds real providers behind the same seam).

Everything run-specific arrives through LangGraph's runtime context
(`RunContext`), set by the executor for each execution.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

from agent_runtime.models.scripted import ScriptedChatModel, ScriptTurn
from agent_runtime.tools.invocations import charge_model_call
from agent_runtime.tools.pipeline import ToolCall, ToolPipeline, ToolRunContext


@dataclass
class RunContext:
    tools: ToolRunContext
    pipeline: ToolPipeline
    max_model_calls: int | None = None
    script: list[ScriptTurn] = field(default_factory=list)


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
        async with ctx.tools.pool.connection() as conn:
            await charge_model_call(conn, fence=ctx.tools.fence, max_calls=ctx.max_model_calls)
        return await handler(request.override(model=ScriptedChatModel(script=ctx.script)))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        ctx: RunContext = request.runtime.context  # type: ignore[assignment]
        tc = request.tool_call
        call = ToolCall(
            id=str(tc["id"]),
            name=tc["name"],
            args=dict(tc["args"]),
            index=call_index(request.state["messages"], str(tc["id"])),
        )
        result = await ctx.pipeline.run(call, ctx.tools)
        return ToolMessage(
            content=result.content, tool_call_id=call.id, name=call.name, status=result.status
        )

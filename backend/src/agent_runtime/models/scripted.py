"""ScriptedChatModel (R14.20): a deterministic chat model for tests and demos.

The reply is chosen by the number of model turns already in the conversation,
never by an in-memory iterator. A replay after a crash, a resume after an
approval, or a different worker process therefore gets exactly the same reply,
which is what durable execution needs from a test double.

LangChain's GenericFakeChatModel can't be used: it has no `bind_tools`, which
create_agent requires (phase 4 research).

A tool-call argument may reference an earlier tool result:
`"${spawn_subagent[0].handle}"` is the `handle` field of the first
`spawn_subagent` result in the conversation. Values a script can't know in
advance (handles derived from idempotency keys) stay scriptable, and the
reference is resolved from the messages, so it is replay-stable too.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, ConfigDict, Field


class ScriptedToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ScriptTurn(BaseModel):
    """One model reply: text, tool calls, or both."""

    model_config = ConfigDict(extra="forbid")

    content: str = ""
    tool_calls: list[ScriptedToolCall] = Field(default_factory=list)


_REF = re.compile(r"\$\{(?P<tool>[a-z_]+)\[(?P<i>\d+)\]\.(?P<field>[a-z_]+)\}")
_MISSING = object()


def _lookup(m: re.Match[str], messages: list[BaseMessage]) -> Any:
    results = [msg for msg in messages if isinstance(msg, ToolMessage) and msg.name == m["tool"]]
    try:
        return json.loads(str(results[int(m["i"])].content))[m["field"]]
    except (IndexError, KeyError, ValueError, TypeError):
        return _MISSING


def _resolve(value: Any, messages: list[BaseMessage]) -> Any:
    """Replace `${tool[i].field}` references with values from earlier tool results:
    a whole-string reference keeps the value's type; one inside a string is
    interpolated. An unresolved reference stays as written (the tool's validation
    then reports it to the "model")."""
    if isinstance(value, list):
        return [_resolve(v, messages) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(v, messages) for k, v in value.items()}
    if not isinstance(value, str):
        return value
    if (whole := _REF.fullmatch(value)) is not None:
        found = _lookup(whole, messages)
        return value if found is _MISSING else found

    def interpolate(m: re.Match[str]) -> str:
        found = _lookup(m, messages)
        return m.group(0) if found is _MISSING else str(found)

    return _REF.sub(interpolate, value)


class ScriptedChatModel(BaseChatModel):
    script: list[ScriptTurn] = Field(default_factory=list)
    # AI messages of earlier turns in the thread: a chat turn's script starts at 0.
    offset: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedChatModel:
        return self  # the script decides which tools are called

    def _reply(self, messages: list[BaseMessage]) -> AIMessage:
        turn = sum(isinstance(m, AIMessage) for m in messages) - self.offset
        if turn >= len(self.script):
            step = ScriptTurn(content="(script finished)")
        else:
            step = self.script[turn]
        prompt_tokens = sum(len(str(m.content)) // 4 + 1 for m in messages)
        return AIMessage(
            content=step.content,
            tool_calls=[
                {
                    "name": c.name,
                    "args": _resolve(c.args, messages),
                    "id": f"call_{turn + self.offset}_{i}",  # unique across a session's turns
                    "type": "tool_call",
                }
                for i, c in enumerate(step.tool_calls)
            ],
            response_metadata={"model_name": "scripted"},
            usage_metadata={
                "input_tokens": prompt_tokens,
                "output_tokens": len(step.content) // 4 + 1,
                "total_tokens": prompt_tokens + len(step.content) // 4 + 1,
            },
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop)

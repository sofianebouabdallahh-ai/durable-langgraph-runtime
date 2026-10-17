"""ScriptedChatModel (R14.20): a deterministic chat model for tests and demos.

The reply is chosen by the number of model turns already in the conversation,
never by an in-memory iterator. A replay after a crash, a resume after an
approval, or a different worker process therefore gets exactly the same reply,
which is what durable execution needs from a test double.

LangChain's GenericFakeChatModel can't be used: it has no `bind_tools`, which
create_agent requires (phase 4 research).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
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


class ScriptedChatModel(BaseChatModel):
    script: list[ScriptTurn] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedChatModel:
        return self  # the script decides which tools are called

    def _reply(self, messages: list[BaseMessage]) -> AIMessage:
        turn = sum(isinstance(m, AIMessage) for m in messages)
        if turn >= len(self.script):
            step = ScriptTurn(content="(script finished)")
        else:
            step = self.script[turn]
        prompt_tokens = sum(len(str(m.content)) // 4 + 1 for m in messages)
        return AIMessage(
            content=step.content,
            tool_calls=[
                {"name": c.name, "args": c.args, "id": f"call_{turn}_{i}", "type": "tool_call"}
                for i, c in enumerate(step.tool_calls)
            ],
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

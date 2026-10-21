"""A model's reasoning (L6): captured from the provider, kept in the transcript."""

from __future__ import annotations

import uuid

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from pydantic import SecretStr

from agent_runtime.models.provider import _reasoning_chat_openai
from agent_runtime.sessions.transcript import transcript_of


def test_reasoning_fields_become_the_messages_reasoning() -> None:
    """Providers say it two ways (`reasoning_content`: DeepSeek, vLLM; `reasoning`:
    Ollama, OpenRouter); both land in additional_kwargs["reasoning"]."""
    model = _reasoning_chat_openai()(model="m", api_key=SecretStr("k"), base_url="http://x/v1")
    for key in ("reasoning_content", "reasoning"):
        response = {
            "id": "r", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "42", key: "6 times 7."}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }  # fmt: skip
        result = model._create_chat_result(response)
        assert result.generations[0].message.additional_kwargs["reasoning"] == "6 times 7."
    chunk = {"choices": [{"index": 0, "delta": {"content": "", "reasoning_content": "Hmm"}}]}
    streamed = model._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, None)
    assert streamed is not None and streamed.message.additional_kwargs["reasoning"] == "Hmm"


def test_the_transcript_keeps_reasoning_with_the_reply_or_its_first_tool_call() -> None:
    run = uuid.uuid4()
    thread = [
        HumanMessage("6*7?", id=f"user:{run}"),
        AIMessage("", id="a1", additional_kwargs={"reasoning": "Use Python."},
                  tool_calls=[{"id": "c1", "name": "run_python", "args": {"code": "6*7"}},
                              {"id": "c2", "name": "save_note", "args": {"text": "x"}}]),
        ToolMessage("42", tool_call_id="c1", name="run_python", id="t1"),
        ToolMessage("ok", tool_call_id="c2", name="save_note", id="t2"),
        AIMessage("42", id="a2", additional_kwargs={"reasoning": "It printed 42."}),
    ]  # fmt: skip
    rows = transcript_of(thread, run)
    calls = [r.content for r in rows if r.type == "tool_call"]
    assert calls[0]["reasoning"] == "Use Python." and "reasoning" not in calls[1]
    (reply,) = [r.content for r in rows if r.type == "assistant"]
    assert reply["reasoning"] == "It printed 42."

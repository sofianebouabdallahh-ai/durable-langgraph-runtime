"""ModelProvider contract (R3.1, SC18): the OpenAI-compatible adapter against the
OpenAI wire protocol, as both `openai` and `ollama`, with no key and no network.

A tiny fake server answers /v1/chat/completions (streamed: text, then a tool call,
then usage, like OpenAI with stream_options.include_usage) and /v1/embeddings.
The same suite runs against the real local Ollama when it is up (`-m live`).
"""

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from pydantic import SecretStr

from agent_runtime.models.provider import (
    EMBED_DIM,
    OpenAICompatibleProvider,
    ScriptedProvider,
    provider_from,
)

SEEN: list[dict[str, Any]] = []


def fake_openai() -> FastAPI:
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Any:
        body = await request.json()
        SEEN.append(body)

        def chunk(delta: dict[str, Any], finish: str | None = None, **extra: Any) -> str:
            data = {
                "id": "c1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": body["model"],
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                **extra,
            }
            return f"data: {json.dumps(data)}\n\n"

        async def events() -> AsyncIterator[str]:
            yield chunk({"role": "assistant", "content": "Let me "})
            yield chunk({"content": "compute."})
            call = {"name": "calculator", "arguments": '{"expression": "6*7"}'}
            yield chunk({"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                         "function": call}]})  # fmt: skip
            yield chunk({}, "tool_calls")
            usage = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
            yield f"data: {json.dumps({'id': 'c1', 'object': 'chat.completion.chunk', 'created': 1, 'model': body['model'], 'choices': [], 'usage': usage})}\n\n"  # noqa: E501
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/v1/embeddings")
    async def embeddings(request: Request) -> Any:
        body = await request.json()
        inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
        data = [{"object": "embedding", "index": i, "embedding": [0.5] * EMBED_DIM}
                for i, _ in enumerate(inputs)]  # fmt: skip
        usage = {"prompt_tokens": 1, "total_tokens": 1}
        return JSONResponse({"object": "list", "model": body["model"], "data": data,
                             "usage": usage})  # fmt: skip

    return app


@pytest.fixture(scope="module")
async def server() -> AsyncIterator[str]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(fake_openai(), port=port, log_level="warning"))
    task = asyncio.create_task(srv.serve())
    while not srv.started:  # noqa: ASYNC110
        await asyncio.sleep(0.02)
    yield f"http://127.0.0.1:{port}/v1"
    srv.should_exit = True
    await task


@tool
def calculator(expression: str) -> str:
    """Evaluate an arithmetic expression."""
    return expression


class Tokens(AsyncCallbackHandler):
    def __init__(self) -> None:
        self.tokens: list[str] = []

    async def on_llm_new_token(self, token: Any, **kw: Any) -> None:
        self.tokens.append(token)


@pytest.mark.parametrize("name", ["openai", "ollama"])
async def test_tool_calls_usage_and_streaming(server: str, name: str) -> None:
    provider = OpenAICompatibleProvider(
        name, server, SecretStr("test-key"), {"default": f"{name}-model", "embed": "e"}
    )
    model = provider.chat("chat", temperature=0.2, script=[], offset=0)
    tokens = Tokens()
    reply = await model.bind_tools([calculator]).ainvoke(
        [HumanMessage("6*7?")], config={"callbacks": [tokens]}
    )
    assert reply.content == "Let me compute."
    assert "".join(tokens.tokens) == "Let me compute."  # streamed: token callbacks fired
    assert reply.tool_calls == [{"name": "calculator", "args": {"expression": "6*7"},
                                 "id": "call_1", "type": "tool_call"}]  # fmt: skip
    assert reply.usage_metadata is not None
    assert (reply.usage_metadata["input_tokens"], reply.usage_metadata["output_tokens"]) == (11, 7)
    assert reply.response_metadata["model_name"] == f"{name}-model"
    sent = SEEN[-1]
    assert sent["model"] == f"{name}-model" and sent["stream"] is True
    assert sent["tools"][0]["function"]["name"] == "calculator"
    assert sent["max_completion_tokens"] == 4096  # R14.5


async def test_embeddings(server: str) -> None:
    models = {"default": "m", "embed": "e"}
    provider = OpenAICompatibleProvider("ollama", server, SecretStr("x"), models)
    vectors = await provider.embed(["a", "b"])
    assert len(vectors) == 2 and len(vectors[0]) == EMBED_DIM


async def test_the_scripted_provider_embeds_deterministically() -> None:
    p = ScriptedProvider()
    a, b = await p.embed(["redis streams", "redis streams"])
    (c,) = await p.embed(["kafka"])
    assert a == b and a != c and len(a) == EMBED_DIM
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9  # unit length


def build(name: Any, ollama_url: str = "u", roles: dict[str, str] | None = None) -> Any:
    return provider_from(name, openai_api_key=None, openai_base_url="u",
                         ollama_base_url=ollama_url, role_models=roles or {})  # fmt: skip


def test_provider_selection() -> None:
    assert build("scripted").name == "scripted"
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build("openai")
    ollama = build("ollama", "http://o/v1", {"chat": "llama3"})
    assert isinstance(ollama, OpenAICompatibleProvider)
    assert (ollama.model_for("chat"), ollama.model_for("planner")) == ("llama3", "qwen2.5:7b")
    assert "test" not in repr(ollama.api_key)  # never printable


@pytest.mark.live
async def test_live_ollama_tool_call() -> None:
    """The same contract against the real local Ollama (make llm-up). Not in CI."""
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            (await client.get("http://127.0.0.1:11434/api/tags")).raise_for_status()
    except httpx.HTTPError:
        pytest.skip("Ollama is not running (make llm-up)")
    provider = build("ollama", "http://127.0.0.1:11434/v1")
    model = provider.chat("chat", temperature=0.0, script=[], offset=0)
    reply = await model.bind_tools([calculator]).ainvoke(
        [HumanMessage("Use the calculator to compute 1234 * 5678.")]
    )
    assert reply.tool_calls and reply.tool_calls[0]["name"] == "calculator"
    assert reply.usage_metadata and reply.usage_metadata["total_tokens"] > 0

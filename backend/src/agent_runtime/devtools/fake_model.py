"""A fake OpenAI-compatible model server, for tests and CI (dev tooling, phase L3b).

`runtime fake-model` serves /v1/chat/completions and /v1/models like a real
OpenAI-compatible service, deterministically, so connections, routing and tests
work with no real model and no key:

- **auth:** with `--key`, any other bearer token gets a 401 (like a wrong key);
- **models:** `fake-<anything>` exists; others get a 404; `fake-notools` never calls
  a tool; `fake-slow` never answers in time;
- **behaviour:** a `ping` tool → it calls ping(42) (the capability test); an agent
  with helpers → it delegates to the first helper listed in its prompt, waits for
  it, then answers; a helper → it returns a result; otherwise a short answer. Every
  answer names the model, so a test can see who answered what;
- **a log:** GET /calls lists what it served (model, which key, tools), so a test
  proves that two helpers used two connections (AC44). DELETE /calls clears it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

HELPER = re.compile(r"^- `([a-z0-9-]+)`:", re.MULTILINE)


def create_app(key: str | None = None) -> FastAPI:
    app = FastAPI(title="fake OpenAI-compatible model")
    calls: list[dict[str, Any]] = []

    @app.get("/v1/models")
    async def models() -> Any:
        return {
            "object": "list",
            "data": [
                {"id": m, "object": "model"}
                for m in ("fake-a", "fake-b", "fake-notools", "fake-slow")
            ],
        }

    @app.get("/calls")
    async def log() -> Any:
        return calls

    @app.delete("/calls")
    async def clear() -> Any:
        calls.clear()
        return {"cleared": True}

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Any:
        auth = request.headers.get("authorization", "")
        if key and auth != f"Bearer {key}":
            return _error(401, "Incorrect API key provided.", "invalid_api_key")
        body = await request.json()
        model = str(body.get("model", ""))
        if not model.startswith("fake-"):
            return _error(404, f"The model `{model}` does not exist.", "model_not_found")
        tools = [t["function"]["name"] for t in body.get("tools") or []]
        calls.append(
            {
                "model": model,
                "key": hashlib.sha256(auth.encode()).hexdigest()[:8],
                "tools": tools,
                "last": body["messages"][-1].get("role"),
            }
        )
        if model == "fake-slow":
            await asyncio.sleep(300)
        reply = _decide(model, body["messages"], tools, len(calls))
        if body.get("stream"):
            return StreamingResponse(_stream(model, reply), media_type="text/event-stream")
        return _complete(model, reply)

    return app


def _decide(model: str, messages: list[dict[str, Any]], tools: list[str], n: int) -> dict[str, Any]:
    """{"text": …} or {"tool": name, "args": {…}}: a tiny deterministic policy."""
    last = messages[-1]
    can = model != "fake-notools"
    if can and "ping" in tools:
        return {"tool": "ping", "args": {"value": 42}, "id": f"call_{n}"}
    if last.get("role") == "tool":
        answered = _tool_name(messages, last.get("tool_call_id"))
        if can and answered == "spawn_subagent" and "wait_subagents" in tools:
            handle = _field(last.get("content"), "handle")
            return {
                "tool": "wait_subagents",
                "args": {"handles": [handle], "timeout_s": 60},
                "id": f"call_{n}",
            }
        return {"text": f"Done. Answered by {model}."}
    if can and "return_result" in tools:  # a helper: hand the result back
        return {
            "tool": "return_result",
            "args": {"summary": f"Helper work by {model}."},
            "id": f"call_{n}",
        }
    if can and "spawn_subagent" in tools:
        system = next((m.get("content") or "" for m in messages if m.get("role") == "system"), "")
        helpers = HELPER.findall(system if isinstance(system, str) else "")
        if helpers:
            task = str(last.get("content") or "")[:200] or "help"
            return {
                "tool": "spawn_subagent",
                "args": {"agent": helpers[0], "task": task},
                "id": f"call_{n}",
            }
    return {"text": f"Hello from {model}."}


def _tool_name(messages: list[dict[str, Any]], call_id: Any) -> str | None:
    for m in reversed(messages):
        for call in m.get("tool_calls") or []:
            if call.get("id") == call_id:
                return str(call["function"]["name"])
    return None


def _field(content: Any, name: str) -> str:
    text = content if isinstance(content, str) else json.dumps(content)
    try:
        value = json.loads(text).get(name)
    except (ValueError, AttributeError):
        found = re.search(rf'"{name}"\s*:\s*"([^"]+)"', text)
        value = found.group(1) if found else None
    return str(value or "")


def _usage() -> dict[str, int]:
    return {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28}


def _stream(model: str, reply: dict[str, Any]) -> AsyncIterator[str]:
    async def events() -> AsyncIterator[str]:
        def chunk(delta: dict[str, Any], finish: str | None = None, **extra: Any) -> str:
            data = {
                "id": "fake",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                **extra,
            }
            return f"data: {json.dumps(data)}\n\n"

        if "text" in reply:
            words = reply["text"].split(" ")
            yield chunk({"role": "assistant", "content": ""})
            for i, word in enumerate(words):
                yield chunk({"content": word + (" " if i < len(words) - 1 else "")})
                await asyncio.sleep(0.01)
            yield chunk({}, "stop")
        else:
            call = {"name": reply["tool"], "arguments": json.dumps(reply["args"])}
            yield chunk(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {"index": 0, "id": reply["id"], "type": "function", "function": call}
                    ],
                }
            )
            yield chunk({}, "tool_calls")
        final = {
            "id": "fake",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": model,
            "choices": [],
            "usage": _usage(),
        }
        yield f"data: {json.dumps(final)}\n\n"
        yield "data: [DONE]\n\n"

    return events()


def _complete(model: str, reply: dict[str, Any]) -> JSONResponse:
    message: dict[str, Any] = {"role": "assistant", "content": reply.get("text")}
    finish = "stop"
    if "tool" in reply:
        message["tool_calls"] = [
            {
                "id": reply["id"],
                "type": "function",
                "function": {"name": reply["tool"], "arguments": json.dumps(reply["args"])},
            }
        ]
        finish = "tool_calls"
    return JSONResponse(
        {
            "id": "fake",
            "object": "chat.completion",
            "created": 1,
            "model": model,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": _usage(),
        }
    )


def _error(status: int, message: str, code: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"message": message, "type": "invalid_request_error", "code": code}},
        status_code=status,
    )

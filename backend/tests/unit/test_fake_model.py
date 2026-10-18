"""The fake OpenAI-compatible server behaves as its docstring promises (L3b.6).

Other tests lean on it to prove routing (AC44) and the capability test, so its
policy is pinned here: auth, unknown models, the ping, delegation, the log.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from agent_runtime.devtools import fake_model

KEY = "unit-fake-key"


def _client(key: str | None = KEY) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=fake_model.create_app(key))
    return httpx.AsyncClient(transport=transport, base_url="http://fake")


def _tools(*names: str) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": n, "parameters": {}}} for n in names]


async def _ask(
    client: httpx.AsyncClient, model: str, messages: list[dict[str, Any]], *tools: str,
    key: str = KEY,
) -> httpx.Response:  # fmt: skip
    body: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        body["tools"] = _tools(*tools)
    return await client.post(
        "/v1/chat/completions", json=body, headers={"authorization": f"Bearer {key}"}
    )


def _message(response: httpx.Response) -> dict[str, Any]:
    message: dict[str, Any] = response.json()["choices"][0]["message"]
    return message


async def test_a_wrong_key_and_an_unknown_model_are_refused() -> None:
    async with _client() as client:
        user = [{"role": "user", "content": "hi"}]
        assert (await _ask(client, "fake-a", user, key="wrong")).status_code == 401
        assert (await _ask(client, "gpt-4o", user)).status_code == 404


async def test_the_ping_is_answered_with_a_tool_call_unless_the_model_has_no_tools() -> None:
    async with _client() as client:
        user = [{"role": "user", "content": "ping"}]
        call = _message(await _ask(client, "fake-a", user, "ping"))["tool_calls"][0]
        assert call["function"]["name"] == "ping"
        chatty = _message(await _ask(client, "fake-notools", user, "ping"))
        assert "tool_calls" not in chatty
        assert chatty["content"] == "Hello from fake-notools."


async def test_an_agent_delegates_to_its_first_listed_helper_and_a_helper_reports() -> None:
    system = "You are X.\n\n## Your helpers\n- `scout`: finds things\n- `writer`: writes"
    async with _client() as client:
        main = [{"role": "system", "content": system}, {"role": "user", "content": "go"}]
        spawn = _message(await _ask(client, "fake-a", main, "spawn_subagent", "wait_subagents"))
        assert spawn["tool_calls"][0]["function"]["name"] == "spawn_subagent"
        assert '"agent": "scout"' in spawn["tool_calls"][0]["function"]["arguments"]
        helper = _message(await _ask(client, "fake-b", main[1:], "return_result"))
        assert '"Helper work by fake-b."' in helper["tool_calls"][0]["function"]["arguments"]


async def test_the_log_tells_connections_apart_without_keeping_keys() -> None:
    async with _client(key=None) as client:
        user = [{"role": "user", "content": "hi"}]
        await _ask(client, "fake-a", user, key="key-one")
        await _ask(client, "fake-b", user, key="key-two")
        calls = (await client.get("/calls")).json()
        assert [c["model"] for c in calls] == ["fake-a", "fake-b"]
        assert calls[0]["key"] != calls[1]["key"]
        assert "key-one" not in str(calls)
        await client.delete("/calls")
        assert (await client.get("/calls")).json() == []


async def test_a_slow_conversation_waits_before_each_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("agent_runtime.devtools.fake_model.asyncio.sleep", sleep)
    async with _client() as client:
        await _ask(client, "fake-a", [{"role": "user", "content": "[slow] plan it"}])
        await _ask(client, "fake-a", [{"role": "user", "content": "plan it"}])
    assert waits == [fake_model.SLOW_S]

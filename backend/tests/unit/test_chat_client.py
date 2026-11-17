"""chat_client.py: the terminal chat over the API (`./setup.sh --chat`), against a fake API.

The fake serves the session stream one connection at a time from a script, so a test can
drop the stream mid-reply and see what the client asks for when it comes back.
"""

import json
from typing import Any

import httpx
import pytest

from agent_runtime import chat_client
from agent_runtime.chat_client import chat


def event(type_: str, payload: dict[str, Any], seq: int | None = None, run_id: str = "r1") -> str:
    envelope = {"run_id": run_id, "seq": seq, "type": type_, "payload": payload}
    head = f"id: {seq}\n" if seq is not None else ""
    return f"{head}event: {type_}\ndata: {json.dumps(envelope)}\n\n"


def status(value: str) -> str:
    return event("turn.status", {"run_id": "r1", "status": value})


def message(seq: int, kind: str, content: dict[str, Any]) -> str:
    return event("message.created", {"type": kind, "content": content, "run_id": "r1"}, seq=seq)


DETAIL = {
    "status": "completed",
    "reason": None,
    "model_calls": 2,
    "tool_calls": 1,
    "tokens": 42,
    "cost": 0,
}


class FakeNuria:
    """The few routes the chat uses. `streams`: one body per stream connection, in order;
    after the last, an empty one (the client reconnects, as against a quiet server)."""

    def __init__(
        self, streams: list[str], *, session_done: bool = False, send_status: int = 202
    ) -> None:
        self.streams, self.session_done, self.send_status = list(streams), session_done, send_status
        self.stream_headers: list[dict[str, str]] = []
        self.stored = "The answer is 42."

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if (method, path) == ("POST", "/api/sessions"):
            return httpx.Response(201, json={"id": "s1", "agent": "chat"})
        if path == "/api/sessions/s1/stream":
            self.stream_headers.append(dict(request.headers))
            body = self.streams.pop(0) if self.streams else ": quiet\n\n"
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=body.encode()
            )
        if (method, path) == ("POST", "/api/sessions/s1/messages"):
            if self.send_status != 202:
                return httpx.Response(
                    self.send_status, json={"title": "Conflict", "detail": "a turn is still active"}
                )
            return httpx.Response(202, json={"run_id": "r1", "message_id": "m1", "seq": 1})
        if (method, path) == ("GET", "/api/sessions/s1"):
            active = None if self.session_done else "r1"
            return httpx.Response(
                200, json={"id": "s1", "active_run_id": active, "active_run_status": None}
            )
        if path == "/api/runs/r1":
            return httpx.Response(200, json={"id": "r1", "status": "completed"})
        if path == "/api/sessions/s1/messages":
            return httpx.Response(
                200,
                json={
                    "messages": [
                        {
                            "seq": 2,
                            "run_id": "r1",
                            "type": "assistant",
                            "content": {"text": self.stored},
                        }
                    ]
                },
            )
        if path == "/api/activity/turns/r1":
            return httpx.Response(200, json=DETAIL)
        return httpx.Response(404, json={"title": "Not Found"})


async def run(fake: FakeNuria, messages: list[str]) -> tuple[int, str]:
    shown: list[str] = []
    code = await chat(
        "http://nuria/api",
        "chat",
        messages,
        transport=httpx.MockTransport(fake),
        write=shown.append,
    )
    return code, "".join(shown)


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_client, "QUIET_S", 0.05)


async def test_a_turn_streams_its_words_shows_its_tools_and_ends_with_a_summary() -> None:
    stream = "".join([
        ": keep-alive\n\n", status("queued"), message(1, "user", {"text": "6 x 7?"}),
        status("running"),
        message(2, "assistant", {"text": ""}),  # the model's first call: a tool, no words
        message(3, "tool_call", {"tool": "calculator", "args": {"expression": "6*7"}}),
        message(4, "tool_result", {"result": 42}),
        event("token", {"text": "The answer "}), event("token", {"text": "is 42."}),
        message(5, "assistant", {"text": "The answer is 42."}), status("completed"),
    ])  # fmt: skip
    code, shown = await run(FakeNuria([stream]), ["6 x 7?"])
    assert code == 0
    assert "session s1 with chat (through http://nuria/api)" in shown
    assert 'calculator({"expression": "6*7"})' in shown and "↳ 42" in shown
    assert shown.count("The answer is 42.") == 1  # streamed, then not printed again
    assert "[completed · 2 model calls · 1 tools · 42 tokens · $0.0000 · " in shown


async def test_words_a_dropped_connection_lost_come_from_the_stored_reply_once() -> None:
    first = (
        status("running")
        + message(2, "assistant", {"text": ""})
        + event("token", {"text": "The ans"})
    )
    second = message(5, "assistant", {"text": "The answer is 42."}) + status("completed")
    fake = FakeNuria([first, second])
    code, shown = await run(fake, ["6 x 7?"])
    assert code == 0 and "The answer is 42." in shown and shown.count("The ans") == 1
    assert fake.stream_headers[1].get("last-event-id") == "2"  # resumed after what it saw


async def test_a_turn_that_ended_while_nothing_was_heard_is_asked_of_the_session() -> None:
    code, shown = await run(FakeNuria([], session_done=True), ["6 x 7?"])
    assert code == 0 and "The answer is 42." in shown and "[completed · " in shown


async def test_an_approval_is_said_and_the_chat_goes_on() -> None:
    stream = status("running") + status("waiting_approval")
    code, shown = await run(FakeNuria([stream]), ["tell the team"])
    assert code == 0 and "waiting for your approval: Approve or Reject it in the app" in shown


async def test_a_refused_message_is_shown_and_the_chat_goes_on() -> None:
    code, shown = await run(FakeNuria([], send_status=409), ["one", "two"])
    assert code == 0 and shown.count("! a turn is still active") == 2


async def test_a_nuria_that_is_not_running_is_said_plainly() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    shown: list[str] = []
    code = await chat(
        "http://nuria/api",
        "chat",
        ["hi"],
        transport=httpx.MockTransport(refuse),
        write=shown.append,
    )
    assert code == 1 and "Nuria isn't answering at http://nuria/api" in "".join(shown)

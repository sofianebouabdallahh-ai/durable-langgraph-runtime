"""Enough of Nuria's API for the client's tests, on `httpx.MockTransport`: sessions, sends
(idempotent by key), a run whose status moves on cue, the turn's messages, and a session
stream whose successive connections follow a script (events, a drain, a drop, an error).

The stream steps, one connection each list:
    ("event", type, payload, seq)   seq None: transient (no `id:`)
    ("ping",)                       a `: ping` keep-alive
    ("drain", after_seq)            `event: reconnect`, then the connection ends
    ("drop",)                       the connection breaks (httpx.ReadError)
    ("status", code)                answer the connection with that status instead
    ("run", status)                 set the run's status, as if it moved meanwhile
A connection's list running out is a clean close; a connection beyond the lists fails the
test (a client that loops would otherwise hang it).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx

SESSION = "33333333-3333-3333-3333-333333333333"
TS = "2026-11-15T00:00:00+00:00"
Step = tuple[Any, ...]


class FakeNuria:
    def __init__(self, *, async_mode: bool) -> None:
        self.async_mode = async_mode
        self.run_id = str(uuid.UUID(int=1))
        self.run: dict[str, Any] = {"id": self.run_id, "status": "running", "reason": None,
                                    "interrupt_payload": None}  # fmt: skip
        self.statuses: list[str] = []  # each GET /runs/{id} takes the next; the last stays
        self.messages: list[dict[str, Any]] = []
        self.keys: dict[str, dict[str, Any]] = {}
        self.send_answers: list[tuple[int, str]] = []  # (status, problem slug) before a 202
        self.connections: list[list[Step]] = []
        self.stream_headers: list[str | None] = []  # each connection's Last-Event-ID
        self.sends: list[str | None] = []  # each send's Idempotency-Key
        self.turns_made = 0

    # ------------------------------------------------------------------ helpers
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def add_message(
        self, seq: int, kind: str = "assistant", text: str | None = None
    ) -> dict[str, Any]:
        row = {"seq": seq, "message_id": f"m{seq}", "run_id": self.run_id, "type": kind,
               "role": "assistant" if kind == "assistant" else "user",
               "content": {} if text is None else {"text": text}, "created_at": TS}  # fmt: skip
        self.messages.append(row)
        return row

    def wire(self, kind: str, payload: dict[str, Any], seq: int | None) -> bytes:
        data = {"run_id": self.run_id, "seq": seq, "after_seq": None if seq else 0, "ts": TS,
                "epoch": 1, "type": kind, "payload": payload}  # fmt: skip
        head = f"id: {seq}\n" if seq is not None else ""
        return f"{head}event: {kind}\ndata: {json.dumps(data)}\n\n".encode()

    # ------------------------------------------------------------------- routes
    def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path.removeprefix("/api"), request.method
        if method == "POST" and path == "/sessions":
            return self.json(
                201, {"id": SESSION, "agent": "chat", "title": None, "status": "active"}
            )
        if method == "GET" and path == f"/sessions/{SESSION}":
            return self.json(
                200, {"id": SESSION, "agent": "chat", "title": "t", "status": "active"}
            )
        if method == "GET" and path.startswith("/sessions/") and path.endswith("/stream"):
            return self.stream(request)
        if method == "POST" and path == f"/sessions/{SESSION}/messages":
            return self.send(request)
        if method == "GET" and path == f"/sessions/{SESSION}/messages":
            after = int(request.url.params.get("after_seq", "0"))
            rows = [m for m in self.messages if m["seq"] > after]
            return self.json(200, {"messages": rows, "next_after_seq": None})
        if method == "GET" and path == f"/runs/{self.run_id}":
            if self.statuses:
                self.run["status"] = (
                    self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
                )
            return self.json(200, self.run)
        if method == "POST" and path == f"/runs/{self.run_id}/cancel":
            self.run["status"] = "cancelled"
            return self.json(202, self.run)
        return self.problem(404, "not-found")

    def send(self, request: httpx.Request) -> httpx.Response:
        key = request.headers.get("idempotency-key")
        self.sends.append(key)
        if self.send_answers:
            status, slug = self.send_answers.pop(0)
            return self.problem(status, slug, retry_after="0" if status in (429, 503) else None)
        if key in self.keys:
            return self.json(202, self.keys[key])
        self.turns_made += 1
        self.add_message(1, "user", json.loads(request.content)["content"])
        accepted = {"message_id": "m1", "seq": 1, "run_id": self.run_id}
        if key is not None:
            self.keys[key] = accepted
        return self.json(202, accepted)

    def stream(self, request: httpx.Request) -> httpx.Response:
        self.stream_headers.append(request.headers.get("last-event-id"))
        if not self.connections:  # fail, don't hang: a client looping would connect forever
            raise AssertionError(f"stream connection #{len(self.stream_headers)} wasn't scripted")
        steps = self.connections.pop(0)
        if steps and steps[0][0] == "status":
            return self.problem(
                steps[0][1], "draining" if steps[0][1] == 503 else "x", retry_after="0"
            )
        content: Any = self.async_body(steps) if self.async_mode else self.sync_body(steps)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=content)

    def chunks(self, steps: list[Step]) -> Iterator[bytes | Exception]:
        yield b"retry: 2000\n: stream open\n\n"
        for step in steps:
            if step[0] == "event":
                _, kind, payload, seq = step
                yield self.wire(kind, payload, seq)
            elif step[0] == "ping":
                yield b": ping\n\n"
            elif step[0] == "drain":
                data = json.dumps({"after_seq": step[1]})
                yield f"event: reconnect\ndata: {data}\nretry: 0\n\n".encode()
                return
            elif step[0] == "drop":
                yield httpx.ReadError("the connection broke")
                return
            elif step[0] == "run":
                self.run["status"] = step[1]

    def sync_body(self, steps: list[Step]) -> Iterator[bytes]:
        for chunk in self.chunks(steps):
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    async def async_body(self, steps: list[Step]) -> AsyncIterator[bytes]:
        for chunk in self.chunks(steps):
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    @staticmethod
    def json(status: int, body: Any) -> httpx.Response:
        return httpx.Response(status, json=body)

    @staticmethod
    def problem(status: int, slug: str, *, retry_after: str | None = None) -> httpx.Response:
        body = {"type": f"https://agent-runtime.dev/problems/{slug}", "title": slug,
                "status": status, "detail": slug}  # fmt: skip
        headers = {"content-type": "application/problem+json"}
        if retry_after is not None:
            headers["retry-after"] = retry_after
        return httpx.Response(status, content=json.dumps(body).encode(), headers=headers)

"""The terminal chat as a client of a running Nuria: `runtime chat --api URL`.

`./setup.sh --chat` runs it in a one-off container of the stack. It talks to the API the
way the web app does (create a chat, send a message, follow the session's stream), so the
turn runs on the stack's workers, and the container needs no database grant at all. Before,
the chat ran the turn in that container, as the API's least-privilege role, which may not
touch LangGraph's checkpoints: every turn failed. The in-process chat (`runtime chat`
without `--api`) stays for the developer loop, which connects as the owner.

Pattern: Observer over the session stream (SSE). The stream's `turn.status` is transient:
one sent while the client reconnects is gone. So when the stream is quiet, the client asks
the session whether its turn is still the active one, and the run's status is the answer.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import httpx

STOPS = frozenset({"completed", "failed", "cancelled", "waiting_approval"})
QUIET_S = 2.0  # this long without an event: ask the session whether the turn is over
TIMEOUT = httpx.Timeout(30.0)
STREAM_TIMEOUT = httpx.Timeout(10.0, read=None)  # the stream waits as long as the turn


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


@dataclass(frozen=True)
class Event:
    type: str
    data: dict[str, Any]
    id: str | None


async def sse(response: httpx.Response) -> AsyncIterator[Event]:
    """The events of a `text/event-stream` response (the WHATWG format: `event:`, `data:`,
    `id:`, comments, a blank line ends an event)."""
    kind, id_ = "message", None
    data: list[str] = []
    async for line in response.aiter_lines():
        if not line:
            if data:
                try:
                    parsed = json.loads("\n".join(data))
                except ValueError:
                    parsed = {}
                yield Event(kind, parsed if isinstance(parsed, dict) else {}, id_)
            kind, data, id_ = "message", [], None
            continue
        if line.startswith(":"):  # a keep-alive
            continue
        field, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if field == "event":
            kind = value
        elif field == "data":
            data.append(value)
        elif field == "id":
            id_ = value


class SessionFollower:
    """Reads a session's stream in the background, through drains and dropped connections:
    it reconnects from the last persisted event it saw (`Last-Event-ID`), and drops a
    replayed one, so every event reaches the queue once."""

    def __init__(self, client: httpx.AsyncClient, session_id: str) -> None:
        self._client, self._session_id = client, session_id
        self.cursor: int | None = None
        self.events: asyncio.Queue[Event] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._follow())

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _follow(self) -> None:
        failures = 0
        while True:
            headers = {"Accept": "text/event-stream"}
            if self.cursor is not None:
                headers["Last-Event-ID"] = str(self.cursor)
            try:
                async with self._client.stream(
                    "GET", f"/sessions/{self._session_id}/stream", headers=headers,
                    timeout=STREAM_TIMEOUT,
                ) as response:  # fmt: skip
                    if response.status_code == 200:
                        failures = 0
                        await self._read(response)
            except httpx.HTTPError:
                pass  # a dropped or refused connection: try again
            failures += 1
            await asyncio.sleep(min(5.0, 0.25 * 2 ** min(failures, 5)))

    async def _read(self, response: httpx.Response) -> None:
        async for event in sse(response):
            if event.type == "reconnect":  # the replica is draining: go to another one
                return
            if event.id is not None and event.id.isdigit():
                if self.cursor is not None and int(event.id) <= self.cursor:
                    continue  # a replay of one already seen
                self.cursor = int(event.id)
            await self.events.put(event)


def print_live(type_: str, payload: dict[str, Any], write: Callable[[str], None] = _write) -> None:
    """What the terminal shows of a live event: the reply's words, tool calls and their
    results, helpers' progress. Shared with the in-process chat."""
    if type_ == "token":
        write(str(payload.get("text", "")))
    elif type_ == "message.created":
        kind, content = payload.get("type"), payload.get("content") or {}
        if kind == "tool_call":
            write(f"\n  ⚙ {content.get('tool')}({json.dumps(content.get('args'))[:120]})\n")
        elif kind == "tool_result":
            body = content.get("result", content.get("error"))
            write(f"  ↳ {json.dumps(body, default=str)[:160]}\n")
    elif type_.startswith("subagent."):
        agent = payload.get("agent", "")
        detail = payload.get("message") or payload.get("status") or ""
        write(f"\n  ◇ {type_.removeprefix('subagent.')} {agent} {detail}\n")


class Chat:
    """One terminal chat with one agent, over the API."""

    def __init__(self, client: httpx.AsyncClient, agent: str, write: Callable[[str], None]) -> None:
        self._client, self._agent, self._write = client, agent, write
        self.session_id = ""
        self._follower: SessionFollower | None = None

    async def open(self) -> None:
        created = await self._client.post("/sessions", json={"agent": self._agent})
        created.raise_for_status()
        self.session_id = str(created.json()["id"])
        self._follower = SessionFollower(self._client, self.session_id)
        self._follower.start()  # before the first message: no word of the reply is missed

    async def close(self) -> None:
        if self._follower is not None:
            await self._follower.close()

    async def say(self, text: str) -> str | None:
        """Send `text`, print the turn as it happens; its final status (None: not sent)."""
        started = time.monotonic()
        sent = await self._client.post(
            f"/sessions/{self.session_id}/messages", json={"content": text}
        )
        if sent.status_code != 202:
            self._write(f"  ! {_problem(sent)}\n")
            return None
        run_id = str(sent.json()["run_id"])
        self._write(f"{self._agent}> ")
        status, replied, streamed = await self._follow(run_id)
        if status == "completed" and not replied:  # the stream ended first: the stored reply
            self._write(_rest(await self._stored_reply(run_id), streamed))
        if status == "waiting_approval":
            self._write(
                "\n  ⏸ waiting for your approval: Approve or Reject it in the app;"
                " the turn goes on from there.\n"
            )
        self._write(await self._summary(run_id, status, time.monotonic() - started))
        return status

    async def _follow(self, run_id: str) -> tuple[str, bool, str]:
        """(final status, whether a reply was shown, the words streamed since the last one)."""
        assert self._follower is not None
        streamed, replied = "", False
        while True:
            try:
                event = await asyncio.wait_for(self._follower.events.get(), QUIET_S)
            except TimeoutError:
                if (status := await self._ended(run_id)) is not None:
                    return status, replied, streamed
                continue
            if str(event.data.get("run_id")) != run_id:
                continue  # another turn's, or the chat's
            payload = event.data.get("payload") or {}
            if event.type == "turn.status" and payload.get("status") in STOPS:
                return str(payload["status"]), replied, streamed
            if event.type == "token":
                streamed += str(payload.get("text", ""))
            if event.type == "message.created" and payload.get("type") == "assistant":
                text = str((payload.get("content") or {}).get("text") or "")
                if text:  # the stored reply: whatever the stream didn't show of it
                    self._write(_rest(text, streamed))
                    replied = True
                streamed = ""
                continue
            print_live(event.type, payload, self._write)

    async def _ended(self, run_id: str) -> str | None:
        """The run's status if its turn is over (or waits for a person), else None."""
        session = await self._client.get(f"/sessions/{self.session_id}")
        if session.status_code != 200:
            return None
        view = session.json()
        if (
            view.get("active_run_id") == run_id
            and view.get("active_run_status") != "waiting_approval"
        ):
            return None
        run = await self._client.get(f"/runs/{run_id}")
        return str(run.json()["status"]) if run.status_code == 200 else None

    async def _stored_reply(self, run_id: str) -> str:
        listed = await self._client.get(
            f"/sessions/{self.session_id}/messages", params={"limit": 500}
        )
        replies = [m for m in listed.json().get("messages", [])
                   if m.get("run_id") == run_id and m.get("type") == "assistant"]  # fmt: skip
        return str((replies[-1].get("content") or {}).get("text") or "") if replies else ""

    async def _summary(self, run_id: str, status: str, elapsed_s: float) -> str:
        detail = await self._client.get(f"/activity/turns/{run_id}")
        if detail.status_code != 200:
            return f"\n  [{status} · {elapsed_s:.1f}s]\n\n"
        d = detail.json()
        reason = f" {d['reason']}" if d.get("reason") else ""
        return (f"\n  [{status}{reason} · {d.get('model_calls', 0)} model calls"
                f" · {d.get('tool_calls', 0)} tools · {d.get('tokens', 0)} tokens"
                f" · ${float(d.get('cost') or 0):.4f} · {elapsed_s:.1f}s]\n\n")  # fmt: skip


def _rest(reply: str, streamed: str) -> str:
    """What of the stored `reply` the terminal hasn't shown: the words a dropped connection
    lost, never a second copy."""
    if reply.startswith(streamed):
        return reply[len(streamed) :]
    return f"\n{reply}" if streamed else reply


def _problem(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    return str(body.get("detail") or body.get("title") or f"HTTP {response.status_code}")


async def chat(
    api: str,
    agent: str,
    messages: list[str] | None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    write: Callable[[str], None] = _write,
    read: Callable[[str], str] = input,
) -> int:
    """`messages` (non-interactive), or lines read until EOF or `/quit`."""
    async with httpx.AsyncClient(
        base_url=api.rstrip("/"), timeout=TIMEOUT, transport=transport
    ) as client:
        conversation = Chat(client, agent, write)
        try:
            await conversation.open()
        except httpx.HTTPError as exc:
            write(
                f"Nuria isn't answering at {api} ({type(exc).__name__}): is it running?"
                " ./setup.sh starts it.\n"
            )
            return 1
        write(f"session {conversation.session_id} with {agent} (through {api})\n\n")
        try:
            queue = list(messages) if messages else None
            while True:
                if queue is not None:
                    if not queue:
                        break
                    text = queue.pop(0)
                    write(f"you> {text}\n")
                else:
                    try:
                        text = (await asyncio.to_thread(read, "you> ")).strip()
                    except EOFError:
                        break
                    if text in ("/quit", "/exit"):
                        break
                    if not text:
                        continue
                await conversation.say(text)
        finally:
            await conversation.close()
    return 0

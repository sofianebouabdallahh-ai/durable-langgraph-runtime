"""The transcript as a projection of the agent's state (CR-001 R12.3, R12.4).

`TranscriptWriter.write` runs inside each superstep's checkpoint transaction (it
is called by the step outbox from `FencedCheckpointer.on_commit`). It maps the
thread's messages after this turn's user message to transcript rows:

    AIMessage   → `assistant` {text, model, tokens} (if it has text)
                  + one `tool_call` {tool_call_id, tool, args} per tool call
    ToolMessage → `tool_result` {tool_call_id, tool, result | error, cached, duration_ms}
    SystemMessage (session_start context) → `system` {text}

Ids are positional and deterministic, `sha256(run_id · node · index · type)`, so
a reclaimed worker that re-produces a superstep finds every row already there
and writes nothing. The checkpoint and the transcript commit together, so they
can't disagree; `transcript_of` is the same mapping, for the R12.4 check.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from agent_runtime.db import Conn
from agent_runtime.fencing import Fence
from agent_runtime.sessions.store import Message, MessageType, NewMessage, SessionRepository
from agent_runtime.sessions.store import message_id as make_id
from agent_runtime.sessions.turns import REPAIR_PREFIX, baseline
from agent_runtime.streaming.bus import EventBus, StreamEvent, session_channel
from agent_runtime.tools.hooks import redact

log = logging.getLogger(__name__)

MESSAGE_CREATED = "message.created"  # on the session channel (CR-001 amendment to R1.5)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content blocks
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content)


def _result(message: ToolMessage) -> dict[str, Any]:
    artifact = message.artifact if isinstance(message.artifact, dict) else {}
    text = _text(message.content)
    body: dict[str, Any]
    if message.status == "error":
        body = {"error": text}
    else:
        try:
            body = {"result": json.loads(text)}
        except ValueError:
            body = {"result": text}
    return {"tool_call_id": message.tool_call_id, "tool": message.name, **body,
            "cached": bool(artifact.get("cached", False)),
            "duration_ms": artifact.get("duration_ms")}  # fmt: skip


def transcript_of(messages: list[BaseMessage], run_id: uuid.UUID) -> list[NewMessage]:
    """What this turn contributes to the transcript, given the thread's messages.
    Secret-looking strings are redacted (R14.12): the model's own tool-call args are
    recorded as it produced them, before any pre_tool hook ran."""
    return [NewMessage(m.message_id, m.type, redact(m.content))
            for m in _transcript_of(messages, run_id)]  # fmt: skip


def _transcript_of(messages: list[BaseMessage], run_id: uuid.UUID) -> list[NewMessage]:
    start = baseline(messages, run_id)
    if start is None:
        return []
    repairs = f"{REPAIR_PREFIX}{run_id}:"
    out: list[NewMessage] = []
    for i, m in enumerate(messages):
        if i > start and isinstance(m, HumanMessage) and (m.id or "").startswith("user:"):
            break  # the next turn's user message: what follows is that turn's
        if i <= start and not (m.id or "").startswith(repairs):
            continue
        if isinstance(m, AIMessage):
            text = _text(m.content)
            if text:
                usage: dict[str, Any] = dict(m.usage_metadata or {})
                content: dict[str, Any] = {
                    "text": text, "model": m.response_metadata.get("model_name"),
                    "tokens": usage.get("total_tokens"),
                }  # fmt: skip
                if m.additional_kwargs.get("budget_limited"):  # R14.2: "stopped early"
                    content["budget_limited"] = True
                out.append(NewMessage(make_id(run_id, "messages", i, "assistant"), "assistant",
                                      content))  # fmt: skip
            for j, tc in enumerate(m.tool_calls):
                out.append(NewMessage(make_id(run_id, "messages", f"{i}.{j}", "tool_call"),
                                      "tool_call", {"tool_call_id": tc["id"], "tool": tc["name"],
                                                    "args": tc["args"]}))  # fmt: skip
        elif isinstance(m, ToolMessage):
            out.append(NewMessage(make_id(run_id, "messages", i, "tool_result"), "tool_result",
                                  _result(m)))  # fmt: skip
        elif isinstance(m, SystemMessage):
            out.append(NewMessage(make_id(run_id, "messages", i, "system"), "system",
                                  {"text": _text(m.content)}))  # fmt: skip
    return out


def event_message(run_id: uuid.UUID, type: MessageType, content: dict[str, Any]) -> NewMessage:
    """An `interrupt` / `approval` / `error` row. Its id is derived from its content,
    so writing it again (a retried pause, a reclaim) is a no-op."""
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()
    return NewMessage(make_id(run_id, type, digest[:16], type), type, content)


@dataclass
class TranscriptWriter:
    session_id: uuid.UUID
    run_id: uuid.UUID
    fence: Fence
    bus: EventBus | None = None
    _just_written: list[Message] = field(default_factory=list)

    async def write(self, conn: Conn, messages: list[BaseMessage]) -> None:
        """Inside the checkpoint's transaction."""
        repo = SessionRepository(conn)
        written = await repo.append(
            self.session_id, transcript_of(messages, self.run_id),
            run_id=self.run_id, epoch=self.fence.epoch,
        )  # fmt: skip
        self._just_written = written  # replaced: a rollback discards them

    async def write_event(self, conn: Conn, type: MessageType, content: dict[str, Any]) -> None:
        """An interrupt / error row, inside the caller's fenced transaction."""
        repo = SessionRepository(conn)
        self._just_written += await repo.append(
            self.session_id, [event_message(self.run_id, type, content)],
            run_id=self.run_id, epoch=self.fence.epoch,
        )  # fmt: skip

    async def publish(self) -> None:
        written, self._just_written = self._just_written, []
        await publish_messages(self.bus, written)


def to_stream_event(message: Message) -> StreamEvent:
    return StreamEvent(
        run_id=message.run_id or uuid.UUID(int=0),
        seq=message.seq,
        ts=message.created_at
        if message.created_at.tzinfo
        else message.created_at.replace(tzinfo=UTC),
        epoch=message.epoch or 0,
        type=MESSAGE_CREATED,
        payload=message.view(),
    )


async def publish_messages(bus: EventBus | None, messages: list[Message]) -> None:
    """Best effort, after commit: readers back-fill from Postgres (R12.5)."""
    if bus is None:
        return
    for m in messages:
        try:
            await bus.publish(session_channel(m.session_id), to_stream_event(m))
        except Exception:
            log.warning("publish of message %s failed; readers will back-fill", m.seq,
                        exc_info=True)  # fmt: skip


def transient(
    session_id: uuid.UUID, run_id: uuid.UUID, type: str, payload: dict[str, Any], after_seq: int
) -> tuple[str, StreamEvent]:
    """A transient session event (`run.status`, `token`): pub/sub only, never replayed."""
    return session_channel(session_id), StreamEvent(
        run_id=run_id, seq=None, ts=datetime.now(UTC), epoch=0, type=type, payload=payload,
        after_seq=after_seq,
    )  # fmt: skip

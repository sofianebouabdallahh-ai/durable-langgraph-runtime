"""What the async and the sync client share, without I/O: reading a turn's events, building
its result, and keeping streamed text whole."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from nuria import _sse
from nuria.types import (
    CANCELLED,
    COMPLETED,
    FAILED,
    STOPS,
    WAITING_APPROVAL,
    AwaitingApproval,
    Cancelled,
    Completed,
    Failed,
    HelperEvent,
    Message,
    MessageEvent,
    PendingApproval,
    StatusEvent,
    TokenEvent,
    TurnEvent,
    TurnResult,
)

DEFAULT_TIMEOUT_S = 30.0
# Above the server's keep-alive (`: ping` every 15 s by default): a silent connection is dead.
STREAM_READ_TIMEOUT_S = 60.0
# `wait()` polls the run: quickly at first, then every 10 s, for as long as it takes.
WAIT_FIRST_S, WAIT_FACTOR, WAIT_CAP_S = 0.25, 1.5, 10.0
PAGE = 500


def turn_event(event: _sse.Event, run_id: str) -> TurnEvent | None:
    """One SSE event of the session stream, as an event of this turn; None if it belongs to
    another turn, is of a type this client doesn't know, or doesn't parse."""
    try:
        wire = json.loads(event.data)
    except ValueError:
        return None
    if not isinstance(wire, dict):
        return None
    payload = wire.get("payload")
    if not isinstance(payload, dict):
        return None
    kind = wire.get("type", event.event)
    if kind == "message.created":
        try:
            message = Message.of(payload)
        except (KeyError, TypeError, ValueError):
            return None
        return MessageEvent(message) if message.run_id == run_id else None
    if str(wire.get("run_id")) != run_id:
        return None
    if kind == "token":
        text = payload.get("text")
        return TokenEvent(text) if isinstance(text, str) else None
    if kind == "turn.status":
        status = payload.get("status")
        reason = payload.get("reason")
        return (
            StatusEvent(status, reason if isinstance(reason, str) else None)
            if isinstance(status, str)
            else None
        )
    if kind in ("subagent.spawned", "subagent.progress", "subagent.completed"):
        handle = payload.get("handle")
        if not isinstance(handle, str):
            return None
        percent = payload.get("percent")
        return HelperEvent(
            kind=kind.removeprefix("subagent."), handle=handle,
            agent=_str(payload.get("agent")), task=_str(payload.get("task")),
            message=_str(payload.get("message")), status=_str(payload.get("status")),
            percent=percent if isinstance(percent, int) else None,
        )  # fmt: skip
    return None


def stops(event: TurnEvent) -> bool:
    """The turn's stream has nothing more to say until someone acts (or ever)."""
    return isinstance(event, StatusEvent) and event.status in STOPS


def answer(messages: Iterable[Message]) -> str | None:
    texts = [m.text for m in messages if m.type == "assistant" and m.text]
    return texts[-1] if texts else None


def result(
    session_id: str, run: dict[str, Any], messages: tuple[Message, ...]
) -> TurnResult | None:
    """The run's result, or None while it's still going (any status but these four)."""
    status, run_id, reason = run.get("status"), str(run.get("id")), run.get("reason")
    reason = reason if isinstance(reason, str) else None
    if status == COMPLETED:
        return Completed(session_id, run_id, answer(messages), messages)
    if status == FAILED:
        return Failed(session_id, run_id, reason, answer(messages), messages)
    if status == CANCELLED:
        return Cancelled(session_id, run_id, reason)
    if status == WAITING_APPROVAL:
        payload = run.get("interrupt_payload")
        return AwaitingApproval(
            session_id, run_id, PendingApproval.of(payload if isinstance(payload, dict) else None)
        )
    return None


def of_run(page: dict[str, Any], run_id: str) -> tuple[list[Message], int | None]:
    """A `GET /sessions/{id}/messages` page: this turn's messages, and where the next starts."""
    rows = page.get("messages")
    messages = (
        [Message.of(m) for m in rows if isinstance(m, dict)] if isinstance(rows, list) else []
    )
    after = page.get("next_after_seq")
    return [m for m in messages if m.run_id == run_id], after if isinstance(after, int) else None


class TextStream:
    """The reply's text from the turn's events. Tokens are transient: one lost on a reconnect
    would leave a gap, so when the stored message arrives, what the tokens missed of it is
    added; once a message has arrived, the next tokens start the next reply."""

    def __init__(self) -> None:
        self._streamed = ""

    def text(self, event: TurnEvent) -> str | None:
        if isinstance(event, TokenEvent):
            self._streamed += event.text
            return event.text
        if isinstance(event, MessageEvent) and event.message.type == "assistant":
            full, streamed = event.message.text or "", self._streamed
            self._streamed = ""
            if full.startswith(streamed) and len(full) > len(streamed):
                return full[len(streamed) :]
        return None


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None

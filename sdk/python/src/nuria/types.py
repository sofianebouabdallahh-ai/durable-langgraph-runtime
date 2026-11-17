"""What the client returns: sessions, messages, a turn's events, and its result.

Read tolerantly from the API's JSON (CR-007 R19.4): only the fields used here are read, so a
field, an event type or a status a newer Nuria adds is ignored, never an error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# A turn's run statuses that end `wait()`. Every other status (queued, running,
# waiting_children, and any a newer Nuria adds) means: keep waiting.
COMPLETED, FAILED, CANCELLED, WAITING_APPROVAL = (
    "completed",
    "failed",
    "cancelled",
    "waiting_approval",
)
ENDED = frozenset({COMPLETED, FAILED, CANCELLED})
STOPS = ENDED | {WAITING_APPROVAL}  # the turn won't move without someone


@dataclass(frozen=True, slots=True)
class SessionInfo:
    id: str
    agent: str | None
    title: str | None
    status: str

    @classmethod
    def of(cls, data: dict[str, Any]) -> SessionInfo:
        return cls(id=str(data["id"]), agent=data.get("agent"), title=data.get("title"),
                   status=str(data.get("status", "")))  # fmt: skip


@dataclass(frozen=True, slots=True)
class Message:
    """One transcript message: `type` is `user`, `assistant`, `tool_call`, `tool_result`,
    `system`, …; `content` its fields (an assistant's `text`, a tool call's `args`)."""

    seq: int
    message_id: str
    run_id: str | None
    type: str
    role: str
    content: dict[str, Any]
    created_at: datetime | None

    @classmethod
    def of(cls, data: dict[str, Any]) -> Message:
        created = data.get("created_at")
        content = data.get("content")
        return cls(
            seq=int(data["seq"]), message_id=str(data.get("message_id", "")),
            run_id=str(data["run_id"]) if data.get("run_id") else None,
            type=str(data.get("type", "")), role=str(data.get("role", "")),
            content=content if isinstance(content, dict) else {},
            created_at=datetime.fromisoformat(created) if isinstance(created, str) else None,
        )  # fmt: skip

    @property
    def text(self) -> str | None:
        value = self.content.get("text")
        return value if isinstance(value, str) else None


# ------------------------------------------------------------------- a turn's events
@dataclass(frozen=True, slots=True)
class MessageEvent:
    """A message of the turn was stored (persisted: replayed, never lost)."""

    message: Message


@dataclass(frozen=True, slots=True)
class TokenEvent:
    """Part of the reply, as the model writes it (transient: one may be lost on a reconnect;
    the stored message has the whole text)."""

    text: str


@dataclass(frozen=True, slots=True)
class StatusEvent:
    """The turn changed state (transient)."""

    status: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class HelperEvent:
    """A helper (sub-agent) of the turn started, reported progress, or ended (transient)."""

    kind: str  # "spawned", "progress" or "completed"
    handle: str
    agent: str | None = None
    task: str | None = None
    message: str | None = None
    percent: int | None = None
    status: str | None = None


TurnEvent = MessageEvent | TokenEvent | StatusEvent | HelperEvent


# ---------------------------------------------------------------------- the results
@dataclass(frozen=True, slots=True)
class PendingApproval:
    """What the turn waits for you to approve, in Nuria. The arguments are shown with secrets
    redacted; `hidden` says how many values that redaction took out."""

    approval_id: str | None
    tool: str | None
    args: dict[str, Any]
    hidden: int
    reason: str | None

    @classmethod
    def of(cls, payload: dict[str, Any] | None) -> PendingApproval:
        p = payload or {}
        args = p.get("args")
        hidden = p.get("hidden")
        return cls(
            approval_id=str(p["approval_id"]) if p.get("approval_id") else None,
            tool=p.get("tool"), args=args if isinstance(args, dict) else {},
            hidden=hidden if isinstance(hidden, int) else 0, reason=p.get("reason"),
        )  # fmt: skip


@dataclass(frozen=True, slots=True)
class Completed:
    session_id: str
    run_id: str
    answer: str | None  # the turn's last assistant text
    messages: tuple[Message, ...] = field(default=(), repr=False)


@dataclass(frozen=True, slots=True)
class Failed:
    session_id: str
    run_id: str
    reason: str | None  # `budget:cost`, `loop_detected`, `error:…`
    answer: str | None  # the best answer it gave before it stopped, if any
    messages: tuple[Message, ...] = field(default=(), repr=False)


@dataclass(frozen=True, slots=True)
class Cancelled:
    session_id: str
    run_id: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class AwaitingApproval:
    """The turn is paused until a person approves or rejects a call, in Nuria. It's a result,
    not a timeout: `wait()` again (from any process, any time later) for the end."""

    session_id: str
    run_id: str
    approval: PendingApproval


TurnResult = Completed | Failed | Cancelled | AwaitingApproval

"""The streams' events, as a published contract (CR-007 R19.1, phase S1).

Pattern: Published Language. The two SSE endpoints' events are described here once, and
the spec references them (`text/event-stream` → `itemSchema` → `data` → these models), so
a client generated from the spec gets named, typed events instead of `unknown`.

These models describe the wire; they don't produce it (`streaming/session.py` does). The
server is held to them by the tests: every SSE event a test reads is parsed with them
(`tests/sse.py`), unknown fields included, so a payload changed in the server and not here
fails the test that read it.

    data of one SSE event:  {run_id, seq, after_seq, ts, epoch, type, payload}
      persisted (`id: <seq>`, replayed after Last-Event-ID): seq set, after_seq null
      transient (no id, never replayed): seq null, after_seq the persisted seq it follows
    `event: reconnect` (a replica draining, R10.7): data {after_seq}, then the stream closes

The run stream's `type` is one of the run event types; its payloads stay `object` until a
client needs one typed. The session stream's events are a closed union on `type`. A client
must still ignore a `type` it doesn't know: a newer server may add one (R19.4).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, Field, TypeAdapter

from agent_runtime.api.schemas import MessageView

# Every type the run stream can carry: the persisted run events, and `token` (pub/sub only).
RunEventType = Literal[
    "run.created", "run.started", "run.completed", "run.failed", "run.cancelled",
    "run.reclaimed", "run.released", "run.redriven", "context.trimmed", "context.compacted",
    "node.started", "node.completed", "node.failed", "tool.called", "tool.completed",
    "tool.args_changed", "interrupt.raised", "approval.decided", "run.resumed",
    "policy.decision", "hook.decision", "child.started", "child.completed",
    "children.spawned", "children.completed", "subagent.spawned", "subagent.progress",
    "subagent.completed", "token",
]  # fmt: skip
RUN_EVENT_TYPES: frozenset[str] = frozenset(get_args(RunEventType))  # in sync: a unit test

# Enums, not Literals, so the spec names them (`Schemas["TurnStatus"]` in the web app).


class TurnStatus(StrEnum):
    """A chat turn's lifecycle on the session stream (`streaming/bus.py` TURN_STATUS_OF)."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class HelperStatus(StrEnum):
    """A helper's state (`subagents/store.py` Status)."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class HelperResultStatus(StrEnum):
    """What a finished helper said of its own result (`return_result`)."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class _Envelope(BaseModel):
    run_id: uuid.UUID = Field(description="The run (turn) the event belongs to")
    seq: int | None = Field(
        description="Persisted events: the stream's sequence number, also sent as the SSE "
        "`id` and accepted back as `Last-Event-ID`. Transient events: null"
    )
    after_seq: int | None = Field(
        description="Transient events: the persisted seq they follow. Persisted: null"
    )
    ts: datetime
    epoch: int = Field(description="The lease epoch of the worker that wrote it")


class RunStreamEvent(_Envelope):
    """One event of `GET /runs/{run_id}/stream`. The stream closes after `run.completed`,
    `run.failed` or `run.cancelled`."""

    type: RunEventType
    payload: dict[str, Any]


class TokenPayload(BaseModel):
    text: str = Field(description="The next piece of the reply, as the model wrote it")


class TurnStatusPayload(BaseModel):
    run_id: uuid.UUID
    status: TurnStatus
    event: RunEventType = Field(description="The run event this status comes from")
    reason: str | None = Field(description="Why it failed or was cancelled, when it did")


class HelperSpawnedPayload(BaseModel):
    handle: uuid.UUID
    agent: str
    task: str
    worker: str = Field(description="The worker the helper runs in (the main run's)")


class HelperProgressPayload(BaseModel):
    handle: uuid.UUID
    message: str
    percent: int | None


class HelperCompletedPayload(BaseModel):
    handle: uuid.UUID
    agent: str
    status: HelperStatus
    result_status: HelperResultStatus | None
    reason: str | None


class MessageCreatedEvent(_Envelope):
    """A transcript message (persisted: it has a seq and is replayed)."""

    type: Literal["message.created"]
    payload: MessageView


class TokenEvent(_Envelope):
    """Transient: part of the active turn's reply. The complete reply arrives later as a
    `message.created`."""

    type: Literal["token"]
    payload: TokenPayload


class TurnStatusEvent(_Envelope):
    """Transient: the active turn changed state. Never replayed: a client that reconnects
    reads the turn's status from `GET /runs/{run_id}`."""

    type: Literal["turn.status"]
    payload: TurnStatusPayload


class HelperSpawnedEvent(_Envelope):
    type: Literal["subagent.spawned"]
    payload: HelperSpawnedPayload


class HelperProgressEvent(_Envelope):
    type: Literal["subagent.progress"]
    payload: HelperProgressPayload


class HelperCompletedEvent(_Envelope):
    type: Literal["subagent.completed"]
    payload: HelperCompletedPayload


SessionStreamEvent = Annotated[
    MessageCreatedEvent
    | TokenEvent
    | TurnStatusEvent
    | HelperSpawnedEvent
    | HelperProgressEvent
    | HelperCompletedEvent,
    Field(discriminator="type"),
]


class ReconnectData(BaseModel):
    """`event: reconnect`: this replica is shutting down. Reconnect now (any replica),
    resuming after `after_seq`."""

    after_seq: int


RUN_STREAM: TypeAdapter[RunStreamEvent] = TypeAdapter(RunStreamEvent)
SESSION_STREAM: TypeAdapter[SessionStreamEvent] = TypeAdapter(SessionStreamEvent)
RECONNECT: TypeAdapter[ReconnectData] = TypeAdapter(ReconnectData)

# The SSE `event:` name of each event is its `type`; `reconnect` is the one exception.
RECONNECT_EVENT = "reconnect"

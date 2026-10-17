"""Request and response bodies. These define the published OpenAPI contract."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.runs.state import RunStatus
from agent_runtime.runs.store import Event, Run


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph: str = Field(examples=["toy"])
    input: dict[str, Any] = Field(examples=[{"question": "What is a fencing token?"}])
    options: dict[str, Any] | None = Field(default=None, examples=[{"max_steps": 10}])


class CreateRunResponse(BaseModel):
    run_id: uuid.UUID


class RunView(BaseModel):
    id: uuid.UUID
    graph: str
    kind: str
    status: RunStatus
    reason: str | None
    epoch: int
    owner: str | None = Field(description="Worker (pod) holding the lease, if any")
    lease_expires_at: datetime | None
    steps: int
    reclaims: int = Field(description="Times taken over after a worker died (R2.4)")
    releases: int = Field(description="Graceful hand-offs on worker shutdown (R10.7)")
    cancel_requested: bool
    interrupt_payload: dict[str, Any] | None = Field(
        description="What a waiting_approval run waits on (R1.4)"
    )
    limits: dict[str, Any]
    parent_run_id: uuid.UUID | None = Field(description="Set for child runs (R2.8)")
    root_run_id: uuid.UUID | None
    depth: int = Field(description="0 for a root run, parent's + 1 for a child (R14.6)")
    child_key: str | None
    child_total: int = Field(description="Children spawned so far")
    child_done: int = Field(description="Children that have ended")
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def of(cls, run: Run) -> RunView:
        return cls(
            id=run.id,
            graph=run.graph_name,
            kind=run.kind,
            status=run.status,
            reason=run.reason,
            epoch=run.epoch,
            owner=run.owner,
            lease_expires_at=run.lease_expires_at,
            steps=run.steps,
            reclaims=run.reclaims,
            releases=run.releases,
            cancel_requested=run.cancel_requested,
            interrupt_payload=run.interrupt_payload,
            limits=run.limits,
            parent_run_id=run.parent_run_id,
            root_run_id=run.root_run_id,
            depth=run.depth,
            child_key=run.child_key,
            child_total=run.child_total,
            child_done=run.child_done,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )


class EventView(BaseModel):
    seq: int
    ts: datetime
    epoch: int
    type: str
    payload: dict[str, Any]

    @classmethod
    def of(cls, e: Event) -> EventView:
        return cls(seq=e.seq, ts=e.ts, epoch=e.epoch, type=e.type, payload=e.payload)


class EventsPage(BaseModel):
    events: list[EventView]
    next_after_seq: int = Field(description="Pass as `after_seq` to fetch the next page")


class ResultView(BaseModel):
    run_id: uuid.UUID
    output: dict[str, Any]
    partial: bool


class GraphEdge(BaseModel):
    source: str
    target: str
    conditional: bool


class GraphView(BaseModel):
    name: str
    description: str
    nodes: list[str]
    edges: list[GraphEdge]
    input_schema: dict[str, Any]


class ApprovalEdits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    args: dict[str, Any] | None = Field(
        default=None, description="Replacement tool arguments (re-validated before use)"
    )


class ApprovalRequest(BaseModel):
    """R1.4: `{decision: approve|reject, edits?}`."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    edits: ApprovalEdits | None = None
    reason: str | None = Field(default=None, max_length=2000)


class PauseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class Health(BaseModel):
    status: str


class AdminStatus(BaseModel):
    paused: bool
    reason: str | None
    updated_at: datetime
    queue_depth: int = Field(description="Runs waiting for a worker (R2.9)")

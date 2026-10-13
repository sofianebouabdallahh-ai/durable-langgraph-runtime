"""Request and response bodies. These define the published OpenAPI contract."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

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
    limits: dict[str, Any]
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
            limits=run.limits,
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


class PauseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class Health(BaseModel):
    status: str

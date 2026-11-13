"""Request and response bodies. These define the published OpenAPI contract."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.runs.state import RunStatus
from agent_runtime.runs.store import Event, Run
from agent_runtime.sessions.store import Message, Session
from agent_runtime.subagents.store import Invocation
from agent_runtime.telemetry import trace_id_of


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph: str = Field(examples=["toy"])
    input: dict[str, Any] = Field(examples=[{"question": "What is a fencing token?"}])
    options: dict[str, Any] | None = Field(default=None, examples=[{"max_steps": 10}])


class CreateRunResponse(BaseModel):
    run_id: uuid.UUID


class SubagentView(BaseModel):
    handle: uuid.UUID
    agent: str
    status: str
    progress: str | None = Field(description="The latest report_progress message")
    percent: int | None
    elapsed_s: float
    usage: dict[str, Any]
    result: dict[str, Any] | None


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
    infra_retries: int = Field(
        default=0, description="Releases because Postgres or Redis failed (H4), bounded"
    )
    redrives: int = Field(default=0, description="Times a person tried it again (H4)")
    cancel_requested: bool
    interrupt_payload: dict[str, Any] | None = Field(
        description="The next approval a waiting_approval run waits on (R1.4): its "
        "`approval_id`, `tool`, `args` (secrets redacted), `hidden` (how many values that "
        "redaction took out of `args`, H10), `call_id` and `reason`. Several "
        "can be pending; once this one is decided, the next one shows here."
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
    subagents: list[SubagentView] = Field(
        default_factory=list, description="Sub-agent invocations of this run (CR-005 R16.10)"
    )
    trace_id: str | None = Field(
        default=None, description="The OpenTelemetry trace this run belongs to (R7.1)"
    )
    details_pruned_at: datetime | None = Field(
        default=None,
        description="When retention removed its events and tool calls (H10): the timeline "
        "is empty because it was pruned, not because nothing happened. RETENTION_DAYS.",
    )

    @classmethod
    def of(cls, run: Run, subagents: list[Invocation] | None = None) -> RunView:
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
            infra_retries=run.infra_retries,
            redrives=run.redrives,
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
            subagents=[SubagentView(**i.view(), result=i.result) for i in subagents or []],
            trace_id=trace_id_of(run.traceparent),
            details_pruned_at=run.details_pruned_at,
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
    """R1.4: `{approval_id?, decision: approve|reject, edits?, reason?}`."""

    model_config = ConfigDict(extra="forbid")

    approval_id: uuid.UUID | None = Field(
        default=None,
        description="Which approval this decides (`interrupt_payload.approval_id`). Send it: "
        "it makes sure you decide the call you were shown. Without it, the request applies "
        "only when exactly one approval is pending (409 otherwise).",
    )
    decision: Literal["approve", "reject"]
    edits: ApprovalEdits | None = None
    reason: str | None = Field(default=None, max_length=2000)


class PauseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class Health(BaseModel):
    status: str


class AboutView(BaseModel):
    """What the UI shows about this installation; nothing secret (no keys, no URLs)."""

    version: str | None
    model_provider: str
    demo_model: bool = Field(description="The offline demo model (MODEL_PROVIDER=scripted)")
    chat_model: str | None = Field(description="The chat role's model, when configured")
    tracing: bool = Field(default=False, description="Traces are exported (--observability)")
    trace_ui_url: str | None = Field(
        default=None,
        description="Grafana: a run's trace (Tempo) and its log lines (Loki) open in Explore",
    )
    dashboard_url: str | None = Field(default=None, description="The Grafana dashboard")
    retention_days: int = Field(
        default=90,
        description="A run that ended this many days ago loses its details (H10); 0: never",
    )


class AdminStatus(BaseModel):
    paused: bool
    reason: str | None
    updated_at: datetime
    queue_depth: int = Field(description="Runs waiting for a worker (R2.9)")


# ------------------------------------------------------------ sessions (CR-001)


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str = Field(description="The agent to chat with (GET /agents)")
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None


class UpdateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    status: Literal["archived"] | None = Field(default=None, description="Archive (R12.1)")


class SessionView(BaseModel):
    id: uuid.UUID
    agent: str | None
    title: str | None
    status: str
    active_run_id: uuid.UUID | None
    active_run_status: str | None
    messages: int = Field(description="Transcript length (the last seq)")
    tokens: int
    cost: float
    summary: str | None = Field(description="Stored by the session_end hooks (R15.6)")
    created_at: datetime
    last_activity_at: datetime
    ended_at: datetime | None

    @classmethod
    def of(cls, s: Session) -> SessionView:
        return cls(
            id=s.id, agent=s.agent_name, title=s.title, status=s.status,
            active_run_id=s.active_run_id, active_run_status=s.active_run_status,
            messages=s.last_seq, tokens=s.tokens, cost=s.cost, summary=s.summary,
            created_at=s.created_at, last_activity_at=s.last_activity_at, ended_at=s.ended_at,
        )  # fmt: skip


class MessageView(BaseModel):
    seq: int
    message_id: str
    run_id: uuid.UUID | None
    type: str
    role: str
    content: dict[str, Any]
    created_at: datetime

    @classmethod
    def of(cls, m: Message) -> MessageView:
        return cls(
            seq=m.seq, message_id=m.message_id, run_id=m.run_id, type=m.type, role=m.role,
            content=m.content, created_at=m.created_at,
        )  # fmt: skip


class MessagesPage(BaseModel):
    messages: list[MessageView]
    next_after_seq: int | None


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: Annotated[str, Field(min_length=1, max_length=32_000)]  # R14.5: 32 KB
    options: dict[str, Any] | None = None
    # The scripted test model's replies (R14.20): refused unless MODEL_PROVIDER=scripted
    # (api/sessions.py), and at most 64 turns each (H10).
    script: Annotated[list[dict[str, Any]], Field(max_length=64)] | None = None
    subagent_scripts: dict[str, Annotated[list[dict[str, Any]], Field(max_length=64)]] | None = None


class TurnAccepted(BaseModel):
    message_id: str
    seq: int
    run_id: uuid.UUID


class HelperView(BaseModel):
    """A sub-agent (CR-005), as the UI shows it under its main agent."""

    name: str
    description: str
    model: str
    max_turns: int
    tools: list[dict[str, Any]]
    limits: dict[str, Any]
    prompt: str | None = Field(default=None, description="GET /agents/{name} only")


class AgentView(BaseModel):
    name: str
    display_name: str = Field(description="How people see it (falls back to the name)")
    source: Literal["builtin", "user"] = Field(description="Files in git, or built in the Studio")
    agent_id: uuid.UUID | None = Field(description="A Studio agent's id (for editing)")
    description: str
    version: int
    model: str
    max_turns: int
    tools: list[dict[str, Any]]
    limits: dict[str, Any]
    hooks: dict[str, list[str]]
    subagents: list[str]
    hidden: bool = Field(description="A test or example agent: not offered in the UI")
    helpers: list[HelperView] = Field(description="The sub-agents in detail")
    prompt: str | None = Field(default=None, description="GET /agents/{name} only")

"""Session and agent endpoints (CR-001 R12.10, CR-004 R15.11).

Transport only: parsing and rendering. The rules live in SessionService.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse

from agent_runtime.api.schemas import (
    AgentView,
    ApprovalRequest,
    CreateSessionRequest,
    HelperView,
    MessagesPage,
    MessageView,
    RunView,
    SendMessageRequest,
    SessionView,
    TurnAccepted,
    UpdateSessionRequest,
)
from agent_runtime.graphs import GraphRegistry, UnknownGraph
from agent_runtime.sessions.service import SessionService
from agent_runtime.streaming.session import SessionStream


def get_sessions(request: Request) -> SessionService:
    service: SessionService = request.app.state.sessions
    return service


SessionsDep = Annotated[SessionService, Depends(get_sessions)]

sessions = APIRouter(prefix="/sessions", tags=["sessions"])


@sessions.post("", status_code=status.HTTP_201_CREATED, response_model=SessionView,
               summary="Create a chat session with an agent")  # fmt: skip
async def create_session(body: CreateSessionRequest, service: SessionsDep) -> SessionView:
    return SessionView.of(await service.create(body.agent, body.title))


@sessions.get("", response_model=list[SessionView], summary="List sessions, newest activity first")
async def list_sessions(
    service: SessionsDep,
    status_: Annotated[Literal["active", "archived"] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    before: Annotated[datetime | None, Query(description="Page: last_activity_at <")] = None,
) -> list[SessionView]:
    return [SessionView.of(s) for s in await service.page(status=status_, limit=limit,
                                                          before=before)]  # fmt: skip


@sessions.get("/{session_id}", response_model=SessionView, summary="Session detail")
async def get_session(session_id: uuid.UUID, service: SessionsDep) -> SessionView:
    return SessionView.of(await service.get(session_id))


@sessions.patch("/{session_id}", response_model=SessionView, summary="Rename or archive")
async def update_session(
    session_id: uuid.UUID, body: UpdateSessionRequest, service: SessionsDep
) -> SessionView:
    updated = await service.update(session_id, title=body.title, archive=body.status == "archived")
    return SessionView.of(updated)


@sessions.get("/{session_id}/messages", response_model=MessagesPage, summary="Transcript page")
async def list_messages(
    session_id: uuid.UUID,
    service: SessionsDep,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> MessagesPage:
    page = await service.messages(session_id, after_seq, limit)
    return MessagesPage(
        messages=[MessageView.of(m) for m in page],
        next_after_seq=page[-1].seq if len(page) == limit else None,
    )


@sessions.post("/{session_id}/messages", status_code=status.HTTP_202_ACCEPTED,
               response_model=TurnAccepted, summary="Send a message: starts a turn")  # fmt: skip
async def send_message(
    session_id: uuid.UUID, body: SendMessageRequest, service: SessionsDep
) -> TurnAccepted:
    turn = await service.send(session_id, body.content, body.options, script=body.script,
                              subagent_scripts=body.subagent_scripts)  # fmt: skip
    return TurnAccepted(message_id=turn.message.message_id, seq=turn.message.seq,
                        run_id=turn.run.id)  # fmt: skip


@sessions.post(
    "/{session_id}/approve",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RunView,
    summary="Approve or reject the active turn (R12.6)",
)
async def approve_turn(
    session_id: uuid.UUID, body: ApprovalRequest, service: SessionsDep
) -> RunView:
    edits = body.edits.model_dump() if body.edits else None
    return RunView.of(await service.approve(session_id, body.decision, edits, body.reason))


@sessions.post("/{session_id}/cancel", status_code=status.HTTP_202_ACCEPTED,
               response_model=RunView, summary="Cancel the active turn (R12.7)")  # fmt: skip
async def cancel_turn(session_id: uuid.UUID, service: SessionsDep) -> RunView:
    return RunView.of(await service.cancel(session_id))


@sessions.get(
    "/{session_id}/stream",
    summary="The session's live stream (SSE, R12.5)",
    description="Replays transcript messages after `Last-Event-ID` (or `after_seq`), then "
    "streams new ones from any replica, plus transient events of the active turn (no `id`).",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}, 503: {"description": "Draining"}},
)
async def stream_session(
    session_id: uuid.UUID,
    request: Request,
    service: SessionsDep,
    after_seq: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    from agent_runtime.api.problems import ApiDraining as Draining

    if request.app.state.draining.is_set():
        raise Draining
    await service.get(session_id)  # 404 before opening a stream
    start = after_seq or 0
    if last_event_id is not None and last_event_id.isdigit():
        start = int(last_event_id)
    stream = SessionStream(
        request.app.state.pool, request.app.state.broker, request.app.state.settings,
        session_id, after_seq=start, draining=request.app.state.draining,
    )  # fmt: skip
    return StreamingResponse(
        stream.events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --------------------------------------------------------------- agents (R15.11)

agents = APIRouter(prefix="/agents", tags=["agents"])


def _agent_view(graphs: GraphRegistry, name: str, *, prompt: bool) -> AgentView:
    spec = graphs.get(name)
    if spec.agent is None:
        raise UnknownGraph(f"unknown agent {name!r}")
    a = spec.agent
    fm = a.frontmatter
    return AgentView(
        name=a.id, description=fm.description, version=fm.version, model=fm.model,
        max_turns=fm.max_turns, tools=[t.model_dump(exclude_none=True) for t in fm.tools],
        limits=fm.limits.model_dump(exclude_none=True),
        hooks={k: v for k, v in fm.hooks.model_dump().items() if v},
        subagents=[s.frontmatter.name for s in a.subagents],
        hidden=fm.hidden,
        helpers=[
            HelperView(
                name=s.frontmatter.name, description=s.frontmatter.description,
                model=s.frontmatter.model, max_turns=s.frontmatter.max_turns,
                tools=[t.model_dump(exclude_none=True) for t in s.frontmatter.tools],
                limits=s.frontmatter.limits.model_dump(exclude_none=True),
                prompt=s.prompt if prompt else None,
            )
            for s in a.subagents
        ],
        prompt=a.prompt if prompt else None,
    )  # fmt: skip


def _graphs(request: Request) -> GraphRegistry:
    graphs: GraphRegistry = request.app.state.graphs
    return graphs


@agents.get("", response_model=list[AgentView], summary="Agent definitions")
async def list_agents(graphs: Annotated[GraphRegistry, Depends(_graphs)]) -> list[AgentView]:
    return [_agent_view(graphs, s.name, prompt=False) for s in graphs if s.agent is not None]


@agents.get("/{name}", response_model=AgentView, summary="One agent, with its prompt")
async def get_agent(name: str, graphs: Annotated[GraphRegistry, Depends(_graphs)]) -> AgentView:
    return _agent_view(graphs, name, prompt=True)

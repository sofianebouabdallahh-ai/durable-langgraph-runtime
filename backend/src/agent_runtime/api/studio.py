"""The Agent Studio API (CR-006 R17.1 to R17.3, phase L3a): what the editor calls.

GET  /studio/catalog                      tools, protections, presets, placeholders
GET  /studio/agents · POST /studio/agents create blank, or a copy (`copy_of`)
GET  /studio/agents/{id}                  draft (+ issues, tested, blockers), versions
PUT  /studio/agents/{id}/draft            autosave + validate
POST …/edit · …/publish · …/archive · …/versions/{n}/restore · DELETE …/draft
POST …/test-chat                          a test chat with the draft
GET  …/export · POST /studio/import       agent.md, or a zipped folder
POST /studio/describe · …/{id}/improve    the builder agents: a proposal, nothing saved
GET  /studio/assist/{run_id}               the proposal, once ready
POST /studio/agents/from-proposal          a new agent whose draft is a proposal
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.agents.builder import DraftProposal
from agent_runtime.agents.document import MAX_UPLOAD_BYTES, AgentDocument, ImportRejected
from agent_runtime.agents.schema import MAIN_PLACEHOLDERS, SUB_PLACEHOLDERS
from agent_runtime.agents.studio import (
    PROTECTIONS,
    TOOLS,
    AgentState,
    StudioService,
    presets,
)
from agent_runtime.agents.studio_store import AgentNotFound, Version
from agent_runtime.api.schemas import SessionView
from agent_runtime.mcp import tools as mcp_tools
from agent_runtime.mcp.service import McpStore
from agent_runtime.runs.store import RunNotFound

studio = APIRouter(prefix="/studio", tags=["studio"])


def _studio(request: Request) -> StudioService:
    service: StudioService = request.app.state.studio
    return service


StudioDep = Annotated[StudioService, Depends(_studio)]
GuideFlag = Annotated[bool, Query(description="Built in Getting started: the guide's agent")]


# ------------------------------------------------------------------- schemas


class ToolOption(BaseModel):
    name: str
    label: str
    description: str
    risk: str
    asks_first: bool = Field(description="Needs a person's approval before it runs")
    helpers_allowed: bool = Field(description="Helpers may use it (not approval-gated tools)")
    server: str | None = Field(default=None, description="An MCP tool: its server's name (L8)")


class ProtectionOption(BaseModel):
    hook: str
    point: str
    label: str
    description: str
    default: bool
    helpers: bool = Field(description="Also applies to helpers (tool protections)")


class Preset(BaseModel):
    max_turns: int
    limits: dict[str, Any]


class StudioCatalog(BaseModel):
    tools: list[ToolOption]
    protections: list[ProtectionOption]
    presets: dict[str, Preset]
    placeholders: dict[str, list[str]]
    ceilings: dict[str, float]


class IssueView(BaseModel):
    where: str = Field(description="'agent' or 'helpers.<name>'")
    field: str | None
    message: str


class VersionView(BaseModel):
    number: int
    state: Literal["draft", "published", "archived"]
    changelog: str | None
    created_at: datetime
    published_at: datetime | None

    @classmethod
    def of(cls, v: Version) -> VersionView:
        return cls(number=v.number, state=v.state, changelog=v.changelog,
                   created_at=v.created_at, published_at=v.published_at)  # fmt: skip


class DraftView(BaseModel):
    number: int
    document: AgentDocument
    issues: list[IssueView]
    tested: bool = Field(description="A test-chat reply completed on exactly this draft")
    blockers: list[str] = Field(description="What stands between this draft and publishing")
    tests: int = Field(default=0, description="Its test cases (H6): with any, they're the gate")
    tests_failing: list[str] = Field(
        default_factory=list, description="Cases not passed on exactly this draft"
    )


class StudioAgentView(BaseModel):
    id: uuid.UUID
    name: str
    display_name: str
    description: str
    status: Literal["draft", "published", "changes"] = Field(
        description="Never published / published, nothing pending / published, with a draft"
    )
    archived: bool
    published: VersionView | None
    published_document: AgentDocument | None
    draft: DraftView | None
    versions: list[VersionView]

    @classmethod
    def of(cls, s: AgentState) -> StudioAgentView:
        current = s.draft.version.document if s.draft else (s.published.document if s.published
                                                              else {})  # fmt: skip
        return cls(
            id=s.agent.id, name=s.agent.name,
            display_name=str(current.get("display_name") or s.agent.name),
            description=str(current.get("description") or ""),
            status=("changes" if s.draft and s.published else "draft" if s.draft
                    else "published"),
            archived=s.agent.archived_at is not None,
            published=VersionView.of(s.published) if s.published else None,
            published_document=AgentDocument.model_validate(s.published.document)
            if s.published else None,
            draft=DraftView(
                number=s.draft.version.number,
                document=AgentDocument.model_validate(s.draft.version.document),
                issues=[IssueView(where=i.where, field=i.field, message=i.message)
                        for i in s.draft.issues],
                tested=s.draft.tested, blockers=s.draft.blockers,
                tests=s.draft.tests, tests_failing=s.draft.tests_failing,
            ) if s.draft else None,
            versions=[VersionView.of(v) for v in s.versions],
        )  # fmt: skip


class CreateAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: Annotated[str, Field(min_length=1, max_length=60)]
    description: Annotated[str, Field(max_length=500)] = ""
    copy_of: str | None = Field(default=None, description="An agent to start from (its name)")


class DescribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: Annotated[str, Field(min_length=10, max_length=4000,
                                      description="The assistant the person wants")]  # fmt: skip


class AssistStarted(BaseModel):
    run_id: uuid.UUID


class AssistView(BaseModel):
    status: Literal["working", "done", "failed"]
    kind: Literal["draft", "instructions"]
    proposal: dict[str, Any] | None = Field(
        description="A DraftProposal or an InstructionsProposal, when done"
    )
    problem: str | None = Field(description="Why there's no proposal, in plain words")
    repairs: list[str] = Field(default_factory=list, description="What was fixed in the draft")


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changelog: Annotated[str, Field(max_length=500)] | None = None


# ----------------------------------------------------------------- endpoints


@studio.get("/catalog", response_model=StudioCatalog, summary="What the form offers")
async def catalog(request: Request) -> StudioCatalog:
    service = _studio(request)
    risks = service.tool_risks()
    s = request.app.state.settings
    async with request.app.state.pool.connection() as conn:
        mcp = await mcp_tools.usable(conn)
        servers = {sv.id: sv.display_name for sv in await McpStore(conn).servers()}
    return StudioCatalog(
        tools=[
            *(ToolOption(name=n, label=label, description=desc, risk=risks.get(n, "read"),
                         asks_first=risks.get(n) == "external_side_effect",
                         helpers_allowed=risks.get(n) != "external_side_effect")
              for n, (label, desc) in TOOLS.items()
              if n in service.offered_tools()),
            # The MCP tools people switched on (Settings → Tools), under their server.
            *(ToolOption(name=n, label=t.tool.replace("_", " ").capitalize(),
                         description=t.definition.description, risk=t.risk,
                         asks_first=not t.without_asking, helpers_allowed=t.without_asking,
                         server=servers.get(t.server_id))
              for n, t in mcp.items()),
        ],
        protections=[
            ProtectionOption(hook=h, point=point, label=label, description=desc,
                             default=default, helpers=point in ("pre_tool", "post_tool"))
            for h, (point, label, desc, default) in PROTECTIONS.items()
        ],
        presets={k: Preset(**v) for k, v in presets(s).items()},
        placeholders={"agent": sorted(MAIN_PLACEHOLDERS), "helper": sorted(SUB_PLACEHOLDERS)},
        ceilings={"max_turns": s.ceiling_model_calls, "max_tool_calls": s.ceiling_tool_calls,
                  "timeout_s": s.run_timeout_s},
    )  # fmt: skip


@studio.get("/agents", response_model=list[StudioAgentView], summary="Your agents")
async def list_agents(service: StudioDep) -> list[StudioAgentView]:
    return [StudioAgentView.of(s) for s in await service.all()]


@studio.post("/agents", status_code=status.HTTP_201_CREATED, response_model=StudioAgentView,
             summary="A new agent (blank, or a copy) with a draft")  # fmt: skip
async def create_agent(
    body: CreateAgentRequest, request: Request, service: StudioDep, guide: GuideFlag = False
) -> StudioAgentView:
    try:
        state = await service.create(body.display_name, body.description, body.copy_of)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if guide:
        await _guide(request, state.agent.id)
    return StudioAgentView.of(state)


async def _guide(request: Request, agent_id: uuid.UUID) -> None:
    """Make this the agent the Getting started guide is about (L3d)."""
    from agent_runtime import onboarding

    async with request.app.state.pool.connection() as conn, conn.transaction():
        await onboarding.update(conn, agent_id=agent_id)


@studio.post("/describe", status_code=status.HTTP_202_ACCEPTED, response_model=AssistStarted,
             summary="Draft an agent from a description (the builder agent)")  # fmt: skip
async def describe(body: DescribeRequest, service: StudioDep) -> AssistStarted:
    return AssistStarted(run_id=(await service.describe(body.description)).id)


@studio.post("/agents/{agent_id}/improve", status_code=status.HTTP_202_ACCEPTED,
             response_model=AssistStarted, summary="Suggest clearer instructions")  # fmt: skip
async def improve(agent_id: uuid.UUID, service: StudioDep) -> AssistStarted:
    try:
        return AssistStarted(run_id=(await service.improve(agent_id)).id)
    except LookupError as exc:
        if isinstance(exc, AgentNotFound):
            raise
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@studio.get("/assist/{run_id}", response_model=AssistView, summary="A builder's proposal")
async def assist(run_id: uuid.UUID, service: StudioDep) -> AssistView:
    try:
        found = await service.assist(run_id)
    except LookupError as exc:
        if isinstance(exc, RunNotFound):
            raise
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return AssistView(status=found.status, kind=found.kind, proposal=found.proposal,
                      problem=found.problem, repairs=found.repairs)  # fmt: skip


@studio.post("/agents/from-proposal", status_code=status.HTTP_201_CREATED,
             response_model=StudioAgentView, summary="A new agent from a proposal")  # fmt: skip
async def from_proposal(
    body: DraftProposal, request: Request, service: StudioDep, guide: GuideFlag = False
) -> StudioAgentView:
    state = await service.create_from_proposal(body)
    if guide:
        await _guide(request, state.agent.id)
    return StudioAgentView.of(state)


@studio.get("/agents/{agent_id}", response_model=StudioAgentView, summary="One agent")
async def get_agent(agent_id: uuid.UUID, service: StudioDep) -> StudioAgentView:
    return StudioAgentView.of(await service.get(agent_id))


@studio.put("/agents/{agent_id}/draft", response_model=StudioAgentView,
            summary="Save the draft (autosave); returns its issues")  # fmt: skip
async def save_draft(
    agent_id: uuid.UUID, document: AgentDocument, service: StudioDep
) -> StudioAgentView:
    return StudioAgentView.of(await service.save_draft(agent_id, document))


@studio.post("/agents/{agent_id}/edit", response_model=StudioAgentView,
             summary="Start editing: a draft from the published version")  # fmt: skip
async def edit(agent_id: uuid.UUID, service: StudioDep) -> StudioAgentView:
    return StudioAgentView.of(await service.edit(agent_id))


@studio.delete("/agents/{agent_id}/draft", response_model=StudioAgentView,
               summary="Throw away the draft (back to the published version)")  # fmt: skip
async def discard(agent_id: uuid.UUID, service: StudioDep) -> StudioAgentView:
    return StudioAgentView.of(await service.discard(agent_id))


@studio.post("/agents/{agent_id}/publish", response_model=StudioAgentView,
             summary="Publish the draft as an immutable version (needs a test)")  # fmt: skip
async def publish(agent_id: uuid.UUID, body: PublishRequest, service: StudioDep) -> StudioAgentView:
    return StudioAgentView.of(await service.publish(agent_id, body.changelog))


@studio.post("/agents/{agent_id}/versions/{number}/restore", response_model=StudioAgentView,
             summary="Make an earlier version the draft")  # fmt: skip
async def restore(agent_id: uuid.UUID, number: int, service: StudioDep) -> StudioAgentView:
    try:
        return StudioAgentView.of(await service.restore(agent_id, number))
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@studio.post("/agents/{agent_id}/archive", response_model=StudioAgentView,
             summary="Archive: no new chats; old ones stay readable")  # fmt: skip
async def archive(agent_id: uuid.UUID, service: StudioDep) -> StudioAgentView:
    return StudioAgentView.of(await service.archive(agent_id))


@studio.post("/agents/{agent_id}/test-chat", status_code=status.HTTP_201_CREATED,
             response_model=SessionView, summary="A test chat with the draft")  # fmt: skip
async def test_chat(agent_id: uuid.UUID, service: StudioDep) -> SessionView:
    return SessionView.of(await service.playground(agent_id))


@studio.get("/agents/{agent_id}/test-chat", response_model=SessionView | None,
            summary="The latest test chat still open, if any")  # fmt: skip
async def last_test_chat(agent_id: uuid.UUID, service: StudioDep) -> SessionView | None:
    found = await service.last_playground(agent_id)
    return SessionView.of(found) if found else None


@studio.get("/agents/{agent_id}/export", summary="Download as agent.md (or a zipped folder)",
            responses={200: {"content": {"application/zip": {}, "text/markdown": {}}}})  # fmt: skip
async def export(
    agent_id: uuid.UUID,
    service: StudioDep,
    version: Annotated[
        int | None, Query(ge=1, description="Default: the draft, else current")
    ] = None,
) -> Response:
    try:
        filename, data, media = await service.export(agent_id, version)
    except LookupError as exc:
        if isinstance(exc, AgentNotFound):
            raise
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    disposition = f'attachment; filename="{filename}"'
    return Response(data, media_type=media, headers={"Content-Disposition": disposition})


@studio.post("/import", status_code=status.HTTP_201_CREATED, response_model=StudioAgentView,
             summary="Import an agent.md or a zipped folder (the file is the body)")  # fmt: skip
async def import_agent(
    request: Request,
    service: StudioDep,
    filename: Annotated[str, Query(min_length=1, max_length=200)],
) -> StudioAgentView:
    data = bytearray()
    async for chunk in request.stream():  # bounded: never buffer more than the limit
        data += chunk
        if len(data) > MAX_UPLOAD_BYTES:
            raise ImportRejected(f"the file is larger than {MAX_UPLOAD_BYTES // 1_000_000} MB")
    return StudioAgentView.of(await service.import_(filename, bytes(data)))

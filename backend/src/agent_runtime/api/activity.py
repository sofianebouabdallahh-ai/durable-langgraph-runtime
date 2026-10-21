"""Activity (phase L7): what all agents have been doing.

    GET /activity                   now, totals, per day, agents, models, tools, errors
    GET /activity/turns             every turn, newest first (filters, a cursor)
    GET /activity/turns/{run_id}    one turn, with its model calls per model
    GET /activity/sessions          the chats with a turn in range

Range 24h · 7d · 30d; `agent` for one agent; `include_tests` for test chats.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agent_runtime.activity import ActivityRepository, Range, Scope
from agent_runtime.db import Pool

activity_router = APIRouter(prefix="/activity", tags=["activity"])


def _pool(request: Request) -> Pool:
    pool: Pool = request.app.state.pool
    return pool


PoolDep = Annotated[Pool, Depends(_pool)]
RangeQ = Annotated[Range, Query(alias="range", description="24h, 7d or 30d")]
AgentQ = Annotated[str | None, Query(description="One agent (its name); all by default")]
TestsQ = Annotated[bool, Query(description="Count test chats from the Studio too")]


class Waiting(BaseModel):
    run_id: uuid.UUID
    session_id: uuid.UUID | None
    agent: str | None
    tool: str | None
    since: datetime | None


class Now(BaseModel):
    running: int
    waiting_approval: int
    queued: int
    spend_today: float
    waiting: list[Waiting]


class Approvals(BaseModel):
    asked: int
    approved: int
    rejected: int


class Totals(BaseModel):
    turns: int
    failed: int
    chats: int
    tokens: int
    cost: float
    tool_calls: int
    model_calls: int
    helpers: int
    approvals: Approvals


class Day(BaseModel):
    day: date
    turns: int
    failed: int
    cost: float
    by_agent: dict[str, int] = Field(description="Turns per agent that day")


class AgentRow(BaseModel):
    agent: str
    turns: int
    failed: int
    p50_s: float | None = Field(description="Median turn time")
    p95_s: float | None
    tokens: int
    cost: float
    last_turn: datetime | None


class ModelRow(BaseModel):
    model: str
    calls: int
    tokens_in: int
    tokens_out: int
    cost: float
    avg_ms: int | None = Field(description="Average time per call")


class ToolRow(BaseModel):
    tool: str | None
    calls: int
    failed: int
    cached: int
    p95_ms: float | None


class ErrorRow(BaseModel):
    reason: str | None
    agent: str
    count: int
    run_id: uuid.UUID = Field(description="The latest failed turn")
    session_id: uuid.UUID | None
    at: datetime


class ActivityView(BaseModel):
    range: Range
    now: Now
    totals: Totals
    days: list[Day]
    agents: list[AgentRow]
    models: list[ModelRow]
    tools: list[ToolRow]
    errors: list[ErrorRow]


class TurnRow(BaseModel):
    id: uuid.UUID
    created_at: datetime
    agent: str | None
    agent_version: int | None
    status: str
    reason: str | None
    session_id: uuid.UUID | None
    session_title: str | None
    test: bool | None
    steps: int
    model_calls: int
    tool_calls: int
    tokens: int
    cost: float
    duration_s: float | None
    reclaims: int
    models: list[str]

    @classmethod
    def of(cls, row: dict[str, Any]) -> TurnRow:
        return cls(
            id=row["id"], created_at=row["created_at"], agent=row["agent_name"],
            agent_version=row["agent_version"], status=row["status"], reason=row["reason"],
            session_id=row["session_id"], session_title=row["session_title"],
            test=row["test"], steps=row["steps"], model_calls=row["model_calls"],
            tool_calls=row["tool_calls_total"], tokens=row["tokens"], cost=row["cost"],
            duration_s=row["duration_s"], reclaims=row["reclaims"], models=list(row["models"]),
        )  # fmt: skip


class ModelUsage(BaseModel):
    model: str
    calls: int
    tokens_in: int
    tokens_out: int
    cost: float
    duration_ms: int


class TurnDetail(TurnRow):
    usage: list[ModelUsage] = Field(description="Its model calls, per model")


class SessionRow(BaseModel):
    id: uuid.UUID
    title: str | None
    agent: str | None
    status: str
    messages: int
    turns: int = Field(description="Turns in range")
    failed: int
    tokens: int
    cost: float
    created_at: datetime
    last_activity_at: datetime
    test: bool


@activity_router.get("", response_model=ActivityView, summary="What all agents have been doing")
async def activity(
    pool: PoolDep, range_: RangeQ = "7d", agent: AgentQ = None, include_tests: TestsQ = False
) -> ActivityView:
    scope = Scope.of(range_, agent, include_tests)
    async with pool.connection() as conn:
        repo = ActivityRepository(conn)
        return ActivityView(
            range=range_,
            now=Now(**await repo.now()),
            totals=Totals(**await repo.totals(scope)),
            days=[Day(**d) for d in await repo.series(scope)],
            agents=[AgentRow(**a) for a in await repo.agents(scope)],
            models=[ModelRow(**m) for m in await repo.models(scope)],
            tools=[ToolRow(**t) for t in await repo.tools(scope)],
            errors=[ErrorRow(**e) for e in await repo.errors(scope)],
        )


@activity_router.get("/turns", response_model=list[TurnRow], summary="Turns, newest first")
async def turns(
    pool: PoolDep,
    range_: RangeQ = "7d",
    agent: AgentQ = None,
    include_tests: TestsQ = False,
    status: Annotated[str | None, Query(description="e.g. failed")] = None,
    reason: Annotated[str | None, Query(description="e.g. timeout")] = None,
    session_id: uuid.UUID | None = None,
    before: Annotated[datetime | None, Query(description="Page: created_at <")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[TurnRow]:
    scope = Scope.of(range_, agent, include_tests or session_id is not None)
    async with pool.connection() as conn:
        rows = await ActivityRepository(conn).turns(
            scope, status=status, reason=reason, session_id=session_id, before=before,
            limit=limit,
        )  # fmt: skip
    return [TurnRow.of(r) for r in rows]


@activity_router.get("/turns/{run_id}", response_model=TurnDetail, summary="One turn")
async def turn(run_id: uuid.UUID, pool: PoolDep) -> TurnDetail:
    async with pool.connection() as conn:
        repo = ActivityRepository(conn)
        rows = await repo.one_turn(run_id)
        if not rows:
            raise HTTPException(404, "no such turn")
        usage = await repo.model_usage(run_id)
    return TurnDetail(**TurnRow.of(rows[0]).model_dump(), usage=[ModelUsage(**u) for u in usage])


@activity_router.get("/sessions", response_model=list[SessionRow], summary="Chats in range")
async def sessions(
    pool: PoolDep,
    range_: RangeQ = "7d",
    agent: AgentQ = None,
    include_tests: TestsQ = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SessionRow]:
    async with pool.connection() as conn:
        rows = await ActivityRepository(conn).sessions(
            Scope.of(range_, agent, include_tests), limit=limit
        )
    return [SessionRow(**r) for r in rows]

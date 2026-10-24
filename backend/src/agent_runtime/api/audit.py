"""Who did what, and what people thought of the replies (phase L7d).

    GET    /audit                    the trail, newest first (filters, a cursor)
    GET    /audit.csv                the same, as a file to download
    GET    /runs/{run_id}/feedback   a reply's 👍 / 👎, if it has one
    PUT    /runs/{run_id}/feedback   rate it (or change the rating)
    DELETE /runs/{run_id}/feedback   take the rating back

The trail can only be read here: nothing in the API changes or deletes it.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from agent_runtime.audit import AuditEvent, AuditLog
from agent_runtime.db import Pool
from agent_runtime.feedback import FeedbackRepository, NotRatable, Rating

audit_router = APIRouter(tags=["audit"])


def _pool(request: Request) -> Pool:
    pool: Pool = request.app.state.pool
    return pool


PoolDep = Annotated[Pool, Depends(_pool)]


class AuditRow(BaseModel):
    id: uuid.UUID
    at: datetime
    actor: str
    action: str = Field(description="e.g. agent.published, kill_switch.on")
    target_type: str
    target_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    request_id: str | None
    trace_id: str | None

    @classmethod
    def of(cls, e: AuditEvent) -> AuditRow:
        return cls(**{f: getattr(e, f) for f in cls.model_fields})


ActionQ = Annotated[str | None, Query(max_length=60, description="e.g. agent.published")]
TargetQ = Annotated[str | None, Query(max_length=60, description="e.g. agent")]
TargetIdQ = Annotated[str | None, Query(max_length=200)]
BeforeQ = Annotated[datetime | None, Query(description="Page: at <")]


async def _events(
    pool: Pool, action: str | None, target_type: str | None, target_id: str | None,
    before: datetime | None, limit: int,
) -> list[AuditEvent]:  # fmt: skip
    async with pool.connection() as conn:
        return await AuditLog(conn).list(
            action=action, target_type=target_type, target_id=target_id, before=before,
            limit=limit,
        )  # fmt: skip


@audit_router.get("/audit", response_model=list[AuditRow], summary="Who changed what")
async def audit(
    pool: PoolDep,
    action: ActionQ = None,
    target_type: TargetQ = None,
    target_id: TargetIdQ = None,
    before: BeforeQ = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditRow]:
    return [AuditRow.of(e) for e in await _events(pool, action, target_type, target_id,
                                                  before, limit)]  # fmt: skip


@audit_router.get("/audit.csv", summary="The trail as a CSV file", response_class=Response)
async def audit_csv(
    pool: PoolDep,
    action: ActionQ = None,
    target_type: TargetQ = None,
    target_id: TargetIdQ = None,
) -> Response:
    events = await _events(pool, action, target_type, target_id, None, 10_000)
    out = io.StringIO()
    writer = csv.writer(out)
    columns = ["at", "actor", "action", "target_type", "target_id", "before", "after",
               "request_id", "trace_id"]  # fmt: skip
    writer.writerow(columns)
    for e in events:
        writer.writerow([
            _cell(json.dumps(v, default=str, ensure_ascii=False)
                  if isinstance(v := getattr(e, c), dict) else v)
            for c in columns
        ])  # fmt: skip
    return Response(
        out.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="nuria-audit.csv"'},
    )  # fmt: skip


def _cell(value: Any) -> str:
    """No formula injection: a cell a spreadsheet would run as a formula gets a quote."""
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


class FeedbackView(BaseModel):
    run_id: uuid.UUID
    rating: Rating
    reason: str | None
    agent: str | None
    agent_version: int | None
    updated_at: datetime


class FeedbackIn(BaseModel):
    rating: Rating
    reason: str | None = Field(
        default=None, max_length=500, description="What was wrong (or right)"
    )


@audit_router.get("/runs/{run_id}/feedback", response_model=FeedbackView | None,
                  summary="A reply's rating")  # fmt: skip
async def get_feedback(run_id: uuid.UUID, pool: PoolDep) -> FeedbackView | None:
    async with pool.connection() as conn:
        f = await FeedbackRepository(conn).get(run_id)
    return _view(f) if f else None


@audit_router.put("/runs/{run_id}/feedback", response_model=FeedbackView, summary="Rate a reply")
async def put_feedback(run_id: uuid.UUID, body: FeedbackIn, pool: PoolDep) -> FeedbackView:
    async with pool.connection() as conn:
        try:
            f = await FeedbackRepository(conn).rate(run_id, body.rating, body.reason)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except NotRatable as exc:
            raise HTTPException(409, str(exc)) from exc
    return _view(f)


@audit_router.delete("/runs/{run_id}/feedback", status_code=204, summary="Take a rating back")
async def delete_feedback(run_id: uuid.UUID, pool: PoolDep) -> None:
    async with pool.connection() as conn:
        await FeedbackRepository(conn).clear(run_id)


def _view(f: Any) -> FeedbackView:
    return FeedbackView(run_id=f.run_id, rating=f.rating, reason=f.reason, agent=f.agent_name,
                        agent_version=f.agent_version, updated_at=f.updated_at)  # fmt: skip

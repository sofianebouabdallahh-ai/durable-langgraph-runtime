"""Opt-in usage counts (phase L5): see agent_runtime/usage.py. Transport only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from agent_runtime import usage
from agent_runtime.audit import AuditLog
from agent_runtime.config import Settings
from agent_runtime.db import Pool


class TelemetryView(BaseModel):
    sharing: bool = Field(
        description="Usage counts are attached to feedback you send (off by default)"
    )
    fields: dict[str, str] = Field(description="What each count is: never content, names or keys")
    report: dict[str, Any] = Field(description="Exactly what would be attached")


class TelemetryUpdate(BaseModel):
    sharing: bool


telemetry_router = APIRouter(prefix="/telemetry", tags=["telemetry"])


async def _view(request: Request) -> TelemetryView:
    pool: Pool = request.app.state.pool
    settings: Settings = request.app.state.settings
    async with pool.connection() as conn:
        return TelemetryView(
            sharing=await usage.sharing(conn), fields=usage.FIELDS,
            report=await usage.report(conn, settings),
        )  # fmt: skip


@telemetry_router.get("", response_model=TelemetryView, summary="Usage counts and the switch")
async def get_telemetry(request: Request) -> TelemetryView:
    return await _view(request)


@telemetry_router.put(
    "", response_model=TelemetryView, summary="Turn sharing usage counts on or off"
)
async def set_telemetry(body: TelemetryUpdate, request: Request) -> TelemetryView:
    pool: Pool = request.app.state.pool
    async with pool.connection() as conn, conn.transaction():
        was = await usage.sharing(conn)
        await usage.set_sharing(conn, body.sharing)
        await AuditLog(conn).record(
            "usage_sharing.changed", "setting", "usage_sharing",
            before={"sharing": was}, after={"sharing": body.sharing},
        )  # fmt: skip
    return await _view(request)

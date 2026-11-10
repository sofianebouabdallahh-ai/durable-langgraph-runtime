"""Notifications, as delivered (phase H4).

    GET /notifications   whether a webhook is set up (its host only: a URL can carry a
                         token), and the latest notifications with how their delivery went

Read only: what `notify` queues is sent by the workers (notifications/delivery.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from agent_runtime.config import Settings
from agent_runtime.db import Pool

notifications_router = APIRouter(tags=["notifications"])


def _pool(request: Request) -> Pool:
    pool: Pool = request.app.state.pool
    return pool


PoolDep = Annotated[Pool, Depends(_pool)]
Status = Literal["pending", "sending", "delivered", "failed", "skipped"]


class NotificationView(BaseModel):
    id: str = Field(description="The notification's id, as the chat shows it")
    to: str
    message: str = Field(description="Its first 300 characters")
    agent: str | None
    status: Status
    attempts: int
    last_status: int | None = Field(description="The webhook's last HTTP status")
    last_error: str | None
    created_at: datetime
    delivered_at: datetime | None


class NotificationsView(BaseModel):
    webhook: str | None = Field(description="The webhook's host, if one is set up")
    signed: bool = Field(description="Deliveries carry a webhook-signature")
    notifications: list[NotificationView]


@notifications_router.get(
    "/notifications",
    response_model=NotificationsView,
    summary="The latest notifications and their delivery",
)
async def list_notifications(
    request: Request, pool: PoolDep, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> NotificationsView:
    settings: Settings = request.app.state.settings
    url = settings.notify_webhook_url.strip()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT n.key, n.recipient, left(n.message, 300) AS message, r.agent_name,
                   d.status, d.attempts, d.last_status, d.last_error, n.created_at,
                   d.delivered_at
            FROM outbox_notifications n
            JOIN notification_deliveries d USING (key)
            JOIN runs r ON r.id = n.run_id
            ORDER BY n.created_at DESC LIMIT %s
            """,
            (limit,),
        )
        rows = await cur.fetchall()
    return NotificationsView(
        webhook=urlsplit(url).hostname if url else None,
        signed=settings.notify_webhook_secret is not None,
        notifications=[
            NotificationView(
                id=r["key"][:16], to=r["recipient"], message=r["message"],
                agent=r["agent_name"], status=r["status"], attempts=r["attempts"],
                last_status=r["last_status"], last_error=r["last_error"],
                created_at=r["created_at"], delivered_at=r["delivered_at"],
            )
            for r in rows
        ],
    )  # fmt: skip

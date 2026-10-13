"""Kill switch state (R14.18), stored in Postgres so every replica and worker sees it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agent_runtime.db import Conn


@dataclass(frozen=True, slots=True)
class AdminState:
    paused: bool
    reason: str | None
    updated_at: datetime


class AdminRepository:
    def __init__(self, conn: Conn) -> None:
        self._conn = conn

    async def get(self) -> AdminState:
        cur = await self._conn.execute("SELECT paused, reason, updated_at FROM admin_state")
        row = await cur.fetchone()
        if row is None:  # migration 0002 inserts the single row
            raise RuntimeError("admin_state row missing; run `runtime db upgrade`")
        return AdminState(row["paused"], row["reason"], row["updated_at"])

    async def set_paused(self, paused: bool, reason: str | None = None) -> AdminState:
        cur = await self._conn.execute(
            "UPDATE admin_state SET paused = %s, reason = %s, updated_at = now() "
            "RETURNING paused, reason, updated_at",
            (paused, reason if paused else None),
        )
        row = await cur.fetchone()
        if row is None:
            raise RuntimeError("admin_state row missing; run `runtime db upgrade`")
        return AdminState(row["paused"], row["reason"], row["updated_at"])

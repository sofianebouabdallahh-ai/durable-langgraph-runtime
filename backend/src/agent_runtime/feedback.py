"""👍 / 👎 on a reply (phase L7d): one rating per turn, with an optional reason.

Stored with the turn's agent and version, so Activity can show how each agent is doing,
and so a later phase can turn rated replies into evaluation sets. A rating can be
changed or taken back.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from agent_runtime.db import Conn

Rating = Literal["up", "down"]
_VALUE: dict[Rating, int] = {"up": 1, "down": -1}


class NotRatable(Exception):
    """Only a finished chat turn can be rated."""


@dataclass(frozen=True, slots=True)
class Feedback:
    run_id: uuid.UUID
    rating: Rating
    reason: str | None
    agent_name: str | None
    agent_version: int | None
    updated_at: datetime


class FeedbackRepository:
    def __init__(self, conn: Conn) -> None:
        self._conn = conn

    async def get(self, run_id: uuid.UUID) -> Feedback | None:
        cur = await self._conn.execute("SELECT * FROM reply_feedback WHERE run_id = %s", (run_id,))
        row = await cur.fetchone()
        return _feedback(row) if row else None

    async def rate(self, run_id: uuid.UUID, rating: Rating, reason: str | None) -> Feedback:
        """Set (or change) the rating of a finished turn. LookupError: no such run;
        NotRatable: not a chat turn, or still going."""
        cur = await self._conn.execute(
            "SELECT kind, status, session_id, agent_name, agent_version FROM runs WHERE id = %s",
            (run_id,),
        )
        run = await cur.fetchone()
        if run is None:
            raise LookupError(f"no run {run_id}")
        if run["kind"] != "turn" or run["status"] not in ("completed", "failed", "cancelled"):
            raise NotRatable("only a finished reply can be rated")
        cur = await self._conn.execute(
            """
            INSERT INTO reply_feedback (run_id, session_id, agent_name, agent_version, rating,
                                        reason)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id) DO UPDATE SET rating = EXCLUDED.rating,
                                               reason = EXCLUDED.reason, updated_at = now()
            RETURNING *
            """,
            (run_id, run["session_id"], run["agent_name"], run["agent_version"],
             _VALUE[rating], (reason or "").strip()[:500] or None),
        )  # fmt: skip
        row = await cur.fetchone()
        assert row is not None
        return _feedback(row)

    async def clear(self, run_id: uuid.UUID) -> None:
        await self._conn.execute("DELETE FROM reply_feedback WHERE run_id = %s", (run_id,))


def _feedback(row: dict[str, object]) -> Feedback:
    return Feedback(
        run_id=row["run_id"],  # type: ignore[arg-type]
        rating="up" if row["rating"] == 1 else "down",
        reason=row["reason"],  # type: ignore[arg-type]
        agent_name=row["agent_name"],  # type: ignore[arg-type]
        agent_version=row["agent_version"],  # type: ignore[arg-type]
        updated_at=row["updated_at"],  # type: ignore[arg-type]
    )

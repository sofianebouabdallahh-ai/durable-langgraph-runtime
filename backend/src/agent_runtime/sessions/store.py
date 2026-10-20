"""Sessions and their transcript (CR-001 R12.1, R12.3): `sessions`, `session_messages`.

Rules:
- **Append-only**, `seq` strictly increasing per session: allocated from
  `sessions.last_seq` under the session's row lock, in the writer's transaction.
- **Deterministic ids**: a message that already exists (same `message_id`) is
  skipped *before* a seq is allocated, so a re-produced superstep writes nothing
  and leaves no gap.
- **Fenced**: worker writes carry the run's epoch (checked by the caller's
  `check_fence` and by the database trigger); API writes carry none.
- Lock order: the run row (fence) before the session row, everywhere.

Like RunRepository, it records what it wrote (`created`) so callers publish
after COMMIT.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from agent_runtime.db import Conn
from agent_runtime.ids import new_id

MessageType = Literal[
    "user", "assistant", "tool_call", "tool_result", "interrupt", "approval", "error", "system"
]
Role = Literal["user", "assistant", "tool", "system"]
ROLE_OF: dict[str, Role] = {
    "user": "user", "assistant": "assistant", "tool_call": "assistant", "tool_result": "tool",
    "interrupt": "system", "approval": "user", "error": "system", "system": "system",
}  # fmt: skip


def message_id(run_id: uuid.UUID, node: str, index: int | str, type: str) -> str:
    """R12.3: sha256(run_id · node · message_index · type)."""
    return hashlib.sha256(f"{run_id}·{node}·{index}·{type}".encode()).hexdigest()


class SessionNotFound(LookupError):
    def __init__(self, session_id: uuid.UUID) -> None:
        super().__init__(f"session {session_id} not found")
        self.session_id = session_id


class SessionArchived(Exception):
    def __init__(self, session_id: uuid.UUID) -> None:
        super().__init__(f"session {session_id} is archived; it accepts no new turns")
        self.session_id = session_id


class TurnActive(Exception):
    """R12.2: one non-terminal run per session."""

    def __init__(self, session_id: uuid.UUID, run_id: uuid.UUID, status: str) -> None:
        super().__init__(f"session {session_id} has an active turn ({run_id}, {status})")
        self.session_id = session_id
        self.run_id = run_id
        self.status = status


class NoActiveTurn(Exception):
    def __init__(self, session_id: uuid.UUID) -> None:
        super().__init__(f"session {session_id} has no active turn")
        self.session_id = session_id


@dataclass(frozen=True, slots=True)
class Session:
    id: uuid.UUID
    graph_name: str
    agent_name: str | None
    title: str | None
    status: Literal["active", "archived"]
    last_seq: int
    tokens: int
    cost: float
    summary: str | None
    created_at: datetime
    last_activity_at: datetime
    ended_at: datetime | None
    active_run_id: uuid.UUID | None = None
    active_run_status: str | None = None
    playground_of: uuid.UUID | None = None  # a test chat for this agent's draft (L3a)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Session:
        return cls(
            id=row["id"], graph_name=row["graph_name"], agent_name=row["agent_name"],
            title=row["title"], status=row["status"], last_seq=row["last_seq"],
            tokens=row["tokens"], cost=float(row["cost"]), summary=row["summary"],
            created_at=row["created_at"], last_activity_at=row["last_activity_at"],
            ended_at=row["ended_at"], active_run_id=row.get("active_run_id"),
            active_run_status=row.get("active_run_status"),
            playground_of=row.get("playground_of"),
        )  # fmt: skip


@dataclass(frozen=True, slots=True)
class Message:
    session_id: uuid.UUID
    seq: int
    message_id: str
    run_id: uuid.UUID | None
    epoch: int | None
    type: MessageType
    role: Role
    content: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Message:
        return cls(
            session_id=row["session_id"], seq=row["seq"], message_id=row["message_id"],
            run_id=row["run_id"], epoch=row["epoch"], type=row["type"], role=row["role"],
            content=row["content"], created_at=row["created_at"],
        )  # fmt: skip

    def view(self) -> dict[str, Any]:
        return {
            "seq": self.seq, "message_id": self.message_id,
            "run_id": str(self.run_id) if self.run_id else None, "type": self.type,
            "role": self.role, "content": self.content, "created_at": self.created_at.isoformat(),
        }  # fmt: skip


@dataclass(frozen=True, slots=True)
class NewMessage:
    message_id: str
    type: MessageType
    content: dict[str, Any]


_SESSION = """
    s.id, s.graph_name, s.agent_name, s.title, s.status, s.last_seq, s.tokens, s.cost,
    s.summary, s.created_at, s.last_activity_at, s.ended_at, s.playground_of,
    r.id AS active_run_id, r.status AS active_run_status
"""
_FROM = """
    FROM sessions s LEFT JOIN runs r
      ON r.session_id = s.id AND r.status NOT IN ('completed', 'failed', 'cancelled')
"""
_MESSAGE = "session_id, seq, message_id, run_id, epoch, type, role, content, created_at"


class SessionRepository:
    def __init__(self, conn: Conn) -> None:
        self._conn = conn
        self.created: list[Message] = []  # publish after COMMIT

    async def create(
        self,
        *,
        graph_name: str,
        agent_name: str | None,
        title: str | None,
        playground_of: uuid.UUID | None = None,
    ) -> Session:
        cur = await self._conn.execute(
            "INSERT INTO sessions (id, graph_name, agent_name, title, playground_of) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (new_id(), graph_name, agent_name, title, playground_of),
        )
        row = await cur.fetchone()
        assert row is not None
        return await self.get(row["id"])

    async def get(self, session_id: uuid.UUID) -> Session:
        cur = await self._conn.execute(f"SELECT {_SESSION} {_FROM} WHERE s.id = %s", (session_id,))
        row = await cur.fetchone()
        if row is None:
            raise SessionNotFound(session_id)
        return Session.from_row(row)

    async def latest_test_chat(self, agent_id: uuid.UUID) -> Session | None:
        """The agent's most recent test chat still open (the Studio shows it again)."""
        cur = await self._conn.execute(
            f"SELECT {_SESSION} {_FROM} WHERE s.playground_of = %s AND s.status = 'active' "
            "ORDER BY s.created_at DESC LIMIT 1",
            (agent_id,),
        )
        row = await cur.fetchone()
        return Session.from_row(row) if row else None

    async def page(
        self, *, status: str | None, limit: int, before: datetime | None = None
    ) -> list[Session]:
        """Newest activity first (R12.10); `before` pages by last_activity_at."""
        cur = await self._conn.execute(
            f"""
            SELECT {_SESSION} {_FROM}
            WHERE (%(status)s::text IS NULL OR s.status = %(status)s)
              AND (%(before)s::timestamptz IS NULL OR s.last_activity_at < %(before)s)
              AND s.playground_of IS NULL  -- test chats live in the Studio, not the list
            ORDER BY s.last_activity_at DESC, s.id DESC LIMIT %(limit)s
            """,
            {"status": status, "before": before, "limit": limit},
        )
        return [Session.from_row(r) for r in await cur.fetchall()]

    async def lock(self, session_id: uuid.UUID) -> Session:
        """Take the session's row lock (serialises its writers) and return it."""
        cur = await self._conn.execute(
            "SELECT id FROM sessions WHERE id = %s FOR NO KEY UPDATE", (session_id,)
        )
        if await cur.fetchone() is None:
            raise SessionNotFound(session_id)
        return await self.get(session_id)

    async def rename(self, session_id: uuid.UUID, title: str) -> None:
        await self._conn.execute(
            "UPDATE sessions SET title = %s WHERE id = %s", (title, session_id)
        )

    async def archive(self, session_id: uuid.UUID) -> bool:
        """active → archived, exactly once (the caller then enqueues session_end)."""
        cur = await self._conn.execute(
            "UPDATE sessions SET status = 'archived', ended_at = now() "
            "WHERE id = %s AND status = 'active' RETURNING id",
            (session_id,),
        )
        return await cur.fetchone() is not None

    async def set_summary(self, session_id: uuid.UUID, summary: str) -> None:
        await self._conn.execute(
            "UPDATE sessions SET summary = %s WHERE id = %s", (summary, session_id)
        )

    async def idle(self, older_than_s: float, limit: int = 100) -> list[uuid.UUID]:
        """Active sessions idle past the TTL with no active turn (R15.6)."""
        cur = await self._conn.execute(
            f"""
            SELECT s.id {_FROM}
            WHERE s.status = 'active' AND r.id IS NULL
              AND s.last_activity_at < now() - make_interval(secs => %s)
            ORDER BY s.last_activity_at LIMIT %s
            """,
            (older_than_s, limit),
        )
        return [r["id"] for r in await cur.fetchall()]

    async def append(
        self,
        session_id: uuid.UUID,
        messages: list[NewMessage],
        *,
        run_id: uuid.UUID | None,
        epoch: int | None,
    ) -> list[Message]:
        """Append the messages that don't exist yet, in order. Must run inside the
        caller's transaction; takes the session's row lock."""
        if self._conn.info.transaction_status != TransactionStatus.INTRANS:
            raise RuntimeError("append must be called inside a transaction")
        if not messages:
            return []
        await self.lock(session_id)
        cur = await self._conn.execute(
            "SELECT message_id FROM session_messages WHERE message_id = ANY(%s)",
            ([m.message_id for m in messages],),
        )
        existing = {r["message_id"] for r in await cur.fetchall()}
        written: list[Message] = []
        for m in messages:
            if m.message_id in existing:
                continue
            cur = await self._conn.execute(
                "UPDATE sessions SET last_seq = last_seq + 1, last_activity_at = now() "
                "WHERE id = %s RETURNING last_seq",
                (session_id,),
            )
            seq_row = await cur.fetchone()
            assert seq_row is not None
            cur = await self._conn.execute(
                f"""
                INSERT INTO session_messages
                    (session_id, seq, message_id, run_id, epoch, type, role, content)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {_MESSAGE}
                """,
                (session_id, seq_row["last_seq"], m.message_id, run_id, epoch, m.type,
                 ROLE_OF[m.type], Jsonb(m.content)),
            )  # fmt: skip
            row = await cur.fetchone()
            assert row is not None
            written.append(Message.from_row(row))
        self.created.extend(written)
        return written

    async def message(self, session_id: uuid.UUID, message_id: str) -> Message | None:
        cur = await self._conn.execute(
            "SELECT * FROM session_messages WHERE session_id = %s AND message_id = %s",
            (session_id, message_id),
        )
        row = await cur.fetchone()
        return Message.from_row(row) if row else None

    async def messages(
        self, session_id: uuid.UUID, *, after_seq: int = 0, limit: int = 100
    ) -> list[Message]:
        cur = await self._conn.execute(
            f"SELECT {_MESSAGE} FROM session_messages WHERE session_id = %s AND seq > %s "
            "ORDER BY seq LIMIT %s",
            (session_id, after_seq, limit),
        )
        return [Message.from_row(r) for r in await cur.fetchall()]

    async def recent_user_messages(self, session_id: uuid.UUID, *, within_s: float) -> int:
        cur = await self._conn.execute(
            "SELECT count(*) AS n FROM session_messages WHERE session_id = %s AND type = 'user' "
            "AND created_at > now() - make_interval(secs => %s)",
            (session_id, within_s),
        )
        row = await cur.fetchone()
        return int(row["n"]) if row else 0

    async def add_usage(self, session_id: uuid.UUID, tokens: int, cost: float) -> None:
        await self._conn.execute(
            "UPDATE sessions SET tokens = tokens + %s, cost = cost + %s WHERE id = %s",
            (tokens, cost, session_id),
        )

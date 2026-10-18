"""Persistence for user agents and their versions (CR-006 R17.1). Pattern: Repository.

The version lifecycle (draft → published → archived) is enforced twice: here, by the
only operations offered, and in the database, by a trigger that freezes a published
version (migration 0010). "Tested" is derived, never stored: a completed test-chat
turn pinned to the draft's bundle hash.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from psycopg.types.json import Jsonb

from agent_runtime.db import Conn
from agent_runtime.ids import new_id

State = Literal["draft", "published", "archived"]
WORKSPACE = "local"  # the local release has one workspace; the beta adds tenancy (P7)


class AgentNotFound(LookupError):
    pass


class NameTaken(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StoredAgent:
    id: uuid.UUID
    name: str
    created_at: datetime
    archived_at: datetime | None


@dataclass(frozen=True, slots=True)
class Version:
    agent_id: uuid.UUID
    number: int
    state: State
    document: dict[str, Any]
    bundle_hash: str | None
    changelog: str | None
    created_at: datetime
    published_at: datetime | None
    skill_lock: dict[str, str] | None = None  # skill name → version hash, set at publish

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Version:
        return cls(
            agent_id=row["agent_id"], number=row["number"], state=row["state"],
            document=row["document"], bundle_hash=row["bundle_hash"],
            changelog=row["changelog"], created_at=row["created_at"],
            published_at=row["published_at"], skill_lock=row["skill_lock"],
        )  # fmt: skip


_VERSION = (
    "agent_id, number, state, document, bundle_hash, changelog, created_at, published_at, "
    "skill_lock"
)


class AgentStore:
    def __init__(self, conn: Conn) -> None:
        self._conn = conn

    # ------------------------------------------------------------------ agents

    async def create(self, name: str, document: dict[str, Any]) -> tuple[StoredAgent, Version]:
        agent_id = new_id()
        cur = await self._conn.execute(
            "INSERT INTO agents (id, workspace_id, name) VALUES (%s, %s, %s) "
            "ON CONFLICT (workspace_id, name) DO NOTHING "
            "RETURNING id, name, created_at, archived_at",
            (agent_id, WORKSPACE, name),
        )
        row = await cur.fetchone()
        if row is None:
            raise NameTaken(name)
        draft = await self._insert_version(agent_id, 1, document)
        return StoredAgent(**row), draft

    async def get(self, agent_id: uuid.UUID) -> StoredAgent:
        cur = await self._conn.execute(
            "SELECT id, name, created_at, archived_at FROM agents WHERE id = %s", (agent_id,)
        )
        row = await cur.fetchone()
        if row is None:
            raise AgentNotFound(str(agent_id))
        return StoredAgent(**row)

    async def by_name(self, name: str) -> StoredAgent | None:
        cur = await self._conn.execute(
            "SELECT id, name, created_at, archived_at FROM agents "
            "WHERE workspace_id = %s AND name = %s",
            (WORKSPACE, name),
        )
        row = await cur.fetchone()
        return StoredAgent(**row) if row else None

    async def all(self) -> list[StoredAgent]:
        cur = await self._conn.execute(
            "SELECT id, name, created_at, archived_at FROM agents WHERE workspace_id = %s "
            "ORDER BY created_at DESC",
            (WORKSPACE,),
        )
        return [StoredAgent(**r) for r in await cur.fetchall()]

    async def archive(self, agent_id: uuid.UUID) -> None:
        await self._conn.execute(
            "UPDATE agents SET archived_at = coalesce(archived_at, now()) WHERE id = %s",
            (agent_id,),
        )

    # ---------------------------------------------------------------- versions

    async def versions(self, agent_id: uuid.UUID) -> list[Version]:
        cur = await self._conn.execute(
            f"SELECT {_VERSION} FROM agent_versions WHERE agent_id = %s ORDER BY number DESC",
            (agent_id,),
        )
        return [Version.from_row(r) for r in await cur.fetchall()]

    async def draft(self, agent_id: uuid.UUID) -> Version | None:
        cur = await self._conn.execute(
            f"SELECT {_VERSION} FROM agent_versions WHERE agent_id = %s AND state = 'draft'",
            (agent_id,),
        )
        row = await cur.fetchone()
        return Version.from_row(row) if row else None

    async def published(self, agent_id: uuid.UUID) -> Version | None:
        """The current version: the newest published one."""
        cur = await self._conn.execute(
            f"SELECT {_VERSION} FROM agent_versions WHERE agent_id = %s AND state = 'published' "
            "ORDER BY number DESC LIMIT 1",
            (agent_id,),
        )
        row = await cur.fetchone()
        return Version.from_row(row) if row else None

    async def version(self, agent_id: uuid.UUID, number: int) -> Version | None:
        cur = await self._conn.execute(
            f"SELECT {_VERSION} FROM agent_versions WHERE agent_id = %s AND number = %s",
            (agent_id, number),
        )
        row = await cur.fetchone()
        return Version.from_row(row) if row else None

    async def open_draft(self, agent_id: uuid.UUID, document: dict[str, Any]) -> Version:
        """The agent's draft, creating it (from `document`) if there is none."""
        if (existing := await self.draft(agent_id)) is not None:
            return existing
        cur = await self._conn.execute(
            "SELECT coalesce(max(number), 0) + 1 AS n FROM agent_versions WHERE agent_id = %s",
            (agent_id,),
        )
        row = await cur.fetchone()
        assert row is not None
        return await self._insert_version(agent_id, row["n"], document)

    async def save_draft(
        self, agent_id: uuid.UUID, document: dict[str, Any], bundle_hash: str | None
    ) -> Version:
        cur = await self._conn.execute(
            f"UPDATE agent_versions SET document = %s, bundle_hash = %s "
            f"WHERE agent_id = %s AND state = 'draft' RETURNING {_VERSION}",
            (Jsonb(document), bundle_hash, agent_id),
        )
        row = await cur.fetchone()
        if row is None:
            raise AgentNotFound(f"{agent_id} has no draft")
        return Version.from_row(row)

    async def publish(
        self,
        agent_id: uuid.UUID,
        changelog: str | None,
        bundle_hash: str,
        skill_lock: dict[str, str],
    ) -> Version:
        """Freeze the draft: its content, the bundle it runs and the skill versions it
        locks (the AC47 trigger keeps all three from changing afterwards)."""
        cur = await self._conn.execute(
            f"UPDATE agent_versions SET state = 'published', published_at = now(), changelog = %s, "
            f"bundle_hash = %s, skill_lock = %s "
            f"WHERE agent_id = %s AND state = 'draft' RETURNING {_VERSION}",
            (changelog, bundle_hash, Jsonb(skill_lock), agent_id),
        )
        row = await cur.fetchone()
        if row is None:
            raise AgentNotFound(f"{agent_id} has no draft")
        return Version.from_row(row)

    async def discard_draft(self, agent_id: uuid.UUID) -> None:
        await self._conn.execute(
            "DELETE FROM agent_versions WHERE agent_id = %s AND state = 'draft'", (agent_id,)
        )

    async def tested(self, agent_id: uuid.UUID, bundle_hash: str) -> bool:
        """A test-chat turn on exactly this definition completed (R17.3)."""
        cur = await self._conn.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM runs r JOIN sessions s ON s.id = r.session_id
                WHERE s.playground_of = %s AND r.agent_hash = %s AND r.status = 'completed'
            ) AS tested
            """,
            (agent_id, bundle_hash),
        )
        row = await cur.fetchone()
        return bool(row and row["tested"])

    async def _insert_version(
        self, agent_id: uuid.UUID, number: int, document: dict[str, Any]
    ) -> Version:
        cur = await self._conn.execute(
            f"INSERT INTO agent_versions (agent_id, number, state, document) "
            f"VALUES (%s, %s, 'draft', %s) RETURNING {_VERSION}",
            (agent_id, number, Jsonb(document)),
        )
        row = await cur.fetchone()
        assert row is not None
        return Version.from_row(row)

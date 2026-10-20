"""Skills in Postgres (migration 0012): the library, its versions, their files.

Pattern: content-addressed storage (like agent bundles). A version's key is its
content hash, files are keyed by their sha256, and both are insert-only: the same
content is stored once, and nothing written can change (grants enforce it).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from psycopg.types.json import Jsonb

from agent_runtime.db import Conn
from agent_runtime.skills.scan import ScanReport
from agent_runtime.skills.spec import SkillContent, SkillFile

WORKSPACE = "local"  # one user locally; the beta scopes rows by workspace (CR-006 R19)
Trust = Literal["private", "built_in"]
Origin = Literal["created", "uploaded", "imported", "built_in"]


class SkillNotFound(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class Skill:
    id: uuid.UUID
    name: str
    trust: Trust
    origin: Origin
    current_hash: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Skill:
        return cls(**{k: row[k] for k in cls.__slots__})


@dataclass(frozen=True, slots=True)
class SkillVersion:
    hash: str
    name: str
    description: str
    instructions: str
    meta: dict[str, Any]
    files: list[dict[str, Any]]  # the manifest: path, sha256, size, kind
    scan: dict[str, Any]  # {status, findings}
    created_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> SkillVersion:
        return cls(**{k: row[k] for k in cls.__slots__})

    def entry(self, path: str) -> dict[str, Any] | None:
        return next((f for f in self.files if f["path"] == path), None)


_SKILL = "id, name, trust, origin, current_hash, created_at, updated_at, archived_at"
# The newest check of a version: a later rules version's, else the one stored with it.
_LATEST_SCAN = (
    "coalesce((SELECT sc.scan FROM skill_scans sc WHERE sc.hash = skill_versions.hash "
    "ORDER BY sc.rules DESC LIMIT 1), skill_versions.scan) AS scan"
)
_VERSION = f"hash, name, description, instructions, meta, files, {_LATEST_SCAN}, created_at"


class SkillStore:
    def __init__(self, conn: Conn) -> None:
        self._conn = conn

    # ---------------------------------------------------------------- library

    async def all(self, *, archived: bool = False) -> list[Skill]:
        cur = await self._conn.execute(
            f"SELECT {_SKILL} FROM skills WHERE workspace_id = %s "
            "AND (%s OR archived_at IS NULL) ORDER BY trust DESC, name",
            (WORKSPACE, archived),
        )
        return [Skill.from_row(r) for r in await cur.fetchall()]

    async def get(self, skill_id: uuid.UUID) -> Skill:
        cur = await self._conn.execute(f"SELECT {_SKILL} FROM skills WHERE id = %s", (skill_id,))
        row = await cur.fetchone()
        if row is None:
            raise SkillNotFound(str(skill_id))
        return Skill.from_row(row)

    async def by_name(self, name: str, *, archived: bool = False) -> Skill | None:
        cur = await self._conn.execute(
            f"SELECT {_SKILL} FROM skills WHERE workspace_id = %s AND name = %s "
            "AND (%s OR archived_at IS NULL)",
            (WORKSPACE, name, archived),
        )
        row = await cur.fetchone()
        return Skill.from_row(row) if row else None

    async def by_names(self, names: Iterable[str]) -> dict[str, Skill]:
        """The live skills with these names (archived ones are left out)."""
        cur = await self._conn.execute(
            f"SELECT {_SKILL} FROM skills WHERE workspace_id = %s AND name = ANY(%s) "
            "AND archived_at IS NULL",
            (WORKSPACE, list(names)),
        )
        return {r["name"]: Skill.from_row(r) for r in await cur.fetchall()}

    async def insert(
        self, skill_id: uuid.UUID, name: str, trust: Trust, origin: Origin, current_hash: str
    ) -> Skill:
        cur = await self._conn.execute(
            f"""
            INSERT INTO skills (id, workspace_id, name, trust, origin, current_hash)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING {_SKILL}
            """,
            (skill_id, WORKSPACE, name, trust, origin, current_hash),
        )
        row = await cur.fetchone()
        assert row is not None
        return Skill.from_row(row)

    async def point(self, skill_id: uuid.UUID, current_hash: str) -> Skill:
        """Make `current_hash` the skill's current version (and bring it back if archived:
        only built-ins are re-pointed that way, by the startup sync)."""
        cur = await self._conn.execute(
            f"UPDATE skills SET current_hash = %s, updated_at = now() WHERE id = %s "
            f"RETURNING {_SKILL}",
            (current_hash, skill_id),
        )
        row = await cur.fetchone()
        if row is None:
            raise SkillNotFound(str(skill_id))
        return Skill.from_row(row)

    async def archive(self, skill_id: uuid.UUID) -> None:
        await self._conn.execute(
            "UPDATE skills SET archived_at = now(), updated_at = now() "
            "WHERE id = %s AND archived_at IS NULL",
            (skill_id,),
        )

    # ---------------------------------------------------------------- versions

    async def put_version(self, content: SkillContent, report: ScanReport) -> str:
        """Store a version and its files if new; return its hash either way."""
        digest = content.content_hash()
        for f in content.files:
            await self._conn.execute(
                "INSERT INTO skill_files (sha256, data, size) VALUES (%s, %s, %s) "
                "ON CONFLICT (sha256) DO NOTHING",
                (f.sha256, f.data, len(f.data)),
            )
        await self._conn.execute(
            """
            INSERT INTO skill_versions (hash, name, description, instructions, meta, files, scan)
            VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (hash) DO NOTHING
            """,
            (
                digest,
                content.name,
                content.description,
                content.instructions,
                Jsonb(dict(content.meta)),
                Jsonb(content.manifest()),
                Jsonb(report.as_json()),
            ),
        )
        return digest

    async def version(self, digest: str) -> SkillVersion:
        cur = await self._conn.execute(
            f"SELECT {_VERSION} FROM skill_versions WHERE hash = %s", (digest,)
        )
        row = await cur.fetchone()
        if row is None:
            raise SkillNotFound(digest)
        return SkillVersion.from_row(row)

    async def versions(self, digests: Iterable[str]) -> dict[str, SkillVersion]:
        cur = await self._conn.execute(
            f"SELECT {_VERSION} FROM skill_versions WHERE hash = ANY(%s)", (list(digests),)
        )
        return {r["hash"]: SkillVersion.from_row(r) for r in await cur.fetchall()}

    async def checked_before(self, rules: int) -> list[str]:
        """The versions last checked with older rules (stored scans before RULES 2 have
        no `rules`: 1)."""
        cur = await self._conn.execute(
            "SELECT v.hash FROM skill_versions v WHERE coalesce("
            "(SELECT max(sc.rules) FROM skill_scans sc WHERE sc.hash = v.hash), "
            "(v.scan->>'rules')::int, 1) < %s ORDER BY v.created_at",
            (rules,),
        )
        return [r["hash"] for r in await cur.fetchall()]

    async def add_scan(self, digest: str, report: ScanReport) -> None:
        """A newer check of a stored version (append-only: the version stays as it was)."""
        await self._conn.execute(
            "INSERT INTO skill_scans (hash, rules, scan) VALUES (%s, %s, %s) "
            "ON CONFLICT (hash, rules) DO NOTHING",  # another replica checked it first
            (digest, report.as_json()["rules"], Jsonb(report.as_json())),
        )

    async def file(self, sha256: str) -> bytes:
        cur = await self._conn.execute("SELECT data FROM skill_files WHERE sha256 = %s", (sha256,))
        row = await cur.fetchone()
        if row is None:
            raise SkillNotFound(sha256)
        return bytes(row["data"])

    async def content(self, digest: str) -> SkillContent:
        """A version with its files' bytes: what Download and edits start from."""
        v = await self.version(digest)
        files = tuple([SkillFile(f["path"], await self.file(f["sha256"])) for f in v.files])
        return SkillContent(v.name, v.description, v.instructions, v.meta, files)

    async def used_by(self) -> dict[str, list[str]]:
        """Skill name → the agents whose current draft or published version names it."""
        cur = await self._conn.execute(
            """
            SELECT DISTINCT s.name AS skill, a.name AS agent
            FROM agents a
            JOIN agent_versions v ON v.agent_id = a.id AND v.state IN ('draft', 'published')
            CROSS JOIN LATERAL (
                SELECT jsonb_array_elements_text(COALESCE(v.document -> 'skills', '[]'))
                UNION
                SELECT jsonb_array_elements_text(COALESCE(h -> 'skills', '[]'))
                FROM jsonb_array_elements(COALESCE(v.document -> 'helpers', '[]')) AS h
            ) AS s (name)
            WHERE a.archived_at IS NULL AND a.workspace_id = %s
            ORDER BY 1, 2
            """,
            (WORKSPACE,),
        )
        out: dict[str, list[str]] = {}
        for row in await cur.fetchall():
            out.setdefault(row["skill"], []).append(row["agent"])
        return out

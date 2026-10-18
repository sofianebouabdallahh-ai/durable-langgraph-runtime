"""Snapshot agent definitions into Postgres (R15.4).

Pattern: content-addressed storage. The row key is the hash of the resolved
definition, so storing the same definition twice is a no-op and a run's
`agent_hash` pins exactly what it executes.
"""

from dataclasses import dataclass
from typing import Any

from psycopg.types.json import Jsonb

from agent_runtime.agents.loader import canonical_content, content_hash
from agent_runtime.agents.schema import (
    AgentDefinition,
    MainAgentFrontmatter,
    SubAgentDefinition,
    SubAgentFrontmatter,
)
from agent_runtime.db import Conn
from agent_runtime.skills.binding import SkillSet, manifest
from agent_runtime.skills.store import SkillStore, SkillVersion


class AgentDefinitionRepository:
    def __init__(self, conn: Conn) -> None:
        self._conn = conn

    async def snapshot(self, defn: AgentDefinition | SubAgentDefinition) -> str:
        """Store `defn` if new; return its hash either way."""
        content = canonical_content(defn)
        digest = content_hash(content)
        await self._conn.execute(
            """
            INSERT INTO agent_definitions (hash, name, version, kind, content)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (hash) DO NOTHING
            """,
            (digest, defn.id, defn.frontmatter.version, defn.kind, Jsonb(content)),
        )
        return digest


class SnapshotMissing(LookupError):
    pass


def bundle_content(defn: AgentDefinition, skills: SkillSet | None = None) -> dict[str, Any]:
    """What a bundle stores: `{main: hash, helpers: [[name, hash], …], skills: [[owner,
    name, version], …]}`. Lists, because jsonb doesn't keep object key order and the
    order is part of the definition. `skills` only when there are any, so bundles from
    before skills keep their hashes."""
    content: dict[str, Any] = {
        "main": content_hash(canonical_content(defn)),
        "helpers": [[s.frontmatter.name, content_hash(canonical_content(s))]
                    for s in defn.subagents],
    }  # fmt: skip
    if skills and (entries := manifest(skills)):
        content["skills"] = entries
    return content


def bundle_digest(defn: AgentDefinition, skills: SkillSet | None = None) -> str:
    """The hash `snapshot_bundle` would return, computed without writing anything (the
    Studio asks it on every read: is this exact draft, with today's skills, tested?)."""
    return content_hash(bundle_content(defn, skills))


async def snapshot_bundle(conn: Conn, defn: AgentDefinition, skills: SkillSet | None = None) -> str:
    """Snapshot an agent with its helpers and its skill versions; return the bundle's
    hash (what a run pins)."""
    repo = AgentDefinitionRepository(conn)
    await repo.snapshot(defn)
    for sub in defn.subagents:
        await repo.snapshot(sub)
    content = bundle_content(defn, skills)
    digest = content_hash(content)
    await conn.execute(
        """
        INSERT INTO agent_definitions (hash, name, version, kind, content)
        VALUES (%s, %s, %s, 'bundle', %s)
        ON CONFLICT (hash) DO NOTHING
        """,
        (digest, defn.id, defn.frontmatter.version, Jsonb(content)),
    )
    return digest


@dataclass(frozen=True, slots=True)
class Bundle:
    definition: AgentDefinition
    skills: SkillSet


async def load_bundle(conn: Conn, digest: str) -> Bundle:
    """What a bundle pinned, rebuilt from its snapshots (no files, no Studio, no library:
    skill versions are immutable rows, so archiving a skill changes nothing here)."""
    bundle = await _content(conn, digest, "bundle")
    main = await _content(conn, str(bundle["main"]), "main")
    helpers = [await _content(conn, str(h), "sub") for _, h in bundle["helpers"]]
    definition = AgentDefinition(
        id=main["id"],
        frontmatter=MainAgentFrontmatter.model_validate(main["frontmatter"]),
        prompt=main["prompt"],
        subagents=tuple(
            SubAgentDefinition(
                id=h["id"],
                frontmatter=SubAgentFrontmatter.model_validate(h["frontmatter"]),
                prompt=h["prompt"],
            )
            for h in helpers
        ),
    )
    entries = bundle.get("skills") or []
    versions = await SkillStore(conn).versions(str(e[2]) for e in entries)
    skills: dict[str, tuple[SkillVersion, ...]] = {}
    for owner, _, version in entries:
        skills[str(owner)] = (*skills.get(str(owner), ()), versions[str(version)])
    return Bundle(definition, skills)


async def _content(conn: Conn, digest: str, kind: str) -> dict[str, Any]:
    cur = await conn.execute(
        "SELECT content FROM agent_definitions WHERE hash = %s AND kind = %s", (digest, kind)
    )
    row = await cur.fetchone()
    if row is None:
        raise SnapshotMissing(f"no {kind} snapshot {digest}")
    content: dict[str, Any] = row["content"]
    return content

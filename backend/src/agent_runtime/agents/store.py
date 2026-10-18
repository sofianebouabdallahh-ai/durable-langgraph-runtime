"""Snapshot agent definitions into Postgres (R15.4).

Pattern: content-addressed storage. The row key is the hash of the resolved
definition, so storing the same definition twice is a no-op and a run's
`agent_hash` pins exactly what it executes.
"""

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


async def snapshot_bundle(conn: Conn, defn: AgentDefinition) -> str:
    """Snapshot an agent with its helpers; return the bundle's hash (what a run pins).

    A bundle is `{main: hash, helpers: [[name, hash], …]}`: a list, because jsonb
    doesn't keep object key order and the helpers' order is part of the definition."""
    repo = AgentDefinitionRepository(conn)
    content: dict[str, Any] = {
        "main": await repo.snapshot(defn),
        "helpers": [[s.frontmatter.name, await repo.snapshot(s)] for s in defn.subagents],
    }
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


async def load_bundle(conn: Conn, digest: str) -> AgentDefinition:
    """The definition a bundle pinned, rebuilt from its snapshots (no files, no Studio)."""
    bundle = await _content(conn, digest, "bundle")
    main = await _content(conn, str(bundle["main"]), "main")
    helpers = [await _content(conn, str(h), "sub") for _, h in bundle["helpers"]]
    return AgentDefinition(
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


async def _content(conn: Conn, digest: str, kind: str) -> dict[str, Any]:
    cur = await conn.execute(
        "SELECT content FROM agent_definitions WHERE hash = %s AND kind = %s", (digest, kind)
    )
    row = await cur.fetchone()
    if row is None:
        raise SnapshotMissing(f"no {kind} snapshot {digest}")
    content: dict[str, Any] = row["content"]
    return content

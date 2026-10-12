"""Snapshot agent definitions into Postgres (R15.4).

Pattern: content-addressed storage. The row key is the hash of the resolved
definition, so storing the same definition twice is a no-op and a run's
`agent_hash` pins exactly what it executes.
"""

from psycopg.types.json import Jsonb

from agent_runtime.agents.loader import canonical_content, content_hash
from agent_runtime.agents.schema import AgentDefinition, SubAgentDefinition
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

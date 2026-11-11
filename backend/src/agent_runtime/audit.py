"""Who did what (phase L7d): an append-only audit trail.

    audit_events: at, actor, action, target (type, id), before, after, request_id, trace_id

Each change records its row **in its own transaction** (Unit of Work): the change and its
row commit together, or neither does. The API's database user can insert and read rows,
never update or delete them (migration 0020). The actor is `local` until Nuria has
accounts. Before and after hold what changed, never a secret: a key is recorded as set,
with its fingerprint, and everything goes through `redact()` as well.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from psycopg.types.json import Jsonb

from agent_runtime import logs, telemetry
from agent_runtime.db import Conn
from agent_runtime.ids import new_id
from agent_runtime.redaction import redact

Action = Literal[
    "approval.decided",
    "run.redriven",
    "kill_switch.on",
    "kill_switch.off",
    "agent.created",
    "agent.imported",
    "agent.restored",
    "agent.published",
    "agent.archived",
    "skill.created",
    "skill.updated",
    "skill.archived",
    "model_connection.added",
    "model_connection.changed",
    "model_connection.removed",
    "default_model.changed",
    "tool_settings.changed",
    "usage_sharing.changed",
    "mcp_server.added",
    "mcp_server.changed",
    "mcp_server.removed",
    "mcp_tool.enabled",
    "mcp_tool.disabled",
    "mcp_tool.approved_change",
    "memory.deleted",
    "memory.restored",
    "memory.cleared",
]
ACTOR = "local"  # one person per installation, until accounts (P7)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: uuid.UUID
    at: datetime
    actor: str
    action: str
    target_type: str
    target_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    request_id: str | None
    trace_id: str | None


class AuditLog:
    """Repository for `audit_events`, bound to the change's connection (and so to its
    transaction)."""

    def __init__(self, conn: Conn) -> None:
        self._conn = conn

    async def record(
        self,
        action: Action,
        target_type: str,
        target_id: object | None = None,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        bound = logs.fields()
        await self._conn.execute(
            """
            INSERT INTO audit_events (id, actor, action, target_type, target_id, before, after,
                                      request_id, trace_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                new_id(), ACTOR, action, target_type,
                None if target_id is None else str(target_id),
                None if before is None else Jsonb(redact(before)),
                None if after is None else Jsonb(redact(after)),
                bound.get("request_id"), bound.get("trace_id") or telemetry.run_trace_id(),
            ),
        )  # fmt: skip

    async def list(
        self,
        *,
        action: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        before: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Newest first; `before` pages back (its `at` is exclusive)."""
        cur = await self._conn.execute(
            """
            SELECT * FROM audit_events
            WHERE (%(action)s::text IS NULL OR action = %(action)s)
              AND (%(type)s::text IS NULL OR target_type = %(type)s)
              AND (%(id)s::text IS NULL OR target_id = %(id)s)
              AND (%(before)s::timestamptz IS NULL OR at < %(before)s)
            ORDER BY at DESC, id DESC
            LIMIT %(limit)s
            """,
            {"action": action, "type": target_type, "id": target_id, "before": before,
             "limit": limit},
        )  # fmt: skip
        return [AuditEvent(**row) for row in await cur.fetchall()]


def key_change(fingerprint: str | None) -> dict[str, Any]:
    """How a key appears in the trail: that one is set, and which (its fingerprint)."""
    return {"key": "set", "key_fingerprint": fingerprint} if fingerprint else {"key": None}

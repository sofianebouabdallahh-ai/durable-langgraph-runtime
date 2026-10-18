"""Anonymous usage counts, opt-in (phase L5, local-release §4.8).

Off by default. When the person turns it on (Settings → Privacy), the counts are
attached to the feedback reports *they* send, shown in full first. Nothing is sent
by itself: there is no server to send to until the hosted beta.

Every field is a version, a kind or a count: never a name, a title, a message, a
prompt, a key or a URL (docs/setup/testers.md lists them; a test checks that no
content string ends up here).

Pattern: Query object. The report is computed from the database on request, so
there is nothing to collect, store or forget.
"""

from __future__ import annotations

import os
import platform
from importlib import metadata
from typing import Any

from agent_runtime.config import Settings
from agent_runtime.db import Conn
from agent_runtime.models.connections import WORKSPACE

FIELDS = {
    "version": "Nuria's version",
    "deployment": "compose or kubernetes",
    "cpu": "the server's CPU architecture (e.g. arm64)",
    "model_provider": "the setup's model provider type (scripted, ollama, openai)",
    "connections": "model connections you added, by type",
    "chats": "chats, all time",
    "turns": "chat turns, all time",
    "turns_failed": "turns that failed, by reason (e.g. budget:tokens)",
    "days_active": "days with at least one turn",
    "agents": "agents you made",
    "agents_published": "agent versions you published",
    "skills": "skills you added (not the built-in ones)",
    "approvals": "approvals decided, by decision",
}


async def sharing(conn: Conn) -> bool:
    cur = await conn.execute(
        "SELECT share_usage FROM workspace_settings WHERE workspace_id = %s", (WORKSPACE,)
    )
    row = await cur.fetchone()
    return bool(row and row["share_usage"])


async def set_sharing(conn: Conn, enabled: bool) -> None:
    await conn.execute(
        """
        INSERT INTO workspace_settings (workspace_id, share_usage) VALUES (%s, %s)
        ON CONFLICT (workspace_id) DO UPDATE SET share_usage = EXCLUDED.share_usage,
                                                 updated_at = now()
        """,
        (WORKSPACE, enabled),
    )


async def _scalar(conn: Conn, sql: str) -> int:
    cur = await conn.execute(sql)
    row = await cur.fetchone()
    return int(next(iter(row.values()))) if row else 0


async def _by(conn: Conn, sql: str) -> dict[str, int]:
    cur = await conn.execute(sql)
    return {str(r["k"]): int(r["n"]) for r in await cur.fetchall()}


async def report(conn: Conn, settings: Settings) -> dict[str, Any]:
    """The counts, exactly as they would be shared."""
    try:
        version: str | None = metadata.version("durable-agent-runtime")
    except metadata.PackageNotFoundError:
        version = None
    return {
        "version": version,
        "deployment": "kubernetes" if os.environ.get("POD_NAMESPACE") else "compose",
        "cpu": platform.machine(),
        "model_provider": settings.model_provider,
        "connections": await _by(conn, "SELECT kind AS k, count(*) AS n FROM model_connections "
                                       "WHERE archived_at IS NULL GROUP BY kind"),
        "chats": await _scalar(conn, "SELECT count(*) FROM sessions WHERE playground_of IS NULL"),
        "turns": await _scalar(conn, "SELECT count(*) FROM runs WHERE kind = 'turn'"),
        "turns_failed": await _by(conn, "SELECT coalesce(reason, 'unknown') AS k, count(*) AS n "
                                        "FROM runs WHERE kind = 'turn' AND status = 'failed' "
                                        "GROUP BY 1"),
        "days_active": await _scalar(conn, "SELECT count(DISTINCT created_at::date) FROM runs "
                                           "WHERE kind = 'turn'"),
        "agents": await _scalar(conn, "SELECT count(*) FROM agents"),
        "agents_published": await _scalar(conn, "SELECT count(*) FROM agent_versions "
                                                "WHERE state <> 'draft'"),
        "skills": await _scalar(conn, "SELECT count(*) FROM skills WHERE origin <> 'built_in'"),
        "approvals": await _by(conn, "SELECT payload->>'decision' AS k, count(*) AS n "
                                     "FROM run_events WHERE type = 'approval.decided' GROUP BY 1"),
    }  # fmt: skip

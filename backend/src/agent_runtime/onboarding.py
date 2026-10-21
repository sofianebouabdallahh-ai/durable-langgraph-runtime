"""Getting started (phase L3d): a newcomer's first agent, in five steps.

    1 model   a model that answers: the default connection passed its test, or setup
              chose a real model ("use the demo model for now" skips it)
    2 agent   the guide's agent exists
    3 tool    it has a tool
    4 helper  it has a helper
    5 try     tested in a test chat, published, and a first real chat answered

Pattern: Specification per step, over facts read from the account. Progress is
derived, never stored (like "Tested", L3a): a step done in any screen, any browser,
ticks; undone (the helper removed), it un-ticks. Only the guide's own choices are
stored (which agent, the model step skipped, dismissed).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from agent_runtime.db import Conn

WORKSPACE = "local"
StepKey = Literal["model", "agent", "tool", "helper", "try"]
STEPS: tuple[StepKey, ...] = ("model", "agent", "tool", "helper", "try")


@dataclass(frozen=True, slots=True)
class GuideAgent:
    id: uuid.UUID
    name: str
    display_name: str


@dataclass(frozen=True, slots=True)
class Progress:
    done: dict[StepKey, bool]
    skipped: dict[StepKey, bool]
    agent: GuideAgent | None
    dismissed: bool
    tried: dict[str, bool] = field(default_factory=dict)  # step 5's parts

    @property
    def next(self) -> StepKey | None:
        return next((s for s in STEPS if not (self.done[s] or self.skipped[s])), None)

    @property
    def finished(self) -> bool:
        return self.next is None


async def _settings(conn: Conn) -> dict[str, Any]:
    cur = await conn.execute(
        """
        SELECT ws.guide_agent_id, ws.guide_model_skipped_at, ws.guide_dismissed_at,
               c.test_status AS default_status
        FROM workspace_settings ws
        LEFT JOIN model_connections c
               ON c.id = ws.default_connection_id AND c.archived_at IS NULL
        WHERE ws.workspace_id = %s
        """,
        (WORKSPACE,),
    )
    return await cur.fetchone() or {}


async def _agent(
    conn: Conn, agent_id: uuid.UUID | None
) -> tuple[GuideAgent, dict[str, Any]] | None:
    """The guide's agent and its current form (the draft, else the published version)."""
    if agent_id is None:
        return None
    cur = await conn.execute(
        """
        SELECT a.id, a.name, v.document
        FROM agents a
        JOIN LATERAL (
            SELECT document FROM agent_versions
            WHERE agent_id = a.id AND state IN ('draft', 'published')
            ORDER BY (state = 'draft') DESC, number DESC LIMIT 1
        ) v ON true
        WHERE a.id = %s AND a.archived_at IS NULL
        """,
        (agent_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    doc: dict[str, Any] = row["document"]
    return GuideAgent(row["id"], row["name"], doc.get("display_name") or row["name"]), doc


async def _tried(conn: Conn, agent: GuideAgent) -> dict[str, bool]:
    cur = await conn.execute(
        """
        SELECT
          EXISTS (SELECT 1 FROM runs r JOIN sessions s ON s.id = r.session_id
                  WHERE s.playground_of = %(id)s AND r.kind = 'turn'
                    AND r.status = 'completed') AS tested,
          EXISTS (SELECT 1 FROM agent_versions
                  WHERE agent_id = %(id)s AND state = 'published') AS published,
          EXISTS (SELECT 1 FROM runs r JOIN sessions s ON s.id = r.session_id
                  WHERE s.playground_of IS NULL AND s.graph_name = %(name)s
                    AND r.kind = 'turn' AND r.status = 'completed') AS chatted
        """,
        {"id": agent.id, "name": agent.name},
    )
    row = await cur.fetchone() or {}
    return {k: bool(row.get(k)) for k in ("tested", "published", "chatted")}


async def progress(conn: Conn, *, real_setup_model: bool) -> Progress:
    """Where the guide stands, from the account's facts. `real_setup_model`: setup
    chose a real model (not the offline demo)."""
    settings = await _settings(conn)
    found = await _agent(conn, settings.get("guide_agent_id"))
    agent, doc = found if found else (None, {})
    tried = await _tried(conn, agent) if agent else {}
    done: dict[StepKey, bool] = {
        "model": settings.get("default_status") == "ready" or real_setup_model,
        "agent": agent is not None,
        "tool": bool(doc.get("tools")),
        "helper": bool(doc.get("helpers")),
        "try": all(tried.values()) if tried else False,
    }
    skipped: dict[StepKey, bool] = {s: False for s in STEPS}
    skipped["model"] = not done["model"] and settings.get("guide_model_skipped_at") is not None
    return Progress(done, skipped, agent, settings.get("guide_dismissed_at") is not None, tried)


async def update(
    conn: Conn,
    *,
    agent_id: uuid.UUID | None = None,
    skip_model: bool | None = None,
    dismissed: bool | None = None,
    restart: bool = False,
) -> None:
    """The guide's own choices. `restart` forgets them all (the facts stay: a model
    that's ready is still ready)."""
    sets: list[str] = []
    values: list[Any] = []
    if restart:
        sets += ["guide_agent_id = NULL", "guide_model_skipped_at = NULL",
                 "guide_dismissed_at = NULL"]  # fmt: skip
    if agent_id is not None:
        sets.append("guide_agent_id = %s")
        values.append(agent_id)
    if skip_model is not None:
        sets.append(f"guide_model_skipped_at = {'now()' if skip_model else 'NULL'}")
    if dismissed is not None:
        sets.append(f"guide_dismissed_at = {'now()' if dismissed else 'NULL'}")
    if not sets:
        return
    await conn.execute(
        "INSERT INTO workspace_settings (workspace_id) VALUES (%s) ON CONFLICT DO NOTHING",
        (WORKSPACE,),
    )
    await conn.execute(
        f"UPDATE workspace_settings SET {', '.join(sets)}, updated_at = now() "
        "WHERE workspace_id = %s",
        (*values, WORKSPACE),
    )

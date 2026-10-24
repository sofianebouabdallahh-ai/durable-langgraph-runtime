"""Kill switches (phase L6): stop one agent, or every agent, now; nothing new starts
until it's turned back on.

- **One agent**: a `kill_switches` row, and every unfinished run of that agent
  cancelled (its chats, test chats and helpers). New messages to it are refused.
- **Every agent**: the runtime's admission pause (R14.18) and every unfinished run
  cancelled. New messages and runs are refused.

Cancelling is immediate: a worker watches its run's cancel flag every second and stops
the step in progress (a model call, a tool, a helper), not only between steps (see
`RunExecutor._under_lease`). A turn waiting for approval or still queued is cancelled
on the spot.

Pattern: a Facade over the admission pause, the switches table and run cancellation.
"""

from __future__ import annotations

import logging
import uuid

from agent_runtime import logs
from agent_runtime.admin import AdminRepository
from agent_runtime.audit import AuditLog
from agent_runtime.db import Pool
from agent_runtime.runs.service import RunService
from agent_runtime.runs.store import RunTerminal
from agent_runtime.runs.switches import KillSwitchRepository, KillSwitchState

log = logging.getLogger(__name__)

UNFINISHED = "status NOT IN ('completed', 'failed', 'cancelled')"


class KillSwitch:
    def __init__(self, pool: Pool, runs: RunService) -> None:
        self._pool = pool
        self._runs = runs

    async def state(self) -> KillSwitchState:
        async with self._pool.connection() as conn:
            admin = await AdminRepository(conn).get()
            agents = await KillSwitchRepository(conn).all()
        return KillSwitchState(
            all_off=admin.paused,
            reason=admin.reason if admin.paused else None,
            since=admin.updated_at if admin.paused else None,
            agents=agents,
        )

    async def stop(self, agent: str | None, reason: str | None) -> int:
        """Switch `agent` (None: every agent) off and cancel its unfinished runs now.
        Returns how many runs were cancelled (their descendants go with them)."""
        async with self._pool.connection() as conn, conn.transaction():
            await AuditLog(conn).record("kill_switch.on", "agent", agent or "*",
                                        after={"reason": reason})  # fmt: skip
            if agent is None:
                await AdminRepository(conn).set_paused(True, reason or "every agent stopped")
                cur = await conn.execute(
                    f"SELECT id FROM runs WHERE {UNFINISHED} AND parent_run_id IS NULL"
                )
            else:
                await KillSwitchRepository(conn).engage(agent, reason)
                cur = await conn.execute(
                    f"SELECT id FROM runs WHERE {UNFINISHED} AND parent_run_id IS NULL "
                    "AND agent_name = %s",
                    (agent,),
                )
            ids: list[uuid.UUID] = [r["id"] for r in await cur.fetchall()]
        cancelled = 0
        for run_id in ids:
            try:
                await self._runs.cancel(run_id)
                cancelled += 1
            except RunTerminal:
                pass  # it finished meanwhile
        logs.event(log, f"kill switch on: {agent or 'every agent'}", agent=agent,
                   cancelled=cancelled, level=logging.WARNING)  # fmt: skip
        return cancelled

    async def resume(self, agent: str | None) -> None:
        """Switch `agent` (None: every agent) back on. Nothing cancelled comes back."""
        async with self._pool.connection() as conn, conn.transaction():
            if agent is None:
                await AdminRepository(conn).set_paused(False)
            else:
                await KillSwitchRepository(conn).release(agent)
            await AuditLog(conn).record("kill_switch.off", "agent", agent or "*")
        logs.event(log, f"kill switch off: {agent or 'every agent'}", agent=agent)

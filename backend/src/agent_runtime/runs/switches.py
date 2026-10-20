"""Agents switched off (phase L6): the `kill_switches` table, and the check new work
passes. The facade that switches agents off and cancels their runs: kill_switch.py."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agent_runtime.db import Conn


class AgentSwitchedOff(Exception):
    """A message or run for an agent whose kill switch is on."""

    def __init__(self, agent: str, reason: str | None) -> None:
        why = f" ({reason})" if reason else ""
        super().__init__(f"This agent is switched off{why}. Turn it back on to use it.")
        self.agent = agent
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Switch:
    agent: str
    reason: str | None
    since: datetime


@dataclass(frozen=True, slots=True)
class KillSwitchState:
    all_off: bool  # every agent (the admission pause)
    reason: str | None
    since: datetime | None
    agents: list[Switch]


class KillSwitchRepository:
    def __init__(self, conn: Conn) -> None:
        self._conn = conn

    async def all(self) -> list[Switch]:
        cur = await self._conn.execute(
            "SELECT agent, reason, engaged_at FROM kill_switches ORDER BY engaged_at"
        )
        return [Switch(r["agent"], r["reason"], r["engaged_at"]) for r in await cur.fetchall()]

    async def get(self, agent: str) -> Switch | None:
        cur = await self._conn.execute(
            "SELECT agent, reason, engaged_at FROM kill_switches WHERE agent = %s", (agent,)
        )
        row = await cur.fetchone()
        return Switch(row["agent"], row["reason"], row["engaged_at"]) if row else None

    async def engage(self, agent: str, reason: str | None) -> None:
        await self._conn.execute(
            "INSERT INTO kill_switches (agent, reason) VALUES (%s, %s) "
            "ON CONFLICT (agent) DO UPDATE SET reason = EXCLUDED.reason",
            (agent, reason),
        )

    async def release(self, agent: str) -> None:
        await self._conn.execute("DELETE FROM kill_switches WHERE agent = %s", (agent,))


async def ensure_on(conn: Conn, agent: str) -> None:
    """Raise AgentSwitchedOff when `agent`'s kill switch is on (new work only)."""
    if (switch := await KillSwitchRepository(conn).get(agent)) is not None:
        raise AgentSwitchedOff(agent, switch.reason)

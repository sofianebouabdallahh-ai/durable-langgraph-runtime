"""Persistence for sub-agent invocations (CR-005 R16.3): `subagent_invocations`.

Every write is fenced by the MAIN run's epoch (sub-agents share its lease), both
here (`check_fence`) and by the database trigger from migration 0004. Each
state change and its `subagent.*` event commit together; callers publish
`emitted` after the commit, like `RunRepository`.

    running ──► completed   (returned success/partial, or stopped on its own)
            ──► failed      (returned failed, an error, a budget)
            ──► cancelled   (cancel_subagent, the main run ended, a hard limit)
            ──► timed_out   (its timeout)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from psycopg.types.json import Jsonb

from agent_runtime.db import Conn
from agent_runtime.fencing import Fence, check_fence
from agent_runtime.runs.events import EventType
from agent_runtime.runs.store import Event, RunRepository
from agent_runtime.tools.invocations import BudgetExceeded

Status = Literal["running", "completed", "failed", "cancelled", "timed_out"]
ResultStatus = Literal["success", "partial", "failed"]

PROGRESS_MIN_INTERVAL_S = 2.0  # R16.5: at most one update per 2 s …
PROGRESS_MAX_UPDATES = 50  # … and 50 per sub-agent


def handle_for(key: str) -> uuid.UUID:
    """The handle IS derived from the spawning call's idempotency key, so replaying
    `spawn_subagent` after a crash yields the same handle (R16.4)."""
    return uuid.UUID(key[:32])


@dataclass(frozen=True, slots=True)
class Invocation:
    handle: uuid.UUID
    run_id: uuid.UUID
    agent: str  # full id: "<main>/<sub>"
    task: str
    context: str | None
    status: Status
    progress: dict[str, Any]
    result: dict[str, Any] | None  # {status, summary, result, reason}
    usage: dict[str, Any]
    thread_id: str
    epoch: int
    spawned_by: str
    cancel_requested: bool
    cancel_reason: str | None
    created_at: datetime
    finished_at: datetime | None

    @property
    def name(self) -> str:
        return self.agent.split("/", 1)[-1]

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Invocation:
        return cls(
            handle=row["handle"],
            run_id=row["run_id"],
            agent=row["agent"],
            task=row["task"],
            context=row["context"],
            status=row["status"],
            progress=row["progress"],
            result=row["result"],
            usage=row["usage"],
            thread_id=row["thread_id"],
            epoch=row["epoch"],
            spawned_by=row["spawned_by_tool_call_id"],
            cancel_requested=row["cancel_requested"],
            cancel_reason=row["cancel_reason"],
            created_at=row["created_at"],
            finished_at=row["finished_at"],
        )

    def view(self) -> dict[str, Any]:
        """What the main agent (subagent_status) and the API see."""
        elapsed_end = self.finished_at or datetime.now(self.created_at.tzinfo)
        return {
            "handle": str(self.handle),
            "agent": self.name,
            "status": self.status,
            "progress": self.progress.get("message"),
            "percent": self.progress.get("percent"),
            "elapsed_s": round((elapsed_end - self.created_at).total_seconds(), 1),
            "usage": self.usage,
        }


_COLUMNS = """
    handle, run_id, agent, task, context, status, progress, result, usage, thread_id,
    epoch, spawned_by_tool_call_id, cancel_requested, cancel_reason, created_at, finished_at
"""


class SubagentRepository:
    def __init__(self, conn: Conn) -> None:
        self._conn = conn
        self.runs = RunRepository(conn)  # events go into the main run's log

    @property
    def emitted(self) -> list[Event]:
        return self.runs.emitted

    async def spawn(
        self,
        fence: Fence,
        *,
        key: str,
        agent: str,
        task: str,
        context: str | None,
        max_total: int,
        worker: str | None = None,
    ) -> tuple[Invocation, bool]:
        """Insert the invocation, or return the existing one for this key. Returns
        (invocation, created). Raises SpawnRefused past `max_total` per run."""
        handle = handle_for(key)
        async with self._conn.transaction():
            await check_fence(self._conn, fence)
            existing = await self._one("spawned_by_tool_call_id = %s", key)
            if existing is not None:
                return existing, False
            cur = await self._conn.execute(
                "SELECT count(*) AS n FROM subagent_invocations WHERE run_id = %s",
                (fence.run_id,),
            )
            row = await cur.fetchone()
            if row is not None and row["n"] >= max_total:
                raise SpawnRefused(f"at most {max_total} sub-agents per run")
            cur = await self._conn.execute(
                f"""
                INSERT INTO subagent_invocations
                    (handle, run_id, agent, task, context, thread_id, epoch,
                     spawned_by_tool_call_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {_COLUMNS}
                """,
                (handle, fence.run_id, agent, task, context,
                 f"{fence.run_id}/sub/{handle}", fence.epoch, key),
            )  # fmt: skip
            created = await cur.fetchone()
            assert created is not None
            await self.runs.append_event(
                fence.run_id, epoch=fence.epoch, type=EventType.SUBAGENT_SPAWNED,
                payload={"handle": str(handle), "agent": agent, "task": task[:500],
                         "worker": worker},  # AC37: they run in the main run's worker
            )  # fmt: skip
            return Invocation.from_row(created), True

    async def get(self, handle: uuid.UUID) -> Invocation | None:
        return await self._one("handle = %s", handle)

    async def list(
        self, run_id: uuid.UUID, handles: list[uuid.UUID] | None = None
    ) -> list[Invocation]:
        if handles is None:
            cur = await self._conn.execute(
                f"SELECT {_COLUMNS} FROM subagent_invocations WHERE run_id = %s "
                "ORDER BY created_at, handle",
                (run_id,),
            )
        else:
            cur = await self._conn.execute(
                f"SELECT {_COLUMNS} FROM subagent_invocations "
                "WHERE run_id = %s AND handle = ANY(%s) ORDER BY created_at, handle",
                (run_id, handles),
            )
        return [Invocation.from_row(r) for r in await cur.fetchall()]

    async def report_progress(
        self, fence: Fence, handle: uuid.UUID, message: str, percent: int | None
    ) -> str | None:
        """Store a progress update and emit it; None if accepted, else why it was
        dropped (rate limit, R16.5)."""
        async with self._conn.transaction():
            await check_fence(self._conn, fence)
            cur = await self._conn.execute(
                """
                SELECT progress,
                       CASE WHEN progress ? 'at'
                            THEN extract(epoch FROM now() - (progress->>'at')::timestamptz)
                       END AS since_s
                FROM subagent_invocations WHERE handle = %s FOR UPDATE
                """,
                (handle,),
            )
            row = await cur.fetchone()
            assert row is not None
            updates = int(row["progress"].get("updates", 0))
            if updates >= PROGRESS_MAX_UPDATES:
                return f"dropped: at most {PROGRESS_MAX_UPDATES} progress updates"
            if row["since_s"] is not None and row["since_s"] < PROGRESS_MIN_INTERVAL_S:
                return f"dropped: at most one progress update per {PROGRESS_MIN_INTERVAL_S:g}s"
            await self._conn.execute(
                """
                UPDATE subagent_invocations SET epoch = %s,
                    progress = jsonb_build_object('message', %s::text, 'percent', %s::int,
                                                  'updates', %s::int, 'at', now())
                WHERE handle = %s
                """,
                (fence.epoch, message, percent, updates + 1, handle),
            )
            await self.runs.append_event(
                fence.run_id, epoch=fence.epoch, type=EventType.SUBAGENT_PROGRESS,
                payload={"handle": str(handle), "message": message, "percent": percent},
            )  # fmt: skip
            return None

    async def set_result(self, fence: Fence, handle: uuid.UUID, result: dict[str, Any]) -> None:
        """`return_result`: record the result. The invocation ends when the
        sub-agent's graph stops (right after: its next model call short-circuits)."""
        async with self._conn.transaction():
            await check_fence(self._conn, fence)
            await self._conn.execute(
                "UPDATE subagent_invocations SET result = %s, epoch = %s "
                "WHERE handle = %s AND status = 'running'",
                (Jsonb(result), fence.epoch, handle),
            )

    async def finish(
        self, fence: Fence, handle: uuid.UUID, status: Status, result: dict[str, Any]
    ) -> Invocation | None:
        """End a running invocation (exactly once: later calls change nothing). A
        result already recorded by return_result wins over `result`."""
        async with self._conn.transaction():
            await check_fence(self._conn, fence)
            cur = await self._conn.execute(
                f"""
                UPDATE subagent_invocations SET
                    status = %s, result = coalesce(result, %s), epoch = %s, finished_at = now()
                WHERE handle = %s AND status = 'running'
                RETURNING {_COLUMNS}
                """,
                (status, Jsonb(result), fence.epoch, handle),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            inv = Invocation.from_row(row)
            await self.runs.append_event(
                fence.run_id, epoch=fence.epoch, type=EventType.SUBAGENT_COMPLETED,
                payload={"handle": str(handle), "agent": inv.name, "status": status,
                         "result_status": (inv.result or {}).get("status"),
                         "reason": (inv.result or {}).get("reason")},
            )  # fmt: skip
            return inv

    async def request_cancel(self, fence: Fence, handle: uuid.UUID, reason: str) -> bool:
        async with self._conn.transaction():
            await check_fence(self._conn, fence)
            cur = await self._conn.execute(
                "UPDATE subagent_invocations SET cancel_requested = true, cancel_reason = %s, "
                "epoch = %s WHERE handle = %s AND status = 'running' RETURNING 1",
                (reason, fence.epoch, handle),
            )
            return await cur.fetchone() is not None

    async def charge(
        self,
        fence: Fence,
        handle: uuid.UUID,
        *,
        model_calls: int = 0,
        tool: str | None = None,
        max_model_calls: int | None,
        max_tool_calls: int | None,
        max_for_tool: int | None = None,
    ) -> None:
        """A sub-agent's OWN budget (R16.8), in the caller's (fenced) transaction.
        The run's budget is charged separately, so usage rolls up (R14.1). Stamps the
        current epoch: the database trigger rejects an update that keeps an older one
        (a sub-agent spawned before a reclaim)."""
        cur = await self._conn.execute(
            "SELECT usage FROM subagent_invocations WHERE handle = %s FOR UPDATE", (handle,)
        )
        row = await cur.fetchone()
        assert row is not None
        usage = dict(row["usage"])
        per_tool = dict(usage.get("per_tool", {}))
        if model_calls:
            used = int(usage.get("model_calls", 0))
            if max_model_calls is not None and used + model_calls > max_model_calls:
                raise BudgetExceeded("subagent:max_turns", f"max_turns={max_model_calls} reached")
            usage["model_calls"] = used + model_calls
        if tool is not None:
            used = int(usage.get("tool_calls", 0))
            if max_tool_calls is not None and used + 1 > max_tool_calls:
                raise BudgetExceeded(
                    "subagent:max_tool_calls", f"max_tool_calls={max_tool_calls} reached"
                )
            if max_for_tool is not None and per_tool.get(tool, 0) + 1 > max_for_tool:
                raise BudgetExceeded(
                    "subagent:max_tool_calls", f"max_calls={max_for_tool} for {tool!r} reached"
                )
            usage["tool_calls"] = used + 1
            per_tool[tool] = per_tool.get(tool, 0) + 1
            usage["per_tool"] = per_tool
        await self._conn.execute(
            "UPDATE subagent_invocations SET usage = %s, epoch = %s WHERE handle = %s",
            (Jsonb(usage), fence.epoch, handle),
        )

    async def _one(self, where: str, value: Any) -> Invocation | None:
        cur = await self._conn.execute(
            f"SELECT {_COLUMNS} FROM subagent_invocations WHERE {where}", (value,)
        )
        row = await cur.fetchone()
        return Invocation.from_row(row) if row else None


class SpawnRefused(Exception):
    """A spawn the orchestrator won't do (limit, unknown sub-agent): a tool error."""

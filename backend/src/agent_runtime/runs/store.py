"""Run persistence: creating runs, changing their status, appending events.

Rule (R1.1): a status change and the event that records it are written in the
same transaction. Either both are visible or neither is, so the event log can
never disagree with the `runs` table.

Event `seq` is allocated by incrementing `runs.last_event_seq` in that same
transaction. The UPDATE takes the run's row lock, so concurrent writers for one
run queue up, and a rolled-back transaction gives its number back: sequence
numbers are gap-free and strictly increasing per run (R1.5).

Patterns:
- Repository: `RunRepository` is the only code that knows the SQL for runs and
  events. Callers speak in domain operations (create, transition, append_event)
  and get immutable domain objects (`Run`, `Event`) back, never raw rows.
- Unit of Work: the repository is bound to one connection and never commits on
  its own behalf beyond the atomic operation it implements. A caller that needs
  several operations to succeed or fail together wraps them in
  `async with conn.transaction():` (nested calls become savepoints). This is how
  the executor will commit a status change, its events and the LangGraph
  checkpoint as one unit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from agent_runtime.db import Conn
from agent_runtime.fencing import Fence, check_fence
from agent_runtime.ids import new_id
from agent_runtime.runs.events import EventType
from agent_runtime.runs.state import InvalidTransition, RunStatus, sources_of


class RunTerminal(Exception):
    """The run already ended; it can't be cancelled, resumed or executed."""

    def __init__(self, run: Run) -> None:
        super().__init__(f"run {run.id} is {run.status}; it has already ended")
        self.run = run


class NotWaitingForApproval(Exception):
    def __init__(self, run: Run) -> None:
        super().__init__(f"run {run.id} is {run.status}, not waiting_approval")
        self.run = run


class RunNotFound(LookupError):
    def __init__(self, run_id: uuid.UUID) -> None:
        super().__init__(f"run {run_id} not found")
        self.run_id = run_id


@dataclass(frozen=True, slots=True)
class Run:
    id: uuid.UUID
    graph_name: str
    kind: str
    thread_id: str
    status: RunStatus
    reason: str | None
    epoch: int
    owner: str | None
    lease_expires_at: datetime | None
    input: dict[str, Any]
    options: dict[str, Any]
    limits: dict[str, Any]
    steps: int
    parent_run_id: uuid.UUID | None
    session_id: uuid.UUID | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested: bool = False
    reclaims: int = 0
    releases: int = 0
    message_id: str | None = None
    interrupt_payload: dict[str, Any] | None = None  # what the run is waiting on (R1.4)
    resume_value: dict[str, Any] | None = None  # the human's decision, for Command(resume=…)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Run:
        return cls(
            id=row["id"],
            graph_name=row["graph_name"],
            kind=row["kind"],
            thread_id=row["thread_id"],
            status=RunStatus(row["status"]),
            reason=row["reason"],
            epoch=row["epoch"],
            owner=row["owner"],
            lease_expires_at=row["lease_expires_at"],
            input=row["input"],
            options=row["options"],
            limits=row["limits"],
            steps=row["steps"],
            parent_run_id=row["parent_run_id"],
            session_id=row["session_id"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            cancel_requested=row["cancel_requested"],
            reclaims=row["reclaims"],
            releases=row["releases"],
            message_id=row["message_id"],
            interrupt_payload=row["interrupt_payload"],
            resume_value=row["resume_value"],
        )


@dataclass(frozen=True, slots=True)
class Lease:
    """Ownership of a run at one epoch. `fence` must accompany every write."""

    fence: Fence
    reclaimed: bool  # the run was `running` under a dead owner (R2.4)
    reclaims: int


@dataclass(frozen=True, slots=True)
class Event:
    run_id: uuid.UUID
    seq: int
    ts: datetime
    epoch: int
    type: str
    payload: dict[str, Any]

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Event:
        return cls(
            run_id=row["run_id"],
            seq=row["seq"],
            ts=row["ts"],
            epoch=row["epoch"],
            type=row["type"],
            payload=row["payload"],
        )


def _required(row: dict[str, Any] | None, statement: str) -> dict[str, Any]:
    """`RETURNING` on a successful INSERT always yields a row. Raise instead of
    `assert` so the invariant still holds under `python -O`."""
    if row is None:
        raise RuntimeError(f"{statement} returned no row")
    return row


_RUN_COLUMNS = """
    id, graph_name, kind, thread_id, status, reason, epoch, owner, lease_expires_at,
    input, options, limits, steps, parent_run_id, session_id,
    created_at, started_at, finished_at, cancel_requested, reclaims, releases, message_id,
    interrupt_payload, resume_value
"""


class RunRepository:
    """Persistence for runs and their events, bound to one connection."""

    def __init__(self, conn: Conn) -> None:
        self._conn = conn
        # Every event this repository wrote. Callers publish them *after* their
        # transaction commits (R1.5), never before: an event must exist in
        # Postgres before anyone hears about it, and a rolled-back one never.
        self.emitted: list[Event] = []

    async def create(
        self,
        *,
        graph_name: str,
        input: dict[str, Any],
        kind: str = "workflow",
        options: dict[str, Any] | None = None,
        limits: dict[str, Any] | None = None,
        session_id: uuid.UUID | None = None,
        parent_run_id: uuid.UUID | None = None,
        traceparent: str | None = None,
    ) -> Run:
        """Insert a `queued` run and its `run.created` event, atomically."""
        run_id = new_id()
        # R1.2: a chat turn continues its session's thread; anything else is its own thread.
        thread_id = str(session_id) if session_id is not None else str(run_id)
        async with self._conn.transaction():
            cur = await self._conn.execute(
                f"""
                INSERT INTO runs (id, graph_name, kind, thread_id, input, options, limits,
                                  session_id, parent_run_id, traceparent)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {_RUN_COLUMNS}
                """,
                (
                    run_id,
                    graph_name,
                    kind,
                    thread_id,
                    Jsonb(input),
                    Jsonb(options or {}),
                    Jsonb(limits or {}),
                    session_id,
                    parent_run_id,
                    traceparent,
                ),
            )
            row = _required(await cur.fetchone(), "INSERT INTO runs … RETURNING")
            await self.append_event(run_id, epoch=0, type=EventType.RUN_CREATED, payload={})
        return Run.from_row(row)

    async def append_event(
        self,
        run_id: uuid.UUID,
        *,
        epoch: int,
        type: EventType,
        payload: dict[str, Any],
    ) -> Event:
        """Append one event. Must run inside the caller's transaction (Unit of Work)."""
        if self._conn.info.transaction_status != TransactionStatus.INTRANS:
            raise RuntimeError("append_event must be called inside a transaction")
        cur = await self._conn.execute(
            "UPDATE runs SET last_event_seq = last_event_seq + 1 "
            "WHERE id = %s RETURNING last_event_seq",
            (run_id,),
        )
        row = await cur.fetchone()
        if row is None:
            raise RunNotFound(run_id)
        cur = await self._conn.execute(
            """
            INSERT INTO run_events (run_id, seq, epoch, type, payload)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING run_id, seq, ts, epoch, type, payload
            """,
            (run_id, row["last_event_seq"], epoch, str(type), Jsonb(payload)),
        )
        event_row = _required(await cur.fetchone(), "INSERT INTO run_events … RETURNING")
        event = Event.from_row(event_row)
        self.emitted.append(event)
        return event

    async def transition(
        self,
        run_id: uuid.UUID,
        target: RunStatus,
        *,
        event: EventType,
        fence: Fence | None = None,
        reason: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Run:
        """Move a run to `target` and record `event`, atomically.

        The WHERE clause only matches legal source states (optimistic
        concurrency): when two processes race to change the same run, exactly
        one succeeds; the other sees zero rows and gets `InvalidTransition`
        naming the run's real current status.

        `fence`: a worker's transitions are fenced (R2.3); a stale epoch raises
        `FencedError` and nothing is written. API-side transitions pass None.
        Leaving `running` releases the lease (owner and expiry cleared).
        """
        async with self._conn.transaction():
            if fence is not None:
                await check_fence(self._conn, fence)
            cur = await self._conn.execute(
                f"""
                UPDATE runs SET
                    status      = %(target)s,
                    reason      = %(reason)s,
                    started_at  = CASE WHEN %(target)s = 'running'
                                       THEN coalesce(started_at, now()) ELSE started_at END,
                    finished_at = CASE WHEN %(terminal)s THEN now() ELSE NULL END,
                    owner            = CASE WHEN %(target)s = 'running' THEN owner END,
                    lease_expires_at = CASE WHEN %(target)s = 'running' THEN lease_expires_at END,
                    -- running → queued is a graceful release (R10.7): counted, but not
                    -- toward max_reclaims (R2.4)
                    releases    = releases + CASE WHEN status = 'running' AND %(target)s = 'queued'
                                                  THEN 1 ELSE 0 END
                WHERE id = %(id)s AND status = ANY(%(sources)s)
                RETURNING {_RUN_COLUMNS}
                """,
                {
                    "id": run_id,
                    "target": str(target),
                    "reason": reason,
                    "terminal": target.is_terminal,
                    "sources": [str(s) for s in sources_of(target)],
                },
            )
            row = await cur.fetchone()
            if row is None:
                current = await self.get(run_id)  # raises RunNotFound
                raise InvalidTransition(current.status, target)
            await self.append_event(run_id, epoch=row["epoch"], type=event, payload=payload or {})
        return Run.from_row(row)

    async def request_cancel(self, run_id: uuid.UUID) -> Run:
        """Cooperative cancel (R1.6). A run nobody is executing ends now; a
        running one is flagged and its worker cancels it before its next node."""
        async with self._conn.transaction():
            cur = await self._conn.execute(
                f"UPDATE runs SET cancel_requested = true WHERE id = %s "
                f"AND status NOT IN ('completed', 'failed', 'cancelled') RETURNING {_RUN_COLUMNS}",
                (run_id,),
            )
            row = await cur.fetchone()
            if row is None:
                raise RunTerminal(await self.get(run_id))  # or RunNotFound
            run = Run.from_row(row)
            if run.status is RunStatus.RUNNING:
                return run
            return await self.transition(
                run_id, RunStatus.CANCELLED, event=EventType.RUN_CANCELLED,
                reason="cancel_requested", payload={"reason": "cancel_requested"},
            )  # fmt: skip

    async def set_interrupt(self, run_id: uuid.UUID, payload: dict[str, Any] | None) -> None:
        """Record what the run waits on. Call inside the pause's fenced transaction."""
        await self._conn.execute(
            "UPDATE runs SET interrupt_payload = %s WHERE id = %s",
            (Jsonb(payload) if payload is not None else None, run_id),
        )

    async def decide_approval(
        self,
        run_id: uuid.UUID,
        *,
        decision: str,
        edits: dict[str, Any] | None,
        reason: str | None,
        decided_by: str,
    ) -> Run:
        """R1.4. approve → store the resume value and re-queue; reject → cancelled(rejected).

        Works with no worker alive: the run holds no lease while it waits.
        Raises NotWaitingForApproval (→ 409) unless the run is waiting_approval."""
        async with self._conn.transaction():
            cur = await self._conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM runs WHERE id = %s FOR UPDATE", (run_id,)
            )
            row = await cur.fetchone()
            if row is None:
                raise RunNotFound(run_id)
            run = Run.from_row(row)
            if run.status is not RunStatus.WAITING_APPROVAL:
                raise NotWaitingForApproval(run)
            await self.append_event(
                run_id,
                epoch=run.epoch,
                type=EventType.APPROVAL_DECIDED,
                payload={"decision": decision, "edits": edits, "reason": reason,
                         "decided_by": decided_by},
            )  # fmt: skip
            if decision == "reject":
                await self.set_interrupt(run_id, None)
                return await self.transition(
                    run_id, RunStatus.CANCELLED, event=EventType.RUN_CANCELLED,
                    reason="rejected", payload={"reason": "rejected", "comment": reason},
                )  # fmt: skip
            await self._conn.execute(
                "UPDATE runs SET resume_value = %s, interrupt_payload = NULL WHERE id = %s",
                (Jsonb({"decision": "approve", "edits": edits or {}}), run_id),
            )
            return await self.transition(
                run_id, RunStatus.QUEUED, event=EventType.RUN_RESUMED_AFTER_APPROVAL
            )

    async def is_cancel_requested(self, run_id: uuid.UUID) -> bool:
        cur = await self._conn.execute("SELECT cancel_requested FROM runs WHERE id = %s", (run_id,))
        row = await cur.fetchone()
        return bool(row and row["cancel_requested"])

    # ------------------------------------------------------------- ownership

    async def acquire_lease(self, run_id: uuid.UUID, owner: str, ttl_s: float) -> Lease | None:
        """Take ownership of a runnable run (R2.3); None if someone else holds it.

        Succeeds for a `queued` run, or a `running` run whose lease expired (its
        worker died or froze): that is a *reclaim* (R2.4) and is counted. The
        epoch bump is what fences off the previous owner.
        """
        cur = await self._conn.execute(
            """
            UPDATE runs SET
                owner            = %(owner)s,
                epoch            = epoch + 1,
                lease_expires_at = now() + make_interval(secs => %(ttl)s),
                reclaims         = reclaims + CASE WHEN status = 'running' THEN 1 ELSE 0 END
            WHERE id = %(id)s
              AND status IN ('queued', 'running')
              AND (owner IS NULL OR lease_expires_at < now())
            RETURNING epoch, status, reclaims
            """,
            {"id": run_id, "owner": owner, "ttl": ttl_s},
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return Lease(
            fence=Fence(run_id, row["epoch"]),
            reclaimed=row["status"] == RunStatus.RUNNING,
            reclaims=row["reclaims"],
        )

    async def renew_lease(self, fence: Fence, owner: str, ttl_s: float) -> bool:
        """Heartbeat (R2.3). False means ownership is gone: stop working."""
        cur = await self._conn.execute(
            """
            UPDATE runs SET lease_expires_at = now() + make_interval(secs => %(ttl)s)
            WHERE id = %(id)s AND epoch = %(epoch)s AND owner = %(owner)s
              AND status = 'running'
            RETURNING 1
            """,
            {"id": fence.run_id, "epoch": fence.epoch, "owner": owner, "ttl": ttl_s},
        )
        return await cur.fetchone() is not None

    # --------------------------------------------------------- usage & output

    async def add_steps(self, run_id: uuid.UUID, n: int) -> int:
        """Count committed supersteps (R1.7). Call inside the fenced transaction."""
        cur = await self._conn.execute(
            "UPDATE runs SET steps = steps + %s WHERE id = %s RETURNING steps", (n, run_id)
        )
        row = await cur.fetchone()
        if row is None:
            raise RunNotFound(run_id)
        return int(row["steps"])

    async def save_result(
        self, run_id: uuid.UUID, output: dict[str, Any], *, partial: bool = False
    ) -> None:
        await self._conn.execute(
            "INSERT INTO run_results (run_id, output, partial) VALUES (%s, %s, %s)",
            (run_id, Jsonb(output), partial),
        )

    async def get_result(self, run_id: uuid.UUID) -> dict[str, Any] | None:
        cur = await self._conn.execute(
            "SELECT output, partial FROM run_results WHERE run_id = %s", (run_id,)
        )
        return await cur.fetchone()

    async def get(self, run_id: uuid.UUID) -> Run:
        cur = await self._conn.execute(f"SELECT {_RUN_COLUMNS} FROM runs WHERE id = %s", (run_id,))
        row = await cur.fetchone()
        if row is None:
            raise RunNotFound(run_id)
        return Run.from_row(row)

    async def list_events(
        self, run_id: uuid.UUID, *, after_seq: int = 0, limit: int = 100
    ) -> list[Event]:
        """Persisted events after `after_seq`, in order (the replay path, R2.5)."""
        cur = await self._conn.execute(
            """
            SELECT run_id, seq, ts, epoch, type, payload FROM run_events
            WHERE run_id = %s AND seq > %s ORDER BY seq LIMIT %s
            """,
            (run_id, after_seq, limit),
        )
        return [Event.from_row(r) for r in await cur.fetchall()]

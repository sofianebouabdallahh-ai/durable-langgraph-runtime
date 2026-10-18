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


class FanOutRejected(Exception):
    """A fan-out breached a limit (R14.6) or was malformed. Nothing was created; the
    spawning node sees this as an error it can handle, never as a crash."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class NewChild:
    """A validated child run, ready to insert (see RunService.prepare)."""

    key: str
    graph_name: str
    input: dict[str, Any]
    options: dict[str, Any]
    limits: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ChildOutcome:
    key: str
    run_id: uuid.UUID
    graph_name: str
    status: RunStatus
    reason: str | None
    output: dict[str, Any] | None  # run_results.output when completed

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ChildOutcome:
        return cls(
            key=row["child_key"],
            run_id=row["id"],
            graph_name=row["graph_name"],
            status=RunStatus(row["status"]),
            reason=row["reason"],
            output=row["output"],
        )


@dataclass(frozen=True, slots=True)
class FanOutLimits:
    max_children: int
    max_depth: int
    max_descendants: int


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
    # the run tree (R2.8, R14.6): a root has no parent, root_run_id None and depth 0
    root_run_id: uuid.UUID | None = None
    depth: int = 0
    child_key: str | None = None
    child_total: int = 0
    child_done: int = 0
    # The agent bundle this run executes (R15.4): the snapshot it was created with.
    agent_hash: str | None = None
    # What each model string resolved to when the run was created (phase L3b).
    model_bindings: dict[str, Any] | None = None

    @property
    def root_id(self) -> uuid.UUID:
        return self.root_run_id or self.id

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
            root_run_id=row["root_run_id"],
            depth=row["depth"],
            child_key=row["child_key"],
            agent_hash=row.get("agent_hash"),
            model_bindings=row.get("model_bindings"),
            child_total=row["child_total"],
            child_done=row["child_done"],
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
    # The run's chat session, if it is a turn: not stored with the event, read with
    # it, so the post-commit publish can tell the session's stream too (turn.status).
    session_id: uuid.UUID | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Event:
        return cls(
            run_id=row["run_id"],
            seq=row["seq"],
            ts=row["ts"],
            epoch=row["epoch"],
            type=row["type"],
            payload=row["payload"],
            session_id=row.get("session_id"),
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
    interrupt_payload, resume_value, root_run_id, depth, child_key, child_total, child_done,
    agent_hash, model_bindings
"""


class RunRepository:
    """Persistence for runs and their events, bound to one connection."""

    def __init__(self, conn: Conn) -> None:
        self._conn = conn
        # Every event this repository wrote. Callers publish them *after* their
        # transaction commits (R1.5), never before: an event must exist in
        # Postgres before anyone hears about it, and a rolled-back one never.
        self.emitted: list[Event] = []
        # Runs that became `queued` (spawned children; a parent whose children all
        # ended). Like events, they are sent to the work queue only AFTER COMMIT:
        # a message must never point at a row that might still roll back. The
        # outbox relay re-sends any that are lost.
        self.ready: list[uuid.UUID] = []

    @property
    def conn(self) -> Conn:
        """For collaborators that must write in this repository's transaction."""
        return self._conn

    async def create(
        self,
        *,
        graph_name: str,
        input: dict[str, Any],
        kind: str = "workflow",
        options: dict[str, Any] | None = None,
        limits: dict[str, Any] | None = None,
        session_id: uuid.UUID | None = None,
        parent: Run | None = None,
        child_key: str | None = None,
        traceparent: str | None = None,
        agent: tuple[str, str, int] | None = None,
        idempotency_key: str | None = None,
        model_bindings: dict[str, Any] | None = None,
    ) -> Run:
        """Insert a `queued` run and its `run.created` event, atomically.

        A child (`parent` + `child_key`) joins its parent's tree. Use
        `spawn_children`, which also enforces the fan-out limits."""
        run_id = new_id()
        # R1.2: a chat turn continues its session's thread; anything else is its own thread.
        thread_id = str(session_id) if session_id is not None else str(run_id)
        async with self._conn.transaction():
            cur = await self._conn.execute(
                f"""
                INSERT INTO runs (id, graph_name, kind, thread_id, input, options, limits,
                                  session_id, parent_run_id, root_run_id, depth, child_key,
                                  traceparent, agent_hash, agent_name, agent_version,
                                  idempotency_key, model_bindings)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    parent.id if parent else None,
                    parent.root_id if parent else None,
                    parent.depth + 1 if parent else 0,
                    child_key,
                    traceparent,
                    agent[0] if agent else None,  # (bundle hash, name, version)
                    agent[1] if agent else None,
                    agent[2] if agent else None,
                    idempotency_key,
                    Jsonb(model_bindings) if model_bindings is not None else None,
                ),
            )
            row = _required(await cur.fetchone(), "INSERT INTO runs … RETURNING")
            await self.append_event(
                run_id, epoch=0, type=EventType.RUN_CREATED,
                payload={"parent_run_id": str(parent.id), "key": child_key} if parent else {},
            )  # fmt: skip
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
            "WHERE id = %s RETURNING last_event_seq, session_id",
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
        event = Event.from_row({**event_row, "session_id": row["session_id"]})
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
            if target.is_terminal and row["parent_run_id"] is not None:
                await self._child_ended(Run.from_row(row))
        return Run.from_row(row)

    async def _child_ended(self, child: Run) -> None:
        """Fan-in (R2.8), in the child's terminal transaction.

        Every terminal transition goes through `transition`, so no path (worker,
        reaper, API cancel) can forget this. The parent's row lock serialises
        siblings: exactly one of them sees child_done reach child_total and
        re-queues the parent, even when all finish at once. A parent that is no
        longer waiting (cancelled) is left alone.
        """
        assert child.parent_run_id is not None
        cur = await self._conn.execute(
            """
            UPDATE runs SET child_done = child_done + 1
            WHERE id = %s AND status = 'waiting_children'
            RETURNING epoch, child_done, child_total
            """,
            (child.parent_run_id,),
        )
        parent = await cur.fetchone()
        if parent is None:
            return
        await self.append_event(
            child.parent_run_id,
            epoch=parent["epoch"],
            type=EventType.CHILD_COMPLETED,
            payload={"child_run_id": str(child.id), "key": child.child_key,
                     "status": str(child.status), "reason": child.reason},
        )  # fmt: skip
        if parent["child_done"] == parent["child_total"]:
            await self.transition(
                child.parent_run_id, RunStatus.QUEUED, event=EventType.CHILDREN_COMPLETED,
                payload={"children": parent["child_total"]},
            )  # fmt: skip
            self.ready.append(child.parent_run_id)

    # ------------------------------------------------------------- the run tree

    async def spawn_children(
        self,
        parent: Run,
        fence: Fence,
        children: list[NewChild],
        limits: FanOutLimits,
        payload: dict[str, Any],
    ) -> list[Run]:
        """Fan out (R2.8) in ONE fenced transaction: insert the children, count them,
        and move the parent to waiting_children (its lease released). All or nothing.

        Raises FanOutRejected for a breached limit (R14.6) or a reused key; the
        transaction then rolls back and nothing exists.
        """
        n = len(children)
        keys = [c.key for c in children]
        if n == 0:
            raise FanOutRejected("a fan-out needs at least one child")
        if len(set(keys)) != n:
            raise FanOutRejected("child keys must be unique")
        if n > limits.max_children:
            raise FanOutRejected(f"max_children={limits.max_children} exceeded ({n} children)")
        if parent.depth + 1 > limits.max_depth:
            raise FanOutRejected(f"max sub-run depth {limits.max_depth} exceeded")
        async with self._conn.transaction():
            await check_fence(self._conn, fence)
            # Lock order everywhere is deepest first (child → parent → root): here the
            # parent holds its fence lock, then the root.
            cur = await self._conn.execute(
                "SELECT descendants FROM runs WHERE id = %s FOR NO KEY UPDATE", (parent.root_id,)
            )
            root = _required(await cur.fetchone(), "SELECT root")
            if root["descendants"] + n > limits.max_descendants:
                raise FanOutRejected(
                    f"max {limits.max_descendants} descendants per root run exceeded"
                )
            created: list[Run] = []
            for child in children:
                run = await self.create(
                    graph_name=child.graph_name, input=child.input, kind="child",
                    options=child.options, limits=child.limits,
                    parent=parent, child_key=child.key,
                )  # fmt: skip
                created.append(run)
            await self._conn.execute(
                "UPDATE runs SET descendants = descendants + %s WHERE id = %s",
                (n, parent.root_id),
            )
            await self._conn.execute(
                "UPDATE runs SET child_total = child_total + %s, interrupt_payload = %s "
                "WHERE id = %s",
                (n, Jsonb(payload), parent.id),
            )
            await self.transition(
                parent.id, RunStatus.WAITING_CHILDREN, event=EventType.CHILDREN_SPAWNED,
                fence=fence,
                payload={"children": [{"key": r.child_key, "run_id": str(r.id),
                                       "graph": r.graph_name} for r in created]},
            )  # fmt: skip
            self.ready.extend(r.id for r in created)
        return created

    async def children(self, parent_id: uuid.UUID, keys: list[str]) -> list[ChildOutcome]:
        """The children with these keys, in the order of `keys`, with their results."""
        cur = await self._conn.execute(
            """
            SELECT r.id, r.child_key, r.graph_name, r.status, r.reason, rr.output
            FROM runs r LEFT JOIN run_results rr ON rr.run_id = r.id
            WHERE r.parent_run_id = %s AND r.child_key = ANY(%s)
            """,
            (parent_id, keys),
        )
        by_key = {row["child_key"]: ChildOutcome.from_row(row) for row in await cur.fetchall()}
        return [by_key[k] for k in keys if k in by_key]

    async def has_unsuccessful_children(self, parent_id: uuid.UUID) -> bool:
        """`partial` (R2.8): some child of this run did not complete."""
        cur = await self._conn.execute(
            "SELECT EXISTS (SELECT 1 FROM runs WHERE parent_run_id = %s "
            "AND status <> 'completed') AS partial",
            (parent_id,),
        )
        row = await cur.fetchone()
        return bool(row and row["partial"])

    async def queue_depth(self) -> int:
        """Runs waiting for a worker (R2.9). Counted in Postgres, the source of
        truth: right even when Redis is down or holds duplicate messages."""
        cur = await self._conn.execute("SELECT count(*) AS n FROM runs WHERE status = 'queued'")
        row = await cur.fetchone()
        return int(row["n"]) if row else 0

    async def request_cancel(self, run_id: uuid.UUID) -> Run:
        """Cooperative cancel (R1.6), cascading to every live descendant (R2.8).

        A run nobody is executing ends now; a running one is flagged and its
        worker cancels it before its next node.

        Locks are taken deepest first (grandchildren, children, then this run),
        the same order as a child's fan-in (child → parent), so a cancel racing a
        finishing child can't deadlock. Cancels are then APPLIED shallowest first:
        once the parent is cancelled, a child that ends no longer re-queues it.
        """
        async with self._conn.transaction():
            cur = await self._conn.execute(
                """
                WITH RECURSIVE tree AS (
                    SELECT id FROM runs WHERE parent_run_id = %(id)s
                    UNION ALL
                    SELECT r.id FROM runs r JOIN tree t ON r.parent_run_id = t.id
                )
                SELECT r.id, r.depth FROM runs r JOIN tree USING (id)
                WHERE r.status NOT IN ('completed', 'failed', 'cancelled')
                ORDER BY r.depth DESC, r.id
                FOR NO KEY UPDATE OF r
                """,
                {"id": run_id},
            )
            descendants = sorted(await cur.fetchall(), key=lambda r: (r["depth"], r["id"]))
            run = await self._cancel_one(run_id)
            if run is None:
                raise RunTerminal(await self.get(run_id))  # or RunNotFound
            for d in descendants:
                await self._cancel_one(d["id"])
            return run

    async def _cancel_one(self, run_id: uuid.UUID) -> Run | None:
        cur = await self._conn.execute(
            f"UPDATE runs SET cancel_requested = true WHERE id = %s "
            f"AND status NOT IN ('completed', 'failed', 'cancelled') RETURNING {_RUN_COLUMNS}",
            (run_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return None  # ended meanwhile
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
                f"SELECT {_RUN_COLUMNS} FROM runs WHERE id = %s FOR NO KEY UPDATE", (run_id,)
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

    async def add_usage(self, run_id: uuid.UUID, tokens: int, cost: float) -> None:
        """Tokens and cost of a committed step (R14.1), for the run and its ancestors
        (roll-up), and for its session. Inside the step's (fenced) transaction; the run
        row is already locked, ancestors are locked here, deepest first."""
        await self._conn.execute(
            """
            UPDATE runs SET tokens = tokens + %(t)s, cost = cost + %(c)s
            WHERE id IN (
                SELECT id FROM runs
                WHERE id = %(id)s
                   OR id = (SELECT parent_run_id FROM runs WHERE id = %(id)s)
                   OR id = (SELECT root_run_id FROM runs WHERE id = %(id)s)
                ORDER BY depth DESC FOR NO KEY UPDATE
            )
            """,
            {"id": run_id, "t": tokens, "c": cost},
        )
        await self._conn.execute(
            "UPDATE sessions SET tokens = tokens + %(t)s, cost = cost + %(c)s "
            "WHERE id = (SELECT session_id FROM runs WHERE id = %(id)s)",
            {"id": run_id, "t": tokens, "c": cost},
        )

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

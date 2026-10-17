"""Session use cases (CR-001 R12.1, R12.2, R12.6, R12.7, R12.10; CR-004 R15.6).

Pattern: Service Layer, composed with RunService: a turn IS a run, so run
validation (`prepare`), admission control and enqueueing are reused, not copied.

    send a turn ── ONE transaction ─────────────────────────────────────────────
      lock the session · active? no turn running? (409s) · INSERT the run
      (thread = session) · INSERT the `user` message
    └── after COMMIT: publish the message, enqueue the run

Approve and cancel forward to the session's active run and add an `approval` /
`error` message in the same transaction. Archiving is active → archived exactly
once and enqueues a `session_end` run (R15.6): it gets a lease, fencing and
reclaim like any run. Idle sessions are archived the same way.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import GraphRegistry, UnknownGraph
from agent_runtime.runs.relay import OutboxRelay
from agent_runtime.runs.service import Overloaded, RunService, prepare
from agent_runtime.runs.state import RunStatus
from agent_runtime.runs.store import Run, RunRepository
from agent_runtime.sessions.store import (
    Message,
    NewMessage,
    NoActiveTurn,
    Session,
    SessionArchived,
    SessionRepository,
    TurnActive,
    message_id,
)
from agent_runtime.sessions.transcript import event_message, publish_messages
from agent_runtime.streaming.bus import EventBus, publish_events

log = logging.getLogger(__name__)


class NotAnAgent(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"{name!r} is not an agent; sessions chat with agents")
        self.name = name


@dataclass(frozen=True)
class Turn:
    message: Message
    run: Run


class SessionService:
    def __init__(
        self,
        pool: Pool,
        settings: Settings,
        graphs: GraphRegistry,
        runs: RunService,
        relay: OutboxRelay | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self._pool = pool
        self._settings = settings
        self._graphs = graphs
        self._runs = runs
        self._relay = relay
        self._bus = bus

    # ---------------------------------------------------------------- sessions

    async def create(self, agent: str, title: str | None = None) -> Session:
        spec = self._graphs.get(agent)  # UnknownGraph → 404
        if spec.agent is None:
            raise NotAnAgent(agent)
        async with self._pool.connection() as conn, conn.transaction():
            return await SessionRepository(conn).create(
                graph_name=agent, agent_name=agent, title=title
            )

    async def get(self, session_id: uuid.UUID) -> Session:
        async with self._pool.connection() as conn:
            return await SessionRepository(conn).get(session_id)

    async def page(
        self, *, status: str | None, limit: int, before: datetime | None
    ) -> list[Session]:
        async with self._pool.connection() as conn:
            return await SessionRepository(conn).page(status=status, limit=limit, before=before)

    async def messages(self, session_id: uuid.UUID, after_seq: int, limit: int) -> list[Message]:
        async with self._pool.connection() as conn:
            repo = SessionRepository(conn)
            await repo.get(session_id)  # 404 for an unknown session
            return await repo.messages(session_id, after_seq=after_seq, limit=limit)

    async def update(self, session_id: uuid.UUID, *, title: str | None, archive: bool) -> Session:
        async with self._pool.connection() as conn:
            async with conn.transaction():
                repo = SessionRepository(conn)
                await repo.lock(session_id)
                if title is not None:
                    await repo.rename(session_id, title)
            if archive:
                await self.archive(session_id)
            return await SessionRepository(conn).get(session_id)

    async def archive(self, session_id: uuid.UUID) -> Run | None:
        """active → archived once, and a `session_end` run (R15.6). None if it was
        already archived. An active turn may finish; no new turn is accepted."""
        async with self._pool.connection() as conn:
            runs = RunRepository(conn)
            async with conn.transaction():
                repo = SessionRepository(conn)
                session = await repo.lock(session_id)
                if not await repo.archive(session_id):
                    return None
                run = await runs.create(
                    graph_name=session.graph_name, kind="session_end",
                    input={"session_id": str(session_id)},
                    limits={"timeout_s": 60, "max_steps": 1},
                )  # fmt: skip
        await publish_events(self._bus, runs.emitted)
        await self._enqueue(run.id)
        return run

    async def archive_idle(self, ttl_s: float) -> int:
        """The sweep (R15.6): archive sessions idle past the TTL; each gets session_end."""
        async with self._pool.connection() as conn:
            idle = await SessionRepository(conn).idle(ttl_s)
        archived = 0
        for session_id in idle:
            if await self.archive(session_id) is not None:
                archived += 1
        return archived

    # ------------------------------------------------------------------- turns

    async def send(
        self,
        session_id: uuid.UUID,
        content: str,
        options: dict[str, Any] | None = None,
        *,
        script: list[dict[str, Any]] | None = None,
        subagent_scripts: dict[str, list[dict[str, Any]]] | None = None,
    ) -> Turn:
        """R12.2. Raises SessionNotFound, SessionArchived, TurnActive (→ 409),
        AdmissionPaused, Overloaded, pydantic.ValidationError, LimitAboveCeiling."""
        session = await self.get(session_id)
        inp: dict[str, Any] = {"message": content}
        if script is not None:
            inp["script"] = script
        if subagent_scripts is not None:
            inp["subagent_scripts"] = subagent_scripts
        prepared = prepare(self._graphs, self._settings, session.graph_name, inp, options)
        await self._runs.admit()
        async with self._pool.connection() as conn:
            runs = RunRepository(conn)
            repo = SessionRepository(conn)
            async with conn.transaction():
                locked = await repo.lock(session_id)
                if locked.status != "active":
                    raise SessionArchived(session_id)
                await self._check_rate(repo, session_id)
                if locked.active_run_id is not None:
                    raise TurnActive(session_id, locked.active_run_id,
                                     str(locked.active_run_status))  # fmt: skip
                run = await runs.create(
                    graph_name=prepared.graph_name, kind="turn", input=prepared.input,
                    options=prepared.options, limits=prepared.limits, session_id=session_id,
                )  # fmt: skip
                (message,) = await repo.append(
                    session_id,
                    [NewMessage(message_id(run.id, "user", 0, "user"), "user", {"text": content})],
                    run_id=run.id, epoch=None,
                )  # fmt: skip
        await publish_events(self._bus, runs.emitted)
        await publish_messages(self._bus, repo.created)
        await self._enqueue(run.id)
        return Turn(message, run)

    async def approve(
        self,
        session_id: uuid.UUID,
        decision: str,
        edits: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> Run:
        """R12.6: forward to the active run's approval and record an `approval` message,
        in one transaction. Raises NoActiveTurn, NotWaitingForApproval (→ 409)."""
        active = await self._active(session_id)
        async with self._pool.connection() as conn:
            runs = RunRepository(conn)
            repo = SessionRepository(conn)
            async with conn.transaction():
                waiting = await runs.get(active)
                run = await runs.decide_approval(
                    active, decision=decision, edits=edits, reason=reason, decided_by="local"
                )
                content = {"decision": decision, "edits": edits, "reason": reason,
                           "interrupt": waiting.interrupt_payload}  # fmt: skip
                await repo.append(session_id, [event_message(active, "approval", content)],
                                  run_id=active, epoch=None)  # fmt: skip
        await publish_events(self._bus, runs.emitted)
        await publish_messages(self._bus, repo.created)
        if run.status is RunStatus.QUEUED:
            await self._enqueue(run.id)
        return run

    async def cancel(self, session_id: uuid.UUID) -> Run:
        """R12.7: cancel the active turn; the session stays active. A turn nobody was
        executing ends now, so its `error` message is written here; a running turn's
        worker writes it when it stops."""
        active = await self._active(session_id)
        run = await self._runs.cancel(active)
        if run.status is RunStatus.CANCELLED:
            async with self._pool.connection() as conn:
                repo = SessionRepository(conn)
                async with conn.transaction():
                    await repo.append(
                        session_id,
                        [event_message(active, "error", {"reason": "cancel_requested"})],
                        run_id=active, epoch=None,
                    )  # fmt: skip
            await publish_messages(self._bus, repo.created)
        return run

    async def _check_rate(self, repo: SessionRepository, session_id: uuid.UUID) -> None:
        """R14.8: at most N user messages per session per minute (under the session lock,
        so concurrent senders can't both slip through)."""
        limit = self._settings.session_messages_per_minute
        recent = await repo.recent_user_messages(session_id, within_s=60)
        if recent >= limit:
            raise Overloaded(
                recent, limit, retry_after_s=60, reason="rate_limited",
                detail=f"at most {limit} messages per minute in a session",
            )  # fmt: skip

    async def _active(self, session_id: uuid.UUID) -> uuid.UUID:
        session = await self.get(session_id)
        if session.active_run_id is None:
            raise NoActiveTurn(session_id)
        return session.active_run_id

    async def _enqueue(self, run_id: uuid.UUID) -> None:
        if self._relay is None:
            return
        try:
            await self._relay.enqueue(run_id)
        except Exception:
            log.warning("run %s is queued but not sent; the relay will send it", run_id,
                        exc_info=True)  # fmt: skip


__all__ = ["NotAnAgent", "Overloaded", "SessionService", "Turn", "UnknownGraph"]

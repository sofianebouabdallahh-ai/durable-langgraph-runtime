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

from psycopg.errors import UniqueViolation

from agent_runtime.agents.schema import AgentDefinition
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import GraphRegistry, UnknownGraph
from agent_runtime.runs.limits import playground_limits
from agent_runtime.runs.relay import OutboxRelay
from agent_runtime.runs.service import Overloaded, RunService, prepare_spec
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


class DuplicateSend(Exception):
    """Two attempts of one send (same idempotency key) raced; retry to get the turn."""


class ChatLimitReached(Exception):
    """The agent allows this many messages per chat (`max_session_turns`)."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"This chat has reached its limit of {limit} messages: start a new chat.")
        self.limit = limit


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
        self._agents = runs.agents
        self._relay = relay
        self._bus = bus

    # ---------------------------------------------------------------- sessions

    async def create(
        self, agent: str, title: str | None = None, *, playground_of: uuid.UUID | None = None
    ) -> Session:
        """A chat with a built-in or published agent; or, with `playground_of`, a test
        chat with that user agent's draft (hidden from the chat list)."""
        if playground_of is None:
            try:
                if self._graphs.get(agent).agent is None:
                    raise NotAnAgent(agent)
            except UnknownGraph:
                if not await self._agents.exists(agent):
                    raise
        async with self._pool.connection() as conn, conn.transaction():
            return await SessionRepository(conn).create(
                graph_name=agent, agent_name=agent, title=title, playground_of=playground_of
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
                # session_end runs the hooks of the version the chat last ran (R15.4)
                cur = await conn.execute(
                    "SELECT agent_hash, agent_name, agent_version FROM runs "
                    "WHERE session_id = %s AND agent_hash IS NOT NULL "
                    "ORDER BY created_at DESC LIMIT 1",
                    (session_id,),
                )
                last = await cur.fetchone()
                run = await runs.create(
                    graph_name=session.graph_name, kind="session_end",
                    input={"session_id": str(session_id)},
                    limits={"timeout_s": 60, "max_steps": 1},
                    agent=(last["agent_hash"], last["agent_name"], last["agent_version"])
                    if last else None,
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
        idempotency_key: str | None = None,
    ) -> Turn:
        """R12.2. Raises SessionNotFound, SessionArchived, TurnActive (→ 409),
        AdmissionPaused, Overloaded, pydantic.ValidationError, LimitAboveCeiling,
        AgentUnavailable.

        The turn pins its agent: the definition is resolved and snapshotted now, and
        the run stores the bundle hash (R15.4, AC47). With an `idempotency_key`, a
        retried send returns the turn the first attempt created."""
        session = await self.get(session_id)
        if idempotency_key and (done := await self._sent(session_id, idempotency_key)):
            return done
        async with self._pool.connection() as conn:
            pinned = await self._agents.resolve(conn, session.graph_name,
                                                draft_of=session.playground_of)  # fmt: skip
            # Its models, bound now: a later change of the default can't move this turn.
            bindings = await self._runs.models.bind(conn, pinned.definition)
            limit = pinned.definition.frontmatter.max_session_turns
            if limit is not None:
                cur = await conn.execute(
                    "SELECT count(*) AS n FROM session_messages WHERE session_id = %s "
                    "AND type = 'user'",
                    (session_id,),
                )
                sent = (await cur.fetchone() or {}).get("n", 0)
                if sent >= limit:
                    raise ChatLimitReached(limit)
        if script is None and self._settings.model_provider == "scripted":
            script, subagent_scripts = self._demo(pinned.definition, content)
        inp: dict[str, Any] = {"message": content}
        if script is not None:
            inp["script"] = script
        if subagent_scripts is not None:
            inp["subagent_scripts"] = subagent_scripts
        prepared = prepare_spec(self._agents.spec_of(pinned), self._settings, inp, options)
        limits = prepared.limits
        if session.playground_of is not None:  # a test chat: the small test budget (R17.3)
            limits = playground_limits(limits, self._settings)
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
                try:
                    run = await runs.create(
                        graph_name=prepared.graph_name, kind="turn", input=prepared.input,
                        options=prepared.options, limits=limits, session_id=session_id,
                        agent=(pinned.bundle_hash, pinned.definition.id, pinned.version),
                        idempotency_key=idempotency_key, model_bindings=bindings,
                    )  # fmt: skip
                except UniqueViolation:  # the same send, raced: the other attempt won
                    raise DuplicateSend from None
                (message,) = await repo.append(
                    session_id,
                    [NewMessage(message_id(run.id, "user", 0, "user"), "user", {"text": content})],
                    run_id=run.id, epoch=None,
                )  # fmt: skip
        await publish_events(self._bus, runs.emitted)
        await publish_messages(self._bus, repo.created)
        await self._enqueue(run.id)
        return Turn(message, run)

    async def _sent(self, session_id: uuid.UUID, key: str) -> Turn | None:
        """The turn an earlier attempt of this send created, if any."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id FROM runs WHERE session_id = %s AND idempotency_key = %s",
                (session_id, key),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            run = await RunRepository(conn).get(row["id"])
            message = await SessionRepository(conn).message(
                session_id, message_id(run.id, "user", 0, "user")
            )
        return Turn(message, run) if message else None

    @staticmethod
    def _demo(
        agent: AgentDefinition, content: str
    ) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]] | None]:
        """The offline demo model's reply to free text (models/demo.py). Stored in the
        run's input like a sent script, so replays read it back."""
        from agent_runtime.models.demo import demo_script

        script, subs = demo_script(content, agent)
        return script, subs or None

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

"""One client's live stream of a run: the imperative shell around StreamMerger (R2.5).

    1. subscribe to run:{id} (confirmed) BEFORE reading Postgres, so no event can
       fall between the replay and the live feed;
    2. replay from Postgres: every event after the client's Last-Event-ID;
    3. live: feed Pub/Sub events to the merger; back-fill any hole from Postgres;
    4. safety net: if nothing live arrived for `stream_poll_s`, poll Postgres
       (Pub/Sub is at-most-once: even the final run.completed may be lost);
    5. `: ping` keep-alive when idle; close after the terminal event;
       `event: reconnect` when this replica is shutting down (R10.7).

Output is SSE-encoded bytes. Persisted events carry `id: <seq>` (the browser
sends it back as Last-Event-ID); transient events carry no id.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from fastapi.sse import format_sse_event

from agent_runtime.config import Settings
from agent_runtime.db import Conn, Pool
from agent_runtime.runs.store import RunRepository
from agent_runtime.streaming.broker import Broker
from agent_runtime.streaming.bus import (
    StreamEvent,
    run_channel,
    session_channel,
    to_stream_event,
)
from agent_runtime.streaming.merger import StreamMerger

RETRY_MS = 2000  # browser reconnect delay after a dropped connection
PAGE = 500


def encode(event: StreamEvent) -> bytes:
    data = json.loads(event.to_json())
    return format_sse_event(
        data_str=json.dumps(data, separators=(",", ":")),
        event=event.type,
        id=str(event.seq) if event.persisted else None,
    )


class PersistedStream(ABC):
    """Pattern: Template Method. The algorithm above, for any persisted, seq-ordered
    log with a Pub/Sub channel. Subclasses say which channel and how to read a page."""

    def __init__(
        self,
        pool: Pool,
        broker: Broker,
        settings: Settings,
        *,
        after_seq: int,
        draining: asyncio.Event,
    ) -> None:
        self._pool = pool
        self._broker = broker
        self._settings = settings
        self._merger = StreamMerger(after_seq, max_buffer=settings.stream_queue_size)
        self._draining = draining

    @abstractmethod
    def channel(self) -> str: ...

    @abstractmethod
    async def page(self, conn: Conn, *, after: int, limit: int) -> list[StreamEvent]:
        """Persisted items with seq > after, in order."""

    async def events(self) -> AsyncIterator[bytes]:
        yield format_sse_event(retry=RETRY_MS, comment="stream open")
        async with self._broker.listen(self.channel()) as listener:
            for chunk in await self._catch_up():
                yield chunk
            now = time.monotonic()
            last_live, last_sent = now, now
            while not self._merger.done:
                if self._draining.is_set():
                    yield format_sse_event(
                        event="reconnect",
                        data_str=json.dumps({"after_seq": self._merger.last}),
                        retry=0,
                    )
                    return
                if listener.take_overflow():  # we fell behind: Postgres has it all
                    while not listener.queue.empty():
                        listener.queue.get_nowait()
                    for chunk in await self._catch_up():
                        yield chunk
                    last_sent = time.monotonic()

                now = time.monotonic()
                wait = min(
                    self._settings.stream_ping_s - (now - last_sent),
                    self._settings.stream_poll_s - (now - last_live),
                )
                event = await self._next_live(listener.queue, max(wait, 0.0))
                now = time.monotonic()
                if event is not None:
                    last_live = now
                    chunks = await self._on_live(event)
                elif now - last_live >= self._settings.stream_poll_s:
                    last_live = now  # safety net: nothing live for a while
                    chunks = await self._catch_up()
                else:
                    chunks = []
                if chunks:
                    for chunk in chunks:
                        yield chunk
                    last_sent = now
                elif now - last_sent >= self._settings.stream_ping_s:
                    yield format_sse_event(comment="ping")
                    last_sent = now

    async def _next_live(
        self, queue: asyncio.Queue[StreamEvent], wait_s: float
    ) -> StreamEvent | None:
        """Next live event, or None after `wait_s` or when draining starts."""
        getter = asyncio.ensure_future(queue.get())
        drain = asyncio.ensure_future(self._draining.wait())
        try:
            done, _ = await asyncio.wait(
                {getter, drain}, timeout=wait_s, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for task in (getter, drain):
                if not task.done():
                    task.cancel()
        return getter.result() if getter in done and not getter.cancelled() else None

    async def _on_live(self, event: StreamEvent) -> list[bytes]:
        if not event.persisted:
            transient = self._merger.accept_transient(event)
            return [encode(transient)] if transient else []
        out = self._merger.accept([event])
        if (gap := self._merger.gap) is not None:  # a publish was lost: back-fill the hole
            out += self._merger.accept(await self._read(after=gap[0], through=gap[1]))
        if self._merger.overflowing:
            out += self._merger.accept(await self._read(after=self._merger.last))
        return [encode(e) for e in out]

    async def _catch_up(self) -> list[bytes]:
        """Everything after what the client has seen, from Postgres, paged."""
        out: list[bytes] = []
        while not self._merger.done:
            page = await self._read(after=self._merger.last, limit=PAGE)
            if not page:
                break
            out += [encode(e) for e in self._merger.accept(page)]
            if len(page) < PAGE:
                break
        return out

    async def _read(
        self, *, after: int, through: int | None = None, limit: int = PAGE
    ) -> list[StreamEvent]:
        if through is not None:
            limit = max(1, through - after)
        async with self._pool.connection() as conn:
            return await self.page(conn, after=after, limit=limit)


class RunStream(PersistedStream):
    """`GET /runs/{id}/stream`: the run's events; closes after its terminal event."""

    def __init__(self, pool: Pool, broker: Broker, settings: Settings, run_id: uuid.UUID,
                 *, after_seq: int, draining: asyncio.Event) -> None:  # fmt: skip
        super().__init__(pool, broker, settings, after_seq=after_seq, draining=draining)
        self._run_id = run_id

    def channel(self) -> str:
        return run_channel(self._run_id)

    async def page(self, conn: Conn, *, after: int, limit: int) -> list[StreamEvent]:
        rows = await RunRepository(conn).list_events(self._run_id, after_seq=after, limit=limit)
        return [to_stream_event(r) for r in rows]


class SessionStream(PersistedStream):
    """`GET /sessions/{id}/stream` (R12.5): the session's transcript, across all its
    turns, plus transient events of the active turn. It never ends on its own: the
    client closes it (or a drain asks it to reconnect)."""

    def __init__(self, pool: Pool, broker: Broker, settings: Settings,
                 session_id: uuid.UUID, *, after_seq: int,
                 draining: asyncio.Event) -> None:  # fmt: skip
        super().__init__(pool, broker, settings, after_seq=after_seq, draining=draining)
        self._session_id = session_id

    def channel(self) -> str:
        return session_channel(self._session_id)

    async def page(self, conn: Conn, *, after: int, limit: int) -> list[StreamEvent]:
        from agent_runtime.sessions.store import SessionRepository
        from agent_runtime.sessions.transcript import to_stream_event as message_event

        rows = await SessionRepository(conn).messages(
            self._session_id, after_seq=after, limit=limit
        )
        return [message_event(m) for m in rows]

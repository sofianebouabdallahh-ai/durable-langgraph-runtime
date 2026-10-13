"""Event bus (R1.5, R2.5): low-latency fan-out of run events to API replicas.

Pattern: Ports & Adapters. `EventBus` is the port; `RedisEventBus` (Redis
Pub/Sub) is the production adapter, `InMemoryEventBus` a fake for tests.

Redis Pub/Sub is at-most-once: a message is lost if no subscriber is connected
or a subscriber fails while handling it. That's acceptable *only* because the
bus is a wake-up hint: every persisted event is already in Postgres before it
is published, and readers replay and back-fill from there.

Wire format (JSON):
- persisted event: {"run_id", "seq", "ts", "epoch", "type", "payload"}
- transient event (e.g. `token`, never persisted): same, with "seq": null and
  "after_seq": the last persisted seq it follows.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

log = logging.getLogger(__name__)

TERMINAL_EVENTS = frozenset({"run.completed", "run.failed", "run.cancelled"})


def run_channel(run_id: uuid.UUID) -> str:
    return f"run:{run_id}"


def session_channel(session_id: uuid.UUID) -> str:  # CR-001, phase 6
    return f"session:{session_id}"


@dataclass(frozen=True, slots=True)
class StreamEvent:
    run_id: uuid.UUID
    seq: int | None  # None for transient events
    ts: datetime
    epoch: int
    type: str
    payload: dict[str, Any]
    after_seq: int | None = None  # transient events: the persisted seq they follow

    @property
    def persisted(self) -> bool:
        return self.seq is not None

    @property
    def terminal(self) -> bool:
        return self.type in TERMINAL_EVENTS

    def to_json(self) -> str:
        return json.dumps(
            {
                "run_id": str(self.run_id),
                "seq": self.seq,
                "after_seq": self.after_seq,
                "ts": self.ts.isoformat(),
                "epoch": self.epoch,
                "type": self.type,
                "payload": self.payload,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> StreamEvent:
        d = json.loads(raw)
        return cls(
            run_id=uuid.UUID(d["run_id"]),
            seq=d["seq"],
            after_seq=d.get("after_seq"),
            ts=datetime.fromisoformat(d["ts"]),
            epoch=int(d["epoch"]),
            type=str(d["type"]),
            payload=dict(d["payload"]),
        )


def to_stream_event(event: Any) -> StreamEvent:
    """A persisted run event (runs.store.Event) in wire form."""
    return StreamEvent(
        run_id=event.run_id, seq=event.seq, ts=event.ts, epoch=event.epoch,
        type=str(event.type), payload=event.payload,
    )  # fmt: skip


async def publish_events(bus: EventBus | None, events: list[Any]) -> None:
    """Best effort, after commit. A lost publish only costs latency: readers
    back-fill from Postgres. It must never fail the run that produced it."""
    if bus is None:
        return
    for event in events:
        try:
            await bus.publish(run_channel(event.run_id), to_stream_event(event))
        except Exception:
            log.warning("publish of %s seq %s failed; readers will back-fill",
                        event.type, event.seq, exc_info=True)  # fmt: skip


class Subscription(Protocol):
    """One connection, many channels."""

    async def subscribe(self, channel: str) -> None:
        """Returns once the server has *confirmed* the subscription."""

    async def unsubscribe(self, channel: str) -> None: ...
    async def get(self, wait_s: float) -> tuple[str, StreamEvent] | None:
        """Next message, waiting up to `wait_s`; None if nothing arrived (a poll)."""

    async def close(self) -> None: ...


class EventBus(Protocol):
    async def publish(self, channel: str, event: StreamEvent) -> None: ...
    def subscription(self) -> Subscription: ...


# --------------------------------------------------------------------- Redis


class RedisEventBus:
    def __init__(self, redis: Redis) -> None:
        self._r = redis

    async def publish(self, channel: str, event: StreamEvent) -> None:
        await self._r.publish(channel, event.to_json())

    def subscription(self) -> RedisSubscription:
        return RedisSubscription(self._r.pubsub())


class RedisSubscription:
    """Not safe for concurrent use: one owner task (the Broker) drives it."""

    def __init__(self, pubsub: PubSub) -> None:
        self._ps = pubsub
        self._channels: set[str] = set()
        self._confirm: dict[str, asyncio.Future[None]] = {}
        self._buffer: list[tuple[str, StreamEvent]] = []

    async def subscribe(self, channel: str) -> None:
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._confirm[channel] = fut
        await self._ps.subscribe(channel)
        self._channels.add(channel)
        # Read until Redis confirms; messages that arrive meanwhile are kept.
        while not fut.done():
            await self._read(wait_s=1.0)

    async def unsubscribe(self, channel: str) -> None:
        self._channels.discard(channel)
        await self._ps.unsubscribe(channel)

    async def get(self, wait_s: float) -> tuple[str, StreamEvent] | None:
        if self._buffer:
            return self._buffer.pop(0)
        if not self._channels:  # redis-py refuses to read with no subscriptions
            await asyncio.sleep(wait_s)
            return None
        await self._read(wait_s)
        return self._buffer.pop(0) if self._buffer else None

    async def _read(self, wait_s: float) -> None:
        msg = await self._ps.get_message(ignore_subscribe_messages=False, timeout=wait_s)
        if msg is None:
            return
        channel = msg["channel"]
        channel = channel.decode() if isinstance(channel, bytes) else str(channel)
        if msg["type"] == "subscribe":
            if (fut := self._confirm.pop(channel, None)) and not fut.done():
                fut.set_result(None)
        elif msg["type"] == "message":
            try:
                self._buffer.append((channel, StreamEvent.from_json(msg["data"])))
            except (ValueError, KeyError, TypeError):
                log.warning("dropping malformed event on %s", channel)

    async def close(self) -> None:
        await self._ps.aclose()  # type: ignore[no-untyped-call]  # redis-py lacks hints


# ------------------------------------------------------------------- in-memory


class InMemoryEventBus:
    """Same semantics as Redis Pub/Sub (fire-and-forget; only current subscribers)."""

    def __init__(self) -> None:
        self._subs: list[InMemorySubscription] = []
        self.published: list[tuple[str, StreamEvent]] = []  # for assertions

    async def publish(self, channel: str, event: StreamEvent) -> None:
        self.published.append((channel, event))
        for sub in self._subs:
            if channel in sub.channels:
                sub.inbox.put_nowait((channel, event))

    def subscription(self) -> InMemorySubscription:
        sub = InMemorySubscription(self)
        self._subs.append(sub)
        return sub


class InMemorySubscription:
    def __init__(self, bus: InMemoryEventBus) -> None:
        self._bus = bus
        self.channels: set[str] = set()
        self.inbox: asyncio.Queue[tuple[str, StreamEvent]] = asyncio.Queue()

    async def subscribe(self, channel: str) -> None:
        self.channels.add(channel)

    async def unsubscribe(self, channel: str) -> None:
        self.channels.discard(channel)

    async def get(self, wait_s: float) -> tuple[str, StreamEvent] | None:
        try:
            return await asyncio.wait_for(self.inbox.get(), timeout=wait_s)
        except TimeoutError:
            return None

    async def close(self) -> None:
        if self in self._bus._subs:
            self._bus._subs.remove(self)

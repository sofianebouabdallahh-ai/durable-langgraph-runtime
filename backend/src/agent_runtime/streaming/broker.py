"""Broker: one Pub/Sub subscription per API replica, fanned out to local streams.

Patterns:
- Pub/Sub multiplexer: however many clients a replica streams to, it holds ONE
  Redis subscription connection. A channel is subscribed when the first local
  stream needs it and unsubscribed when the last one leaves (reference count).
- Single reader: only the broker's reader task reads from the subscription;
  stream tasks only send SUBSCRIBE/UNSUBSCRIBE, and the reader resolves the
  confirmation as soon as Redis replies (one round trip per new channel).
- Bounded queues (backpressure without blocking): each stream gets its own
  bounded queue. A stream that can't keep up is flagged `overflowed` instead
  of slowing the broker (and every other stream) down; it then catches up from
  Postgres, which has every event anyway.

If Redis is unavailable or live streaming is disabled, listeners simply receive
nothing live; streams still complete through Postgres (replay, back-fill and the
safety-net poll), only slower.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass

from agent_runtime.streaming.bus import EventBus, StreamEvent, Subscription

log = logging.getLogger(__name__)


@dataclass(eq=False)
class Listener:
    channel: str
    queue: asyncio.Queue[StreamEvent]
    overflowed: bool = False  # dropped live events: the stream must catch up from Postgres
    live: bool = True  # False if the subscription couldn't be made (Redis down / disabled)

    def take_overflow(self) -> bool:
        """True once per overflow: the caller drains the queue and catches up."""
        if self.overflowed:
            self.overflowed = False
            return True
        return False


class Broker:
    def __init__(self, bus: EventBus | None, *, queue_size: int = 1000) -> None:
        self._bus = bus
        self._queue_size = queue_size
        self._listeners: dict[str, set[Listener]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._sub: Subscription | None = None
        self._task: asyncio.Task[None] | None = None
        self.subscriptions_opened = 0  # for tests and metrics

    @property
    def channels(self) -> int:
        return sum(1 for ls in self._listeners.values() if ls)

    async def start(self) -> None:
        if self._bus is not None:
            self._task = asyncio.create_task(self._run())
            for _ in range(100):  # wait (≤ 1 s) until the subscription exists
                if self._sub is not None:
                    break
                await asyncio.sleep(0.01)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._sub is not None:
            with contextlib.suppress(Exception):
                await self._sub.close()

    @contextlib.asynccontextmanager
    async def listen(self, channel: str) -> AsyncIterator[Listener]:
        """Subscribe (confirmed by the server before this yields), then fan in."""
        listener = Listener(channel, asyncio.Queue(maxsize=self._queue_size))
        async with self._lock:
            first = not self._listeners[channel]
            self._listeners[channel].add(listener)
            listener.live = await self._subscribe(channel) if first else self._sub is not None
        try:
            yield listener
        finally:
            async with self._lock:
                self._listeners[channel].discard(listener)
                if not self._listeners[channel]:
                    del self._listeners[channel]
                    if self._sub is not None:
                        with contextlib.suppress(Exception):
                            await self._sub.unsubscribe(channel)

    async def _subscribe(self, channel: str) -> bool:
        if self._sub is None:
            return False
        try:
            await self._sub.subscribe(channel)
            return True
        except Exception:
            log.warning("broker: subscribe %s failed; stream falls back to polling", channel)
            return False

    async def _run(self) -> None:
        """The only task that touches the subscription."""
        assert self._bus is not None
        while True:
            try:
                self._sub = None
                sub = self._bus.subscription()
                self.subscriptions_opened += 1
                # After a reconnect: resubscribe, and make streams catch up. This runs in
                # standalone mode (subscribe reads its own confirmation): attaching the
                # reader first would make each subscribe wait for a reader that only
                # starts afterwards, so reconnecting would never succeed.
                for channel, listeners in list(self._listeners.items()):
                    if listeners:
                        await sub.subscribe(channel)
                        for listener in listeners:
                            listener.overflowed = True
                sub.attach_reader()  # from here on, _serve is its only reader
                self._sub = sub
                await self._serve(sub)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("broker: subscription lost; reconnecting", exc_info=True)
                await asyncio.sleep(1)

    async def _serve(self, sub: Subscription) -> None:
        while True:
            message = await sub.get(wait_s=1.0)
            if message is None:
                continue
            channel, event = message
            for listener in list(self._listeners.get(channel, ())):
                try:
                    listener.queue.put_nowait(event)
                except asyncio.QueueFull:
                    listener.overflowed = True  # never block the broker for one slow stream

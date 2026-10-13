"""Work queue (R2.1): delivers "run X may need work" hints to workers.

Pattern: Ports & Adapters. Workers depend on the `WorkQueue` protocol only.
`RedisWorkQueue` is the production adapter (a Redis Stream + consumer group);
`InMemoryWorkQueue` is a fake with the same semantics for fast unit tests. One
contract test suite runs against both.

Semantics (competing consumers, at-least-once):
- `read` delivers each new message to exactly one consumer and records it in
  the group's pending entries list (PEL) until `ack`.
- A message is a *hint*, never the source of truth: Postgres (the run's lease)
  decides who executes a run. Duplicates are therefore harmless.
- `touch` re-claims your own pending message, resetting its idle time, so the
  reaper's `autoclaim` (idle > lease TTL) only takes messages of dead workers.
- `ack` also deletes the message from the stream: the stream holds only
  unfinished work, stays small, and "message still exists" means "not done".
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Delivery:
    message_id: str
    run_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class Claimed:
    deliveries: list[Delivery]
    deleted_ids: list[str]  # pending but gone from the stream; dropped from the PEL


class WorkQueue(Protocol):
    async def ensure_group(self) -> None: ...
    async def enqueue(self, run_id: uuid.UUID) -> str: ...
    async def read(self, consumer: str, count: int, block_ms: int) -> list[Delivery]: ...
    async def ack(self, *message_ids: str) -> int: ...
    async def touch(self, consumer: str, message_id: str) -> bool: ...
    async def autoclaim(self, consumer: str, min_idle_ms: int, count: int) -> Claimed: ...
    async def exists(self, message_id: str) -> bool: ...
    async def pending_count(self) -> int: ...
    async def remove_consumer_if_idle(self, consumer: str) -> bool: ...


def _parse(message_id: str, fields: dict[str, str]) -> Delivery | None:
    try:
        return Delivery(message_id, uuid.UUID(fields["run_id"]))
    except (KeyError, ValueError):
        return None


class RedisWorkQueue:
    def __init__(self, redis: Redis, stream: str, group: str) -> None:
        self._r = redis
        self.stream = stream
        self.group = group

    async def ensure_group(self) -> None:
        try:
            await self._r.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):  # already exists: fine (idempotent)
                raise

    async def enqueue(self, run_id: uuid.UUID) -> str:
        return str(await self._r.xadd(self.stream, {"run_id": str(run_id)}))

    async def read(self, consumer: str, count: int, block_ms: int) -> list[Delivery]:
        reply = await self._r.xreadgroup(
            self.group, consumer, {self.stream: ">"}, count=count, block=block_ms
        )
        # RESP2 reply: [[stream, [(id, {field: value}), ...]], ...]. Strings, because the
        # client is created with decode_responses=True (redis-py's types can't know that).
        streams = cast("list[tuple[str, list[tuple[str, dict[str, str]]]]]", reply or [])
        return await self._deliveries([m for _, messages in streams for m in messages])

    async def ack(self, *message_ids: str) -> int:
        if not message_ids:
            return 0
        async with self._r.pipeline(transaction=True) as pipe:
            pipe.xack(self.stream, self.group, *message_ids)
            pipe.xdel(self.stream, *message_ids)
            acked, _ = await pipe.execute()
        return int(acked)

    async def touch(self, consumer: str, message_id: str) -> bool:
        claimed = await self._r.xclaim(
            self.stream, self.group, consumer, min_idle_time=0,
            message_ids=[message_id], justid=True,
        )  # fmt: skip
        return bool(claimed)

    async def autoclaim(self, consumer: str, min_idle_ms: int, count: int) -> Claimed:
        _, messages, deleted = await self._r.xautoclaim(
            self.stream, self.group, consumer, min_idle_time=min_idle_ms, count=count
        )
        return Claimed(await self._deliveries(messages), list(deleted))

    async def exists(self, message_id: str) -> bool:
        return bool(await self._r.xrange(self.stream, min=message_id, max=message_id, count=1))

    async def pending_count(self) -> int:
        try:
            info = await self._r.xpending(self.stream, self.group)
        except ResponseError:  # no group yet
            return 0
        return int(info["pending"])

    async def remove_consumer_if_idle(self, consumer: str) -> bool:
        """Drop a consumer from the group only if it holds no pending messages."""
        for c in await self._r.xinfo_consumers(self.stream, self.group):
            if c["name"] == consumer:
                if int(c["pending"]) > 0:
                    return False
                await self._r.xgroup_delconsumer(self.stream, self.group, consumer)
                return True
        return False

    async def _deliveries(self, raw: Sequence[tuple[str, dict[str, str]]]) -> list[Delivery]:
        out: list[Delivery] = []
        for message_id, fields in raw:
            if (d := _parse(message_id, fields)) is not None:
                out.append(d)
            else:  # poison message: never deliverable; drop it so it can't loop forever
                log.error("dropping malformed work message %s: %r", message_id, fields)
                await self.ack(message_id)
        return out


# ---------------------------------------------------------------------- fake


@dataclass
class _Pending:
    consumer: str
    delivered_at: float


@dataclass
class InMemoryWorkQueue:
    """Same semantics as RedisWorkQueue, in memory. For unit tests only."""

    entries: dict[str, uuid.UUID] = field(default_factory=dict)  # stream (insertion-ordered)
    pending: dict[str, _Pending] = field(default_factory=dict)  # PEL
    _next_unread: int = 0
    _seq: int = 0
    _consumers: set[str] = field(default_factory=set)

    async def ensure_group(self) -> None:
        return None

    async def enqueue(self, run_id: uuid.UUID) -> str:
        self._seq += 1
        message_id = f"{int(time.time() * 1000)}-{self._seq}"
        self.entries[message_id] = run_id
        return message_id

    async def read(self, consumer: str, count: int, block_ms: int) -> list[Delivery]:
        self._consumers.add(consumer)
        ids = list(self.entries)[self._next_unread : self._next_unread + count]
        self._next_unread += len(ids)
        now = time.monotonic()
        for mid in ids:
            self.pending[mid] = _Pending(consumer, now)
        return [Delivery(mid, self.entries[mid]) for mid in ids]

    async def ack(self, *message_ids: str) -> int:
        acked = 0
        for mid in message_ids:
            if self.pending.pop(mid, None) is not None:
                acked += 1
            if mid in self.entries:
                index = list(self.entries).index(mid)
                del self.entries[mid]
                if index < self._next_unread:
                    self._next_unread -= 1
        return acked

    async def touch(self, consumer: str, message_id: str) -> bool:
        if message_id not in self.pending or message_id not in self.entries:
            return False
        self.pending[message_id] = _Pending(consumer, time.monotonic())
        return True

    async def autoclaim(self, consumer: str, min_idle_ms: int, count: int) -> Claimed:
        now = time.monotonic()
        claimed: list[Delivery] = []
        deleted: list[str] = []
        for mid, p in list(self.pending.items()):
            if len(claimed) >= count:
                break
            if (now - p.delivered_at) * 1000 < min_idle_ms:
                continue
            if mid not in self.entries:
                del self.pending[mid]
                deleted.append(mid)
                continue
            self.pending[mid] = _Pending(consumer, now)
            claimed.append(Delivery(mid, self.entries[mid]))
        return Claimed(claimed, deleted)

    async def exists(self, message_id: str) -> bool:
        return message_id in self.entries

    async def pending_count(self) -> int:
        return len(self.pending)

    async def remove_consumer_if_idle(self, consumer: str) -> bool:
        if any(p.consumer == consumer for p in self.pending.values()):
            return False
        if consumer in self._consumers:
            self._consumers.discard(consumer)
            return True
        return False


def create_redis(url: str) -> Redis:
    """String responses (not bytes); short socket timeouts so a dead Redis fails fast."""
    return Redis.from_url(
        url, decode_responses=True, socket_connect_timeout=3, health_check_interval=30
    )

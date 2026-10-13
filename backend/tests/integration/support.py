"""Helpers shared by integration tests."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from agent_runtime.db import Pool
from agent_runtime.runs.events import EventType as E
from agent_runtime.runs.store import Event, RunRepository


async def events(pool: Pool, run_id: uuid.UUID) -> list[Event]:
    async with pool.connection() as conn:
        return await RunRepository(conn).list_events(run_id, limit=1000)


def summary(evts: list[Event]) -> list[tuple[str, Any]]:
    return [(e.type, e.payload.get("node") or e.payload.get("reason")) for e in evts]


async def node_completed(pool: Pool, run_id: uuid.UUID, node: str) -> bool:
    return (E.NODE_COMPLETED, node) in summary(await events(pool, run_id))


async def wait_until(
    predicate: Callable[[], Awaitable[bool]], *, timeout_s: float = 10, interval_s: float = 0.05
) -> None:
    """Poll external state (the database) until `predicate` holds, or fail.

    An asyncio.Event can't observe another process's writes, so polling is the
    right tool here; the deadline guarantees a broken test fails, never hangs.
    """
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not await predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError(f"condition not met within {timeout_s}s")
        await asyncio.sleep(interval_s)

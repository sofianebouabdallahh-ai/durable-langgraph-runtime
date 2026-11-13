"""The heartbeat gives up once renewals have failed for a whole lease (H10).

Before, `RunExecutor._heartbeat` retried forever: a worker cut off from Postgres kept
driving its run while the reaper, which could still reach Postgres, handed the run to
another worker, and only the fence caught the zombie's writes, one by one. Now the
heartbeat returns, which the executor treats as the lease being lost (`LeaseLost`), and
the execution stops locally. No database: the pool and the repository are fakes.
"""

from __future__ import annotations

import asyncio
import itertools
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import cast

import pytest

from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.fencing import Fence
from agent_runtime.graphs import GraphRegistry
from agent_runtime.runs import executor as executor_module
from agent_runtime.runs.executor import RunExecutor

TTL = 0.2  # seconds; the heartbeat is a quarter of it (the setting allows up to a third)
HEARTBEAT = 0.05
FENCE = Fence(uuid.uuid4(), 1)


class _FakePool:
    @asynccontextmanager
    async def connection(self) -> AsyncIterator[object]:
        yield object()


def _down() -> bool:
    raise ConnectionError("Postgres unreachable")


def _ok() -> bool:
    return True


def _executor(
    monkeypatch: pytest.MonkeyPatch,
    renew: Callable[[], bool],
    on_heartbeat: Callable[[], Awaitable[object]] | None = None,
) -> tuple[RunExecutor, list[str]]:
    """An executor over a fake pool whose `renew_lease` answers with `renew()`: True or
    False as the database would, or raises as a lost connection does. What each renewal
    did is recorded in the returned list."""
    calls: list[str] = []

    class FakeRepo:
        def __init__(self, conn: object) -> None:
            pass

        async def renew_lease(self, fence: Fence, owner: str, ttl_s: float) -> bool:
            try:
                answer = renew()
            except Exception:
                calls.append("failed")
                raise
            calls.append("ok" if answer else "refused")
            return answer

    monkeypatch.setattr(executor_module, "RunRepository", FakeRepo)
    settings = Settings(postgres_password="pw", lease_ttl_s=TTL, heartbeat_s=HEARTBEAT)  # type: ignore[arg-type]
    ex = RunExecutor(
        cast(Pool, _FakePool()), settings, GraphRegistry([]), owner="w:1",
        on_heartbeat=on_heartbeat,
    )  # fmt: skip
    return ex, calls


async def test_gives_up_once_failures_have_spanned_the_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ex, calls = _executor(monkeypatch, _down)
    t0 = time.monotonic()
    await asyncio.wait_for(ex._heartbeat(FENCE), timeout=TTL * 3)  # returns: the lease is gone
    elapsed = time.monotonic() - t0
    assert calls and set(calls) == {"failed"}
    assert elapsed >= TTL  # never before the lease could have expired for the others
    assert len(calls) <= round(TTL / HEARTBEAT)  # one failure per heartbeat, ttl/heartbeat at most


async def test_a_renewal_that_succeeds_resets_the_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two failures then a success, over and over: the failures never span a whole lease,
    so the heartbeat keeps going (a single failure is a blip, not a lost lease)."""
    pattern = itertools.cycle([_down, _down, _ok])
    ex, calls = _executor(monkeypatch, lambda: next(pattern)())
    with pytest.raises(TimeoutError):  # still heartbeating after three leases' worth
        await asyncio.wait_for(ex._heartbeat(FENCE), timeout=TTL * 3)
    assert calls.count("ok") >= 2 and "failed" in calls


async def test_a_refused_renewal_stops_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Postgres answered: another worker owns the run now (the pre-H10 behaviour, kept)."""
    ex, calls = _executor(monkeypatch, lambda: False)
    await asyncio.wait_for(ex._heartbeat(FENCE), timeout=TTL)
    assert calls == ["refused"]


async def test_each_successful_renewal_touches_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    touched: list[int] = []

    async def touch() -> None:
        touched.append(1)

    ex, calls = _executor(monkeypatch, _ok, on_heartbeat=touch)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(ex._heartbeat(FENCE), timeout=HEARTBEAT * 3.5)
    assert touched and len(touched) == calls.count("ok")

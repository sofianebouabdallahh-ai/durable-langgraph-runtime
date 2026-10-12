"""RunRepository against real Postgres: atomicity, ordering and races."""

import asyncio
import uuid

import pytest

from agent_runtime.db import Pool
from agent_runtime.fencing import FencedError
from agent_runtime.ids import new_id
from agent_runtime.runs.events import EventType
from agent_runtime.runs.state import FailureReason, InvalidTransition, RunStatus
from agent_runtime.runs.store import RunNotFound, RunRepository

pytestmark = pytest.mark.integration

E = EventType
S = RunStatus


async def _new_run(pool: Pool, **kwargs: object) -> uuid.UUID:
    async with pool.connection() as conn:
        run = await RunRepository(conn).create(graph_name="toy", input={"q": "hi"}, **kwargs)  # type: ignore[arg-type]
    return run.id


async def test_create_run_is_queued_with_created_event(pool: Pool) -> None:
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        run = await repo.create(graph_name="toy", input={"q": "hi"})
        events = await repo.list_events(run.id)
    assert run.status is S.QUEUED
    assert run.thread_id == str(run.id)  # standalone run → its own thread (R1.2)
    assert run.id.version == 7
    assert [(e.seq, e.type) for e in events] == [(1, E.RUN_CREATED)]


async def test_session_run_uses_the_session_thread(pool: Pool) -> None:
    session_id = new_id()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO sessions (id, graph_name) VALUES (%s, 'chat')", (session_id,)
        )
        run = await RunRepository(conn).create(
            graph_name="chat", input={}, kind="turn", session_id=session_id
        )
    assert run.thread_id == str(session_id)


async def test_transition_updates_status_and_appends_event_atomically(pool: Pool) -> None:
    run_id = await _new_run(pool)
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        running = await repo.transition(run_id, S.RUNNING, event=E.RUN_STARTED)
        done = await repo.transition(run_id, S.COMPLETED, event=E.RUN_COMPLETED)
        events = await repo.list_events(run_id)
    assert running.started_at is not None and running.finished_at is None
    assert done.status is S.COMPLETED and done.finished_at is not None
    assert [e.type for e in events] == [E.RUN_CREATED, E.RUN_STARTED, E.RUN_COMPLETED]


async def test_failed_run_records_reason(pool: Pool) -> None:
    run_id = await _new_run(pool)
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        await repo.transition(run_id, S.RUNNING, event=E.RUN_STARTED)
        run = await repo.transition(
            run_id, S.FAILED, event=E.RUN_FAILED, reason=FailureReason.STEP_LIMIT
        )
    assert (run.status, run.reason) == (S.FAILED, "step_limit")


async def test_illegal_transition_changes_nothing(pool: Pool) -> None:
    run_id = await _new_run(pool)
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        with pytest.raises(InvalidTransition, match="from queued to completed"):
            await repo.transition(run_id, S.COMPLETED, event=E.RUN_COMPLETED)
        run = await repo.get(run_id)
        events = await repo.list_events(run_id)
    assert run.status is S.QUEUED
    assert len(events) == 1  # no orphan event from the failed attempt


async def test_racing_transitions_exactly_one_wins(pool: Pool) -> None:
    """Two processes try to end the same run at once: one wins, one is told why."""
    run_id = await _new_run(pool)
    async with pool.connection() as conn:
        await RunRepository(conn).transition(run_id, S.RUNNING, event=E.RUN_STARTED)

    async def end(target: RunStatus, event: EventType) -> RunStatus | InvalidTransition:
        async with pool.connection() as conn:
            try:
                run = await RunRepository(conn).transition(run_id, target, event=event)
                return run.status
            except InvalidTransition as exc:
                return exc

    results = await asyncio.gather(
        end(S.COMPLETED, E.RUN_COMPLETED), end(S.CANCELLED, E.RUN_CANCELLED)
    )
    winners = [r for r in results if isinstance(r, RunStatus)]
    losers = [r for r in results if isinstance(r, InvalidTransition)]
    assert len(winners) == 1 and len(losers) == 1
    assert losers[0].current is winners[0]  # the loser learns the real final state


async def test_event_seq_is_gap_free_under_concurrency(pool: Pool) -> None:
    run_id = await _new_run(pool)

    async def append(i: int) -> None:
        async with pool.connection() as conn, conn.transaction():
            await RunRepository(conn).append_event(
                run_id, epoch=1, type=E.NODE_COMPLETED, payload={"i": i}
            )

    await asyncio.gather(*(append(i) for i in range(50)))
    async with pool.connection() as conn:
        events = await RunRepository(conn).list_events(run_id, limit=1000)
    assert [e.seq for e in events] == list(range(1, 52))


async def test_rolled_back_event_does_not_consume_a_seq(pool: Pool) -> None:
    run_id = await _new_run(pool)
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        with pytest.raises(RuntimeError, match="boom"):
            async with conn.transaction():
                await repo.append_event(run_id, epoch=1, type=E.NODE_STARTED, payload={})
                raise RuntimeError("boom")
        async with conn.transaction():
            event = await repo.append_event(run_id, epoch=1, type=E.NODE_STARTED, payload={})
    assert event.seq == 2


async def test_append_event_requires_a_transaction(pool: Pool) -> None:
    run_id = await _new_run(pool)
    async with pool.connection() as conn:
        with pytest.raises(RuntimeError, match="inside a transaction"):
            await RunRepository(conn).append_event(run_id, epoch=1, type=E.NODE_STARTED, payload={})


async def test_list_events_pages_after_seq(pool: Pool) -> None:
    run_id = await _new_run(pool)
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        async with conn.transaction():
            for _ in range(5):
                await repo.append_event(run_id, epoch=1, type=E.NODE_STARTED, payload={})
        page = await repo.list_events(run_id, after_seq=2, limit=2)
    assert [e.seq for e in page] == [3, 4]


async def test_unknown_run(pool: Pool) -> None:
    async with pool.connection() as conn:
        with pytest.raises(RunNotFound):
            await RunRepository(conn).get(uuid.uuid4())


# ------------------------------------------------------------- leases (R2.3)


async def test_acquire_lease_bumps_epoch_and_blocks_a_second_owner(pool: Pool) -> None:
    run_id = await _new_run(pool)
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        lease = await repo.acquire_lease(run_id, "w1:1", ttl_s=30)
        assert lease is not None and lease.fence.epoch == 1 and not lease.reclaimed
        assert await repo.acquire_lease(run_id, "w2:2", ttl_s=30) is None  # still held
        assert (await repo.get(run_id)).owner == "w1:1"


async def test_expired_lease_of_a_running_run_is_a_reclaim(pool: Pool) -> None:
    run_id = await _new_run(pool)
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        first = await repo.acquire_lease(run_id, "w1:1", ttl_s=30)
        assert first is not None
        await repo.transition(run_id, S.RUNNING, event=E.RUN_STARTED, fence=first.fence)
        await conn.execute(
            "UPDATE runs SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
            (run_id,),
        )
        second = await repo.acquire_lease(run_id, "w2:2", ttl_s=30)
    assert second is not None
    assert (second.fence.epoch, second.reclaimed, second.reclaims) == (2, True, 1)


async def test_renew_lease_fails_after_takeover(pool: Pool) -> None:
    run_id = await _new_run(pool)
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        lease = await repo.acquire_lease(run_id, "w1:1", ttl_s=30)
        assert lease is not None
        await repo.transition(run_id, S.RUNNING, event=E.RUN_STARTED, fence=lease.fence)
        assert await repo.renew_lease(lease.fence, "w1:1", ttl_s=30)
        await conn.execute("UPDATE runs SET epoch = epoch + 1 WHERE id = %s", (run_id,))
        assert not await repo.renew_lease(lease.fence, "w1:1", ttl_s=30)


async def test_fenced_transition_rejects_stale_epoch(pool: Pool) -> None:
    run_id = await _new_run(pool)
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        lease = await repo.acquire_lease(run_id, "w1:1", ttl_s=30)
        assert lease is not None
        await conn.execute("UPDATE runs SET epoch = epoch + 1 WHERE id = %s", (run_id,))
        with pytest.raises(FencedError):
            await repo.transition(run_id, S.RUNNING, event=E.RUN_STARTED, fence=lease.fence)
        assert (await repo.get(run_id)).status is S.QUEUED


async def test_leaving_running_releases_the_lease(pool: Pool) -> None:
    run_id = await _new_run(pool)
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        lease = await repo.acquire_lease(run_id, "w1:1", ttl_s=30)
        assert lease is not None
        await repo.transition(run_id, S.RUNNING, event=E.RUN_STARTED, fence=lease.fence)
        done = await repo.transition(run_id, S.COMPLETED, event=E.RUN_COMPLETED, fence=lease.fence)
    assert (done.owner, done.lease_expires_at) == (None, None)

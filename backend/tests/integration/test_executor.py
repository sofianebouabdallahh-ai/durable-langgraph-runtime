"""RunExecutor end to end on Postgres with the `toy` graph."""

import asyncio

import pytest
from pydantic import ValidationError

from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import UnknownGraph, default_registry
from agent_runtime.runs.events import EventType as E
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.limits import LimitAboveCeiling
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.runs.store import RunRepository, RunTerminal
from tests.integration.support import events, node_completed, summary, wait_until

pytestmark = pytest.mark.integration

GRAPHS = default_registry()


@pytest.fixture
def settings_fast(test_settings: Settings) -> Settings:
    """Short lease so crash tests don't wait 30 s; heartbeat stays ≤ ttl/3."""
    return test_settings.model_copy(update={"lease_ttl_s": 1.5, "heartbeat_s": 0.4})


@pytest.fixture
def service(pool: Pool, settings_fast: Settings, checkpoint_tables: None) -> RunService:
    return RunService(pool, settings_fast, GRAPHS)


def executor(pool: Pool, settings: Settings, owner: str = "worker-a:1") -> RunExecutor:
    return RunExecutor(pool, settings, GRAPHS, owner=owner)


async def test_run_completes_with_events_steps_and_result(
    pool: Pool, settings_fast: Settings, service: RunService
) -> None:
    run = await service.create_run("toy", {"question": "why?"})
    done = await executor(pool, settings_fast).execute(run.id)

    assert done.status is S.COMPLETED
    assert (done.steps, done.owner, done.lease_expires_at) == (3, None, None)
    assert summary(await events(pool, run.id)) == [
        (E.RUN_CREATED, None),
        (E.RUN_STARTED, None),
        (E.NODE_STARTED, "plan"),
        (E.NODE_COMPLETED, "plan"),
        (E.NODE_STARTED, "research"),
        (E.NODE_COMPLETED, "research"),
        (E.NODE_STARTED, "answer"),
        (E.NODE_COMPLETED, "answer"),
        (E.RUN_COMPLETED, None),
    ]
    async with pool.connection() as conn:
        result = await RunRepository(conn).get_result(run.id)
    assert result is not None and result["output"]["answer"] == "Toy answer to 'why?'"


async def test_step_limit_stops_before_the_next_node(
    pool: Pool, settings_fast: Settings, service: RunService
) -> None:
    run = await service.create_run("toy", {"question": "q"}, {"max_steps": 2})
    done = await executor(pool, settings_fast).execute(run.id)

    assert (done.status, done.reason, done.steps) == (S.FAILED, "step_limit", 2)
    nodes_started = [
        e.payload["node"] for e in await events(pool, run.id) if e.type == E.NODE_STARTED
    ]
    assert nodes_started == ["plan", "research"]  # `answer` never ran


async def test_wall_clock_timeout(pool: Pool, settings_fast: Settings, service: RunService) -> None:
    run = await service.create_run("toy", {"question": "q", "delay_s": 2}, {"timeout_s": 1})
    t0 = asyncio.get_running_loop().time()
    done = await executor(pool, settings_fast).execute(run.id)
    assert (done.status, done.reason) == (S.FAILED, "timeout")
    assert asyncio.get_running_loop().time() - t0 < 2.5


async def test_node_failure_is_recorded(
    pool: Pool, settings_fast: Settings, service: RunService
) -> None:
    run = await service.create_run("toy", {"question": "q", "fail_at": "research"})
    done = await executor(pool, settings_fast).execute(run.id)

    assert (done.status, done.reason) == (S.FAILED, "error")
    evts = await events(pool, run.id)
    assert (E.NODE_FAILED, "research") in summary(evts)
    assert "InducedFailure" in evts[-1].payload["detail"]


async def test_execute_is_idempotent_while_another_worker_owns_the_run(
    pool: Pool, settings_fast: Settings, service: RunService
) -> None:
    run = await service.create_run("toy", {"question": "q"})
    async with pool.connection() as conn:
        held = await RunRepository(conn).acquire_lease(run.id, "worker-b:2", ttl_s=60)
    assert held is not None

    result = await executor(pool, settings_fast).execute(run.id)
    assert (result.status, result.owner, result.epoch) == (S.QUEUED, "worker-b:2", 1)
    assert summary(await events(pool, run.id)) == [(E.RUN_CREATED, None)]


async def test_terminal_run_cannot_be_resumed(
    pool: Pool, settings_fast: Settings, service: RunService
) -> None:
    run = await service.create_run("toy", {"question": "q"})
    await executor(pool, settings_fast).execute(run.id)
    with pytest.raises(RunTerminal, match="completed"):
        await executor(pool, settings_fast).execute(run.id)


async def test_crashed_worker_is_reclaimed_without_rerunning_committed_steps(
    pool: Pool, settings_fast: Settings, service: RunService
) -> None:
    """Worker A dies after `plan` committed (task cancelled: no cleanup runs, like
    SIGKILL). Its lease expires; worker B reclaims and finishes. The real-process
    SIGKILL version of this test is in test_crash_resume.py."""
    run = await service.create_run("toy", {"question": "q", "delay_s": 0.3})
    worker_a = asyncio.create_task(executor(pool, settings_fast, "worker-a:1").execute(run.id))
    await wait_until(lambda: node_completed(pool, run.id, "plan"))
    worker_a.cancel()  # dies mid-`research`
    await asyncio.gather(worker_a, return_exceptions=True)

    await asyncio.sleep(settings_fast.lease_ttl_s + 0.2)  # lease expires
    done = await executor(pool, settings_fast, "worker-b:2").execute(run.id)

    assert done.status is S.COMPLETED
    assert done.epoch == 2
    evts = summary(await events(pool, run.id))
    assert evts.count((E.NODE_COMPLETED, "plan")) == 1  # committed step never re-ran
    assert evts.count((E.RUN_RECLAIMED, None)) == 1
    assert done.steps == 3


async def test_too_many_reclaims_fails_the_run(
    pool: Pool, settings_fast: Settings, service: RunService
) -> None:
    run = await service.create_run("toy", {"question": "q"})
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE runs SET status = 'running', started_at = now(), owner = 'dead:0', "
            "lease_expires_at = now() - interval '1 second', reclaims = %s WHERE id = %s",
            (settings_fast.max_reclaims, run.id),
        )
    done = await executor(pool, settings_fast).execute(run.id)
    assert (done.status, done.reason) == (S.FAILED, "max_reclaims")


async def test_worker_that_loses_its_lease_stops_and_writes_nothing_more(
    pool: Pool, settings_fast: Settings, service: RunService
) -> None:
    """A takeover mid-run (epoch bump): the old owner's heartbeat or fence stops it."""
    run = await service.create_run("toy", {"question": "q", "delay_s": 0.6})
    worker_a = asyncio.create_task(executor(pool, settings_fast, "worker-a:1").execute(run.id))
    await wait_until(lambda: node_completed(pool, run.id, "plan"))
    async with pool.connection() as conn:  # another worker takes over
        await conn.execute(
            "UPDATE runs SET epoch = epoch + 1, owner = 'worker-b:2' WHERE id = %s", (run.id,)
        )

    result = await asyncio.wait_for(worker_a, timeout=5)
    assert result.status is S.RUNNING  # worker A did not complete or fail the run
    epochs_after_takeover = {e.epoch for e in await events(pool, run.id) if e.seq > 4}
    assert 1 not in epochs_after_takeover  # nothing written by the old epoch after `plan`


async def test_create_run_validation(service: RunService) -> None:
    with pytest.raises(UnknownGraph):
        await service.create_run("nope", {})
    with pytest.raises(ValidationError):
        await service.create_run("toy", {"question": ""})
    with pytest.raises(ValidationError, match="Extra inputs"):
        await service.create_run("toy", {"question": "q"}, {"max_stepz": 3})
    with pytest.raises(LimitAboveCeiling, match="max_steps=999 exceeds the server maximum"):
        await service.create_run("toy", {"question": "q"}, {"max_steps": 999})

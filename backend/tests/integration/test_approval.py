"""Durable human approval (R1.4, SC7): pause → no worker holds the run →
approve (with edits) or reject → resume on any worker."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest

from agent_runtime.api.app import create_app
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.queue import RedisWorkQueue
from agent_runtime.runs.approvals import Approval, ApprovalRepository
from agent_runtime.runs.events import EventType as E
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.runs.store import NotWaitingForApproval, Run, RunTerminal
from agent_runtime.tools.hooks import Continue, HookDecision, HookRegistry, ToolHookInput
from agent_runtime.worker import Worker
from tests.integration.support import events, wait_until

pytestmark = pytest.mark.integration
GRAPHS = default_registry()

NOTIFY_SCRIPT: list[dict[str, Any]] = [
    {"tool_calls": [{"name": "notify", "args": {"to": "ceo", "message": "ship it"}}]},
    {"content": "Notified."},
]


async def notifications(pool: Pool, run: Run) -> list[dict[str, Any]]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT recipient, message FROM outbox_notifications WHERE run_id = %s", (run.id,)
        )
        return list(await cur.fetchall())


async def paused_run(pool: Pool, settings: Settings) -> Run:
    service = RunService(pool, settings, GRAPHS)
    run = await service.create_run(
        "assistant", {"message": "tell the ceo", "script": NOTIFY_SCRIPT}
    )
    return await RunExecutor(pool, settings, GRAPHS, owner="w-a:1").execute(run.id)


async def test_external_side_effect_pauses_durably_without_a_lease(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    run = await paused_run(pool, test_settings)
    assert run.status is S.WAITING_APPROVAL
    assert (run.owner, run.lease_expires_at) == (None, None)  # no worker holds it
    assert run.interrupt_payload is not None
    assert (
        run.interrupt_payload["tool"] == "notify" and run.interrupt_payload["args"]["to"] == "ceo"
    )
    assert await notifications(pool, run) == []  # nothing sent before approval
    assert E.INTERRUPT_RAISED in [e.type for e in await events(pool, run.id)]


async def test_approve_with_edits_resumes_on_another_worker_using_the_edits(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    run = await paused_run(pool, test_settings)
    service = RunService(pool, test_settings, GRAPHS)
    queued = await service.decide_approval(
        run.id, "approve", {"args": {"to": "ops", "message": "ship it (edited)"}}
    )
    assert queued.status is S.QUEUED and queued.interrupt_payload is None
    done = await RunExecutor(pool, test_settings, GRAPHS, owner="w-b:2").execute(run.id)
    assert done.status is S.COMPLETED
    assert await notifications(pool, run) == [{"recipient": "ops", "message": "ship it (edited)"}]
    decided = next(e for e in await events(pool, run.id) if e.type == E.APPROVAL_DECIDED)
    assert decided.payload["decision"] == "approve" and decided.payload["decided_by"] == "local"


async def test_reject_cancels_and_nothing_is_sent(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    run = await paused_run(pool, test_settings)
    rejected = await RunService(pool, test_settings, GRAPHS).decide_approval(
        run.id, "reject", reason="not today"
    )
    assert (rejected.status, rejected.reason) == (S.CANCELLED, "rejected")
    with pytest.raises(RunTerminal):
        await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)
    assert await notifications(pool, run) == []


async def test_approving_a_run_that_is_not_waiting_is_rejected(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    run = await RunService(pool, test_settings, GRAPHS).create_run("toy", {"question": "q"})
    with pytest.raises(NotWaitingForApproval, match="queued, not waiting_approval"):
        await RunService(pool, test_settings, GRAPHS).decide_approval(run.id, "approve")


async def test_crash_after_the_approved_side_effect_resumes_without_repeating_it(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    """The dangerous window: worker A resumes after approval, sends the notification,
    then dies before the step's checkpoint. The checkpoint still shows the pending
    interrupt, so worker B resumes AGAIN, and the ledger must replay, not resend."""
    fast = test_settings.model_copy(update={"lease_ttl_s": 1.0, "heartbeat_s": 0.3})
    run = await paused_run(pool, fast)
    await RunService(pool, fast, GRAPHS).decide_approval(run.id, "approve")

    hold = asyncio.Event()  # never set: worker A "dies" while holding here
    stuck_hooks = HookRegistry()

    @stuck_hooks.hook("redact_secrets_in_args", point="pre_tool")
    async def passthrough(inp: ToolHookInput) -> HookDecision:
        return Continue()

    @stuck_hooks.hook("redact_secrets_in_result", point="post_tool", timeout_s=30)
    async def die_here(inp: ToolHookInput) -> HookDecision:
        await hold.wait()  # after execute + ledger, before the checkpoint
        return Continue()

    worker_a = asyncio.create_task(
        RunExecutor(pool, fast, GRAPHS, owner="w-a:1", hooks=stuck_hooks).execute(run.id)
    )

    async def recorded() -> bool:  # the side effect happened AND the ledger has it done
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT 1 FROM tool_invocations WHERE run_id = %s AND tool = 'notify' "
                "AND status = 'done'",
                (run.id,),
            )
            return await cur.fetchone() is not None

    await wait_until(recorded, timeout_s=10)  # the side effect happened …
    worker_a.cancel()  # … and worker A died before checkpointing it
    await asyncio.gather(worker_a, return_exceptions=True)
    await asyncio.sleep(fast.lease_ttl_s + 0.2)

    done = await RunExecutor(pool, fast, GRAPHS, owner="w-b:2").execute(run.id)
    assert done.status is S.COMPLETED and done.epoch == 3  # paused@1, resumed@2, reclaimed@3
    assert len(await notifications(pool, run)) == 1  # sent exactly once
    completed = [e.payload for e in await events(pool, run.id) if e.type == E.TOOL_COMPLETED]
    assert completed[-1]["tool"] == "notify" and completed[-1]["cached"] is True
    # SC9: the call was run by the pipeline 3 times (pause, resume, resume again) but is
    # charged once; and the counters survived the reclaim (they live on the run row).
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT tool_calls_total, tool_calls, model_calls FROM runs WHERE id = %s", (run.id,)
        )
        counters = await cur.fetchone()
    assert counters is not None
    assert (counters["tool_calls_total"], counters["tool_calls"]) == (1, {"notify": 1})
    assert counters["model_calls"] == 2  # the tool-call reply + the final answer


@pytest.fixture
async def client(
    pool: Pool, test_settings: Settings, queue: RedisWorkQueue, checkpoint_tables: None
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(test_settings, pool=pool, queue=queue)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        yield c


async def test_approve_api_and_worker_round_trip(
    client: httpx.AsyncClient, pool: Pool, test_settings: Settings, queue: RedisWorkQueue
) -> None:
    fast = test_settings.model_copy(
        update={
            "lease_ttl_s": 1.5,
            "heartbeat_s": 0.4,
            "relay_interval_s": 3600,
            "worker_block_ms": 200,
        }
    )
    stop = asyncio.Event()
    worker = asyncio.create_task(
        Worker(pool, queue, fast, GRAPHS, consumer="aw:1", concurrency=2).run(stop)
    )
    try:
        run_id = (
            await client.post(
                "/runs",
                json={"graph": "assistant", "input": {"message": "m", "script": NOTIFY_SCRIPT}},
            )
        ).json()["run_id"]

        async def waiting() -> bool:
            return bool(
                (await client.get(f"/runs/{run_id}")).json()["status"] == "waiting_approval"
            )

        await wait_until(waiting, timeout_s=20)
        view = (await client.get(f"/runs/{run_id}")).json()
        assert view["interrupt_payload"]["type"] == "tool_approval"
        assert await queue.pending_count() == 0  # the worker acked: it holds nothing

        resp = await client.post(f"/runs/{run_id}/approve", json={"decision": "approve"})
        assert resp.status_code == 202 and resp.json()["status"] == "queued"

        async def completed() -> bool:
            return bool((await client.get(f"/runs/{run_id}")).json()["status"] == "completed")

        await wait_until(completed, timeout_s=20)
        again = await client.post(f"/runs/{run_id}/approve", json={"decision": "approve"})
        assert again.status_code == 409
        assert again.json()["type"].endswith("/not-waiting-for-approval")
        bad = await client.post(f"/runs/{run_id}/approve", json={"decision": "maybe"})
        assert bad.status_code == 422
    finally:
        stop.set()
        await worker


# ------------------------------------------------------------- phase H1: binding


class WorkerDies(Exception):
    """Stands for the worker process being killed at a chosen point."""


TWO_STEPS: list[dict[str, Any]] = [
    {"tool_calls": [{"name": "notify", "args": {"to": "ceo", "message": "one"}}]},
    {"tool_calls": [{"name": "notify", "args": {"to": "cfo", "message": "two"}}]},
    {"content": "Both notified."},
]
ONE_STEP: list[dict[str, Any]] = [
    {"tool_calls": [{"name": "notify", "args": {"to": "ceo", "message": "one"}},
                    {"name": "notify", "args": {"to": "cfo", "message": "two"}}]},
    {"content": "Both notified."},
]  # fmt: skip


async def started(pool: Pool, settings: Settings, script: list[dict[str, Any]]) -> Run:
    return await RunService(pool, settings, GRAPHS).create_run(
        "assistant", {"message": "tell them", "script": script}
    )


async def dies_before_the_pause_commits(pool: Pool, settings: Settings, run: Run) -> None:
    """The worker reaches an approval: the interrupt is checkpointed, then the process
    dies before the pause (waiting_approval) commits. Its lease then runs out."""
    executor = RunExecutor(pool, settings, GRAPHS, owner="w-dies:1")

    async def die(*_: Any, **__: Any) -> Run:
        raise WorkerDies

    executor._pause = die  # type: ignore[method-assign]
    with pytest.raises(WorkerDies):
        await executor.execute(run.id)
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE runs SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
            (run.id,),
        )


async def pending_approvals(pool: Pool, run: Run) -> list[Approval]:
    async with pool.connection() as conn:
        return await ApprovalRepository(conn).pending(run.id)


async def test_h1_a_crash_before_the_pause_never_reuses_an_earlier_approval(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    """The review's critical finding: A was approved; B's interrupt is written but the
    worker dies before the pause commits. The reclaimed run must ASK for B, not resume
    it with A's approval."""
    run = await started(pool, test_settings, TWO_STEPS)
    paused = await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)
    assert paused.status is S.WAITING_APPROVAL
    await RunService(pool, test_settings, GRAPHS).decide_approval(run.id, "approve")  # A

    await dies_before_the_pause_commits(pool, test_settings, run)  # A ran, then B asked
    assert await notifications(pool, run) == [{"recipient": "ceo", "message": "one"}]

    reclaimed = await RunExecutor(pool, test_settings, GRAPHS, owner="w-b:2").execute(run.id)
    assert reclaimed.status is S.WAITING_APPROVAL  # asked, not resumed
    assert await notifications(pool, run) == [{"recipient": "ceo", "message": "one"}]
    [b] = await pending_approvals(pool, run)
    assert (b.tool, b.args["to"]) == ("notify", "cfo")
    assert reclaimed.interrupt_payload is not None
    assert reclaimed.interrupt_payload["approval_id"] == str(b.id)

    await RunService(pool, test_settings, GRAPHS).decide_approval(
        run.id, "approve", approval_id=b.id
    )
    done = await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)
    assert done.status is S.COMPLETED
    assert await notifications(pool, run) == [
        {"recipient": "ceo", "message": "one"},
        {"recipient": "cfo", "message": "two"},
    ]  # each exactly once


async def test_h1_a_crash_before_the_first_pause_asks_instead_of_failing(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    run = await paused_run_after_a_crash(pool, test_settings)
    assert run.status is S.WAITING_APPROVAL  # not failed(error)
    assert await notifications(pool, run) == []
    assert len(await pending_approvals(pool, run)) == 1


async def paused_run_after_a_crash(pool: Pool, settings: Settings) -> Run:
    run = await started(pool, settings, NOTIFY_SCRIPT)
    await dies_before_the_pause_commits(pool, settings, run)
    return await RunExecutor(pool, settings, GRAPHS, owner="w-b:2").execute(run.id)


async def test_h1_two_approvals_in_one_step_are_each_asked_and_decided(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    service = RunService(pool, test_settings, GRAPHS)
    run = await started(pool, test_settings, ONE_STEP)
    paused = await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)
    assert paused.status is S.WAITING_APPROVAL
    first, second = await pending_approvals(pool, run)
    assert {first.args["to"], second.args["to"]} == {"ceo", "cfo"}
    asked = [e for e in await events(pool, run.id) if e.type == E.INTERRUPT_RAISED]
    assert sorted(e.payload["approval_id"] for e in asked) == sorted(
        [str(first.id), str(second.id)]
    )

    still = await service.decide_approval(run.id, "approve", approval_id=first.id)
    assert still.status is S.WAITING_APPROVAL  # the other one is still to decide
    assert still.interrupt_payload is not None
    assert still.interrupt_payload["approval_id"] == str(second.id)
    assert await notifications(pool, run) == []  # nothing runs before both are decided

    queued = await service.decide_approval(run.id, "approve", approval_id=second.id)
    assert queued.status is S.QUEUED
    done = await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)
    assert done.status is S.COMPLETED
    sent = sorted(n["recipient"] for n in await notifications(pool, run))
    assert sent == ["ceo", "cfo"]


async def test_h1_rejecting_one_of_two_cancels_the_turn_and_sends_neither(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    service = RunService(pool, test_settings, GRAPHS)
    run = await started(pool, test_settings, ONE_STEP)
    await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)
    first, second = await pending_approvals(pool, run)
    await service.decide_approval(run.id, "approve", approval_id=first.id)
    rejected = await service.decide_approval(run.id, "reject", approval_id=second.id)
    assert (rejected.status, rejected.reason) == (S.CANCELLED, "rejected")
    assert await notifications(pool, run) == []
    assert await pending_approvals(pool, run) == []


async def test_h1_a_call_that_changed_after_approval_is_asked_again(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    run = await paused_run(pool, test_settings)
    [asked] = await pending_approvals(pool, run)
    await RunService(pool, test_settings, GRAPHS).decide_approval(
        run.id, "approve", approval_id=asked.id
    )
    async with pool.connection() as conn:  # the call the person approved isn't this one
        await conn.execute(
            "UPDATE run_approvals SET args_hash = %s WHERE id = %s", ("0" * 64, asked.id)
        )
    again = await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)
    assert again.status is S.WAITING_APPROVAL
    assert await notifications(pool, run) == []
    [fresh] = await pending_approvals(pool, run)
    assert fresh.id != asked.id and fresh.args_hash != "0" * 64
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT status FROM run_approvals WHERE id = %s", (asked.id,))
        assert (await cur.fetchone() or {}).get("status") == "superseded"


async def test_h1_a_run_paused_before_the_upgrade_is_asked_again_once_decided(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    """Migration 0022 backfills approvals with no interrupt id: deciding one re-queues
    the run, which then asks again, bound to the id (fail closed: never zero times)."""
    run = await paused_run(pool, test_settings)
    async with pool.connection() as conn:  # what the backfill leaves
        await conn.execute(
            "UPDATE run_approvals SET interrupt_id = NULL, args_hash = NULL WHERE run_id = %s",
            (run.id,),
        )
    await RunService(pool, test_settings, GRAPHS).decide_approval(run.id, "approve")
    asked = await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)
    assert asked.status is S.WAITING_APPROVAL and await notifications(pool, run) == []
    [bound] = await pending_approvals(pool, run)
    assert bound.interrupt_id is not None and bound.args_hash is not None
    await RunService(pool, test_settings, GRAPHS).decide_approval(
        run.id, "approve", approval_id=bound.id
    )
    done = await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)
    assert done.status is S.COMPLETED and len(await notifications(pool, run)) == 1


async def test_h1_the_api_decides_one_approval_by_id(
    client: httpx.AsyncClient, pool: Pool, test_settings: Settings
) -> None:
    run = await started(pool, test_settings, ONE_STEP)
    await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)
    first, second = await pending_approvals(pool, run)
    url = f"/runs/{run.id}/approve"

    unsaid = await client.post(url, json={"decision": "approve"})
    assert unsaid.status_code == 409 and unsaid.json()["type"].endswith("/approval-conflict")
    assert "2 approvals are pending" in unsaid.json()["detail"]
    unknown = await client.post(url, json={"decision": "approve", "approval_id": str(uuid4())})
    assert unknown.status_code == 409 and "not one of this run's" in unknown.json()["detail"]

    ok = await client.post(url, json={"decision": "approve", "approval_id": str(first.id)})
    assert ok.status_code == 202 and ok.json()["status"] == "waiting_approval"
    assert ok.json()["interrupt_payload"]["approval_id"] == str(second.id)
    twice = await client.post(url, json={"decision": "approve", "approval_id": str(first.id)})
    assert twice.status_code == 409 and "approved, not pending" in twice.json()["detail"]
    last = await client.post(url, json={"decision": "approve", "approval_id": str(second.id)})
    assert last.status_code == 202 and last.json()["status"] == "queued"

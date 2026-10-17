"""Durable human approval (R1.4, SC7): pause → no worker holds the run →
approve (with edits) or reject → resume on any worker."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from agent_runtime.api.app import create_app
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.queue import RedisWorkQueue
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

    async def notified() -> bool:
        return len(await notifications(pool, run)) == 1

    await wait_until(notified, timeout_s=10)  # the side effect happened …
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

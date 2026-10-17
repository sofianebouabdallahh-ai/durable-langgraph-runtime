"""Child runs (R2.8): fan-out, fan-in, partial results, limits (R14.6), cancel
cascade, budget roll-up (R14.1) and idempotent spawn. Phase 5a, SC2-SC9, SC11."""

import asyncio
import uuid
from typing import Any, TypedDict

import pytest

from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.fencing import Fence, FencedError
from agent_runtime.graphs import GraphRegistry, GraphSpec, default_registry
from agent_runtime.graphs.toy import SPEC as TOY
from agent_runtime.runs.events import EventType as E
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.fanout import ChildSpec, FanOutRejected, WorkflowContext
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.runs.store import FanOutLimits, NewChild, Run, RunRepository
from agent_runtime.tools import invocations
from agent_runtime.tools.invocations import BudgetExceeded
from tests.integration.support import events

pytestmark = pytest.mark.integration
GRAPHS = default_registry()


class Sent:
    """Spy for the executor's `enqueue`: what was handed to the work queue."""

    def __init__(self) -> None:
        self.ids: list[uuid.UUID] = []

    async def __call__(self, run_id: uuid.UUID) -> None:
        self.ids.append(run_id)


def executor(pool: Pool, settings: Settings, sent: Sent | None = None, **kw: Any) -> RunExecutor:
    return RunExecutor(pool, settings, kw.pop("graphs", GRAPHS), enqueue=sent, **kw)


async def get(pool: Pool, run_id: uuid.UUID) -> Run:
    async with pool.connection() as conn:
        return await RunRepository(conn).get(run_id)


async def children_of(pool: Pool, parent: uuid.UUID) -> list[Run]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id FROM runs WHERE parent_run_id = %s ORDER BY child_key", (parent,)
        )
        ids = [r["id"] for r in await cur.fetchall()]
    return [await get(pool, i) for i in ids]


async def result(pool: Pool, run_id: uuid.UUID) -> dict[str, Any]:
    async with pool.connection() as conn:
        row = await RunRepository(conn).get_result(run_id)
    assert row is not None
    return row


async def fan_out(
    pool: Pool, settings: Settings, inp: dict[str, Any], sent: Sent | None = None
) -> Run:
    run = await RunService(pool, settings, GRAPHS).create_run("fanout", {"topic": "t", **inp})
    return await executor(pool, settings, sent).execute(run.id)


async def finish_children(pool: Pool, settings: Settings, parent: Run, sent: Sent) -> None:
    for child in await children_of(pool, parent.id):
        await executor(pool, settings, sent).execute(child.id)


# ------------------------------------------------------------- fan-out / fan-in


async def test_parent_fans_out_and_waits_holding_no_lease(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    sent = Sent()
    parent = await fan_out(pool, test_settings, {"n": 3}, sent)
    assert parent.status is S.WAITING_CHILDREN
    assert (parent.owner, parent.lease_expires_at) == (None, None)  # SC2
    assert (parent.child_total, parent.child_done) == (3, 0)
    kids = await children_of(pool, parent.id)
    assert [k.child_key for k in kids] == ["q0", "q1", "q2"]
    assert all(k.status is S.QUEUED and k.depth == 1 for k in kids)
    assert all(k.root_run_id == parent.id and k.graph_name == "toy" for k in kids)
    assert sent.ids == [k.id for k in kids]  # handed to the queue only after COMMIT
    spawned = next(e for e in await events(pool, parent.id) if e.type == E.CHILDREN_SPAWNED)
    assert [c["key"] for c in spawned.payload["children"]] == ["q0", "q1", "q2"]


async def test_the_last_child_requeues_the_parent_which_resumes_with_the_results(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    sent = Sent()
    parent = await fan_out(pool, test_settings, {"n": 3}, sent)
    sent.ids.clear()
    await finish_children(pool, test_settings, parent, sent)
    assert sent.ids == [parent.id]  # exactly the parent, exactly once
    assert (await get(pool, parent.id)).status is S.QUEUED

    done = await executor(pool, test_settings, sent).execute(parent.id)
    assert done.status is S.COMPLETED
    out = await result(pool, parent.id)
    assert out["partial"] is False
    assert out["output"]["summary"] == "3/3 sub-questions answered"
    answers = out["output"]["answers"]
    assert [a["key"] for a in answers] == ["q0", "q1", "q2"]
    assert all(a["answer"].startswith("Toy answer to 't: aspect") for a in answers)
    types = [e.type for e in await events(pool, parent.id)]
    assert types.count(E.CHILD_COMPLETED) == 3 and types.count(E.CHILDREN_COMPLETED) == 1
    assert types.count(E.NODE_COMPLETED) == 3  # plan, research, synthesize: none re-run twice


async def test_some_children_fail_the_parent_continues_with_partial(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    sent = Sent()
    parent = await fan_out(pool, test_settings, {"n": 3, "fail": [1]}, sent)
    await finish_children(pool, test_settings, parent, sent)
    done = await executor(pool, test_settings, sent).execute(parent.id)
    assert done.status is S.COMPLETED
    out = await result(pool, parent.id)
    assert out["partial"] is True  # SC4, also in run_results
    assert out["output"]["summary"] == "2/3 sub-questions answered (partial)"
    assert [a["status"] for a in out["output"]["answers"]] == ["completed", "failed", "completed"]


async def test_every_child_failed_fails_the_parent(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    sent = Sent()
    parent = await fan_out(pool, test_settings, {"n": 2, "fail": [0, 1]}, sent)
    await finish_children(pool, test_settings, parent, sent)
    done = await executor(pool, test_settings, sent).execute(parent.id)
    assert (done.status, done.reason) == (S.FAILED, "children_failed")


async def test_siblings_finishing_concurrently_requeue_the_parent_exactly_once(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    """SC3: the fan-in counter under contention, 50 rounds of 6 simultaneous ends."""
    for _ in range(50):
        parent, fence = await running_root(pool)
        kids = await spawn(pool, parent, fence, 6)

        async def end(child: Run) -> list[uuid.UUID]:
            async with pool.connection() as conn:
                repo = RunRepository(conn)
                await repo.transition(child.id, S.FAILED, event=E.RUN_FAILED, reason="error")
                return repo.ready

        ready = [r for rs in await asyncio.gather(*(end(k) for k in kids)) for r in rs]
        assert ready == [parent.id]
        after = await get(pool, parent.id)
        assert (after.status, after.child_done, after.child_total) == (S.QUEUED, 6, 6)
        types = [e.type for e in await events(pool, parent.id)]
        assert types.count(E.CHILD_COMPLETED) == 6 and types.count(E.CHILDREN_COMPLETED) == 1


# --------------------------------------------------------------------- limits


async def running_root(pool: Pool, limits: dict[str, Any] | None = None) -> tuple[Run, Fence]:
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        run = await repo.create(graph_name="toy", input={"question": "q"}, limits=limits)
        lease = await repo.acquire_lease(run.id, "t:1", 60)
        assert lease is not None
        await repo.transition(run.id, S.RUNNING, event=E.RUN_STARTED, fence=lease.fence)
        return await repo.get(run.id), lease.fence


LIMITS = FanOutLimits(max_children=6, max_depth=2, max_descendants=20)


async def spawn(
    pool: Pool, parent: Run, fence: Fence, n: int, limits: FanOutLimits = LIMITS
) -> list[Run]:
    kids = [NewChild(f"k{i}", "toy", {"question": "q"}, {}, {}) for i in range(n)]
    async with pool.connection() as conn:
        return await RunRepository(conn).spawn_children(parent, fence, kids, limits, {})


@pytest.mark.parametrize(
    ("inp", "update", "reason"),
    [
        ({"n": 7}, {}, "max_children=6 exceeded (7 children)"),
        ({"n": 2}, {"run_max_depth": 0}, "max sub-run depth 0 exceeded"),
        ({"n": 3}, {"run_max_descendants": 2}, "max 2 descendants per root run exceeded"),
    ],
)
async def test_a_breached_limit_is_an_error_the_node_handles_and_nothing_is_created(
    pool: Pool,
    test_settings: Settings,
    checkpoint_tables: None,
    inp: dict[str, Any],
    update: dict[str, Any],
    reason: str,
) -> None:
    settings = test_settings.model_copy(update=update)
    done = await fan_out(pool, settings, inp)
    assert done.status is S.COMPLETED  # SC6: the run continues
    assert (await result(pool, done.id))["output"]["summary"] == f"No research: {reason}"
    assert await children_of(pool, done.id) == []
    assert done.child_total == 0


async def test_the_descendant_limit_counts_the_whole_tree(pool: Pool) -> None:
    root, fence = await running_root(pool)
    limits = FanOutLimits(max_children=6, max_depth=2, max_descendants=5)
    child = (await spawn(pool, root, fence, 3, limits))[0]
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        lease = await repo.acquire_lease(child.id, "t:2", 60)
        assert lease is not None
        await repo.transition(child.id, S.RUNNING, event=E.RUN_STARTED, fence=lease.fence)
        child = await repo.get(child.id)
    with pytest.raises(FanOutRejected, match="max 5 descendants"):
        await spawn(pool, child, lease.fence, 3, limits)  # 3 + 3 > 5
    grandkids = await spawn(pool, child, lease.fence, 2, limits)  # 3 + 2 = 5: allowed
    assert all(g.depth == 2 and g.root_run_id == root.id for g in grandkids)
    assert (await get(pool, root.id)).status is S.WAITING_CHILDREN


async def test_a_stale_owner_cannot_fan_out(pool: Pool) -> None:
    root, fence = await running_root(pool)
    with pytest.raises(FencedError):
        await spawn(pool, root, Fence(root.id, fence.epoch - 1), 2)
    assert await children_of(pool, root.id) == []


# ---------------------------------------------------------- idempotent spawn


async def test_a_crash_before_the_fan_out_commits_spawns_each_child_once_on_retry(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC7. Worker A checkpoints the node's interrupt, then dies before the fan-out
    transaction. Worker B finds the pending interrupt and no children, and fans out."""
    fast = test_settings.model_copy(update={"lease_ttl_s": 1.0, "heartbeat_s": 0.3})
    run = await RunService(pool, fast, GRAPHS).create_run("fanout", {"topic": "t", "n": 3})
    hang, entered = asyncio.Event(), asyncio.Event()
    real = RunRepository.spawn_children

    async def die_here(self: RunRepository, *a: Any, **kw: Any) -> list[Run]:
        entered.set()
        await hang.wait()  # never set: worker A "dies" here, before the fan-out commits
        return await real(self, *a, **kw)

    monkeypatch.setattr(RunRepository, "spawn_children", die_here)
    worker_a = asyncio.create_task(executor(pool, fast).execute(run.id))
    await asyncio.wait_for(entered.wait(), timeout=10)  # the interrupt is checkpointed
    worker_a.cancel()
    await asyncio.gather(worker_a, return_exceptions=True)
    monkeypatch.setattr(RunRepository, "spawn_children", real)
    assert await children_of(pool, run.id) == []  # nothing committed
    await asyncio.sleep(fast.lease_ttl_s + 0.2)

    sent = Sent()
    parent = await executor(pool, fast, sent).execute(run.id)
    assert parent.status is S.WAITING_CHILDREN and parent.epoch == 2
    kids = await children_of(pool, run.id)
    assert [k.child_key for k in kids] == ["q0", "q1", "q2"]  # each exactly once
    await finish_children(pool, fast, parent, sent)
    assert (await executor(pool, fast, sent).execute(run.id)).status is S.COMPLETED


def _registry_with(*nodes: Any) -> GraphRegistry:
    """A graph made of `nodes` (each spawning something), plus toy for the children."""
    from langgraph.graph import END, START, StateGraph
    from pydantic import BaseModel

    class In(BaseModel):
        x: int = 0

    class State(TypedDict, total=False):
        x: int

    def build() -> StateGraph[Any, Any, Any, Any]:
        g = StateGraph(State, context_schema=WorkflowContext)
        previous = START
        for i, fn in enumerate(nodes):
            g.add_node(f"n{i}", fn)
            g.add_edge(previous, f"n{i}")
            previous = f"n{i}"
        g.add_edge(previous, END)
        return g

    return GraphRegistry([TOY, GraphSpec.of_state_graph("custom", "test", In, build)])


async def test_invalid_children_and_reused_keys_are_rejected(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    seen: list[str] = []

    async def spawn_bad(state: dict[str, Any], runtime: Any) -> dict[str, Any]:
        try:
            await runtime.context.spawner.spawn([ChildSpec(key="a", graph="nope", input={})])
        except FanOutRejected as exc:
            seen.append(exc.reason)
        return {}

    async def spawn_ok(state: dict[str, Any], runtime: Any) -> dict[str, Any]:
        await runtime.context.spawner.spawn(
            [ChildSpec(key="a", graph="toy", input={"question": "q"})]
        )
        return {}

    async def spawn_same_key(state: dict[str, Any], runtime: Any) -> dict[str, Any]:
        try:
            await runtime.context.spawner.spawn(
                [ChildSpec(key="a", graph="toy", input={"question": "r"})]
            )
        except FanOutRejected as exc:
            seen.append(exc.reason)
        return {}

    graphs = _registry_with(spawn_bad, spawn_ok, spawn_same_key)
    run = await RunService(pool, test_settings, graphs).create_run("custom", {})
    sent = Sent()
    parent = await executor(pool, test_settings, sent, graphs=graphs).execute(run.id)
    assert parent.status is S.WAITING_CHILDREN and parent.child_total == 1
    await finish_children(pool, test_settings, parent, sent)
    done = await executor(pool, test_settings, sent, graphs=graphs).execute(run.id)
    assert done.status is S.COMPLETED
    assert seen[0].startswith("invalid child: unknown graph 'nope'")
    assert seen[-1] == "child keys must be unique within a run"


# ------------------------------------------------------------ cancel cascade


async def test_cancelling_a_parent_cancels_its_live_descendants(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    parent = await fan_out(pool, test_settings, {"n": 3})
    kids = await children_of(pool, parent.id)
    async with pool.connection() as conn:  # one child is being executed right now
        repo = RunRepository(conn)
        lease = await repo.acquire_lease(kids[0].id, "w:1", 60)
        assert lease is not None
        await repo.transition(kids[0].id, S.RUNNING, event=E.RUN_STARTED, fence=lease.fence)

    cancelled = await RunService(pool, test_settings, GRAPHS).cancel(parent.id)
    assert cancelled.status is S.CANCELLED  # SC8
    after = {k.child_key: await get(pool, k.id) for k in kids}
    assert after["q0"].status is S.RUNNING and after["q0"].cancel_requested  # cooperative
    assert after["q1"].status is S.CANCELLED and after["q2"].status is S.CANCELLED

    async with pool.connection() as conn:  # the running child ends afterwards
        await RunRepository(conn).transition(
            kids[0].id, S.CANCELLED, event=E.RUN_CANCELLED, fence=lease.fence,
            reason="cancel_requested",
        )  # fmt: skip
    final = await get(pool, parent.id)
    assert (final.status, final.child_done) == (S.CANCELLED, 0)  # nothing resurrected it


# ------------------------------------------------------------ budget roll-up


async def leased(pool: Pool, run: Run) -> Fence:
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        lease = await repo.acquire_lease(run.id, "w:9", 60)
        assert lease is not None
        await repo.transition(run.id, S.RUNNING, event=E.RUN_STARTED, fence=lease.fence)
        return lease.fence


async def test_child_usage_rolls_up_and_an_ancestors_limit_stops_the_child(pool: Pool) -> None:
    root, fence = await running_root(pool, {"max_model_calls": 3, "max_tool_calls": 2})
    first, second = await spawn(pool, root, fence, 2)
    f1, f2 = await leased(pool, first), await leased(pool, second)
    async with pool.connection() as conn:
        await invocations.charge_model_call(conn, fence=f1, max_calls=None)
        await invocations.charge_model_call(conn, fence=f2, max_calls=None)
        await invocations.charge_model_call(conn, fence=f1, max_calls=None)
        with pytest.raises(
            BudgetExceeded, match=f"max_model_calls=3 reached by ancestor {root.id}"
        ):
            await invocations.charge_model_call(conn, fence=f2, max_calls=None)
        for i, f in enumerate((f1, f2)):
            await invocations.begin(
                conn, fence=f, key=f"{i:064d}", tool="calculator", max_total=None, max_for_tool=None
            )
        with pytest.raises(BudgetExceeded, match="max_tool_calls=2 reached by ancestor"):
            await invocations.begin(
                conn, fence=f1, key="9" * 64, tool="calculator", max_total=None, max_for_tool=None
            )
    usage = {r.id: r for r in [await get(pool, i) for i in (root.id, first.id, second.id)]}
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, model_calls, tool_calls_total FROM runs WHERE id = ANY(%s)",
            ([root.id, first.id, second.id],),
        )
        counts = {r["id"]: (r["model_calls"], r["tool_calls_total"]) for r in await cur.fetchall()}
    assert usage and counts[root.id] == (3, 2)  # the whole tree
    assert counts[first.id] == (2, 1) and counts[second.id] == (1, 1)


# ------------------------------------------------------------- local fan-out


async def test_local_fanout_runs_the_same_graph_in_process(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    run = await RunService(pool, test_settings, GRAPHS).create_run(
        "fanout", {"topic": "t", "n": 3, "fail": [2]}
    )
    done = await executor(pool, test_settings, local_fanout=True).execute(run.id)
    assert done.status is S.COMPLETED  # SC11: no workers, no child rows
    out = (await result(pool, run.id))["output"]
    assert out["summary"] == "2/3 sub-questions answered (partial)"
    assert await children_of(pool, run.id) == []
    nodes = [e.payload["node"] for e in await events(pool, run.id) if e.type == E.NODE_STARTED]
    assert nodes == ["plan", "research", "synthesize"]  # the children's nodes didn't leak in

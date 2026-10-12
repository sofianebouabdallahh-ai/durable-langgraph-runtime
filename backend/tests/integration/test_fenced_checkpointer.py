"""Spike (task 1.4): does epoch fencing work with real LangGraph checkpoints?

A 3-node graph a → b → c runs with a FencedCheckpointer. To simulate a zombie,
node `b` bumps the run's epoch from inside the run, exactly what a takeover by
another worker does (R2.3). The checkpoint write after `b` must then be
rejected, and a new owner (the new epoch) must resume from the last good
checkpoint without re-executing `a`.
"""

import asyncio
import operator
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Annotated, Protocol, TypedDict

import psycopg
import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph

from agent_runtime.checkpointing import Fence, FencedCheckpointer, FencedError, check_fence
from agent_runtime.db import Pool
from agent_runtime.runs.store import RunRepository

pytestmark = pytest.mark.integration


class State(TypedDict):
    visited: Annotated[list[str], operator.add]


class Node(Protocol):
    """LangGraph node signature: matches add_node's protocol (param named `state`)."""

    def __call__(self, state: State) -> Awaitable[State]: ...


async def _run_with_epoch(pool: Pool, epoch: int) -> uuid.UUID:
    async with pool.connection() as conn:
        run = await RunRepository(conn).create(graph_name="toy", input={})
        await conn.execute("UPDATE runs SET epoch = %s WHERE id = %s", (epoch, run.id))
    return run.id


def _toy_graph(
    executions: Counter[str], on_b: Callable[[], Awaitable[None]] | None = None
) -> StateGraph[State]:
    def make_node(name: str) -> Node:
        async def node(state: State) -> State:
            executions[name] += 1
            if name == "b" and on_b is not None:
                await on_b()
            return {"visited": [name]}

        return node

    g = StateGraph(State)
    for name in "abc":
        g.add_node(name, make_node(name))
    g.add_edge(START, "a")
    g.add_edge("a", "b")
    g.add_edge("b", "c")
    g.add_edge("c", END)
    return g


def _config(run_id: uuid.UUID) -> RunnableConfig:
    return {"configurable": {"thread_id": str(run_id)}}


async def test_control_without_fencing_the_zombie_wins(pool: Pool, checkpoint_tables: None) -> None:
    """Control experiment: proves the problem is real, so the fenced test below
    isn't passing vacuously. With LangGraph's plain checkpointer, a worker whose
    lease was taken over keeps executing and its writes are persisted."""
    run_id = await _run_with_epoch(pool, epoch=1)
    executions: Counter[str] = Counter()

    async def takeover() -> None:
        async with pool.connection() as conn:
            await conn.execute("UPDATE runs SET epoch = epoch + 1 WHERE id = %s", (run_id,))

    zombie = _toy_graph(executions, on_b=takeover).compile(checkpointer=AsyncPostgresSaver(pool))
    await zombie.ainvoke({"visited": []}, _config(run_id), durability="sync")

    saved = await AsyncPostgresSaver(pool).aget_tuple(_config(run_id))
    assert saved is not None
    assert saved.checkpoint["channel_values"]["visited"] == ["a", "b", "c"]  # zombie's work won


async def test_owner_with_current_epoch_checkpoints_normally(
    pool: Pool, checkpoint_tables: None
) -> None:
    run_id = await _run_with_epoch(pool, epoch=1)
    executions: Counter[str] = Counter()
    graph = _toy_graph(executions).compile(
        checkpointer=FencedCheckpointer(pool, Fence(run_id, epoch=1))
    )

    result = await graph.ainvoke({"visited": []}, _config(run_id), durability="sync")

    assert result["visited"] == ["a", "b", "c"]
    saved = await AsyncPostgresSaver(pool).aget_tuple(_config(run_id))
    assert saved is not None
    assert saved.checkpoint["channel_values"]["visited"] == ["a", "b", "c"]


async def test_zombie_write_is_rejected_and_new_owner_resumes(
    pool: Pool, checkpoint_tables: None
) -> None:
    run_id = await _run_with_epoch(pool, epoch=1)
    executions: Counter[str] = Counter()

    async def takeover() -> None:
        # Another worker reclaims the run while this one is inside `b`.
        async with pool.connection() as conn:
            await conn.execute("UPDATE runs SET epoch = epoch + 1 WHERE id = %s", (run_id,))

    zombie = _toy_graph(executions, on_b=takeover).compile(
        checkpointer=FencedCheckpointer(pool, Fence(run_id, epoch=1))
    )
    with pytest.raises(FencedError, match="writer epoch 1, current epoch 2"):
        await zombie.ainvoke({"visited": []}, _config(run_id), durability="sync")

    # Nothing from `b` was persisted: the last good checkpoint is after `a`.
    saved = await AsyncPostgresSaver(pool).aget_tuple(_config(run_id))
    assert saved is not None
    assert saved.checkpoint["channel_values"]["visited"] == ["a"]

    # The new owner (epoch 2) resumes the same thread from that checkpoint.
    owner = _toy_graph(executions).compile(
        checkpointer=FencedCheckpointer(pool, Fence(run_id, epoch=2))
    )
    result = await owner.ainvoke(None, _config(run_id), durability="sync")

    assert result["visited"] == ["a", "b", "c"]
    # `a` committed before the takeover → never re-executed. `b` ran twice: the
    # zombie's run was discarded, which is exactly why side effects need
    # idempotency keys (R2.6) on top of fencing.
    assert executions == Counter({"a": 1, "b": 2, "c": 1})


async def test_fence_check_serialises_with_a_takeover(pool: Pool) -> None:
    """While a fenced write's transaction is open, a takeover must wait for it."""
    run_id = await _run_with_epoch(pool, epoch=1)
    async with pool.connection() as writer, writer.transaction():
        await check_fence(writer, Fence(run_id, epoch=1))  # holds FOR SHARE

        async with pool.connection() as taker:
            await taker.execute("SET lock_timeout = '200ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                await taker.execute("UPDATE runs SET epoch = epoch + 1 WHERE id = %s", (run_id,))
            await taker.execute("RESET lock_timeout")

    # Once the writer committed, the takeover goes through.
    async with pool.connection() as taker:
        await taker.execute("UPDATE runs SET epoch = epoch + 1 WHERE id = %s", (run_id,))
        with pytest.raises(FencedError):
            async with taker.transaction():
                await check_fence(taker, Fence(run_id, epoch=1))


async def test_concurrent_zombie_and_owner_never_both_commit(pool: Pool) -> None:
    """Race a stale-epoch write against a takeover many times: the stale write
    either commits before the takeover or is rejected after it, never after."""
    for _ in range(25):
        run_id = await _run_with_epoch(pool, epoch=1)
        order: list[str] = []

        async def zombie_write(rid: uuid.UUID = run_id, log: list[str] = order) -> None:
            async with pool.connection() as conn:
                try:
                    async with conn.transaction():
                        await check_fence(conn, Fence(rid, epoch=1))
                        log.append("zombie-committed")
                except FencedError:
                    log.append("zombie-rejected")

        async def takeover(rid: uuid.UUID = run_id, log: list[str] = order) -> None:
            async with pool.connection() as conn:
                await conn.execute("UPDATE runs SET epoch = epoch + 1 WHERE id = %s", (rid,))
                log.append("takeover")

        await asyncio.gather(zombie_write(), takeover())
        assert order in (["zombie-committed", "takeover"], ["takeover", "zombie-rejected"])


async def test_unknown_run_is_fenced(pool: Pool) -> None:
    async with pool.connection() as conn:
        with pytest.raises(FencedError, match="run not found"):
            async with conn.transaction():
                await check_fence(conn, Fence(uuid.uuid4(), epoch=1))

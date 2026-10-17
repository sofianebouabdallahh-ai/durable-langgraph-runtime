"""The tool_invocations ledger: "record, then act" (R2.6) + tool budgets (R14.1).

`begin` runs in ONE fenced transaction that locks the run row, so these steps
are atomic with respect to concurrent calls of the same run:

    existing row?  done/failed        → Cached: return the stored result, don't execute
                   in_progress, older epoch → abandoned by a dead owner: take it over
                   (no budget charge: it was counted when first recorded)
    no row         check budgets (total, per tool) → record in_progress → count it

Counting happens exactly when a key is first recorded. LangGraph re-runs a tool
step on resume (measured in the phase 4 research), and that must not consume
budget twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from psycopg.types.json import Jsonb

from agent_runtime.db import Conn
from agent_runtime.fencing import Fence, check_fence


class BudgetExceeded(Exception):
    """A hard limit was hit (R14.1); the run fails with `reason`."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


@dataclass(frozen=True)
class Cached:
    status: Literal["done", "failed"]
    result: Any


@dataclass(frozen=True)
class Started:
    taken_over: bool  # True: re-executing a call a dead owner left in_progress


async def begin(
    conn: Conn,
    *,
    fence: Fence,
    key: str,
    tool: str,
    max_total: int | None,
    max_for_tool: int | None,
) -> Cached | Started:
    async with conn.transaction():
        await check_fence(conn, fence)
        cur = await conn.execute(
            "SELECT tool_calls_total, tool_calls FROM runs WHERE id = %s FOR UPDATE",
            (fence.run_id,),
        )
        run = await cur.fetchone()
        assert run is not None  # check_fence just found it
        cur = await conn.execute(
            "SELECT status, result, epoch FROM tool_invocations WHERE key = %s FOR UPDATE", (key,)
        )
        row = await cur.fetchone()
        if row is not None:
            if row["status"] in ("done", "failed"):
                return Cached(row["status"], row["result"])
            await conn.execute(
                "UPDATE tool_invocations SET epoch = %s, updated_at = now() WHERE key = %s",
                (fence.epoch, key),
            )
            return Started(taken_over=row["epoch"] < fence.epoch)

        total, per_tool = int(run["tool_calls_total"]), dict(run["tool_calls"])
        if max_total is not None and total + 1 > max_total:
            raise BudgetExceeded("budget:tool_calls", f"max_tool_calls={max_total} reached")
        if max_for_tool is not None and per_tool.get(tool, 0) + 1 > max_for_tool:
            raise BudgetExceeded(
                "budget:tool_calls", f"max_calls={max_for_tool} for tool {tool!r} reached"
            )
        await conn.execute(
            "INSERT INTO tool_invocations (key, run_id, tool, status, epoch) "
            "VALUES (%s, %s, %s, 'in_progress', %s)",
            (key, fence.run_id, tool, fence.epoch),
        )
        per_tool[tool] = per_tool.get(tool, 0) + 1
        await conn.execute(
            "UPDATE runs SET tool_calls_total = tool_calls_total + 1, tool_calls = %s "
            "WHERE id = %s",
            (Jsonb(per_tool), fence.run_id),
        )
        return Started(taken_over=False)


async def finish(
    conn: Conn, *, fence: Fence, key: str, status: Literal["done", "failed"], result: Any
) -> None:
    async with conn.transaction():
        await check_fence(conn, fence)
        await conn.execute(
            "UPDATE tool_invocations SET status = %s, result = %s, updated_at = now() "
            "WHERE key = %s AND epoch = %s",
            (status, Jsonb(result), key, fence.epoch),
        )


async def charge_model_call(conn: Conn, *, fence: Fence, max_calls: int | None) -> int:
    """Count one model call against the run's budget (R14.1), durably, BEFORE the call.

    Charged immediately (not with the step's checkpoint): a model call costs money
    the moment it is made, even if the step that made it is later replayed.
    """
    async with conn.transaction():
        await check_fence(conn, fence)
        cur = await conn.execute(
            "UPDATE runs SET model_calls = model_calls + 1 "
            "WHERE id = %(id)s AND (%(max)s::int IS NULL OR model_calls < %(max)s) "
            "RETURNING model_calls",
            {"id": fence.run_id, "max": max_calls},
        )
        row = await cur.fetchone()
    if row is None:
        raise BudgetExceeded("budget:model_calls", f"max_model_calls={max_calls} reached")
    return int(row["model_calls"])

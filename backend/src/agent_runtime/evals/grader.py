"""The worker's side of an eval (phase H6): a test turn is an ordinary turn, with one
`eval_runs` row saying what it's testing.

- When the turn asks for approval, the case answers: the ask is recorded as for any turn
  (the trajectory sees it), then decided at once (`decided_by: eval`) through the normal
  approval path, and the run goes back to the queue.
- When the turn ends, it is graded once: its trajectory (evals/trajectory.py) against the
  case's expectations (evals/checks.py, evals/judge.py). The UPDATE is guarded by
  `status = 'running'`, so a reclaimed or repeated grading never grades it twice.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from psycopg.types.json import Jsonb

from agent_runtime import logs
from agent_runtime.db import Pool
from agent_runtime.evals import checks as checks_
from agent_runtime.evals.cases import Case
from agent_runtime.evals.judge import Usage, judge
from agent_runtime.evals.trajectory import read
from agent_runtime.runs.approvals import ApprovalConflict, ApprovalRepository
from agent_runtime.runs.store import NotWaitingForApproval, Run, RunRepository
from agent_runtime.sessions.store import SessionRepository
from agent_runtime.sessions.transcript import event_message, publish_messages
from agent_runtime.streaming.bus import EventBus, publish_events

log = logging.getLogger(__name__)
DECIDED_BY = "eval"


@dataclass(frozen=True, slots=True)
class EvalRun:
    run_id: uuid.UUID
    case: Case
    status: str


async def of(pool: Pool, run_id: uuid.UUID) -> EvalRun | None:
    """This run's test, if it is one."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            'SELECT "case", status FROM eval_runs WHERE run_id = %s', (run_id,)
        )
        row = await cur.fetchone()
    if row is None:
        return None
    return EvalRun(run_id, Case.model_validate(row["case"]), row["status"])


async def answer_approvals(pool: Pool, e: EvalRun, bus: EventBus | None = None) -> Run:
    """Decide every approval the turn waits on, as the case says, the way a person's
    decision is recorded: the decision, an `approval` row in the test chat, events
    published. Returns the run: back in the queue (approved), or cancelled (rejected).
    Someone who decided first (in the test chat) wins: their decision stands."""
    decision: Literal["approve", "reject"] = "approve" if e.case.approve else "reject"
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        chat = SessionRepository(conn)
        run = await repo.get(e.run_id)
        try:
            for approval in await ApprovalRepository(conn).pending(e.run_id):
                async with conn.transaction():
                    run, decided = await repo.decide_approval(
                        e.run_id, approval_id=approval.id, decision=decision, edits=None,
                        reason="decided by the test", decided_by=DECIDED_BY,
                    )  # fmt: skip
                    if run.session_id is not None:
                        row = event_message(e.run_id, "approval", {
                            "approval_id": str(decided.id), "decision": decision,
                            "reason": "decided by the test"})  # fmt: skip
                        await chat.append(run.session_id, [row], run_id=e.run_id, epoch=None)
                if decision == "reject":
                    break  # one rejection cancels the turn
        except (NotWaitingForApproval, ApprovalConflict):
            run = await repo.get(e.run_id)  # decided meanwhile, by a person or another sweep
    await publish_events(bus, repo.emitted)
    await publish_messages(bus, chat.created)
    logs.event(log, f"eval: the test answered its approvals ({decision})", run_id=str(e.run_id))
    return run


async def grade(
    pool: Pool,
    e: EvalRun,
    *,
    judge_model: BaseChatModel | None,
    record_usage: Callable[[Usage], Awaitable[None]] | None = None,
) -> str:
    """Grade the ended turn once; its outcome (`passed`, `failed` or `error`)."""
    async with pool.connection() as conn:
        t = await read(conn, e.run_id)
    results = checks_.grade(e.case.expect, t)
    if e.case.expect.judge is not None:
        check, usage = await judge(judge_model, e.case.message, t.answer, e.case.expect.judge)
        results.append(check)
        if usage is not None and record_usage is not None:
            await record_usage(usage)
    outcome = checks_.outcome(results)
    async with pool.connection() as conn:
        cur = await conn.execute(
            "UPDATE eval_runs SET status = %s, checks = %s, finished_at = now() "
            "WHERE run_id = %s AND status = 'running' RETURNING run_id",
            (outcome, Jsonb([c.as_dict() for c in results]), e.run_id),
        )
        graded = await cur.fetchone() is not None
    if graded:
        failed = [c.check for c in results if not c.ok]
        logs.event(log, f"eval: {e.case.name}: {outcome}", run_id=str(e.run_id),
                   failed=failed or None)  # fmt: skip
    return outcome


async def give_up(pool: Pool, run_id: uuid.UUID, why: str) -> None:
    """A test that can't be graded (not a passing blip): `error`, with why, not `running`
    forever."""
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE eval_runs SET status = 'error', finished_at = now(), checks = %s "
            "WHERE run_id = %s AND status = 'running'",
            (Jsonb([{"check": "graded", "ok": False, "detail": why[:300], "error": True}]),
             run_id),
        )  # fmt: skip


async def stuck(pool: Pool, limit: int = 20) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Tests the executor didn't settle (a crash, a cancel through the API, an early end):
    (waiting for an approval the case should answer, ended but not graded)."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT e.run_id, r.status FROM eval_runs e JOIN runs r ON r.id = e.run_id
            WHERE e.status = 'running'
              AND (r.status = 'waiting_approval'
                   OR r.status IN ('completed', 'failed', 'cancelled'))
            ORDER BY e.created_at LIMIT %s
            """,
            (limit,),
        )
        rows = await cur.fetchall()
    waiting = [r["run_id"] for r in rows if r["status"] == "waiting_approval"]
    return waiting, [r["run_id"] for r in rows if r["status"] != "waiting_approval"]


def summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    """How many cases passed, failed, errored or still run."""
    out = {"passed": 0, "failed": 0, "error": 0, "running": 0}
    for r in rows:
        out[str(r["status"])] = out.get(str(r["status"]), 0) + 1
    return out

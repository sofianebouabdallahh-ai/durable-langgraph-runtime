"""Evals for Studio agents (phase H6): the Tests tab's use cases.

- Cases: list, add, change, remove (a change makes the case's earlier results stale).
- Run tests: one test chat per case (side effects are simulated there, R17.3), its
  message sent as a turn; the `eval_runs` row is written in the turn's own transaction,
  so no worker can see the turn before it is known to be a test. Workers grade it when it
  ends (evals/grader.py).
- Make this a test: a 👎 reply becomes a case, its reason the judge's rubric.
- The publish gate itself is in the Studio (agents/studio.py), through EvalStore.failing.
"""

from __future__ import annotations

import uuid
from typing import Any

from agent_runtime.agents.studio_store import AgentStore
from agent_runtime.db import Conn, Pool
from agent_runtime.evals.cases import Case, Expect
from agent_runtime.evals.store import EvalStore, Result, StoredCase
from agent_runtime.evals.trajectory import answer
from agent_runtime.feedback import FeedbackRepository
from agent_runtime.ids import new_id
from agent_runtime.runs.store import Run, RunRepository
from agent_runtime.sessions.service import SessionService


class NoCases(Exception):
    """Run tests with no test to run (→ 409)."""


class NotFromStudio(Exception):
    """Make this a test on a reply that isn't a Studio agent's (→ 409)."""


class EvalService:
    def __init__(self, pool: Pool, sessions: SessionService) -> None:
        self._pool = pool
        self._sessions = sessions

    async def cases(self, agent_id: uuid.UUID) -> list[StoredCase]:
        async with self._pool.connection() as conn:
            await AgentStore(conn).get(agent_id)  # AgentNotFound → 404
            return await EvalStore(conn).cases(agent_id)

    async def add(self, agent_id: uuid.UUID, case: Case) -> StoredCase:
        async with self._pool.connection() as conn, conn.transaction():
            await AgentStore(conn).get(agent_id)
            return await EvalStore(conn).add(agent_id, case)

    async def replace(self, agent_id: uuid.UUID, case_id: uuid.UUID, case: Case) -> StoredCase:
        async with self._pool.connection() as conn, conn.transaction():
            return await EvalStore(conn).replace(agent_id, case_id, case)

    async def remove(self, agent_id: uuid.UUID, case_id: uuid.UUID) -> None:
        async with self._pool.connection() as conn, conn.transaction():
            await EvalStore(conn).remove(agent_id, case_id)

    async def run(self, agent_id: uuid.UUID) -> uuid.UUID:
        """Send every case as a turn in its own test chat; the batch's id. Raises
        NoCases, AgentNotFound, AgentUnavailable (an invalid draft)."""
        async with self._pool.connection() as conn:
            agent = await AgentStore(conn).get(agent_id)
            cases = await EvalStore(conn).cases(agent_id)
        if not cases:
            raise NoCases("This agent has no tests yet")
        batch = new_id()
        for stored in cases:
            case = stored.case
            chat = await self._sessions.create(agent.name, f"Test: {case.name}"[:80],
                                               playground_of=agent_id)  # fmt: skip

            async def known(
                conn: Conn, run: Run, key: str = str(stored.id), c: Case = case
            ) -> None:
                await EvalStore(conn).record(
                    run.id, agent=agent.name, agent_id=agent_id, case_key=key, case=c,
                    bundle_hash=run.agent_hash, batch=batch,
                )  # fmt: skip

            await self._sessions.send(
                chat.id, case.message, on_created=known,
                script=[t.model_dump(mode="json") for t in case.script] or None,
                subagent_scripts={k: [t.model_dump(mode="json") for t in v]
                                  for k, v in case.subagent_scripts.items()} or None,
            )  # fmt: skip
        return batch

    async def results(self, agent_id: uuid.UUID, bundle_hash: str | None) -> dict[str, Result]:
        async with self._pool.connection() as conn:
            return await EvalStore(conn).latest(agent_id, bundle_hash)

    async def newest(self, agent_id: uuid.UUID) -> dict[str, Result]:
        async with self._pool.connection() as conn:
            return await EvalStore(conn).newest(agent_id)

    async def batch(self, batch: uuid.UUID) -> list[Result]:
        async with self._pool.connection() as conn:
            return await EvalStore(conn).batch(batch)

    async def from_run(self, run_id: uuid.UUID) -> StoredCase:
        """A 👎 reply of a Studio agent becomes a test: the person's message, and a
        rubric from the reason they gave and the answer they didn't like."""
        async with self._pool.connection() as conn, conn.transaction():
            run = await RunRepository(conn).get(run_id)
            agent = await AgentStore(conn).by_name(run.agent_name or "")
            if agent is None:
                raise NotFromStudio("Only your own agents (Studio) have tests")
            feedback = await FeedbackRepository(conn).get(run_id)
            reply = await answer(conn, run_id)
            case = Case(
                name=f"From a 👎: {_short(_message(run), 60)}",
                message=_message(run),
                expect=Expect(judge=_rubric(reply, feedback.reason if feedback else None)),
            )
            return await EvalStore(conn).add(agent.id, case, from_run=run_id)


def _message(run: Run) -> str:
    message = (run.input or {}).get("message")
    return str(message) if message else "(no message)"


def _rubric(bad: str, reason: str | None) -> str:
    said = f" The person said: “{_short(reason, 300)}”." if reason else ""
    return (f"A better answer than the one the person rated 👎.{said} "
            f"That answer was: “{_short(bad, 600)}”.")  # fmt: skip


def _short(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def summary(results: list[Result]) -> dict[str, Any]:
    counts = {"passed": 0, "failed": 0, "error": 0, "running": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    return counts

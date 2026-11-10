"""Run a built-in agent's suite in this process (phase H6): `runtime eval` and CI.

The same path as a Studio test: each case is a turn in its own chat, with its
`eval_runs` row written in the turn's transaction; the executor answers its approvals and
grades it when it ends. Here the executor runs in this process (as the tests do), so a
suite needs the database, not the workers.

Suites live next to the agent: `agents/<agent>/evals/*.yaml`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_runtime.config import Settings
from agent_runtime.db import Conn, Pool
from agent_runtime.evals.cases import Case, load_dir
from agent_runtime.evals.store import EvalStore
from agent_runtime.graphs import GraphRegistry
from agent_runtime.ids import new_id
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.service import RunService
from agent_runtime.runs.store import Run
from agent_runtime.sessions.service import SessionService

MAX_EXECUTIONS = 10  # a turn that pauses for approval runs again once answered


@dataclass(frozen=True, slots=True)
class Outcome:
    key: str
    case: Case
    status: str
    checks: list[dict[str, Any]]
    run_id: uuid.UUID


def suites(agents_dir: Path, names: list[str] | None = None) -> dict[str, list[tuple[str, Case]]]:
    """Each agent's cases (`<agents_dir>/<agent>/evals/*.yaml`), for `names` or all."""
    out: dict[str, list[tuple[str, Case]]] = {}
    for folder in sorted(p for p in agents_dir.iterdir() if (p / "evals").is_dir()):
        if names and folder.name not in names:
            continue
        out[folder.name] = load_dir(folder / "evals")
    missing = set(names or []) - set(out)
    if missing:
        raise ValueError(f"no suite for {', '.join(sorted(missing))} (agents/<name>/evals/)")
    return out


async def run_suite(
    pool: Pool, settings: Settings, graphs: GraphRegistry, agent: str,
    cases: list[tuple[str, Case]], **executor: Any,
) -> list[Outcome]:  # fmt: skip
    """Every case of `agent`, each as a turn in its own chat, graded; in order.
    `executor`: passed to each RunExecutor (a test swaps the policy, to prove a regression
    fails the suite)."""
    unlimited = settings.model_copy(update={"session_messages_per_minute": 1_000_000})
    sessions = SessionService(pool, unlimited, graphs, RunService(pool, unlimited, graphs))
    batch = new_id()
    out: list[Outcome] = []
    for key, case in cases:
        chat = await sessions.create(agent, f"Test: {case.name}"[:80])

        async def known(conn: Conn, run: Run, k: str = f"{agent}/{key}", c: Case = case) -> None:
            await EvalStore(conn).record(
                run.id, agent=agent, agent_id=None, case_key=k, case=c,
                bundle_hash=run.agent_hash, batch=batch,
            )  # fmt: skip

        turn = await sessions.send(
            chat.id, case.message, on_created=known,
            script=[t.model_dump(mode="json") for t in case.script] or None,
            subagent_scripts={k: [t.model_dump(mode="json") for t in v]
                              for k, v in case.subagent_scripts.items()} or None,
        )  # fmt: skip
        for _ in range(MAX_EXECUTIONS):
            ended = await RunExecutor(pool, settings, graphs, **executor).execute(turn.run.id)
            if ended.status.is_terminal:
                break
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT status, checks FROM eval_runs WHERE run_id = %s", (turn.run.id,)
            )
            row = await cur.fetchone()
        assert row is not None
        out.append(Outcome(key, case, row["status"], list(row["checks"]), turn.run.id))
    return out


def report(agent: str, outcomes: list[Outcome]) -> tuple[str, bool]:
    """Plain text, PASS/FAIL per check; and whether every case passed."""
    lines = [f"== {agent}"]
    for o in outcomes:
        lines.append(f"  {o.status.upper():6} {o.case.name}  ({o.key})")
        for c in o.checks:
            if not c["ok"]:
                mark = "ERROR" if c.get("error") else "FAIL"
                lines.append(
                    f"           {mark}  {c['check']}" + (f": {c['detail']}" if c["detail"] else "")
                )
    ok = all(o.status == "passed" for o in outcomes)
    lines.append(f"  => {sum(o.status == 'passed' for o in outcomes)}/{len(outcomes)} passed")
    return "\n".join(lines), ok

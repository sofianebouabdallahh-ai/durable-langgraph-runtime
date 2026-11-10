"""Persistence for agent evals (phase H6): a Studio agent's cases, and graded turns."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from agent_runtime.db import Conn
from agent_runtime.evals.cases import Case
from agent_runtime.ids import new_id


class CaseNotFound(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class StoredCase:
    id: uuid.UUID
    agent_id: uuid.UUID
    case: Case
    from_run: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Result:
    run_id: uuid.UUID
    session_id: uuid.UUID | None
    case_key: str
    case_hash: str
    bundle_hash: str | None
    batch: uuid.UUID
    status: str
    checks: list[dict[str, Any]]
    created_at: datetime
    finished_at: datetime | None


class EvalStore:
    def __init__(self, conn: Conn) -> None:
        self._conn = conn

    # ------------------------------------------------------------------ cases

    async def cases(self, agent_id: uuid.UUID) -> list[StoredCase]:
        cur = await self._conn.execute(
            'SELECT id, agent_id, "case", from_run, created_at, updated_at FROM agent_evals '
            "WHERE agent_id = %s ORDER BY created_at, id",
            (agent_id,),
        )
        return [_case(r) for r in await cur.fetchall()]

    async def case(self, agent_id: uuid.UUID, case_id: uuid.UUID) -> StoredCase:
        cur = await self._conn.execute(
            'SELECT id, agent_id, "case", from_run, created_at, updated_at FROM agent_evals '
            "WHERE agent_id = %s AND id = %s",
            (agent_id, case_id),
        )
        row = await cur.fetchone()
        if row is None:
            raise CaseNotFound(str(case_id))
        return _case(row)

    async def add(
        self, agent_id: uuid.UUID, case: Case, *, from_run: uuid.UUID | None = None
    ) -> StoredCase:
        cur = await self._conn.execute(
            'INSERT INTO agent_evals (id, agent_id, name, "case", from_run) '
            'VALUES (%s, %s, %s, %s, %s) RETURNING id, agent_id, "case", from_run, '
            "created_at, updated_at",
            (new_id(), agent_id, case.name, Jsonb(case.model_dump(mode="json")), from_run),
        )
        row = await cur.fetchone()
        assert row is not None
        return _case(row)

    async def replace(self, agent_id: uuid.UUID, case_id: uuid.UUID, case: Case) -> StoredCase:
        cur = await self._conn.execute(
            'UPDATE agent_evals SET name = %s, "case" = %s, updated_at = now() '
            "WHERE agent_id = %s AND id = %s "
            'RETURNING id, agent_id, "case", from_run, created_at, updated_at',
            (case.name, Jsonb(case.model_dump(mode="json")), agent_id, case_id),
        )
        row = await cur.fetchone()
        if row is None:
            raise CaseNotFound(str(case_id))
        return _case(row)

    async def remove(self, agent_id: uuid.UUID, case_id: uuid.UUID) -> None:
        cur = await self._conn.execute(
            "DELETE FROM agent_evals WHERE agent_id = %s AND id = %s RETURNING id",
            (agent_id, case_id),
        )
        if await cur.fetchone() is None:
            raise CaseNotFound(str(case_id))

    # ---------------------------------------------------------------- results

    async def record(
        self, run_id: uuid.UUID, *, agent: str, agent_id: uuid.UUID | None, case_key: str,
        case: Case, bundle_hash: str | None, batch: uuid.UUID,
    ) -> None:  # fmt: skip
        """A test turn was sent: grade it when it ends. In the turn's own transaction."""
        await self._conn.execute(
            'INSERT INTO eval_runs (run_id, agent, agent_id, case_key, case_hash, "case", '
            "bundle_hash, batch) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (run_id, agent, agent_id, case_key, case.digest(),
             Jsonb(case.model_dump(mode="json")), bundle_hash, batch),
        )  # fmt: skip

    async def latest(self, agent_id: uuid.UUID, bundle_hash: str | None) -> dict[str, Result]:
        """Each case's latest result on this bundle, by case key."""
        cur = await self._conn.execute(
            """
            SELECT DISTINCT ON (e.case_key) e.*, r.session_id
            FROM eval_runs e JOIN runs r ON r.id = e.run_id
            WHERE e.agent_id = %s AND e.bundle_hash IS NOT DISTINCT FROM %s
            ORDER BY e.case_key, e.created_at DESC
            """,
            (agent_id, bundle_hash),
        )
        return {r["case_key"]: _result(r) for r in await cur.fetchall()}

    async def newest(self, agent_id: uuid.UUID) -> dict[str, Result]:
        """Each case's latest result, on any bundle (the Tests tab says if it's current)."""
        cur = await self._conn.execute(
            """
            SELECT DISTINCT ON (e.case_key) e.*, r.session_id
            FROM eval_runs e JOIN runs r ON r.id = e.run_id
            WHERE e.agent_id = %s ORDER BY e.case_key, e.created_at DESC
            """,
            (agent_id,),
        )
        return {r["case_key"]: _result(r) for r in await cur.fetchall()}

    async def batch(self, batch: uuid.UUID) -> list[Result]:
        cur = await self._conn.execute(
            "SELECT e.*, r.session_id FROM eval_runs e JOIN runs r ON r.id = e.run_id "
            "WHERE e.batch = %s ORDER BY e.created_at",
            (batch,),
        )
        return [_result(r) for r in await cur.fetchall()]

    async def failing(self, agent_id: uuid.UUID, bundle_hash: str) -> list[str]:
        """The names of the cases that haven't passed on exactly this bundle, as they are
        now (an edited case's old result doesn't count): the publish gate."""
        cases = await self.cases(agent_id)
        latest = await self.latest(agent_id, bundle_hash)
        out: list[str] = []
        for c in cases:
            r = latest.get(str(c.id))
            if r is None or r.status != "passed" or r.case_hash != c.case.digest():
                out.append(c.case.name)
        return out


def _case(r: dict[str, Any]) -> StoredCase:
    return StoredCase(id=r["id"], agent_id=r["agent_id"], case=Case.model_validate(r["case"]),
                      from_run=r["from_run"], created_at=r["created_at"],
                      updated_at=r["updated_at"])  # fmt: skip


def _result(r: dict[str, Any]) -> Result:
    return Result(run_id=r["run_id"], session_id=r.get("session_id"), case_key=r["case_key"],
                  case_hash=r["case_hash"], bundle_hash=r["bundle_hash"], batch=r["batch"],
                  status=r["status"], checks=list(r["checks"] or []),
                  created_at=r["created_at"], finished_at=r["finished_at"])  # fmt: skip

"""Activity (phase L7): what all agents have been doing, read from Postgres.

The read side only (a Query Service, CQRS-style): aggregates over chat turns (`runs` of
kind `turn`), their sessions, run events and per-model usage, for the Activity page.
Nothing here writes. Every number comes from the same rows the rest of the app uses, so
it can't drift from them (the tests compare it with raw queries).

A turn's tokens and cost are its own plus its helpers' (they roll up to the turn); per
model, each call counts once, at the run that made it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from agent_runtime.db import Conn

Range = Literal["24h", "7d", "30d"]
RANGES: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


@dataclass(frozen=True)
class Scope:
    """Which turns: since when, one agent or all, test chats in or out."""

    since: datetime
    agent: str | None = None
    include_tests: bool = False

    @classmethod
    def of(cls, range_: str, agent: str | None, include_tests: bool) -> Scope:
        return cls(datetime.now(UTC) - RANGES[range_], agent, include_tests)

    @property
    def params(self) -> dict[str, Any]:
        return {"since": self.since, "agent": self.agent, "tests": self.include_tests}


# The turns in scope: chat turns since `since`, of `agent` (or all), test chats optional.
TURNS = """
    FROM runs r LEFT JOIN sessions s ON s.id = r.session_id
    WHERE r.kind = 'turn' AND r.created_at >= %(since)s
      AND (%(agent)s::text IS NULL OR r.agent_name = %(agent)s)
      AND (%(tests)s OR s.playground_of IS NULL)
"""
# Every run of those turns (the turn itself and its helpers' children), for events.
TURN_RUNS = f"""
    SELECT r.id {TURNS}
    UNION ALL
    SELECT c.id FROM runs c WHERE c.root_run_id IN (SELECT r.id {TURNS})
"""
DURATION = "extract(epoch FROM r.finished_at - r.started_at)"
TURN_COLUMNS = """
    r.id, r.created_at, r.started_at, r.finished_at, r.agent_name, r.agent_version, r.status,
    r.reason, r.session_id, s.title AS session_title, s.playground_of IS NOT NULL AS test,
    r.steps, r.model_calls, r.tool_calls_total, r.tokens, r.cost, r.reclaims,
    coalesce((SELECT array_agg(u.model ORDER BY u.calls DESC)
              FROM run_model_usage u WHERE u.run_id = r.id), '{}') AS models
"""


def _num(value: Any) -> float:
    return float(value) if value is not None else 0.0


def _turn(r: dict[str, Any]) -> dict[str, Any]:
    started, finished = r["started_at"], r["finished_at"]
    return {
        **r,
        "tokens": int(r["tokens"]),
        "cost": _num(r["cost"]),
        "duration_s": (finished - started).total_seconds() if started and finished else None,
    }


class ActivityRepository:
    def __init__(self, conn: Conn) -> None:
        self._conn = conn

    async def _rows(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        cur = await self._conn.execute(sql, params)
        return list(await cur.fetchall())

    async def _row(self, sql: str, params: dict[str, Any]) -> dict[str, Any]:
        rows = await self._rows(sql, params)
        return rows[0] if rows else {}

    # ---------------------------------------------------------------- right now

    async def now(self) -> dict[str, Any]:
        row = await self._row(
            """
            SELECT
              count(*) FILTER (WHERE status = 'running') AS running,
              count(*) FILTER (WHERE status = 'waiting_approval') AS waiting_approval,
              count(*) FILTER (WHERE status = 'queued') AS queued,
              coalesce(sum(cost) FILTER (
                WHERE created_at >= date_trunc('day', now() AT TIME ZONE 'UTC')
                                    AT TIME ZONE 'UTC'), 0) AS spend_today
            FROM runs WHERE kind = 'turn' AND parent_run_id IS NULL
              AND (status IN ('running', 'waiting_approval', 'queued')
                   OR created_at >= now() - interval '1 day')
            """,
            {},
        )
        waiting = await self._rows(
            """
            SELECT r.id, r.session_id, r.agent_name, r.interrupt_payload, r.waiting_since
            FROM runs r WHERE r.status = 'waiting_approval' AND r.kind = 'turn'
            ORDER BY r.waiting_since NULLS LAST LIMIT 20
            """,
            {},
        )
        return {
            "running": row.get("running", 0),
            "waiting_approval": row.get("waiting_approval", 0),
            "queued": row.get("queued", 0),
            "spend_today": _num(row.get("spend_today")),
            "waiting": [
                {
                    "run_id": w["id"],
                    "session_id": w["session_id"],
                    "agent": w["agent_name"],
                    "tool": (w["interrupt_payload"] or {}).get("tool"),
                    "since": w["waiting_since"],
                }
                for w in waiting
            ],
        }

    # ------------------------------------------------------------------- totals

    async def totals(self, scope: Scope) -> dict[str, Any]:
        p = scope.params
        turns = await self._row(
            f"""
            SELECT count(*) AS turns,
                   count(*) FILTER (WHERE r.status = 'failed') AS failed,
                   count(DISTINCT r.session_id) AS chats,
                   coalesce(sum(r.tokens), 0) AS tokens,
                   coalesce(sum(r.cost), 0) AS cost,
                   coalesce(sum(r.tool_calls_total), 0) AS tool_calls,
                   coalesce(sum(r.model_calls), 0) AS model_calls
            {TURNS}
            """,
            p,
        )
        events = await self._row(
            f"""
            SELECT
              count(*) FILTER (WHERE e.type = 'interrupt.raised') AS approvals_asked,
              count(*) FILTER (WHERE e.type = 'approval.decided'
                               AND e.payload->>'decision' = 'approve') AS approved,
              count(*) FILTER (WHERE e.type = 'approval.decided'
                               AND e.payload->>'decision' = 'reject') AS rejected,
              count(*) FILTER (WHERE e.type = 'subagent.spawned') AS helpers
            FROM run_events e WHERE e.run_id IN ({TURN_RUNS})
              AND e.type IN ('interrupt.raised', 'approval.decided', 'subagent.spawned')
            """,
            p,
        )
        return {
            "turns": turns.get("turns", 0),
            "failed": turns.get("failed", 0),
            "chats": turns.get("chats", 0),
            "tokens": int(turns.get("tokens", 0)),
            "cost": _num(turns.get("cost")),
            "tool_calls": int(turns.get("tool_calls", 0)),
            "model_calls": int(turns.get("model_calls", 0)),
            "helpers": events.get("helpers", 0),
            "approvals": {
                "asked": events.get("approvals_asked", 0),
                "approved": events.get("approved", 0),
                "rejected": events.get("rejected", 0),
            },
        }

    # -------------------------------------------------------------- over time

    async def series(self, scope: Scope) -> list[dict[str, Any]]:
        """Per day (UTC): turns, failed turns and cost, and turns per agent."""
        rows = await self._rows(
            f"""
            SELECT date_trunc('day', r.created_at AT TIME ZONE 'UTC')::date AS day,
                   r.agent_name AS agent, count(*) AS turns,
                   count(*) FILTER (WHERE r.status = 'failed') AS failed,
                   coalesce(sum(r.cost), 0) AS cost
            {TURNS}
            GROUP BY 1, 2 ORDER BY 1
            """,
            scope.params,
        )
        days: dict[str, dict[str, Any]] = {}
        for r in rows:
            key = r["day"].isoformat()
            empty = {"day": key, "turns": 0, "failed": 0, "cost": 0.0, "by_agent": {}}
            d = days.setdefault(key, empty)
            d["turns"] += r["turns"]
            d["failed"] += r["failed"]
            d["cost"] += _num(r["cost"])
            d["by_agent"][r["agent"] or "?"] = r["turns"]
        return list(days.values())

    # ------------------------------------------------------------ breakdowns

    async def agents(self, scope: Scope) -> list[dict[str, Any]]:
        rows = await self._rows(
            f"""
            SELECT r.agent_name AS agent, count(*) AS turns,
                   count(*) FILTER (WHERE r.status = 'failed') AS failed,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY {DURATION}) AS p50_s,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY {DURATION}) AS p95_s,
                   coalesce(sum(r.tokens), 0) AS tokens, coalesce(sum(r.cost), 0) AS cost,
                   max(r.created_at) AS last_turn
            {TURNS}
            GROUP BY r.agent_name ORDER BY count(*) DESC
            """,
            scope.params,
        )
        return [
            {
                "agent": r["agent"] or "?",
                "turns": r["turns"],
                "failed": r["failed"],
                "p50_s": r["p50_s"],
                "p95_s": r["p95_s"],
                "tokens": int(r["tokens"]),
                "cost": _num(r["cost"]),
                "last_turn": r["last_turn"],
            }
            for r in rows
        ]

    async def models(self, scope: Scope) -> list[dict[str, Any]]:
        rows = await self._rows(
            f"""
            SELECT u.model, sum(u.calls) AS calls, sum(u.tokens_in) AS tokens_in,
                   sum(u.tokens_out) AS tokens_out, sum(u.cost) AS cost,
                   sum(u.duration_ms) AS duration_ms
            FROM run_model_usage u WHERE u.run_id IN ({TURN_RUNS})
            GROUP BY u.model ORDER BY sum(u.calls) DESC
            """,
            scope.params,
        )
        return [
            {
                "model": r["model"],
                "calls": int(r["calls"]),
                "tokens_in": int(r["tokens_in"]),
                "tokens_out": int(r["tokens_out"]),
                "cost": _num(r["cost"]),
                "avg_ms": round(int(r["duration_ms"]) / int(r["calls"])) if r["calls"] else None,
            }
            for r in rows
        ]

    async def tools(self, scope: Scope) -> list[dict[str, Any]]:
        rows = await self._rows(
            f"""
            SELECT e.payload->>'tool' AS tool, count(*) AS calls,
                   count(*) FILTER (WHERE e.payload->>'status' <> 'done') AS failed,
                   count(*) FILTER (WHERE (e.payload->>'cached')::boolean) AS cached,
                   percentile_cont(0.95) WITHIN GROUP (
                     ORDER BY (e.payload->>'duration_ms')::float) AS p95_ms
            FROM run_events e WHERE e.type = 'tool.completed' AND e.run_id IN ({TURN_RUNS})
            GROUP BY 1 ORDER BY count(*) DESC
            """,
            scope.params,
        )
        return [
            {
                "tool": r["tool"],
                "calls": r["calls"],
                "failed": r["failed"],
                "cached": r["cached"],
                "p95_ms": r["p95_ms"],
            }
            for r in rows
        ]

    async def errors(self, scope: Scope) -> list[dict[str, Any]]:
        """Failed turns, by reason and agent, each with its latest example."""
        rows = await self._rows(
            f"""
            SELECT DISTINCT ON (r.reason, r.agent_name)
                   r.reason, r.agent_name AS agent, r.id AS run_id, r.session_id,
                   r.created_at AS at,
                   count(*) OVER (PARTITION BY r.reason, r.agent_name) AS count
            {TURNS} AND r.status = 'failed'
            ORDER BY r.reason, r.agent_name, r.created_at DESC
            """,
            scope.params,
        )
        return sorted(
            [{**r, "agent": r["agent"] or "?"} for r in rows],
            key=lambda r: -int(r["count"]),
        )

    # -------------------------------------------------------------- the lists

    async def turns(
        self,
        scope: Scope,
        *,
        status: str | None = None,
        reason: str | None = None,
        session_id: uuid.UUID | None = None,
        before: datetime | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Turns, newest first (`before`: the cursor), with their models."""
        rows = await self._rows(
            f"""
            SELECT {TURN_COLUMNS}
            {TURNS}
              AND (%(status)s::text IS NULL OR r.status = %(status)s)
              AND (%(reason)s::text IS NULL OR r.reason = %(reason)s)
              AND (%(session)s::uuid IS NULL OR r.session_id = %(session)s)
              AND (%(before)s::timestamptz IS NULL OR r.created_at < %(before)s)
            ORDER BY r.created_at DESC LIMIT %(limit)s
            """,
            scope.params
            | {
                "status": status,
                "reason": reason,
                "session": session_id,
                "before": before,
                "limit": limit,
            },
        )
        return [_turn(r) for r in rows]

    async def one_turn(self, run_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = await self._rows(
            f"SELECT {TURN_COLUMNS} FROM runs r LEFT JOIN sessions s ON s.id = r.session_id "
            "WHERE r.id = %(id)s",
            {"id": run_id},
        )
        return [_turn(r) for r in rows]

    async def sessions(self, scope: Scope, *, limit: int = 50) -> list[dict[str, Any]]:
        """Chats with a turn in scope, latest activity first, with their totals."""
        rows = await self._rows(
            f"""
            SELECT s.id, s.title, s.agent_name AS agent, s.status, s.last_seq AS messages,
                   s.tokens, s.cost, s.created_at, s.last_activity_at,
                   s.playground_of IS NOT NULL AS test,
                   count(*) AS turns, count(*) FILTER (WHERE r.status = 'failed') AS failed
            {TURNS} AND s.id IS NOT NULL
            GROUP BY s.id ORDER BY s.last_activity_at DESC LIMIT %(limit)s
            """,
            scope.params | {"limit": limit},
        )
        return [{**r, "tokens": int(r["tokens"]), "cost": _num(r["cost"])} for r in rows]

    async def model_usage(self, run_id: uuid.UUID) -> list[dict[str, Any]]:
        """One run's model calls, per model (the turn detail)."""
        rows = await self._rows(
            "SELECT model, calls, tokens_in, tokens_out, cost, duration_ms "
            "FROM run_model_usage WHERE run_id = %(id)s ORDER BY calls DESC",
            {"id": run_id},
        )
        return [{**r, "cost": _num(r["cost"])} for r in rows]

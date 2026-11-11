"""Prometheus metrics (R7.2, with the CR-001, CR-003 and CR-005 additions).

    committed events ──► publish_events ──► observe_events ─► counters, histograms
    model call (middleware) ──► llm_usage                    ─► tokens, cost, calls
    run reaches a stopping point (executor) ──► run_ended    ─► run/turn latency
    StatePoller (API, every few seconds) ── Postgres, Redis  ─► gauges

Patterns:
- Registry: every metric is declared here, once, with its labels; call sites use
  the small functions below and never touch prometheus_client.
- Observer: most counters are derived from the events the runtime already
  commits (R1.5), at the one place they all pass through after COMMIT
  (`publish_events`). An event is counted exactly once, by the process that
  committed it, and a rolled-back (fenced) write is never counted.

The API and the workers each expose their own registry (`/metrics`, and the
worker's `:8081/metrics`); Prometheus sums across replicas. State gauges
(queue depth, leases, sessions, daily cost, kill switch) are the same from every
API replica: dashboards take `max()` of them.

Labels are bounded: tool and node names come from code registries, models from
configuration, reasons from `FailureReason`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

if TYPE_CHECKING:
    from agent_runtime.db import Pool
    from agent_runtime.queue import WorkQueue

log = logging.getLogger(__name__)

_LATENCY = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300)

RUNS = Counter("runtime_runs_total", "Runs that reached an end", ["status", "reason"])
RUNS_STARTED = Counter("runtime_runs_started_total", "Executions started on a fresh lease")
RECLAIMS = Counter("runtime_reclaims_total", "Runs taken over from a dead worker (R2.4)")
RELEASES = Counter("runtime_releases_total", "Graceful hand-offs (R10.7)", ["reason"])
DEFERRED = Counter(
    "runtime_runs_deferred_total", "Runs a worker left for later (H7: newer code)", ["reason"]
)
REDRIVES = Counter("runtime_redrives_total", "Failed runs a person tried again (H4)")
NOTIFICATIONS = Counter(
    "runtime_notifications_total", "Notification delivery attempts (H4)", ["outcome"]
)
APPROVALS = Counter("runtime_approvals_total", "Human decisions on paused runs", ["decision"])
INTERRUPTS = Counter("runtime_interrupts_total", "Runs that paused for a person (R1.4)")
CHILDREN = Counter("runtime_children_spawned_total", "Child runs spawned (R2.8)")
NODE_SECONDS = Histogram(
    "runtime_node_duration_seconds", "Node latency", ["node", "outcome"], buckets=_LATENCY
)
TOOL_CALLS = Counter(
    "runtime_tool_calls_total", "Tool calls that ran or replayed", ["tool", "cached", "status"]
)
TOOL_SECONDS = Histogram(
    "runtime_tool_duration_seconds", "Tool latency", ["tool"], buckets=_LATENCY
)
POLICY = Counter("runtime_policy_decisions_total", "Policy decisions", ["decision", "kind"])
HOOKS = Counter("runtime_hook_decisions_total", "Non-continue hook decisions", ["decision"])
SUBAGENTS = Counter("runtime_subagents_total", "Sub-agents that ended (CR-005)", ["outcome"])
SUBAGENTS_SPAWNED = Counter("runtime_subagents_spawned_total", "Sub-agents spawned")
BUDGET_WARNINGS = Counter(
    "runtime_budget_warnings_total", "Soft limits reached: a wrap-up turn (R14.2)", ["budget"]
)
BUDGET_BREACHES = Counter(
    "runtime_budget_breaches_total", "Runs ended by a budget (R14.1)", ["budget"]
)
LOOPS = Counter("runtime_loop_detections_total", "Runs stopped for not progressing (R14.4)")
LLM_CALLS = Counter("runtime_llm_calls_total", "Model responses", ["model"])
LLM_TOKENS = Counter("runtime_llm_tokens_total", "Model tokens", ["model", "direction"])
LLM_COST = Counter("runtime_llm_cost_usd_total", "Model spend in USD", ["model"])
LLM_SECONDS = Histogram(
    "runtime_llm_duration_seconds", "Model call latency (with retries)", ["model"],
    buckets=_LATENCY,
)  # fmt: skip
RUN_SECONDS = Histogram(
    "runtime_run_duration_seconds",
    "Created → ended (a chat turn: the person's wait)",
    ["kind", "status"],
    buckets=_LATENCY,
)

QUEUE_DEPTH = Gauge("runtime_queue_depth", "Runs waiting for a worker (Postgres)")
PENDING = Gauge("runtime_queue_pending", "Delivered, unacknowledged work messages (Redis)")
LEASES = Gauge("runtime_active_leases", "Runs held by a worker right now")
WAITING = Gauge("runtime_runs_waiting", "Runs paused", ["on"])
SESSIONS = Gauge("runtime_active_sessions", "Chat sessions not archived")
COST_TODAY = Gauge("runtime_cost_today_usd", "Spend since midnight UTC (R14.8)")
PAUSED = Gauge("runtime_kill_switch", "1 while every agent is switched off (R14.18)")
AGENTS_OFF = Gauge("runtime_agents_switched_off", "Agents switched off one by one (L6)")
SUBSCRIBERS = Gauge("runtime_stream_subscribers", "Open live streams on this replica")
INFLIGHT = Gauge("runtime_worker_inflight", "Runs in flight in this worker")
WORKER_LOOP = Gauge("runtime_worker_loop_timestamp_seconds", "Last tick of the worker's loop")


def render() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST


# ------------------------------------------------------------------ events


def _budget(reason: str) -> str | None:
    return reason.removeprefix("budget:") if reason.startswith("budget:") else None


def observe_events(events: Iterable[Any]) -> None:
    """Count committed events (called after COMMIT, once per event). Never raises."""
    for e in events:
        try:
            _observe(str(e.type), e.payload or {})
        except Exception:  # a metric must never fail a run
            log.debug("metrics: could not observe %s", getattr(e, "type", e), exc_info=True)


def _observe(type_: str, p: dict[str, Any]) -> None:
    match type_:
        case "run.completed":
            RUNS.labels("completed", "").inc()
        case "run.failed" | "run.cancelled":
            reason = str(p.get("reason") or "")
            RUNS.labels(type_.removeprefix("run."), reason).inc()
            if budget := _budget(reason):
                BUDGET_BREACHES.labels(budget).inc()
            elif reason == "loop_detected":
                LOOPS.inc()
        case "run.started":
            RUNS_STARTED.inc()
        case "run.reclaimed":
            RECLAIMS.inc()
        case "run.released":
            RELEASES.labels(str(p.get("reason") or "draining")).inc()
        case "run.redriven":
            REDRIVES.inc()
        case "interrupt.raised":
            INTERRUPTS.inc()
        case "approval.decided":
            APPROVALS.labels(str(p.get("decision"))).inc()
        case "children.spawned":
            CHILDREN.inc(len(p.get("children") or []))
        case "node.completed" | "node.failed":
            outcome = "ok" if type_ == "node.completed" else "error"
            NODE_SECONDS.labels(str(p.get("node")), outcome).observe(
                float(p.get("duration_ms") or 0) / 1000
            )
        case "tool.completed":
            tool = str(p.get("tool"))
            TOOL_CALLS.labels(tool, str(bool(p.get("cached"))).lower(), str(p.get("status"))).inc()
            if not p.get("cached"):
                TOOL_SECONDS.labels(tool).observe(float(p.get("duration_ms") or 0) / 1000)
        case "policy.decision":
            POLICY.labels(str(p.get("decision")), str(p.get("kind") or "policy")).inc()
        case "hook.decision":
            HOOKS.labels(str(p.get("decision"))).inc()
        case "subagent.spawned":
            SUBAGENTS_SPAWNED.inc()
        case "subagent.completed":
            SUBAGENTS.labels(str(p.get("status"))).inc()


# ------------------------------------------------------------ direct hooks


def llm_usage(model: str, tokens_in: int, tokens_out: int, cost: float, calls: int = 1) -> None:
    LLM_CALLS.labels(model).inc(calls)
    LLM_TOKENS.labels(model, "in").inc(tokens_in)
    LLM_TOKENS.labels(model, "out").inc(tokens_out)
    LLM_COST.labels(model).inc(cost)  # also 0: a free model still shows as $0


def llm_latency(model: str, seconds: float) -> None:
    LLM_SECONDS.labels(model).observe(seconds)


def run_deferred(reason: str) -> None:
    DEFERRED.labels(reason).inc()


def notification(outcome: str) -> None:
    """One delivery attempt: delivered, retry, failed or refused (H4)."""
    NOTIFICATIONS.labels(outcome).inc()


def budget_warning(kind: str) -> None:
    BUDGET_WARNINGS.labels(kind.removeprefix("budget:")).inc()


def run_ended(kind: str, status: str, seconds: float) -> None:
    RUN_SECONDS.labels(kind, status).observe(max(seconds, 0.0))


# ------------------------------------------------------------ state gauges


class StatePoller:
    """Refreshes the state gauges from Postgres and Redis every `interval_s`.

    A background task rather than a scrape-time collector: prometheus_client
    collects synchronously, and our database access is async."""

    def __init__(self, pool: Pool, queue: WorkQueue | None, interval_s: float = 5.0) -> None:
        self._pool = pool
        self._queue = queue
        self._interval = interval_s
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="metrics-poller")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        while True:
            try:
                await self.poll()
            except Exception:
                log.debug("metrics: state poll failed", exc_info=True)
            await asyncio.sleep(self._interval)

    async def poll(self) -> None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT
                  count(*) FILTER (WHERE status = 'queued')            AS queued,
                  count(*) FILTER (WHERE status = 'running')           AS running,
                  count(*) FILTER (WHERE status = 'waiting_approval')  AS approval,
                  count(*) FILTER (WHERE status = 'waiting_children')  AS children,
                  coalesce(sum(cost) FILTER (
                    WHERE parent_run_id IS NULL AND created_at >=
                      date_trunc('day', now() AT TIME ZONE 'utc') AT TIME ZONE 'utc'), 0) AS cost
                FROM runs
                WHERE status NOT IN ('completed', 'failed', 'cancelled')
                   OR created_at >= now() - interval '1 day'
                """
            )
            row = await cur.fetchone()
            cur = await conn.execute("SELECT count(*) AS n FROM sessions WHERE status = 'active'")
            sessions = await cur.fetchone()
            cur = await conn.execute("SELECT paused FROM admin_state LIMIT 1")
            admin = await cur.fetchone()
            cur = await conn.execute("SELECT count(*) AS n FROM kill_switches")
            switched = await cur.fetchone()
        if row is not None:
            QUEUE_DEPTH.set(row["queued"])
            LEASES.set(row["running"])
            WAITING.labels("approval").set(row["approval"])
            WAITING.labels("children").set(row["children"])
            COST_TODAY.set(float(row["cost"]))
        if sessions is not None:
            SESSIONS.set(sessions["n"])
        PAUSED.set(1 if admin is not None and admin["paused"] else 0)
        AGENTS_OFF.set(switched["n"] if switched is not None else 0)
        if self._queue is not None:
            PENDING.set(await self._queue.pending_count())


def worker_tick() -> None:
    WORKER_LOOP.set(time.time())

"""Retention (phase H10, 2.8): old runs lose their details; the run and the chat stay.

    every RETENTION_SWEEP_S, on every worker:
      ┌─ one ended run older than RETENTION_DAYS, not yet pruned  (FOR NO KEY UPDATE SKIP LOCKED)
      │    DELETE ≤ batch of its run_events, ≤ batch of its tool_invocations
      │    nothing left to delete? → details_pruned_at = now()
      └─ commit, repeat until no run is due
      then: DELETE ≤ batch delivered notifications older than 7 days, repeat until none

What goes: `run_events` and `tool_invocations` (the "What happened?" timeline and the tool
ledger: the bulky, per-step rows), and `outbox_notifications` once delivered for a week
(their `notification_deliveries` row cascades). What stays: the `runs` row (Activity's
counts, the pruned marker), `session_messages` and the session's summary (the chat stays
readable), notes (H8 already made them survive their run), `run_model_usage` (the spend)
and `audit_events` (append-only, by design: never pruned). With RETENTION_DAYS=0 the sweep
does nothing.

Pattern: a sweeper, like `SessionService.archive_idle` (R15.6) and the outbox relay:
periodic, idempotent, safe on every worker at once. Each batch is its own short
transaction that claims one run with `SKIP LOCKED`, so two workers never prune the same
run at the same time, no lock outlives one batch, and a worker that dies mid-run leaves
the run due (its marker is set last, once nothing is left to delete). Deleting rows that
another sweep already deleted is harmless: a DELETE of nothing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agent_runtime import logs
from agent_runtime.db import Pool
from agent_runtime.runs.state import TERMINAL, RunStatus

log = logging.getLogger(__name__)

DELIVERED_KEEP_DAYS = 7  # a delivered notification stays listed this long
# The same list, in the same order, as ix_runs_retention's predicate (0030).
_ENDED = ", ".join(f"'{s}'" for s in RunStatus if s in TERMINAL)


@dataclass(frozen=True, slots=True)
class PruneReport:
    """What one sweep removed. Counts only: never content (logs and tests read these)."""

    runs: int = 0  # runs whose details are now gone (details_pruned_at set this sweep)
    events: int = 0  # run_events rows
    invocations: int = 0  # tool_invocations rows
    notifications: int = 0  # outbox_notifications rows (their deliveries went with them)

    @property
    def total(self) -> int:
        return self.events + self.invocations + self.notifications


async def prune_details(pool: Pool, *, older_than_days: int, batch: int = 1000) -> PruneReport:
    """One sweep: see the module header. `older_than_days` is RETENTION_DAYS; 0 prunes
    nothing. `batch` caps the rows one statement deletes (1,000: short transactions on a
    busy table). Returns what went; logs one line, counts only."""
    if older_than_days <= 0:
        log.debug("retention: off (RETENTION_DAYS=0); nothing pruned")
        return PruneReport()
    runs = events = invocations = notifications = 0
    while True:
        async with pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                f"""
                SELECT id FROM runs
                WHERE details_pruned_at IS NULL AND status IN ({_ENDED})
                  AND finished_at < now() - make_interval(days => %(days)s)
                ORDER BY finished_at
                LIMIT 1
                FOR NO KEY UPDATE SKIP LOCKED
                """,
                {"days": older_than_days},
            )
            row = await cur.fetchone()
            if row is None:
                break  # nothing due that another worker isn't already on
            run_id = row["id"]
            cur = await conn.execute(
                "DELETE FROM run_events WHERE ctid = ANY (ARRAY("
                "SELECT ctid FROM run_events WHERE run_id = %(run)s LIMIT %(batch)s))",
                {"run": run_id, "batch": batch},
            )
            gone_events = max(cur.rowcount, 0)
            cur = await conn.execute(
                "DELETE FROM tool_invocations WHERE ctid = ANY (ARRAY("
                "SELECT ctid FROM tool_invocations WHERE run_id = %(run)s LIMIT %(batch)s))",
                {"run": run_id, "batch": batch},
            )
            gone_invocations = max(cur.rowcount, 0)
            events += gone_events
            invocations += gone_invocations
            if gone_events < batch and gone_invocations < batch:
                # Both tables are empty for this run now (a full batch could hide more).
                await conn.execute(
                    "UPDATE runs SET details_pruned_at = now() WHERE id = %s", (run_id,)
                )
                runs += 1
    while True:
        async with pool.connection() as conn:
            cur = await conn.execute(
                """
                DELETE FROM outbox_notifications WHERE key = ANY (ARRAY(
                    SELECT n.key FROM outbox_notifications n
                    JOIN notification_deliveries d USING (key)
                    WHERE d.status = 'delivered'
                      AND d.delivered_at < now() - make_interval(days => %(days)s)
                    LIMIT %(batch)s))
                """,
                {"days": DELIVERED_KEEP_DAYS, "batch": batch},
            )
            gone = max(cur.rowcount, 0)
        notifications += gone
        if gone < batch:
            break
    report = PruneReport(
        runs=runs, events=events, invocations=invocations, notifications=notifications
    )
    logs.event(
        log, "retention: swept old run details",
        level=logging.INFO if report.total or runs else logging.DEBUG,
        older_than_days=older_than_days, runs=runs, events=events, invocations=invocations,
        notifications=notifications,
    )  # fmt: skip
    return report

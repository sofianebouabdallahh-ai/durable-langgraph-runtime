"""Retention (phase H10, 2.8): a finished run older than RETENTION_DAYS loses its details;
the run and the chat stay.

- `runs.details_pruned_at`: when the sweep (runs/retention.py) removed this run's
  `run_events` and `tool_invocations`. NULL: intact. "What happened?" reads it to say
  "details removed" instead of showing an empty timeline.
- `ix_runs_retention`: the sweep's candidates (ended, not yet pruned, oldest first) are a
  cheap index scan, as the reaper's are (0001).
- Grants (least privilege, R14.13): the worker may DELETE from `run_events`,
  `tool_invocations` and `outbox_notifications`, and from nothing else. It still has no
  DELETE on `runs`, `session_messages`, `notes` or `audit_events` (the audit trail is
  append-only by design). A notification's `notification_deliveries` row goes with it
  (ON DELETE CASCADE, 0024); a cascade runs as the referencing table's owner, so the
  worker needs no DELETE there.

Why a DELETE needs no special order here: no table references `run_events` or
`tool_invocations`, and their only triggers fire on INSERT and UPDATE (the epoch fence,
0004), so removing rows trips nothing.

Additive only (expand step): a worker on the release before ignores the column.

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRUNED = "run_events, tool_invocations, outbox_notifications"


def upgrade() -> None:
    op.execute("ALTER TABLE runs ADD COLUMN details_pruned_at timestamptz")
    op.execute("""
        CREATE INDEX ix_runs_retention ON runs (finished_at)
        WHERE details_pruned_at IS NULL AND status IN ('completed', 'failed', 'cancelled')
    """)
    op.execute(f"GRANT DELETE ON {PRUNED} TO app_worker")


def downgrade() -> None:
    op.execute(f"REVOKE DELETE ON {PRUNED} FROM app_worker")
    op.execute("DROP INDEX IF EXISTS ix_runs_retention")
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS details_pruned_at")

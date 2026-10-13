"""Run dispatch bookkeeping for the outbox relay (phase 2).

`message_id` is the work-queue message that currently represents the run;
`enqueued_at` is when it was last sent. The relay re-sends a run whose message
is missing (Redis flushed, API crashed between INSERT and XADD), which is what
makes "Redis holds nothing that can't be rebuilt" true.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE runs
            ADD COLUMN message_id  text,
            ADD COLUMN enqueued_at timestamptz
    """)
    # The relay's sweep: runs that may need a (new) message.
    op.execute("""
        CREATE INDEX ix_runs_dispatch ON runs (enqueued_at NULLS FIRST)
        WHERE status IN ('queued', 'running')
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_runs_dispatch")
    op.execute("ALTER TABLE runs DROP COLUMN enqueued_at, DROP COLUMN message_id")

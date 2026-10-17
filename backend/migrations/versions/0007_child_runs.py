"""Child runs: the run tree, idempotent spawn, fan-out limits (phase 5a, R2.8, R14.6).

(`runs.root_run_id` and `runs.depth` exist since migration 0002. A root run has
root_run_id NULL and depth 0: it is its own root.)

- runs.child_key: the key the parent gave the child. UNIQUE per parent, so a
  spawn can never create the same child twice (defence in depth: the fan-out
  is already one transaction).
- runs.descendants: on a root, how many runs its tree has spawned (R14.6: ≤ 20).
- ix_runs_queued: the queue depth for backpressure (R2.9) is a count of
  queued runs, read on every POST /runs.

Additive only (expand step): old code that inserts runs without these columns
still works.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE runs
            ADD COLUMN child_key   text CHECK (length(child_key) BETWEEN 1 AND 64),
            ADD COLUMN descendants integer  NOT NULL DEFAULT 0 CHECK (descendants >= 0),
            ADD CONSTRAINT child_has_parent
                CHECK ((parent_run_id IS NULL) = (child_key IS NULL)
                       AND (parent_run_id IS NULL) = (root_run_id IS NULL)
                       AND (parent_run_id IS NULL) = (depth = 0))
    """)
    op.execute(
        "CREATE UNIQUE INDEX ux_runs_child_key ON runs (parent_run_id, child_key) "
        "WHERE parent_run_id IS NOT NULL"
    )
    op.execute("CREATE INDEX ix_runs_queued ON runs (created_at) WHERE status = 'queued'")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_runs_queued")
    op.execute("DROP INDEX IF EXISTS ux_runs_child_key")
    op.execute("""
        ALTER TABLE runs
            DROP CONSTRAINT IF EXISTS child_has_parent,
            DROP COLUMN descendants,
            DROP COLUMN child_key
    """)

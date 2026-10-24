"""Activity (phase L7): per-model usage per run, and the indexes the Activity page reads.

- `run_model_usage`: each run's model calls, tokens in and out, cost and time, per model.
  Written with the step that made the calls, in its (fenced) transaction, like the run's
  totals (R14.1): a step lost to a crash and run again is counted once, not twice.
- Indexes for the Activity page's range and per-agent queries, and for events by type.

Additive only (expand step).

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE run_model_usage (
            run_id      uuid          NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
            model       text          NOT NULL,
            calls       integer       NOT NULL DEFAULT 0,
            tokens_in   bigint        NOT NULL DEFAULT 0,
            tokens_out  bigint        NOT NULL DEFAULT 0,
            cost        numeric(12,6) NOT NULL DEFAULT 0,
            duration_ms bigint        NOT NULL DEFAULT 0,
            PRIMARY KEY (run_id, model)
        )
    """)
    op.execute("CREATE INDEX ix_runs_created ON runs (created_at)")
    op.execute("CREATE INDEX ix_runs_agent_created ON runs (agent_name, created_at)")
    op.execute("CREATE INDEX ix_run_events_type_ts ON run_events (type, ts)")
    # Workers write it with the step; the API reads it.
    op.execute("GRANT SELECT, INSERT, UPDATE ON run_model_usage TO app_worker")
    op.execute("GRANT SELECT ON run_model_usage TO app_api")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_run_events_type_ts")
    op.execute("DROP INDEX IF EXISTS ix_runs_agent_created")
    op.execute("DROP INDEX IF EXISTS ix_runs_created")
    op.execute("DROP TABLE IF EXISTS run_model_usage")

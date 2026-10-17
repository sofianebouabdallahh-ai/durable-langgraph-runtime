"""Tool side-effect tables and the approval resume value (phase 4).

- notes / outbox_notifications: rows written by the save_note and notify
  tools. Their primary key IS the tool call's idempotency key (R2.6), so
  re-executing a call after a crash can never create a second row. Both are
  fenced by the epoch trigger from migration 0004.
- runs.resume_value: what a human decided on an approval (R1.4); the worker
  that resumes the run passes it to LangGraph as Command(resume=...).

Additive only (expand step).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE notes (
            key        text PRIMARY KEY CHECK (length(key) = 64),
            run_id     uuid        NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
            text       text        NOT NULL,
            epoch      bigint      NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE outbox_notifications (
            key        text PRIMARY KEY CHECK (length(key) = 64),
            run_id     uuid        NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
            recipient  text        NOT NULL,
            message    text        NOT NULL,
            epoch      bigint      NOT NULL,
            sent_at    timestamptz,                  -- set by a delivery process (out of scope)
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    for table in ("notes", "outbox_notifications"):
        op.execute(f"CREATE INDEX ix_{table}_run ON {table} (run_id)")
        op.execute(f"""
            CREATE TRIGGER {table}_epoch_fence
            BEFORE INSERT OR UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION enforce_epoch_fence()
        """)
        op.execute(f"GRANT SELECT, INSERT ON {table} TO app_worker")
    op.execute("ALTER TABLE runs ADD COLUMN resume_value jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE runs DROP COLUMN resume_value")
    op.execute("DROP TABLE IF EXISTS outbox_notifications")
    op.execute("DROP TABLE IF EXISTS notes")

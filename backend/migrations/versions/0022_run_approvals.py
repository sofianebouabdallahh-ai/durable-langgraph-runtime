"""One row per approval (phase H1).

- `run_approvals`: each tool call a run asked a person to approve, bound to the
  LangGraph interrupt that asked (`interrupt_id`) and to a hash of the call's real
  arguments (`args_hash`). A run resumes only with decisions whose interrupt id and
  hash match what is pending, so a crash, an earlier decision or a changed call can
  never pass for an approval. Several approvals can be pending in one step.
- Status per row: pending → approved | rejected | cancelled | superseded (the call
  changed and was asked again). At most one live (pending or approved) row per
  interrupt.
- Runs already waiting at upgrade get a row with no `interrupt_id`: it matches no
  interrupt, so once decided the worker asks again, bound to the id (fail closed).

`runs.resume_value` is no longer read or written; it is dropped in a later release
(expand step now, contract later).

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE run_approvals (
            id            uuid        PRIMARY KEY,
            run_id        uuid        NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
            interrupt_id  text,
            call_id       text,
            tool          text        NOT NULL,
            args          jsonb       NOT NULL DEFAULT '{}',
            args_hash     text,
            reason        text,
            status        text        NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled',
                                            'superseded')),
            edits         jsonb,
            comment       text,
            decided_by    text,
            decided_at    timestamptz,
            asked_epoch   integer     NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now(),
            CHECK (status <> 'pending' OR decided_at IS NULL),
            CHECK (status NOT IN ('approved', 'rejected') OR decided_at IS NOT NULL)
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_run_approvals_live ON run_approvals (run_id, interrupt_id)
        WHERE status IN ('pending', 'approved') AND interrupt_id IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX ix_run_approvals_pending ON run_approvals (run_id, created_at)
        WHERE status = 'pending'
    """)
    # Runs paused before this release: one pending row each, with no interrupt id.
    op.execute("""
        INSERT INTO run_approvals (id, run_id, call_id, tool, args, reason, asked_epoch,
                                   created_at)
        SELECT gen_random_uuid(), id, interrupt_payload->>'call_id',
               coalesce(interrupt_payload->>'tool', 'unknown'),
               coalesce(interrupt_payload->'args', '{}'::jsonb),
               interrupt_payload->>'reason', epoch, coalesce(waiting_since, now())
        FROM runs
        WHERE status = 'waiting_approval' AND interrupt_payload->>'type' = 'tool_approval'
    """)
    op.execute("UPDATE runs SET resume_value = NULL WHERE resume_value IS NOT NULL")
    # Workers ask (insert) and supersede; the API decides.
    op.execute("GRANT SELECT, INSERT, UPDATE ON run_approvals TO app_worker")
    op.execute("GRANT SELECT, UPDATE ON run_approvals TO app_api")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS run_approvals")

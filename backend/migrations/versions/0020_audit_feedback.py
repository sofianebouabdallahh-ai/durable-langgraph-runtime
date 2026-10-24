"""Who did what, and what people thought of the replies (phase L7d).

- `audit_events`: an append-only trail of changes (approvals, the kill switch, agents,
  skills, model connections, tool settings, usage sharing). Each row is written in the
  same transaction as its change. The API can insert and read it, never update or delete
  it; the worker can't touch it. Never a secret: a key is "set", with its fingerprint.
- `reply_feedback`: 👍 / 👎 on a reply (one per turn), with an optional reason, the
  agent and its version: the seed of evaluation sets later on.

Additive only (expand step).

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE audit_events (
            id          uuid        PRIMARY KEY,
            at          timestamptz NOT NULL DEFAULT now(),
            actor       text        NOT NULL,
            action      text        NOT NULL,
            target_type text        NOT NULL,
            target_id   text,
            before      jsonb,
            after       jsonb,
            request_id  text,
            trace_id    text
        )
    """)
    op.execute("CREATE INDEX ix_audit_events_at ON audit_events (at DESC)")
    op.execute(
        "CREATE INDEX ix_audit_events_target ON audit_events (target_type, target_id, at DESC)"
    )
    op.execute("""
        CREATE TABLE reply_feedback (
            run_id        uuid        PRIMARY KEY REFERENCES runs (id) ON DELETE CASCADE,
            session_id    uuid        REFERENCES sessions (id) ON DELETE CASCADE,
            agent_name    text,
            agent_version integer,
            rating        smallint    NOT NULL CHECK (rating IN (-1, 1)),
            reason        text        CHECK (char_length(reason) <= 500),
            created_at    timestamptz NOT NULL DEFAULT now(),
            updated_at    timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_reply_feedback_agent ON reply_feedback (agent_name, created_at)")
    # Append-only for the API: insert and read, no UPDATE, no DELETE (SC5).
    op.execute("GRANT SELECT, INSERT ON audit_events TO app_api")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON reply_feedback TO app_api")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reply_feedback")
    op.execute("DROP TABLE IF EXISTS audit_events")

"""Kill switches (phase L6): stop an agent, or every agent, now, until turned back on.

- `kill_switches`: one row per agent that is switched off. Its runs are cancelled the
  moment it goes off (mid-step: workers watch for cancellation every second), and new
  messages to it are refused until the row is deleted. Switching *every* agent off is
  the runtime's admission pause (R14.18, `admin_state`) plus the same cancellation.

Additive only (expand step).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE kill_switches (
            agent       text PRIMARY KEY CHECK (agent ~ '^[a-z][a-z0-9-]*$'),
            reason      text CHECK (length(reason) <= 500),
            engaged_at  timestamptz NOT NULL DEFAULT now()
        )
    """)
    # People turn switches on and off through the API; workers only read them.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON kill_switches TO app_api")
    op.execute("GRANT SELECT ON kill_switches TO app_worker")


def downgrade() -> None:
    op.execute("REVOKE ALL ON kill_switches FROM app_api, app_worker")
    op.execute("DROP TABLE IF EXISTS kill_switches")

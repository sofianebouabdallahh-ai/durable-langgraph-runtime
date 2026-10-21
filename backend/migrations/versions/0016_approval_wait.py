"""Waiting for a person doesn't use up a turn's time (phase L6, found testing with Ollama).

A turn's wall-clock limit (R1.7) counted from its start, approval pauses included: a
person who took six minutes to approve found the turn stopped ("it took too long")
the moment they did, and the action never ran. The limit now covers the agent's own
working time:

- `runs.waiting_since`: when the run last started waiting for an approval;
- `runs.waited_s`: the seconds it has spent waiting for approvals, in total.

The executor's deadline is `started_at + timeout_s + waited_s`. Waiting for helpers
still counts: that is the agent's own work.

Additive only (expand step).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE runs ADD COLUMN waiting_since timestamptz")
    op.execute("ALTER TABLE runs ADD COLUMN waited_s double precision NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS waited_s")
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS waiting_since")

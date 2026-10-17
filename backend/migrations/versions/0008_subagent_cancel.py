"""Sub-agent cooperative cancel (phase 5b, CR-005 R16.3, R16.4).

`subagent_invocations` exists since migration 0002 (fenced by 0004, granted by
0005). This adds the cancel request: `cancel_subagent` sets it, and the
sub-agent stops before its next step or tool call. It is durable so that a
sub-agent recovered after a crash still honours a cancel requested before it.

Additive only (expand step).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE subagent_invocations
            ADD COLUMN cancel_requested boolean NOT NULL DEFAULT false,
            ADD COLUMN cancel_reason    text
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE subagent_invocations
            DROP COLUMN cancel_reason,
            DROP COLUMN cancel_requested
    """)

"""Opt-in usage counts (phase L5): `workspace_settings.share_usage`, off by default.

When on, the installation's anonymous usage counts (agent_runtime/usage.py) are
attached to a feedback report the person sends; nothing is ever sent by itself.

Additive only (expand step).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workspace_settings ADD COLUMN share_usage boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE workspace_settings DROP COLUMN IF EXISTS share_usage")

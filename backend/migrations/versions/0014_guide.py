"""Getting started (phase L3d): what the guide remembers. Its progress is derived.

- `workspace_settings.guide_agent_id`: the agent built in the guide (steps 3 to 5 are
  about it). Archived or removed, the guide simply asks for an agent again.
- `guide_model_skipped_at`: "use the demo model for now" (step 1 skipped, not done).
- `guide_dismissed_at`: the person hid the guide; it stays reachable.

Everything else (a model ready, a tool, a helper, a test, a publish, a chat) is read
from the account itself, so progress can't drift from what exists.

Additive only (expand step).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE workspace_settings
            ADD COLUMN guide_agent_id uuid REFERENCES agents (id) ON DELETE SET NULL,
            ADD COLUMN guide_model_skipped_at timestamptz,
            ADD COLUMN guide_dismissed_at timestamptz
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE workspace_settings
            DROP COLUMN IF EXISTS guide_dismissed_at,
            DROP COLUMN IF EXISTS guide_model_skipped_at,
            DROP COLUMN IF EXISTS guide_agent_id
    """)

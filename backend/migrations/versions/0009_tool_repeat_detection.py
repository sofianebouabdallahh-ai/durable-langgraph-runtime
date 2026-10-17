"""Loop detection (phase 6b, CR-003 R14.4): the ledger knows repeated calls.

`tool_invocations.key` includes the call's position, so two identical calls have
different keys. `args_hash = sha256(node · tool · canonical args)` (no position)
identifies a repeat: the 2nd one is served from the 1st's result, the 3rd ends
the run with `loop_detected`.

Additive only (expand step): rows written before this have NULL and are never
counted as repeats.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE tool_invocations ADD COLUMN args_hash text")
    op.execute(
        "CREATE INDEX ix_tool_invocations_repeat ON tool_invocations (run_id, args_hash) "
        "WHERE args_hash IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tool_invocations_repeat")
    op.execute("ALTER TABLE tool_invocations DROP COLUMN args_hash")

"""The approval card says what it hides (phase H10, 2.7).

- `run_approvals.hidden`: how many values the redaction masked in the arguments the person
  is shown (`args`). The real call, bound by `args_hash`, sends them as they are, so the
  card says so. Approvals asked before this release get 0: their cards show what they
  showed. With the pre_tool redaction on (the default) a card hides nothing anyway, since
  the marker is already in the real arguments.

Additive only (expand step): a worker on the release before inserts without the column and
gets the default. The grants of 0022 cover the new column (they are table-wide).

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE run_approvals ADD COLUMN hidden integer NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE run_approvals DROP COLUMN IF EXISTS hidden")

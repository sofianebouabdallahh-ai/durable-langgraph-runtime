"""Budgets that bind (phase H2).

- `model_connections.prices`: a price per model of the connection, USD per 1M tokens
  (`{model: {input_per_mtok, output_per_mtok}}`), set in Settings → Models. It wins over
  MODEL_PRICES and the built-in table (models/pricing.py).
- `run_model_usage.estimated`: some of these calls were priced by the estimate (an
  unknown model's deliberately high default), so the cost shown is approximate.

Usage is now written the moment a model call returns, not with the step's checkpoint:
a step lost to a crash and run again really called the model twice.

Additive only (expand step).

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE model_connections ADD COLUMN prices jsonb NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE run_model_usage ADD COLUMN estimated boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE run_model_usage DROP COLUMN IF EXISTS estimated")
    op.execute("ALTER TABLE model_connections DROP COLUMN IF EXISTS prices")

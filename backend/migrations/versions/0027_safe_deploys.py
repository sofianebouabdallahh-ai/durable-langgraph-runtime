"""Safe across deploys and side effects (phase H7).

- `tool_invocations.call_key`: the call's place in the run (run · node · position · tool),
  which is how newer code finds a call, whatever its arguments: a deploy that changes an
  argument's default can't make a done call happen again. Unique: one row per place.
  The row's `key` still hashes the arguments, as before, so a worker on the previous
  release finds every call a newer one made (expand/contract: the key can become the
  call_key once no older worker is left). Rows from before have none until a newer
  worker finds them by their key.
- `tool_invocations.call_hash`: sha256 of the call's arguments, kept apart from its
  place: a call that comes back with other arguments is served what it did, and noticed.
- `runs.run_format`: the newest format of code that has had the run (checkpoints,
  ledger). Raised by each lease; a worker whose format is older leaves the run to a
  newer one (rolling upgrades). Rows from before are format 1.
- `runs.code_version`: the release that created the run (support, Activity).

Additive only (expand step). The index is built CONCURRENTLY: the ledger is written by
every tool call, and must not be locked while it builds.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE tool_invocations ADD COLUMN call_key text "
               "CHECK (length(call_key) = 64), ADD COLUMN call_hash text")  # fmt: skip
    op.execute("ALTER TABLE runs ADD COLUMN run_format integer NOT NULL DEFAULT 1, "
               "ADD COLUMN code_version text")  # fmt: skip
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ux_tool_invocations_call_key "
            "ON tool_invocations (call_key) WHERE call_key IS NOT NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ux_tool_invocations_call_key")
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS code_version, "
               "DROP COLUMN IF EXISTS run_format")  # fmt: skip
    op.execute("ALTER TABLE tool_invocations DROP COLUMN IF EXISTS call_hash, "
               "DROP COLUMN IF EXISTS call_key")  # fmt: skip

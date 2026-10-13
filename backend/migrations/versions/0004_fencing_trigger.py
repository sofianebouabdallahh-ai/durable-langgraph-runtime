"""The database rejects stale-epoch writes (R2.3: "the database rejects writes
whose epoch is lower than the run's current epoch").

The application already checks the fence before writing (clearer errors,
fewer wasted round trips). This trigger is defence in depth: code that forgets
the check, or a raw SQL statement, still can't write with a stale epoch.

`FOR SHARE` serialises the check with a takeover's `UPDATE runs SET epoch = …`,
exactly like the application-level check (see docs/design.md, phase 1 spike).
Rows without an epoch (written by the API, not a worker) are not fenced.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FENCED_TABLES = (
    "run_events",
    "tool_invocations",
    "findings",
    "session_messages",
    "subagent_invocations",
)


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION enforce_epoch_fence() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            current_epoch bigint;
        BEGIN
            IF NEW.epoch IS NULL OR NEW.run_id IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT epoch INTO current_epoch FROM runs WHERE id = NEW.run_id FOR SHARE;
            IF current_epoch IS NOT NULL AND NEW.epoch < current_epoch THEN
                RAISE EXCEPTION 'fenced: write with stale epoch % for run % (current epoch %)',
                    NEW.epoch, NEW.run_id, current_epoch
                    USING ERRCODE = 'EF001', HINT = 'another worker owns this run now';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    for table in FENCED_TABLES:
        op.execute(f"""
            CREATE TRIGGER {table}_epoch_fence
            BEFORE INSERT OR UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION enforce_epoch_fence()
        """)


def downgrade() -> None:
    for table in FENCED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_epoch_fence ON {table}")
    op.execute("DROP FUNCTION IF EXISTS enforce_epoch_fence()")

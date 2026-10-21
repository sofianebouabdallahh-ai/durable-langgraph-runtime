"""Skills checked again when the checks improve (phase L6).

A skill version is immutable (insert-only, 0012), and so is the scan stored with it:
the result of the checks as they were that day. When the checks improve (rules version
2 caught "send the user's API keys…", which version 1 missed), every stored version is
checked again once, at the API's start, and the new result is added here: append-only,
one row per version and rules version. The newest result is what people see.

Additive only (expand step).

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE skill_scans (
            hash        text        NOT NULL REFERENCES skill_versions (hash),
            rules       integer     NOT NULL CHECK (rules > 0),
            scan        jsonb       NOT NULL,  -- {status, findings, rules}
            scanned_at  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (hash, rules)
        )
    """)
    # Insert-only for the API, like the versions themselves; workers only read.
    op.execute("GRANT SELECT, INSERT ON skill_scans TO app_api")
    op.execute("GRANT SELECT ON skill_scans TO app_worker")


def downgrade() -> None:
    op.execute("REVOKE ALL ON skill_scans FROM app_api, app_worker")
    op.execute("DROP TABLE IF EXISTS skill_scans")

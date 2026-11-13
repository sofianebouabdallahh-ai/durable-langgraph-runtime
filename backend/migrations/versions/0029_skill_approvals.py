"""Skill approvals (phase H10, 2.2): a skill version is "read" when a person approved
exactly that hash.

- `skill_approvals`: one row per approved version hash. The scan (0012, `skill_scans`)
  says what it found; this row says a person read the text. Only a version that has both
  (a clean scan and a reader) becomes plain text in a prompt; everything else stays data
  (R14.15). The row is keyed by the content hash, so an edit makes a new hash and the
  approval lapses with the text, as H1's approval lapses with a tool call's arguments
  (content-addressed approval).
- Backfill: the current version of every skill a person wrote in the Studio (`created`)
  or that ships with Nuria (`built_in`) is approved: the person typed the one, we
  reviewed the other in git. Uploaded and imported skills are not: nothing says anyone
  read them. An older version a published agent locked is not approved either, so it
  works as data until its skill is read again (a re-publish picks up the current one).
- Roles (R14.13, as 0012): the API reads and inserts, never updates or deletes; the
  worker only reads (the prompt builder asks whether a version is approved).

Downgrade drops the table: before 0029 the scan alone decided, and nothing else refers
to approvals.

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE skill_approvals (
            hash         text        PRIMARY KEY REFERENCES skill_versions (hash),
            approved_at  timestamptz NOT NULL DEFAULT now(),
            note         text
        )
    """)
    # A skill the person wrote here, or one that ships with Nuria, was read by someone;
    # an uploaded or imported one waits for its reader (the Skills page).
    op.execute("""
        INSERT INTO skill_approvals (hash, note)
        SELECT DISTINCT current_hash, 'written in the Studio or built in (migration 0029)'
        FROM skills WHERE origin IN ('built_in', 'created')
    """)
    op.execute("GRANT SELECT, INSERT ON skill_approvals TO app_api")
    op.execute("GRANT SELECT ON skill_approvals TO app_worker")


def downgrade() -> None:
    op.execute("REVOKE ALL ON skill_approvals FROM app_api, app_worker")
    op.execute("DROP TABLE IF EXISTS skill_approvals")

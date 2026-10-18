"""Skills (phase L3c, CR-006 R17.4): the library, immutable versions, locked by publishing.

- `skill_versions`: content-addressed (the hash of name, description, instructions,
  header fields and files), so the same skill is the same row wherever it came from.
  Immutable by grants: the API may insert and read, never update or delete.
- `skill_files`: the files' bytes, by sha256 (shared between versions).
- `skills`: the library entry people see: its name, trust level, origin and current
  version. Archived, never deleted (published agents may still use a version).
- `agent_versions.skill_lock`: {skill name: version hash} set when a version is
  published, and frozen with the rest of it (the AC47 trigger), so editing a skill
  never changes a published agent.

Additive only (expand step).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = r"'^[a-z0-9]+(-[a-z0-9]+)*$'"

FROZEN = """
                NEW.document IS DISTINCT FROM OLD.document
                OR NEW.bundle_hash IS DISTINCT FROM OLD.bundle_hash
                OR NEW.number <> OLD.number OR NEW.agent_id <> OLD.agent_id
                OR NEW.published_at IS DISTINCT FROM OLD.published_at
                OR NEW.changelog IS DISTINCT FROM OLD.changelog{extra}
"""


def _immutable(extra: str) -> str:
    """The AC47 trigger function (migration 0010), with the frozen columns given."""
    return f"""
        CREATE OR REPLACE FUNCTION agent_version_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.state <> 'draft' THEN
                    RAISE EXCEPTION 'agent version %/% is %: it cannot be deleted',
                        OLD.agent_id, OLD.number, OLD.state USING ERRCODE = 'check_violation';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.state <> 'draft' AND ({FROZEN.format(extra=extra)}) THEN
                RAISE EXCEPTION 'agent version %/% is %: its content cannot change',
                    OLD.agent_id, OLD.number, OLD.state USING ERRCODE = 'check_violation';
            END IF;
            IF NOT (OLD.state = NEW.state
                    OR (OLD.state = 'draft' AND NEW.state = 'published')
                    OR (OLD.state = 'published' AND NEW.state = 'archived')) THEN
                RAISE EXCEPTION 'agent version %/%: % → % is not allowed',
                    OLD.agent_id, OLD.number, OLD.state, NEW.state
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END $$
    """


def upgrade() -> None:
    op.execute("""
        CREATE TABLE skill_files (
            sha256  text    PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            data    bytea   NOT NULL,
            size    integer NOT NULL CHECK (size = length(data) AND size <= 10000000)
        )
    """)
    op.execute(f"""
        CREATE TABLE skill_versions (
            hash          text        PRIMARY KEY CHECK (hash ~ '^[0-9a-f]{{64}}$'),
            name          text        NOT NULL CHECK (name ~ {NAME} AND length(name) <= 64),
            description   text        NOT NULL CHECK (length(description) BETWEEN 1 AND 1024),
            instructions  text        NOT NULL CHECK (length(instructions) BETWEEN 1 AND 60000),
            meta          jsonb       NOT NULL DEFAULT '{{}}',
            files         jsonb       NOT NULL DEFAULT '[]',  -- [{{path, sha256, size, kind}}]
            scan          jsonb       NOT NULL,               -- {{status, findings}}
            created_at    timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(f"""
        CREATE TABLE skills (
            id            uuid PRIMARY KEY,
            workspace_id  text        NOT NULL DEFAULT 'local',
            name          text        NOT NULL CHECK (name ~ {NAME} AND length(name) <= 64),
            trust         text        NOT NULL CHECK (trust IN ('private', 'built_in')),
            origin        text        NOT NULL
                          CHECK (origin IN ('created', 'uploaded', 'imported', 'built_in')),
            current_hash  text        NOT NULL REFERENCES skill_versions (hash),
            created_at    timestamptz NOT NULL DEFAULT now(),
            updated_at    timestamptz NOT NULL DEFAULT now(),
            archived_at   timestamptz,
            UNIQUE (workspace_id, name)
        )
    """)
    op.execute("ALTER TABLE agent_versions ADD COLUMN skill_lock jsonb")
    op.execute(_immutable("\n                OR NEW.skill_lock IS DISTINCT FROM OLD.skill_lock"))
    # Least privilege (R14.13): versions and files are insert-only for the API (no
    # UPDATE or DELETE: immutable by grants); workers only read what runs pinned.
    op.execute("GRANT SELECT, INSERT ON skill_versions, skill_files TO app_api")
    op.execute("GRANT SELECT, INSERT, UPDATE ON skills TO app_api")
    op.execute("GRANT SELECT ON skill_versions, skill_files TO app_worker")


def downgrade() -> None:
    op.execute("REVOKE ALL ON skills, skill_versions, skill_files FROM app_api, app_worker")
    op.execute(_immutable(""))
    op.execute("ALTER TABLE agent_versions DROP COLUMN IF EXISTS skill_lock")
    op.execute("DROP TABLE IF EXISTS skills")
    op.execute("DROP TABLE IF EXISTS skill_versions")
    op.execute("DROP TABLE IF EXISTS skill_files")

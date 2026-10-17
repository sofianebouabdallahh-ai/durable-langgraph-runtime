"""Agent Studio (phase L3a, CR-006 R17.1): user agents as versions; turns pin a bundle.

- `agents`: a user agent's identity. `workspace_id` is 'local' for the local release,
  so the hosted beta's tenancy (P7) is an expand step, not a rewrite.
- `agent_versions`: draft → published → archived. At most one draft per agent. **A
  published version's content can never change** (AC47): a trigger refuses it, so the
  rule holds for every client, not just the API. "Tested" isn't stored: it is derived
  from a completed test-chat turn pinned to the draft's bundle hash.
- `agent_definitions` gains the `bundle` kind: `{main: hash, helpers: {name: hash}}`.
  A turn's `agent_hash` is its bundle, so the whole team it runs with is fixed.
- `sessions.playground_of`: a test chat for an agent's draft (hidden from the list).
- `runs.idempotency_key`: a retried send finds the turn it already created.

Additive only (expand step).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE agents (
            id            uuid PRIMARY KEY,
            workspace_id  text        NOT NULL DEFAULT 'local',
            name          text        NOT NULL CHECK (name ~ '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'),
            created_at    timestamptz NOT NULL DEFAULT now(),
            archived_at   timestamptz,
            UNIQUE (workspace_id, name)
        )
    """)
    op.execute("""
        CREATE TABLE agent_versions (
            agent_id      uuid        NOT NULL REFERENCES agents (id),
            number        integer     NOT NULL CHECK (number > 0),
            state         text        NOT NULL CHECK (state IN ('draft', 'published', 'archived')),
            document      jsonb       NOT NULL,          -- the form (agents/document.py)
            bundle_hash   text REFERENCES agent_definitions (hash),  -- set while valid
            changelog     text CHECK (length(changelog) <= 500),
            created_at    timestamptz NOT NULL DEFAULT now(),
            published_at  timestamptz,
            PRIMARY KEY (agent_id, number),
            CHECK ((state = 'draft') = (published_at IS NULL)),
            CHECK (state = 'draft' OR bundle_hash IS NOT NULL)
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX ux_agent_versions_one_draft ON agent_versions (agent_id) "
        "WHERE state = 'draft'"
    )
    # AC47 in the database: once published, a version's content is frozen; its state
    # only moves forward (published → archived); published versions are never deleted.
    op.execute("""
        CREATE FUNCTION agent_version_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.state <> 'draft' THEN
                    RAISE EXCEPTION 'agent version %/% is %: it cannot be deleted',
                        OLD.agent_id, OLD.number, OLD.state USING ERRCODE = 'check_violation';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.state <> 'draft' AND (
                NEW.document IS DISTINCT FROM OLD.document
                OR NEW.bundle_hash IS DISTINCT FROM OLD.bundle_hash
                OR NEW.number <> OLD.number OR NEW.agent_id <> OLD.agent_id
                OR NEW.published_at IS DISTINCT FROM OLD.published_at
                OR NEW.changelog IS DISTINCT FROM OLD.changelog
            ) THEN
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
    """)
    op.execute("""
        CREATE TRIGGER agent_versions_immutable BEFORE UPDATE OR DELETE ON agent_versions
        FOR EACH ROW EXECUTE FUNCTION agent_version_immutable()
    """)

    op.execute("ALTER TABLE agent_definitions DROP CONSTRAINT agent_definitions_kind_check")
    op.execute(
        "ALTER TABLE agent_definitions ADD CONSTRAINT agent_definitions_kind_check "
        "CHECK (kind IN ('main', 'sub', 'bundle'))"
    )
    op.execute("ALTER TABLE sessions ADD COLUMN playground_of uuid REFERENCES agents (id)")
    op.execute("ALTER TABLE runs ADD COLUMN idempotency_key text "
               "CHECK (length(idempotency_key) BETWEEN 1 AND 100)")  # fmt: skip
    op.execute(
        "CREATE UNIQUE INDEX ux_runs_idempotency ON runs (session_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )
    # Least privilege (R14.13): the API manages agents; workers build from snapshots
    # (agent_definitions) and never read the Studio's tables.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON agents, agent_versions TO app_api")


def downgrade() -> None:
    op.execute("REVOKE ALL ON agents, agent_versions FROM app_api")
    op.execute("DROP INDEX IF EXISTS ux_runs_idempotency")
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS idempotency_key")
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS playground_of")
    op.execute("DELETE FROM agent_definitions WHERE kind = 'bundle'")
    op.execute("ALTER TABLE agent_definitions DROP CONSTRAINT agent_definitions_kind_check")
    op.execute(
        "ALTER TABLE agent_definitions ADD CONSTRAINT agent_definitions_kind_check "
        "CHECK (kind IN ('main', 'sub'))"
    )
    op.execute("DROP TRIGGER IF EXISTS agent_versions_immutable ON agent_versions")
    op.execute("DROP FUNCTION IF EXISTS agent_version_immutable()")
    op.execute("DROP TABLE IF EXISTS agent_versions")
    op.execute("DROP TABLE IF EXISTS agents")

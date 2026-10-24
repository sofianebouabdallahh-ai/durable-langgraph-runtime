"""MCP servers and their tools (phase L8).

- `mcp_servers`: a remote MCP server people added (Settings → Tools): its address, and
  optionally a token, sealed like model keys (envelope encryption, `NURIA_SECRET_KEY`),
  sent in the header they named.
- `mcp_tools`: each tool the server offers. `definition` and `digest` are what a person
  approved (switched on); `latest` and `latest_digest` what the server offered when last
  asked. They differ when the server changed the tool: it is then blocked until someone
  looks again ("rug pull" protection). New tools start switched off.
- `agent_versions.mcp_lock`: the MCP tools a published version uses, with the definitions
  approved when it was published; frozen afterwards like `skill_lock` (the AC47 trigger).

Additive only (expand step).

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FROZEN = """
                NEW.document IS DISTINCT FROM OLD.document
                OR NEW.bundle_hash IS DISTINCT FROM OLD.bundle_hash
                OR NEW.number <> OLD.number OR NEW.agent_id <> OLD.agent_id
                OR NEW.published_at IS DISTINCT FROM OLD.published_at
                OR NEW.changelog IS DISTINCT FROM OLD.changelog
                OR NEW.skill_lock IS DISTINCT FROM OLD.skill_lock{extra}
"""


def _immutable(extra: str) -> str:
    """The AC47 trigger function (migrations 0010, 0012), with the frozen columns given."""
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
        CREATE TABLE mcp_servers (
            id               uuid        PRIMARY KEY,
            workspace_id     text        NOT NULL,
            name             text        NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]{0,31}$'),
            display_name     text        NOT NULL CHECK (char_length(display_name) <= 60),
            url              text        NOT NULL CHECK (url ~ '^https?://'),
            header_name      text        NOT NULL DEFAULT 'Authorization'
                                         CHECK (header_name ~ '^[A-Za-z0-9-]{1,64}$'),
            key_ciphertext   bytea,
            key_nonce        bytea,
            wrapped_key      bytea,
            wrapped_nonce    bytea,
            kek_version      integer,
            key_fingerprint  text,
            status           text        NOT NULL DEFAULT 'untested'
                             CHECK (status IN ('untested', 'ready', 'failed')),
            status_detail    text,
            protocol_version text,
            tested_at        timestamptz,
            created_at       timestamptz NOT NULL DEFAULT now(),
            updated_at       timestamptz NOT NULL DEFAULT now(),
            archived_at      timestamptz,
            UNIQUE (workspace_id, name),
            CHECK ((key_ciphertext IS NULL) = (wrapped_key IS NULL)
                   AND (key_ciphertext IS NULL) = (key_nonce IS NULL)
                   AND (key_ciphertext IS NULL) = (kek_version IS NULL))
        )
    """)
    op.execute("""
        CREATE TABLE mcp_tools (
            server_id      uuid        NOT NULL REFERENCES mcp_servers (id) ON DELETE CASCADE,
            name           text        NOT NULL,
            definition     jsonb,
            digest         text,
            latest         jsonb       NOT NULL,
            latest_digest  text        NOT NULL,
            enabled        boolean     NOT NULL DEFAULT false,
            without_asking boolean     NOT NULL DEFAULT false,
            scan           jsonb       NOT NULL DEFAULT '{}',
            seen_at        timestamptz NOT NULL DEFAULT now(),
            updated_at     timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (server_id, name),
            CHECK (NOT enabled OR (definition IS NOT NULL AND digest IS NOT NULL))
        )
    """)
    op.execute("ALTER TABLE agent_versions ADD COLUMN mcp_lock jsonb")
    op.execute(_immutable("\n                OR NEW.mcp_lock IS DISTINCT FROM OLD.mcp_lock"))
    # People manage servers through the API; workers read them to call the tools.
    op.execute("GRANT SELECT, INSERT, UPDATE ON mcp_servers, mcp_tools TO app_api")
    op.execute("GRANT SELECT ON mcp_servers, mcp_tools TO app_worker")


def downgrade() -> None:
    op.execute(_immutable(""))
    op.execute("ALTER TABLE agent_versions DROP COLUMN IF EXISTS mcp_lock")
    op.execute("DROP TABLE IF EXISTS mcp_tools")
    op.execute("DROP TABLE IF EXISTS mcp_servers")

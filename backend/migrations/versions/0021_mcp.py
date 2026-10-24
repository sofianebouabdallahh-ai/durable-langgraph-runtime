"""MCP servers and their tools (phase L8).

- `mcp_servers`: a remote MCP server people added (Settings → Tools): its address, and
  optionally a token, sealed like model keys (envelope encryption, `NURIA_SECRET_KEY`),
  sent in the header they named.
- `mcp_tools`: each tool the server offers. `definition` and `digest` are what a person
  approved (switched on); `latest` and `latest_digest` what the server offered when last
  asked. They differ when the server changed the tool: it is then blocked until someone
  looks again ("rug pull" protection). New tools start switched off.

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
    # People manage servers through the API; workers read them to call the tools.
    op.execute("GRANT SELECT, INSERT, UPDATE ON mcp_servers, mcp_tools TO app_api")
    op.execute("GRANT SELECT ON mcp_servers, mcp_tools TO app_worker")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mcp_tools")
    op.execute("DROP TABLE IF EXISTS mcp_servers")

"""Your own model (phase L3b, CR-006 R18.2 to R18.4): model connections, the default, bindings.

- `model_connections`: where a model lives (kind, base URL) and its key, **encrypted**
  (envelope AES-256-GCM, agent_runtime/keys.py): the ciphertext, the wrapped data
  key, their nonces and the master key's version. The plaintext key is never stored.
  `name` is what definitions say (`<name>:<model>`); `key_fingerprint` tells keys
  apart without revealing them.
- `workspace_settings`: the default connection and model (what `model: chat` uses).
- `runs.model_bindings`: what each model string of the turn's agent resolved to when
  the turn was created, so changing the default never changes a running turn.

Additive only (expand step).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE model_connections (
            id               uuid PRIMARY KEY,
            workspace_id     text        NOT NULL DEFAULT 'local',
            name             text        NOT NULL CHECK (name ~ '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'),
            display_name     text        NOT NULL CHECK (length(display_name) BETWEEN 1 AND 60),
            kind             text        NOT NULL
                             CHECK (kind IN ('ollama', 'openai', 'azure_foundry', 'compatible')),
            base_url         text        NOT NULL CHECK (base_url ~ '^https?://'),
            key_ciphertext   bytea,
            key_nonce        bytea,
            wrapped_key      bytea,
            wrapped_nonce    bytea,
            kek_version      integer,
            key_fingerprint  text,
            models           jsonb       NOT NULL DEFAULT '[]',
            test_status      text        NOT NULL DEFAULT 'untested'
                             CHECK (test_status IN ('untested', 'ready', 'failed')),
            test_detail      text,
            tested_model     text,
            tested_at        timestamptz,
            created_at       timestamptz NOT NULL DEFAULT now(),
            updated_at       timestamptz NOT NULL DEFAULT now(),
            archived_at      timestamptz,
            UNIQUE (workspace_id, name),
            -- a key is all or nothing: never a ciphertext without what opens it
            CHECK ((key_ciphertext IS NULL) = (wrapped_key IS NULL)
                   AND (key_ciphertext IS NULL) = (key_nonce IS NULL)
                   AND (key_ciphertext IS NULL) = (kek_version IS NULL))
        )
    """)
    op.execute("""
        CREATE TABLE workspace_settings (
            workspace_id          text PRIMARY KEY,
            default_connection_id uuid REFERENCES model_connections (id),
            default_model         text,
            updated_at            timestamptz NOT NULL DEFAULT now(),
            CHECK ((default_connection_id IS NULL) = (default_model IS NULL))
        )
    """)
    op.execute("ALTER TABLE runs ADD COLUMN model_bindings jsonb")
    # The API manages connections; workers read them (they open a key in memory, for
    # one call) and the default.
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON model_connections, workspace_settings TO app_api"
    )
    op.execute("GRANT SELECT ON model_connections, workspace_settings TO app_worker")


def downgrade() -> None:
    op.execute("REVOKE ALL ON model_connections, workspace_settings FROM app_api, app_worker")
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS model_bindings")
    op.execute("DROP TABLE IF EXISTS workspace_settings")
    op.execute("DROP TABLE IF EXISTS model_connections")

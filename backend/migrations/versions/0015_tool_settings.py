"""Real tools (phase L6a): the settings the web tools use, per workspace.

- `tool_settings.search_provider`: `searxng` (the default: in the stack, no key),
  `tavily` or `brave` (a key, encrypted like model keys: envelope AES-256-GCM, bound
  to its row and purpose).
- `searxng_url`: another SearXNG instance, when someone runs their own.
- `web_allowlist`: when set, pages are read only from these sites.

Additive only (expand step).

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE tool_settings (
            workspace_id     text PRIMARY KEY,
            search_provider  text NOT NULL DEFAULT 'searxng'
                             CHECK (search_provider IN ('searxng', 'tavily', 'brave')),
            searxng_url      text CHECK (searxng_url ~ '^https?://'),
            key_ciphertext   bytea,
            key_nonce        bytea,
            wrapped_key      bytea,
            wrapped_nonce    bytea,
            kek_version      integer,
            key_fingerprint  text,
            web_allowlist    jsonb NOT NULL DEFAULT '[]',
            updated_at       timestamptz NOT NULL DEFAULT now(),
            CHECK ((key_ciphertext IS NULL) = (wrapped_key IS NULL)
                   AND (key_ciphertext IS NULL) = (key_nonce IS NULL)
                   AND (key_ciphertext IS NULL) = (kek_version IS NULL))
        )
    """)
    # The API manages them; workers read them (and open the key in memory, for one call).
    op.execute("GRANT SELECT, INSERT, UPDATE ON tool_settings TO app_api")
    op.execute("GRANT SELECT ON tool_settings TO app_worker")


def downgrade() -> None:
    op.execute("REVOKE ALL ON tool_settings FROM app_api, app_worker")
    op.execute("DROP TABLE IF EXISTS tool_settings")

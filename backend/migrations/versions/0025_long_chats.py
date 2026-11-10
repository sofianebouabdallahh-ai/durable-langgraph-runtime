"""Long chats (phase H5).

- `model_connections.context_tokens`: the connection's models' context window, set in
  Settings → Models; NULL: the default (CONTEXT_TOKENS, LOCAL_CONTEXT_TOKENS).
- `prune_checkpoints(thread, keep_latest, upto)`: a finished run's thread keeps only its
  latest checkpoint (per namespace), the writes of what's kept and the blobs a kept
  checkpoint references; with keep_latest false (a helper's thread) it keeps nothing.
  `upto`: the finished run's own last checkpoint; only rows older than it go, so a next
  turn that has already started is never touched. LangGraph
  stores the whole message list in each checkpoint, so without this a chat's storage
  grows with turns².

  SECURITY DEFINER, owned by the migrator: the worker can call this one function and
  still has no DELETE on LangGraph's tables (least privilege, R14.13). Only rows OLDER
  than both `upto` and a namespace's latest checkpoint go (checkpoint ids are
  time-ordered). The tables are LangGraph's own,
  created after the migrations by `runtime db init`; the body is checked when it runs.

Additive only (expand step).

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE model_connections ADD COLUMN context_tokens integer "
               "CHECK (context_tokens BETWEEN 2048 AND 10000000)")  # fmt: skip
    op.execute("""
        CREATE FUNCTION prune_checkpoints(p_thread text, p_keep_latest boolean,
                                          p_upto text DEFAULT NULL)
        RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE
            removed integer := 0;
        BEGIN
            IF to_regclass('public.checkpoints') IS NULL THEN
                RETURN 0;
            END IF;
            IF p_keep_latest THEN
                DELETE FROM checkpoints c
                WHERE c.thread_id = p_thread
                  AND (p_upto IS NULL OR c.checkpoint_id < p_upto)
                  AND c.checkpoint_id < (SELECT max(l.checkpoint_id) FROM checkpoints l
                                         WHERE l.thread_id = c.thread_id
                                           AND l.checkpoint_ns = c.checkpoint_ns);
            ELSE
                DELETE FROM checkpoints WHERE thread_id = p_thread;
            END IF;
            GET DIAGNOSTICS removed = ROW_COUNT;
            DELETE FROM checkpoint_writes w
            WHERE w.thread_id = p_thread
              AND NOT EXISTS (SELECT 1 FROM checkpoints c
                              WHERE c.thread_id = w.thread_id
                                AND c.checkpoint_ns = w.checkpoint_ns
                                AND c.checkpoint_id = w.checkpoint_id);
            DELETE FROM checkpoint_blobs b
            WHERE b.thread_id = p_thread
              AND NOT EXISTS (SELECT 1 FROM checkpoints c
                              WHERE c.thread_id = b.thread_id
                                AND c.checkpoint_ns = b.checkpoint_ns
                                AND c.checkpoint -> 'channel_versions' ->> b.channel
                                    = b.version);
            RETURN removed;
        END;
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION prune_checkpoints(text, boolean, text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION prune_checkpoints(text, boolean, text) TO app_worker")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS prune_checkpoints(text, boolean, text)")
    op.execute("ALTER TABLE model_connections DROP COLUMN IF EXISTS context_tokens")

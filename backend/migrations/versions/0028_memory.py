"""Memory across chats (phase H8).

- `notes.agent`, `notes.test_scope`: whose memory a note is, fixed when it is written. A
  BEFORE INSERT trigger sets both from the note's run (its agent; for a Studio test chat
  or an eval turn, that chat, or the run itself when it has none), so the scope comes
  from the run row, never from the model, and a worker on the release before (which
  doesn't know the columns) still writes scoped notes. Rows from before are backfilled
  the same way. Reads no longer join `runs`.
- `notes.run_id`: nullable, `ON DELETE SET NULL`. Clearing old runs keeps what they
  remembered; a test's notes still go with their run (a BEFORE DELETE trigger).
- `note_forgets`: a note the agent was asked to forget, one row per note. An insert by
  the run that forgets it, fenced by that run's epoch, rather than an update of the note:
  the fence checks a note's own (older) run, which may have been taken over since.
  Forgotten notes leave the prompt and recall_notes; a person can restore one (the API
  deletes the row) or delete the note for good.
- Roles: the worker still only reads and inserts; the API reads and deletes notes, and
  restores forgotten ones.

Downgrade: forgotten notes are deleted (0027 would show them to the model again), and so
are notes whose run is gone (they have no run there).

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A run's memory scope: its agent, and for a test (a Studio test chat or an eval turn)
    # the chat it keeps to. One definition, for the trigger and for every read.
    op.execute("""
        CREATE FUNCTION run_memory_scope(run uuid, OUT agent text, OUT test_scope uuid)
        LANGUAGE sql STABLE AS $$
            SELECT coalesce(r.agent_name, r.graph_name),
                   CASE WHEN s.playground_of IS NOT NULL
                          OR EXISTS (SELECT 1 FROM eval_runs e WHERE e.run_id = r.id)
                        THEN coalesce(r.session_id, r.id) END
            FROM runs r LEFT JOIN sessions s ON s.id = r.session_id
            WHERE r.id = run
        $$
    """)
    op.execute("ALTER TABLE notes ADD COLUMN agent text, ADD COLUMN test_scope uuid")
    # The backfill fills in derived columns, not a worker's write: the epoch fence (which
    # fires on every update) would refuse any note whose run was leased again since (a
    # resume after an approval, a takeover), so it is off for this statement only.
    op.execute("ALTER TABLE notes DISABLE TRIGGER notes_epoch_fence")
    op.execute("UPDATE notes n SET (agent, test_scope) = "
               "(SELECT s.agent, s.test_scope FROM run_memory_scope(n.run_id) s)")  # fmt: skip
    op.execute("ALTER TABLE notes ENABLE TRIGGER notes_epoch_fence")
    op.execute("ALTER TABLE notes ALTER COLUMN agent SET NOT NULL")
    op.execute("""
        CREATE FUNCTION note_scope() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            SELECT s.agent, s.test_scope INTO NEW.agent, NEW.test_scope
            FROM run_memory_scope(NEW.run_id) s;
            IF NEW.agent IS NULL THEN
                RAISE EXCEPTION 'a note needs a run: %', NEW.run_id;
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER notes_scope BEFORE INSERT ON notes
        FOR EACH ROW EXECUTE FUNCTION note_scope()
    """)
    op.execute("ALTER TABLE notes DROP CONSTRAINT notes_run_id_fkey, "
               "ALTER COLUMN run_id DROP NOT NULL, "
               "ADD CONSTRAINT notes_run_id_fkey FOREIGN KEY (run_id) "
               "REFERENCES runs (id) ON DELETE SET NULL")  # fmt: skip
    op.execute("CREATE INDEX ix_notes_memory ON notes (agent, author, created_at DESC)")
    # A test's notes (a Studio test chat, an eval turn) belong to the test: they go with
    # their run, as every note did before. Real notes outlive it (SET NULL above).
    op.execute("""
        CREATE FUNCTION test_notes_go_with_their_run() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            DELETE FROM notes WHERE run_id = OLD.id AND test_scope IS NOT NULL;
            RETURN OLD;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER runs_test_notes BEFORE DELETE ON runs
        FOR EACH ROW EXECUTE FUNCTION test_notes_go_with_their_run()
    """)
    op.execute("""
        CREATE TABLE note_forgets (
            note_key     text        PRIMARY KEY REFERENCES notes (key) ON DELETE CASCADE,
            key          text        NOT NULL UNIQUE CHECK (length(key) = 64),
            run_id       uuid        REFERENCES runs (id) ON DELETE SET NULL,
            epoch        bigint      NOT NULL,
            forgotten_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TRIGGER note_forgets_epoch_fence
        BEFORE INSERT OR UPDATE ON note_forgets
        FOR EACH ROW EXECUTE FUNCTION enforce_epoch_fence()
    """)
    op.execute("GRANT SELECT, INSERT ON note_forgets TO app_worker")
    op.execute("GRANT SELECT, DELETE ON notes TO app_api")
    op.execute("GRANT SELECT, DELETE ON note_forgets TO app_api")


def downgrade() -> None:
    op.execute("REVOKE ALL ON note_forgets FROM app_api, app_worker")
    op.execute("REVOKE SELECT, DELETE ON notes FROM app_api")
    # 0027 can't tell a forgotten note from another: forgetting it is the safe reading
    # (it mustn't reach the model again).
    op.execute("DELETE FROM notes n USING note_forgets f WHERE f.note_key = n.key")
    op.execute("DROP TABLE IF EXISTS note_forgets")
    op.execute("DROP TRIGGER IF EXISTS runs_test_notes ON runs")
    op.execute("DROP FUNCTION IF EXISTS test_notes_go_with_their_run()")
    op.execute("DROP INDEX IF EXISTS ix_notes_memory")
    # A note whose run was deleted has no run to belong to before 0028.
    op.execute("DELETE FROM notes WHERE run_id IS NULL")
    op.execute("ALTER TABLE notes DROP CONSTRAINT notes_run_id_fkey, "
               "ALTER COLUMN run_id SET NOT NULL, "
               "ADD CONSTRAINT notes_run_id_fkey FOREIGN KEY (run_id) "
               "REFERENCES runs (id) ON DELETE CASCADE")  # fmt: skip
    op.execute("DROP TRIGGER IF EXISTS notes_scope ON notes")
    op.execute("DROP FUNCTION IF EXISTS note_scope()")
    op.execute("DROP FUNCTION IF EXISTS run_memory_scope(uuid)")
    op.execute("ALTER TABLE notes DROP COLUMN IF EXISTS test_scope, "
               "DROP COLUMN IF EXISTS agent")  # fmt: skip

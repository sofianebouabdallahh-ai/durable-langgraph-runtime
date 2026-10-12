"""Migration tests: the chain applies, reverses, and the constraints hold."""

import uuid

import psycopg
import pytest
from alembic import command
from alembic.config import Config

pytestmark = pytest.mark.integration

TABLES = {
    "sessions",
    "runs",
    "run_events",
    "run_results",
    "tool_invocations",
    "findings",
    "documents",
    "chunks",
    "session_messages",
}


def _tables(conn: psycopg.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT tablename FROM pg_tables "
        "WHERE schemaname = 'public' AND tablename != 'alembic_version'"
    ).fetchall()
    return {r[0] for r in rows}


def test_upgrade_downgrade_upgrade(alembic_cfg: Config, test_db_url: str) -> None:
    """Every migration must reverse cleanly, so a bad deploy can be rolled back."""
    url = test_db_url.replace("postgresql+psycopg", "postgresql")
    command.upgrade(alembic_cfg, "head")
    with psycopg.connect(url) as conn:
        assert _tables(conn) == TABLES
    command.downgrade(alembic_cfg, "base")
    with psycopg.connect(url) as conn:
        assert _tables(conn) == set()
    command.upgrade(alembic_cfg, "head")
    with psycopg.connect(url) as conn:
        assert _tables(conn) == TABLES


def _insert_session(conn: psycopg.Connection) -> uuid.UUID:
    sid = uuid.uuid4()
    conn.execute("INSERT INTO sessions (id, graph_name) VALUES (%s, 'chat')", (sid,))
    return sid


def _insert_run(
    conn: psycopg.Connection, *, session_id: uuid.UUID | None = None, status: str = "queued"
) -> uuid.UUID:
    rid = uuid.uuid4()
    finished = "now()" if status in ("completed", "failed", "cancelled") else "NULL"
    conn.execute(
        f"INSERT INTO runs (id, graph_name, session_id, thread_id, status, input, finished_at) "
        f"VALUES (%s, 'chat', %s, %s, %s, '{{}}', {finished})",
        (rid, session_id, str(session_id or rid), status),
    )
    return rid


def test_one_active_run_per_session(migrated_db: psycopg.Connection) -> None:
    sid = _insert_session(migrated_db)
    _insert_run(migrated_db, session_id=sid, status="completed")
    _insert_run(migrated_db, session_id=sid, status="running")  # one active: fine
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_run(migrated_db, session_id=sid, status="queued")  # second active: rejected


def test_runs_without_session_are_unconstrained(migrated_db: psycopg.Connection) -> None:
    _insert_run(migrated_db, status="running")
    _insert_run(migrated_db, status="running")


def test_unknown_status_rejected(migrated_db: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_run(migrated_db, status="paused")


def test_terminal_run_must_have_finished_at(migrated_db: psycopg.Connection) -> None:
    rid = _insert_run(migrated_db, status="running")
    with pytest.raises(psycopg.errors.CheckViolation):
        migrated_db.execute("UPDATE runs SET status = 'completed' WHERE id = %s", (rid,))


def test_run_event_seq_is_unique_per_run(migrated_db: psycopg.Connection) -> None:
    rid = _insert_run(migrated_db)
    insert = "INSERT INTO run_events (run_id, seq, epoch, type) VALUES (%s, %s, 1, 'run.started')"
    migrated_db.execute(insert, (rid, 1))
    with pytest.raises(psycopg.errors.UniqueViolation):
        migrated_db.execute(insert, (rid, 1))


def test_session_message_id_dedups(migrated_db: psycopg.Connection) -> None:
    """A reclaimed worker re-writing the same message is a no-op (R12.3)."""
    sid = _insert_session(migrated_db)
    insert = (
        "INSERT INTO session_messages (session_id, seq, message_id, type, role, content) "
        "VALUES (%s, %s, 'm-1', 'user', 'user', '{\"text\": \"hi\"}') "
        "ON CONFLICT (message_id) DO NOTHING"
    )
    migrated_db.execute(insert, (sid, 1))
    migrated_db.execute(insert, (sid, 2))
    count = migrated_db.execute(
        "SELECT count(*) FROM session_messages WHERE session_id = %s", (sid,)
    ).fetchone()
    assert count == (1,)


def test_vector_extension_and_dimension(migrated_db: psycopg.Connection) -> None:
    did = uuid.uuid4()
    migrated_db.execute(
        "INSERT INTO documents (id, title, path, sha256) VALUES (%s, 't', 'p', 'x')", (did,)
    )
    insert = (
        "INSERT INTO chunks (id, document_id, ord, text, embedding) VALUES (%s, %s, %s, 'c', %s)"
    )
    good = "[" + ",".join(["0.1"] * 768) + "]"
    migrated_db.execute(insert, (uuid.uuid4(), did, 0, good))
    with pytest.raises(psycopg.errors.DataException):
        migrated_db.execute(insert, (uuid.uuid4(), did, 1, "[0.1,0.2]"))

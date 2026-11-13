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
    "agent_definitions",
    "admin_state",
    "subagent_invocations",
    "notes",
    "outbox_notifications",
    "agents",
    "agent_versions",
    "model_connections",
    "workspace_settings",
    "skills",
    "skill_versions",
    "skill_files",
    "tool_settings",
    "kill_switches",
    "skill_scans",
    "run_model_usage",
    "audit_events",
    "reply_feedback",
    "mcp_servers",
    "mcp_tools",
    "run_approvals",
    "notification_deliveries",
    "agent_evals",
    "eval_runs",
    "note_forgets",
    "skill_approvals",
}


# Owned by LangGraph's checkpointer (created by its own `setup()`), not by Alembic.
LANGGRAPH_TABLES = {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}


def _tables(conn: psycopg.Connection) -> set[str]:
    """Tables managed by our migrations (excludes Alembic's and LangGraph's own)."""
    rows = conn.execute(
        "SELECT tablename FROM pg_tables "
        "WHERE schemaname = 'public' AND tablename != 'alembic_version'"
    ).fetchall()
    return {r[0] for r in rows} - LANGGRAPH_TABLES


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


def test_admin_state_is_a_single_row(migrated_db: psycopg.Connection) -> None:
    """The kill switch has exactly one row; a second one is impossible (R14.18)."""
    rows = migrated_db.execute("SELECT paused FROM admin_state").fetchall()
    assert rows == [(False,)]
    with pytest.raises(psycopg.errors.CheckViolation):
        migrated_db.execute("INSERT INTO admin_state (id) VALUES (false)")


def test_new_run_columns_have_safe_defaults(migrated_db: psycopg.Connection) -> None:
    """Expand step: old code inserting runs without the new columns still works."""
    rid = _insert_run(migrated_db)
    row = migrated_db.execute(
        "SELECT kind, steps, model_calls, tool_calls_total, tool_calls, depth, limits "
        "FROM runs WHERE id = %s",
        (rid,),
    ).fetchone()
    assert row == ("workflow", 0, 0, 0, {}, 0, {})


def test_subagent_spawn_is_idempotent_by_tool_call(migrated_db: psycopg.Connection) -> None:
    """Replaying a spawn after a reclaim must not create a second invocation (R16.4)."""
    rid = _insert_run(migrated_db, status="running")
    insert = (
        "INSERT INTO subagent_invocations "
        "(handle, run_id, agent, task, thread_id, epoch, spawned_by_tool_call_id) "
        "VALUES (%s, %s, 'chat/researcher', 't', %s, 1, 'call-1') "
        "ON CONFLICT (spawned_by_tool_call_id) DO NOTHING"
    )
    for _ in range(2):
        handle = uuid.uuid4()
        migrated_db.execute(insert, (handle, rid, f"{rid}/sub/{handle}"))
    count = migrated_db.execute(
        "SELECT count(*) FROM subagent_invocations WHERE run_id = %s", (rid,)
    ).fetchone()
    assert count == (1,)


def test_sc9_database_rejects_stale_epoch_writes(migrated_db: psycopg.Connection) -> None:
    """The trigger fences writes even when application code is bypassed."""
    rid = _insert_run(migrated_db, status="running")
    migrated_db.execute("UPDATE runs SET epoch = 3 WHERE id = %s", (rid,))
    insert = (
        "INSERT INTO run_events (run_id, seq, epoch, type) VALUES (%s, %s, %s, 'node.completed')"
    )

    migrated_db.execute(insert, (rid, 1, 3))  # current epoch: accepted
    migrated_db.execute(insert, (rid, 2, 4))  # a newer epoch (racing takeover): accepted
    migrated_db.execute("SAVEPOINT before_stale")
    with pytest.raises(psycopg.Error) as exc:
        migrated_db.execute(insert, (rid, 3, 2))  # stale: rejected
    assert exc.value.sqlstate == "EF001"
    assert "stale epoch 2" in str(exc.value)
    migrated_db.execute("ROLLBACK TO SAVEPOINT before_stale")

    # Updates are fenced too (e.g. a zombie finishing a tool invocation).
    migrated_db.execute(
        "INSERT INTO tool_invocations (key, run_id, tool, status, epoch) "
        "VALUES (%s, %s, 'search', 'in_progress', 3)",
        ("a" * 64, rid),
    )
    with pytest.raises(psycopg.Error, match="stale epoch 1"):
        migrated_db.execute(
            "UPDATE tool_invocations SET status = 'done', epoch = 1 WHERE key = %s", ("a" * 64,)
        )


def test_rows_without_an_epoch_are_not_fenced(migrated_db: psycopg.Connection) -> None:
    sid = _insert_session(migrated_db)
    migrated_db.execute(
        "INSERT INTO session_messages (session_id, seq, message_id, type, role, content) "
        "VALUES (%s, 1, 'm-api', 'user', 'user', '{}')",
        (sid,),
    )


# ------------------------------------------------------------ Studio (L3a, AC47)


def _agent_with_version(conn: psycopg.Connection, state: str = "draft") -> uuid.UUID:
    agent = uuid.uuid4()
    digest = "a" * 64
    conn.execute(
        "INSERT INTO agent_definitions (hash, name, version, kind, content) "
        "VALUES (%s, 't', 1, 'bundle', '{}') ON CONFLICT DO NOTHING",
        (digest,),
    )
    conn.execute("INSERT INTO agents (id, name) VALUES (%s, %s)", (agent, f"a{agent.hex[:8]}"))
    conn.execute(
        "INSERT INTO agent_versions (agent_id, number, state, document, bundle_hash) "
        "VALUES (%s, 1, 'draft', '{}', %s)",
        (agent, digest),
    )
    if state == "published":
        conn.execute(
            "UPDATE agent_versions SET state = 'published', published_at = now() "
            "WHERE agent_id = %s",
            (agent,),
        )
    return agent


def test_a_published_version_can_never_change(migrated_db: psycopg.Connection) -> None:
    agent = _agent_with_version(migrated_db, "published")
    for change in ("document = '{\"x\": 1}'", "changelog = 'sneaky'", "state = 'draft'"):
        migrated_db.execute("SAVEPOINT s")
        with pytest.raises(psycopg.errors.CheckViolation):
            migrated_db.execute(f"UPDATE agent_versions SET {change} WHERE agent_id = %s", (agent,))
        migrated_db.execute("ROLLBACK TO SAVEPOINT s")
    with pytest.raises(psycopg.errors.CheckViolation):
        migrated_db.execute("DELETE FROM agent_versions WHERE agent_id = %s", (agent,))


def test_versions_only_move_forward_and_one_draft_per_agent(
    migrated_db: psycopg.Connection,
) -> None:
    agent = _agent_with_version(migrated_db, "published")
    migrated_db.execute(
        "UPDATE agent_versions SET state = 'archived' WHERE agent_id = %s", (agent,)
    )
    migrated_db.execute(
        "INSERT INTO agent_versions (agent_id, number, state, document) "
        "VALUES (%s, 2, 'draft', '{}')",
        (agent,),
    )
    migrated_db.execute("UPDATE agent_versions SET document = '{\"a\": 1}' WHERE number = 2 "
                        "AND agent_id = %s", (agent,))  # a draft is editable  # fmt: skip
    with pytest.raises(psycopg.errors.UniqueViolation):
        migrated_db.execute(
            "INSERT INTO agent_versions (agent_id, number, state, document) "
            "VALUES (%s, 3, 'draft', '{}')",
            (agent,),
        )


def test_a_retried_send_finds_its_turn(migrated_db: psycopg.Connection) -> None:
    session = migrated_db.execute(
        "INSERT INTO sessions (id, graph_name) VALUES (%s, 'chat') RETURNING id", (uuid.uuid4(),)
    ).fetchone()
    assert session is not None
    insert = (
        "INSERT INTO runs (id, graph_name, thread_id, input, status, finished_at, session_id,"
        " idempotency_key, kind) "
        "VALUES (%s, 'chat', 't', '{}', 'completed', now(), %s, 'k1', 'turn')"
    )
    migrated_db.execute(insert.replace("'completed'", "'cancelled'"), (uuid.uuid4(), session[0]))
    with pytest.raises(psycopg.errors.UniqueViolation):
        migrated_db.execute(insert, (uuid.uuid4(), session[0]))


def test_notifications_from_before_delivery_are_never_sent_by_an_upgrade(
    alembic_cfg: Config, test_db_url: str
) -> None:
    """H4: a notification queued before Nuria delivered them is backfilled as skipped (an
    upgrade sends nothing by surprise); one queued after gets a pending delivery."""
    url = test_db_url.replace("postgresql+psycopg", "postgresql")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "0023")
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            rid = _insert_run(conn, status="running")
            conn.execute(
                "INSERT INTO outbox_notifications (key, run_id, recipient, message, epoch) "
                "VALUES (%s, %s, 'ops', 'old news', 0)", ("a" * 64, rid),
            )  # fmt: skip
        command.upgrade(alembic_cfg, "head")
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO outbox_notifications (key, run_id, recipient, message, epoch) "
                "VALUES (%s, %s, 'ops', 'new', 0)", ("b" * 64, rid),
            )  # fmt: skip
            rows = conn.execute(
                "SELECT key, status FROM notification_deliveries WHERE key IN (%s, %s) "
                "ORDER BY key", ("a" * 64, "b" * 64),
            ).fetchall()  # fmt: skip
            conn.execute("DELETE FROM runs WHERE id = %s", (rid,))
        assert rows == [("a" * 64, "skipped"), ("b" * 64, "pending")]
    finally:
        command.upgrade(alembic_cfg, "head")


def test_notes_from_before_memory_keep_their_agent_and_test_scope(
    alembic_cfg: Config, test_db_url: str
) -> None:
    """H8: notes written before 0028 are scoped from their runs (a Studio test chat's
    stays in that chat); a note written by a worker that doesn't know the columns is
    scoped by the trigger; going back to 0027 and up again works."""
    url = test_db_url.replace("postgresql+psycopg", "postgresql")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "0027")
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            real = _insert_run(conn, status="running")
            agent = conn.execute(
                "INSERT INTO agents (id, name) VALUES (gen_random_uuid(), %s) RETURNING id",
                (f"t{uuid.uuid4().hex[:8]}",),
            ).fetchone()
            assert agent is not None
            test_chat = uuid.uuid4()
            conn.execute("INSERT INTO sessions (id, graph_name, playground_of) "
                         "VALUES (%s, 'chat', %s)", (test_chat, agent[0]))  # fmt: skip
            tested = _insert_run(conn, status="running", session_id=test_chat)
            for key, rid in (("c" * 64, real), ("d" * 64, tested)):
                conn.execute("INSERT INTO notes (key, run_id, text, epoch) "
                             "VALUES (%s, %s, 'old', 0)", (key, rid))  # fmt: skip
            # Leased again since (a resume after an approval): the notes' epoch is older
            # than their run's, which the fence refuses on any update.
            conn.execute("UPDATE runs SET epoch = 3 WHERE id IN (%s, %s)", (real, tested))
        command.upgrade(alembic_cfg, "head")
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("INSERT INTO notes (key, run_id, text, epoch) "
                         "VALUES (%s, %s, 'from an H7 worker', 3)", ("e" * 64, real))  # fmt: skip
            rows = conn.execute(
                "SELECT key, agent, test_scope FROM notes WHERE key IN (%s, %s, %s) ORDER BY key",
                ("c" * 64, "d" * 64, "e" * 64),
            ).fetchall()
            assert rows == [("c" * 64, "chat", None), ("d" * 64, "chat", test_chat),
                            ("e" * 64, "chat", None)]  # fmt: skip
        command.downgrade(alembic_cfg, "0027")
        command.upgrade(alembic_cfg, "head")
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("DELETE FROM runs WHERE id IN (%s, %s)", (real, tested))
            conn.execute("DELETE FROM sessions WHERE id = %s", (test_chat,))
            conn.execute("DELETE FROM agents WHERE id = %s", (agent[0],))
    finally:
        command.upgrade(alembic_cfg, "head")


def test_skills_written_here_or_built_in_are_read_but_uploaded_ones_wait(
    alembic_cfg: Config, test_db_url: str
) -> None:
    """H10 2.2: 0029 approves the current version of every skill a person wrote in the
    Studio or that ships with Nuria; an uploaded or imported one waits for its reader.
    Going back to 0028 and up again works (and approves the same ones again)."""
    url = test_db_url.replace("postgresql+psycopg", "postgresql")
    tag = uuid.uuid4().hex[:8]
    hashes = {origin: (str(i) * 64) for i, origin in
              enumerate(("created", "uploaded", "imported", "built_in"), start=1)}  # fmt: skip
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "0028")
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            for origin, digest in hashes.items():
                name = f"m-{origin.replace('_', '-')}-{tag}"
                conn.execute(
                    "INSERT INTO skill_versions (hash, name, description, instructions, scan) "
                    "VALUES (%s, %s, 'd', 'i', '{\"status\": \"clean\", \"findings\": []}')",
                    (digest, name),
                )
                conn.execute(
                    "INSERT INTO skills (id, name, trust, origin, current_hash) "
                    "VALUES (gen_random_uuid(), %s, %s, %s, %s)",
                    (name, "built_in" if origin == "built_in" else "private", origin, digest),
                )
        for _ in range(2):  # the backfill, and the backfill again after a rollback
            command.upgrade(alembic_cfg, "head")
            with psycopg.connect(url, autocommit=True) as conn:
                rows = conn.execute(
                    "SELECT hash FROM skill_approvals WHERE hash = ANY(%s) ORDER BY hash",
                    (list(hashes.values()),),
                ).fetchall()
            assert rows == [(hashes["created"],), (hashes["built_in"],)]
            command.downgrade(alembic_cfg, "0028")
        command.upgrade(alembic_cfg, "head")
        with psycopg.connect(url, autocommit=True) as conn:
            mine = list(hashes.values())
            conn.execute("DELETE FROM skills WHERE current_hash = ANY(%s)", (mine,))
            conn.execute("DELETE FROM skill_approvals WHERE hash = ANY(%s)", (mine,))
            conn.execute("DELETE FROM skill_versions WHERE hash = ANY(%s)", (mine,))
    finally:
        command.upgrade(alembic_cfg, "head")

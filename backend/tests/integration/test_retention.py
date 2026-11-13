"""Retention (phase H10, 2.8): a run that ended RETENTION_DAYS ago loses its events and
tool calls; the run, the chat, its notes and the audit trail stay; 0 keeps everything;
delivered notifications go after a week; the worker's own role can do it and nothing more."""

import uuid
from collections.abc import AsyncIterator

import pytest
from psycopg import errors

from agent_runtime.config import Settings, component_credentials
from agent_runtime.db import Pool, create_pool
from agent_runtime.dbadmin import provision_users
from agent_runtime.runs.events import EventType as E
from agent_runtime.runs.retention import PruneReport, prune_details
from agent_runtime.runs.state import FailureReason
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.runs.store import RunRepository

pytestmark = pytest.mark.integration


async def ended_run(
    pool: Pool,
    *,
    days_ago: int,
    events: int = 3,
    invocations: int = 2,
    session_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """A completed run that ended `days_ago`, with `events` node events on top of the
    created/started/completed three, and `invocations` tool calls in the ledger."""
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        run = await repo.create(
            graph_name="toy", input={"q": "old"},
            kind="turn" if session_id else "workflow", session_id=session_id,
        )  # fmt: skip
        await repo.transition(run.id, S.RUNNING, event=E.RUN_STARTED)
        async with conn.transaction():
            for i in range(events):
                await repo.append_event(
                    run.id, epoch=0, type=E.NODE_COMPLETED, payload={"node": f"n{i}"}
                )
        await repo.transition(run.id, S.COMPLETED, event=E.RUN_COMPLETED)
        for _ in range(invocations):  # the fence (0004) wants an epoch >= the run's (0)
            await conn.execute(
                "INSERT INTO tool_invocations (key, run_id, tool, status, result, epoch) "
                "VALUES (%s, %s, 'search', 'done', '{}', 0)",
                (uuid.uuid4().hex * 2, run.id),
            )
        await conn.execute(
            "UPDATE runs SET finished_at = now() - make_interval(days => %(d)s), "
            "created_at = created_at - make_interval(days => %(d)s) WHERE id = %(id)s",
            {"d": days_ago, "id": run.id},
        )
    return run.id


async def count(pool: Pool, table: str, where: str, *params: object) -> int:
    async with pool.connection() as conn:
        cur = await conn.execute(f"SELECT count(*) AS n FROM {table} WHERE {where}", params)
        row = await cur.fetchone()
    return int(row["n"]) if row else 0


async def pruned_at(pool: Pool, run_id: uuid.UUID) -> object:
    async with pool.connection() as conn:
        return (await RunRepository(conn).get(run_id)).details_pruned_at


async def notification(pool: Pool, run_id: uuid.UUID, *, status: str, days_ago: int) -> str:
    """One `notify` outbox row whose delivery ended `status` `days_ago`."""
    key = uuid.uuid4().hex * 2
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO outbox_notifications (key, run_id, recipient, message, epoch) "
            "VALUES (%s, %s, 'ops', 'done', 0)",
            (key, run_id),
        )  # the 0024 trigger adds its pending delivery row
        await conn.execute(
            "UPDATE notification_deliveries SET status = %s, delivered_at = CASE WHEN %s = "
            "'delivered' THEN now() - make_interval(days => %s) END WHERE key = %s",
            (status, status, days_ago, key),
        )
    return key


async def test_old_runs_lose_their_details_and_keep_everything_else(pool: Pool) -> None:
    """SC8: events and tool calls of a run two days old are gone and the run says so; the
    run row, the chat, its note and the audit trail are untouched; a fresh run is intact."""
    session = uuid.uuid4()
    async with pool.connection() as conn:
        await conn.execute("INSERT INTO sessions (id, graph_name) VALUES (%s, 'chat')", (session,))
    old = await ended_run(pool, days_ago=2, session_id=session)
    fresh = await ended_run(pool, days_ago=0)
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO session_messages (session_id, seq, message_id, run_id, type, role, "
            "content) VALUES (%s, 1, %s, %s, 'assistant', 'assistant', '{\"text\": \"42\"}')",
            (session, f"m-{old}", old),
        )
        await conn.execute(
            "INSERT INTO notes (key, run_id, text, epoch) VALUES (%s, %s, 'remember', 0)",
            (uuid.uuid4().hex * 2, old),
        )
        await conn.execute(
            "INSERT INTO audit_events (id, actor, action, target_type, target_id) "
            "VALUES (%s, 'test', 'run.created', 'run', %s)",
            (uuid.uuid4(), str(old)),
        )
    audit_before = await count(pool, "audit_events", "true")

    report = await prune_details(pool, older_than_days=1)

    assert report.runs >= 1 and report.events >= 6 and report.invocations >= 2
    assert await count(pool, "run_events", "run_id = %s", old) == 0
    assert await count(pool, "tool_invocations", "run_id = %s", old) == 0
    assert await pruned_at(pool, old) is not None
    async with pool.connection() as conn:
        run = await RunRepository(conn).get(old)  # the run row stays, as it ended
    assert run.status is S.COMPLETED and run.session_id == session
    assert await count(pool, "session_messages", "run_id = %s", old) == 1
    assert await count(pool, "notes", "run_id = %s", old) == 1
    assert await count(pool, "audit_events", "true") == audit_before
    # A run that ended today keeps everything.
    assert await count(pool, "run_events", "run_id = %s", fresh) == 6
    assert await count(pool, "tool_invocations", "run_id = %s", fresh) == 2
    assert await pruned_at(pool, fresh) is None


async def test_batches_continue_until_a_run_is_clean(pool: Pool) -> None:
    """A batch smaller than the run's rows means several short transactions; the marker
    is set only once nothing is left, so a sweep cut short leaves the run due, not lying."""
    old = await ended_run(pool, days_ago=3, events=7, invocations=5)  # 10 events, 5 calls

    report = await prune_details(pool, older_than_days=1, batch=4)

    assert report.events >= 10 and report.invocations >= 5
    assert await count(pool, "run_events", "run_id = %s", old) == 0
    assert await count(pool, "tool_invocations", "run_id = %s", old) == 0
    assert await pruned_at(pool, old) is not None


async def test_zero_days_keeps_everything(pool: Pool) -> None:
    """RETENTION_DAYS=0: the sweep is off; even a run from last week keeps its details."""
    old = await ended_run(pool, days_ago=7)

    assert await prune_details(pool, older_than_days=0) == PruneReport()
    assert await count(pool, "run_events", "run_id = %s", old) == 6
    assert await count(pool, "tool_invocations", "run_id = %s", old) == 2
    assert await pruned_at(pool, old) is None


async def test_a_run_still_going_is_never_touched(pool: Pool) -> None:
    """Age is counted from the end: a run that started two days ago and hasn't ended
    keeps its timeline; once it ends, it is as fresh as its finish time."""
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        run = await repo.create(graph_name="toy", input={"q": "slow"})
        await repo.transition(run.id, S.RUNNING, event=E.RUN_STARTED)
        await conn.execute(
            "UPDATE runs SET created_at = now() - interval '2 days', "
            "started_at = now() - interval '2 days' WHERE id = %s",
            (run.id,),
        )

    await prune_details(pool, older_than_days=1)
    assert await count(pool, "run_events", "run_id = %s", run.id) == 2
    assert await pruned_at(pool, run.id) is None

    async with pool.connection() as conn:
        await RunRepository(conn).transition(
            run.id, S.CANCELLED, event=E.RUN_CANCELLED, reason=FailureReason.CANCEL_REQUESTED
        )
    await prune_details(pool, older_than_days=1)
    assert await count(pool, "run_events", "run_id = %s", run.id) == 3  # ended just now
    assert await pruned_at(pool, run.id) is None


async def test_the_sweep_is_idempotent(pool: Pool) -> None:
    """A second sweep right after the first finds nothing: pruned runs are marked, and a
    marked run is never selected again."""
    old = await ended_run(pool, days_ago=2)

    first = await prune_details(pool, older_than_days=1)
    second = await prune_details(pool, older_than_days=1)

    assert first.runs >= 1
    assert second == PruneReport()
    assert await pruned_at(pool, old) is not None


async def test_delivered_notifications_go_after_a_week(pool: Pool) -> None:
    """A notification delivered more than seven days ago goes (with its delivery row);
    one delivered today, and one that failed long ago, stay listed."""
    run = await ended_run(pool, days_ago=0)
    old = await notification(pool, run, status="delivered", days_ago=8)
    recent = await notification(pool, run, status="delivered", days_ago=0)
    failed = await notification(pool, run, status="failed", days_ago=8)

    report = await prune_details(pool, older_than_days=1)

    assert report.notifications >= 1
    assert await count(pool, "outbox_notifications", "key = %s", old) == 0
    assert await count(pool, "notification_deliveries", "key = %s", old) == 0  # cascaded
    assert await count(pool, "outbox_notifications", "key = ANY(%s)", [recent, failed]) == 2


# ------------------------------------------------------ as the worker's own role (R14.13)


@pytest.fixture
async def as_worker(pool: Pool, test_settings: Settings) -> AsyncIterator[Pool]:
    if component_credentials("worker") is None:
        pytest.fail("WORKER_POSTGRES_USER/PASSWORD not set (see .env.example)")
    async with pool.connection() as conn:
        await provision_users(conn)
    async with create_pool(test_settings.for_component("worker"), max_size=4) as p:
        yield p


async def denied(pool: Pool, statement: str) -> bool:
    async with pool.connection() as conn:
        try:
            await conn.execute(statement)
        except errors.InsufficientPrivilege:
            return True
    return False


async def test_the_worker_role_can_prune_details_and_nothing_more(
    pool: Pool, as_worker: Pool
) -> None:
    """The 0031 grants are sufficient (the sweep runs as app_worker, the delivery row
    cascades without a DELETE on its table) and no wider: still no DELETE on runs, the
    chat, notes, deliveries or the audit trail."""
    old = await ended_run(pool, days_ago=2)
    sent = await notification(pool, old, status="delivered", days_ago=8)

    report = await prune_details(as_worker, older_than_days=1)

    assert report.runs >= 1 and report.notifications >= 1
    assert await count(pool, "run_events", "run_id = %s", old) == 0
    assert await count(pool, "tool_invocations", "run_id = %s", old) == 0
    assert await count(pool, "notification_deliveries", "key = %s", sent) == 0
    assert await pruned_at(pool, old) is not None
    for table in ("runs", "session_messages", "notes", "notification_deliveries",
                  "audit_events", "run_model_usage"):  # fmt: skip
        assert await denied(as_worker, f"DELETE FROM {table}"), table

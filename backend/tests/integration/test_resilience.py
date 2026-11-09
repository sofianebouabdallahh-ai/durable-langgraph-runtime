"""Phase H4: an infrastructure error doesn't end a run for good, and a failed run can be
tried again (redrive) from its last checkpoint, with nothing done twice."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import psycopg
import pytest

from agent_runtime.api.app import create_app
from agent_runtime.checkpointing import FencedCheckpointer
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.queue import RedisWorkQueue
from agent_runtime.runs.events import EventType as E
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.runs.store import NotRedrivable, Run, RunRepository
from agent_runtime.sessions.service import SessionService
from agent_runtime.sessions.store import Message, SessionRepository
from tests.integration.support import events, wait_until

pytestmark = pytest.mark.integration
GRAPHS = default_registry()


def note(text: str, linger_s: float = 0.0) -> dict[str, Any]:
    args: dict[str, Any] = {"text": text} | ({"linger_s": linger_s} if linger_s else {})
    return {"tool_calls": [{"name": "save_note", "args": args}]}


def say(text: str) -> dict[str, Any]:
    return {"content": text}


@pytest.fixture
def failing_puts(monkeypatch: pytest.MonkeyPatch, pool: Pool) -> Callable[..., list[int]]:
    """Make checkpoint writes fail: `fail(exc, at={3})` raises `exc` on those calls
    (counted from 1), `always=True` on every one from the first in `at`;
    `after_tool=True`: once, on the first write after the turn's note was saved (so the
    side effect is done and the step that did it isn't committed)."""

    def arm(
        exc: BaseException, at: frozenset[int] | set[int] = frozenset(), always: bool = False,
        after_tool: bool = False,
    ) -> list[int]:  # fmt: skip
        calls, fired = [0], [False]
        real = FencedCheckpointer.aput

        async def aput(self: FencedCheckpointer, *a: Any, **kw: Any) -> Any:
            calls[0] += 1
            if after_tool and not fired[0]:
                async with pool.connection() as conn:
                    cur = await conn.execute("SELECT 1 FROM notes WHERE run_id = %s",
                                             (self.fence.run_id,))  # fmt: skip
                    if await cur.fetchone() is not None:
                        fired[0] = True
                        raise exc
            if calls[0] in at or (always and at and calls[0] >= min(at)):
                raise exc
            return await real(self, *a, **kw)

        monkeypatch.setattr(FencedCheckpointer, "aput", aput)
        return calls

    return arm


async def assistant_run(pool: Pool, settings: Settings, script: list[dict[str, Any]]) -> Run:
    return await RunService(pool, settings, GRAPHS).create_run(
        "assistant", {"message": "keep this", "script": script}
    )


async def execute(pool: Pool, settings: Settings, run_id: uuid.UUID) -> Run:
    return await RunExecutor(pool, settings, GRAPHS).execute(run_id)


async def notes(pool: Pool, run_id: uuid.UUID) -> int:
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT count(*) AS n FROM notes WHERE run_id = %s", (run_id,))
        row = await cur.fetchone()
    return int(row["n"]) if row else 0


async def released(pool: Pool, run_id: uuid.UUID) -> list[dict[str, Any]]:
    return [e.payload for e in await events(pool, run_id) if e.type == E.RUN_RELEASED]


async def failed_payload(pool: Pool, run_id: uuid.UUID) -> dict[str, Any]:
    (event,) = [e for e in await events(pool, run_id) if e.type == E.RUN_FAILED]
    return event.payload


# ------------------------------------------------- infrastructure errors (finding 16)


async def test_an_infrastructure_error_mid_run_releases_it_and_it_resumes_without_redoing(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    failing_puts: Callable[..., list[int]],
) -> None:  # fmt: skip
    run = await assistant_run(pool, test_settings, [note("kept"), say("Kept.")])
    failing_puts(psycopg.OperationalError("server closed the connection unexpectedly"), {3})
    first = await execute(pool, test_settings, run.id)
    assert (first.status, first.owner, first.infra_retries) == (S.QUEUED, None, 1)
    (release,) = await released(pool, run.id)
    assert release["reason"] == "infrastructure" and "OperationalError" in release["detail"]
    done = await execute(pool, test_settings, run.id)
    assert done.status is S.COMPLETED
    assert await notes(pool, run.id) == 1  # the tool ran once (the ledger)
    assert E.RUN_FAILED not in [e.type for e in await events(pool, run.id)]


async def test_an_infrastructure_error_that_never_heals_ends_the_run_after_the_retries(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    failing_puts: Callable[..., list[int]],
) -> None:  # fmt: skip
    settings = test_settings.model_copy(update={"max_infra_retries": 2})
    run = await assistant_run(pool, settings, [note("kept"), say("Kept.")])
    failing_puts(psycopg.errors.AdminShutdown("terminating connection"), {1}, always=True)
    outcomes = [await execute(pool, settings, run.id) for _ in range(3)]
    assert [o.status for o in outcomes] == [S.QUEUED, S.QUEUED, S.FAILED]
    assert outcomes[-1].reason == "infrastructure"
    payload = await failed_payload(pool, run.id)
    assert payload["can_retry"] is True and "AdminShutdown" in payload["detail"]


async def test_a_bug_still_fails_the_run_at_once(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    failing_puts: Callable[..., list[int]],
) -> None:  # fmt: skip
    run = await assistant_run(pool, test_settings, [note("kept"), say("Kept.")])
    failing_puts(ValueError("a bug"), {3})
    ended = await execute(pool, test_settings, run.id)
    assert (ended.status, ended.reason, ended.infra_retries) == (S.FAILED, "error", 0)
    assert await released(pool, run.id) == []


async def test_database_connections_cut_mid_tool_call_never_fail_the_run(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    """The real thing: every connection to the database is terminated (what a failover or
    a restart does) while the turn's tool call runs."""
    run = await assistant_run(pool, test_settings, [note("kept", linger_s=2.0), say("Kept.")])
    task = asyncio.create_task(execute(pool, test_settings, run.id))
    await wait_until(lambda: _has_notes(pool, run.id), timeout_s=20)
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT count(pg_terminate_backend(pid)) AS n FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid()"
        )
        killed = await cur.fetchone()
    assert killed is not None and killed["n"] >= 1
    ended = await task
    for _ in range(3):  # a release (or two) is fine; failing is not
        if ended.status is not S.QUEUED:
            break
        ended = await execute(pool, test_settings, run.id)
    assert ended.status is S.COMPLETED
    assert await notes(pool, run.id) == 1


async def _has_notes(pool: Pool, run_id: uuid.UUID) -> bool:
    return await notes(pool, run_id) > 0


# --------------------------------------------------------------- redrive


async def test_a_failed_run_is_redriven_from_its_checkpoint_and_nothing_runs_twice(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    failing_puts: Callable[..., list[int]],
) -> None:  # fmt: skip
    run = await assistant_run(pool, test_settings, [note("kept"), say("Kept.")])
    failing_puts(ValueError("a bug, fixed by the next deploy"), after_tool=True)
    failed = await execute(pool, test_settings, run.id)
    assert (failed.status, failed.reason) == (S.FAILED, "error")
    assert await notes(pool, run.id) == 1  # done, in a step that didn't commit
    service = RunService(pool, test_settings, GRAPHS)
    again = await service.redrive(run.id)
    assert (again.status, again.reason, again.redrives, again.finished_at) == (
        S.QUEUED, None, 1, None)  # fmt: skip
    done = await execute(pool, test_settings, run.id)
    assert done.status is S.COMPLETED
    assert await notes(pool, run.id) == 1  # the done tool call wasn't run again
    types = [e.type for e in await events(pool, run.id)]
    assert types.count(E.RUN_REDRIVEN) == 1 and types[-1] == E.RUN_COMPLETED
    async with pool.connection() as conn:
        audit = await conn.execute(
            "SELECT after FROM audit_events WHERE action = 'run.redriven' AND target_id = %s",
            (str(run.id),),
        )
        assert [r["after"] for r in await audit.fetchall()] == [{"redrives": 1}]


async def test_a_run_that_would_fail_the_same_way_is_not_redriven(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    looping = [{"tool_calls": [{"name": "calculator", "args": {"expression": "1+1"}}]}] * 6
    run = await RunService(pool, test_settings, GRAPHS).create_run(
        "assistant", {"message": "loop", "script": looping}, {"max_tool_calls": 2}
    )
    ended = await execute(pool, test_settings, run.id)
    assert ended.status is S.FAILED and ended.reason not in ("error", "infrastructure")
    with pytest.raises(NotRedrivable, match="fail the same way"):
        await RunService(pool, test_settings, GRAPHS).redrive(run.id)
    done = await assistant_run(pool, test_settings, [say("hi")])
    await execute(pool, test_settings, done.id)
    with pytest.raises(NotRedrivable, match="Only a failed run"):
        await RunService(pool, test_settings, GRAPHS).redrive(done.id)


# ------------------------------------------------------- a chat turn, tried again


def chats(pool: Pool, settings: Settings) -> SessionService:
    return SessionService(pool, settings, GRAPHS, RunService(pool, settings, GRAPHS))


async def transcript(pool: Pool, session_id: uuid.UUID) -> list[Message]:
    async with pool.connection() as conn:
        return await SessionRepository(conn).messages(session_id, limit=1000)


async def test_a_failed_chat_turn_is_tried_again_and_the_chat_shows_what_happened(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    failing_puts: Callable[..., list[int]],
) -> None:  # fmt: skip
    service = chats(pool, test_settings)
    sid = (await service.create("chat")).id
    sent = await service.send(sid, "keep this", script=[note("kept"), say("Kept.")])
    failing_puts(ValueError("a bug"), after_tool=True)
    failed = await execute(pool, test_settings, sent.run.id)
    assert failed.status is S.FAILED
    (error,) = [m for m in await transcript(pool, sid) if m.type == "error"]
    assert error.content["can_retry"] is True
    await RunService(pool, test_settings, GRAPHS).redrive(sent.run.id)
    done = await execute(pool, test_settings, sent.run.id)
    assert done.status is S.COMPLETED
    msgs = await transcript(pool, sid)
    kinds = [m.type for m in msgs]
    retry = next(i for i, m in enumerate(msgs) if m.type == "system" and "retry" in m.content)
    assert kinds.index("error") < retry < len(kinds) - 1
    assert msgs[retry].content == {"text": "Tried again", "retry": 1}
    assert msgs[-1].type == "assistant" and msgs[-1].content["text"] == "Kept."
    assert len({m.message_id for m in msgs}) == len(msgs)
    assert await notes(pool, sent.run.id) == 1


async def test_the_same_failure_after_a_retry_is_written_again(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    failing_puts: Callable[..., list[int]],
) -> None:  # fmt: skip
    service = chats(pool, test_settings)
    sid = (await service.create("chat")).id
    sent = await service.send(sid, "keep this", script=[note("kept"), say("Kept.")])
    failing_puts(ValueError("still broken"), {1}, always=True)
    await execute(pool, test_settings, sent.run.id)
    await RunService(pool, test_settings, GRAPHS).redrive(sent.run.id)
    again = await execute(pool, test_settings, sent.run.id)
    assert again.status is S.FAILED
    errors = [m for m in await transcript(pool, sid) if m.type == "error"]
    assert [e.content.get("attempt") for e in errors] == [None, 2]


async def test_only_the_chats_latest_turn_can_be_tried_again(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    failing_puts: Callable[..., list[int]],
) -> None:  # fmt: skip
    service = chats(pool, test_settings)
    sid = (await service.create("chat")).id
    first = await service.send(sid, "one", script=[note("kept"), say("Kept.")])
    calls = failing_puts(ValueError("a bug"), {3})
    await execute(pool, test_settings, first.run.id)
    calls[0] = 100  # healed
    later = await service.send(sid, "two", script=[say("Two.")])
    with pytest.raises(NotRedrivable, match="latest"):  # a turn runs (queued) after it
        await RunService(pool, test_settings, GRAPHS).redrive(first.run.id)
    await execute(pool, test_settings, later.run.id)
    with pytest.raises(NotRedrivable, match="latest"):
        await RunService(pool, test_settings, GRAPHS).redrive(first.run.id)
    await service.archive(sid)
    async with pool.connection() as conn:
        assert (await RunRepository(conn).get(first.run.id)).status is S.FAILED


# --------------------------------------------------------------- the API


@pytest.fixture
async def client(
    pool: Pool, test_settings: Settings, queue: RedisWorkQueue, checkpoint_tables: None
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(test_settings, pool=pool, queue=queue)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        yield c


async def test_the_api_redrives_or_says_why_not(
    client: httpx.AsyncClient, pool: Pool, test_settings: Settings,
    failing_puts: Callable[..., list[int]],
) -> None:  # fmt: skip
    run = await assistant_run(pool, test_settings, [note("kept"), say("Kept.")])
    failing_puts(ValueError("a bug"), {3})
    await execute(pool, test_settings, run.id)
    ok = await client.post(f"/runs/{run.id}/redrive")
    assert ok.status_code == 202
    assert (ok.json()["status"], ok.json()["redrives"]) == ("queued", 1)
    again = await client.post(f"/runs/{run.id}/redrive")
    assert again.status_code == 409
    assert again.json()["type"].endswith("/not-redrivable")
    assert (await client.post(f"/runs/{uuid.uuid4()}/redrive")).status_code == 404


async def test_trying_again_is_new_work_and_respects_the_kill_switch(
    pool: Pool, test_settings: Settings, checkpoint_tables: None,
    failing_puts: Callable[..., list[int]],
) -> None:  # fmt: skip
    from agent_runtime.runs.service import AdmissionPaused

    run = await assistant_run(pool, test_settings, [note("kept"), say("Kept.")])
    failing_puts(ValueError("a bug"), after_tool=True)
    await execute(pool, test_settings, run.id)
    async with pool.connection() as conn:  # Stop was pressed before it failed
        await conn.execute("UPDATE runs SET cancel_requested = true WHERE id = %s", (run.id,))
        await conn.execute("UPDATE admin_state SET paused = true")
    service = RunService(pool, test_settings, GRAPHS)
    try:
        with pytest.raises(AdmissionPaused):
            await service.redrive(run.id)
    finally:
        async with pool.connection() as conn:
            await conn.execute("UPDATE admin_state SET paused = false")
    again = await service.redrive(run.id)
    assert again.cancel_requested is False  # trying again is a new decision
    assert (await execute(pool, test_settings, run.id)).status is S.COMPLETED

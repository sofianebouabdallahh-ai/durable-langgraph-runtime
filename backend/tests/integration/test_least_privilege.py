"""SC10: each component connects as its own user and can do only its job (R14.13)."""

import uuid
from collections.abc import AsyncIterator

import psycopg
import pytest
from psycopg import errors

from agent_runtime.config import Settings, component_credentials
from agent_runtime.db import Pool, create_pool
from agent_runtime.dbadmin import grant_checkpoint_tables, provision_users
from agent_runtime.graphs import default_registry
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus

pytestmark = pytest.mark.integration


@pytest.fixture
async def provisioned(pool: Pool, checkpoint_tables: None) -> None:
    for component in ("api", "worker"):
        if component_credentials(component) is None:
            pytest.fail(f"{component.upper()}_POSTGRES_USER/PASSWORD not set (see .env.example)")
    async with pool.connection() as conn:
        await provision_users(conn)
        await grant_checkpoint_tables(conn)


@pytest.fixture
async def as_api(test_settings: Settings, provisioned: None) -> AsyncIterator[Pool]:
    async with create_pool(test_settings.for_component("api"), max_size=2) as p:
        yield p


@pytest.fixture
async def as_worker(test_settings: Settings, provisioned: None) -> AsyncIterator[Pool]:
    async with create_pool(test_settings.for_component("worker"), max_size=4) as p:
        yield p


async def denied(pool: Pool, statement: str) -> bool:
    async with pool.connection() as conn:
        try:
            await conn.execute(statement)
        except errors.InsufficientPrivilege:
            return True
    return False


async def test_worker_cannot_drop_delete_truncate_or_create(as_worker: Pool) -> None:
    assert await denied(as_worker, "DROP TABLE runs")
    assert await denied(as_worker, "DELETE FROM runs")
    assert await denied(as_worker, "TRUNCATE run_events")
    assert await denied(as_worker, "CREATE TABLE sneaky (id int)")
    assert await denied(as_worker, "UPDATE admin_state SET paused = true")


async def test_api_cannot_read_checkpoints_or_tool_results(as_api: Pool) -> None:
    assert await denied(as_api, "SELECT * FROM checkpoints LIMIT 1")
    assert await denied(as_api, "SELECT * FROM tool_invocations LIMIT 1")
    assert await denied(as_api, "DELETE FROM runs")
    assert await denied(
        as_api, "INSERT INTO run_results (run_id, output) VALUES (gen_random_uuid(), '{}')"
    )


async def test_skill_versions_are_immutable_and_workers_only_read_skills(
    as_api: Pool, as_worker: Pool
) -> None:
    """L3c: a skill version, once written, can't be changed or removed by anyone but
    a migration; workers read what runs pinned and nothing else."""
    assert await denied(as_api, "UPDATE skill_versions SET instructions = 'evil'")
    assert await denied(as_api, "DELETE FROM skill_versions")
    assert await denied(as_api, "UPDATE skill_files SET data = 'x'")
    assert await denied(as_api, "DELETE FROM skills")
    assert await denied(as_worker, "INSERT INTO skill_files (sha256, data, size) VALUES "
                        "(repeat('a', 64), 'x', 1)")  # fmt: skip
    assert await denied(as_worker, "SELECT * FROM skills")
    assert not await denied(as_worker, "SELECT hash FROM skill_versions LIMIT 1")


async def test_a_full_run_works_with_only_these_privileges(
    as_api: Pool, as_worker: Pool, test_settings: Settings
) -> None:
    """The grants are sufficient, not just restrictive: create as the API user,
    execute (checkpoints, events, fencing trigger, result) as the worker user."""
    graphs = default_registry()
    run = await RunService(as_api, test_settings, graphs).create_run("toy", {"question": "least"})
    done = await RunExecutor(as_worker, test_settings, graphs, owner="lp:1").execute(run.id)
    assert done.status is RunStatus.COMPLETED


async def test_memory_with_only_these_privileges(
    as_api: Pool, as_worker: Pool, test_settings: Settings
) -> None:
    """H8: a worker reads and adds memory, and forgets by adding a row; only the API
    deletes or restores, and it never writes a note. The memory turn and the person's
    page work with exactly these grants."""
    from agent_runtime.memory.store import Memory

    graphs = default_registry()
    marker = f"lp-{uuid.uuid4().hex[:8]}"
    run = await RunService(as_api, test_settings, graphs).create_run("assistant", {
        "message": "remember", "script": [
            {"tool_calls": [{"name": "save_note", "args": {"text": marker}}]},
            {"content": "ok"}]})  # fmt: skip
    done = await RunExecutor(as_worker, test_settings, graphs, owner="lp:2").execute(run.id)
    assert done.status is RunStatus.COMPLETED
    async with as_api.connection() as conn:
        (note,) = [n for n in await Memory(conn).of_agent("assistant") if n.text == marker]
        assert await Memory(conn).delete("assistant", note.id) is not None
    assert await denied(as_worker, "DELETE FROM notes")
    assert await denied(as_worker, "UPDATE notes SET text = 'x'")
    assert await denied(as_worker, "DELETE FROM note_forgets")
    assert await denied(as_api, "UPDATE notes SET text = 'x'")
    assert await denied(as_api, "INSERT INTO notes (key, run_id, text, epoch) "
                        "VALUES (repeat('a', 64), gen_random_uuid(), 'x', 0)")  # fmt: skip


@pytest.mark.parametrize(
    ("role", "allowed", "forbidden"),
    [
        (
            "app_sandboxd",
            "SELECT id, status, epoch FROM runs LIMIT 1",
            "SELECT input FROM runs LIMIT 1",
        ),
        ("app_ingest", "SELECT count(*) FROM documents", "SELECT count(*) FROM runs"),
    ],
)
def test_group_roles_without_users_yet(
    test_db_url: str, provisioned: None, role: str, allowed: str, forbidden: str
) -> None:
    with psycopg.connect(test_db_url.replace("postgresql+psycopg", "postgresql")) as conn:
        conn.execute(f"SET ROLE {role}")
        conn.execute(allowed)
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute(forbidden)


def test_services_refuse_to_start_without_their_own_user(
    test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WORKER_POSTGRES_USER", raising=False)
    with pytest.raises(ValueError, match="WORKER_POSTGRES_USER and WORKER_POSTGRES_PASSWORD"):
        test_settings.for_component("worker")

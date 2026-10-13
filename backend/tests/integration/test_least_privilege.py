"""SC10: each component connects as its own user and can do only its job (R14.13)."""

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


async def test_a_full_run_works_with_only_these_privileges(
    as_api: Pool, as_worker: Pool, test_settings: Settings
) -> None:
    """The grants are sufficient, not just restrictive: create as the API user,
    execute (checkpoints, events, fencing trigger, result) as the worker user."""
    graphs = default_registry()
    run = await RunService(as_api, test_settings, graphs).create_run("toy", {"question": "least"})
    done = await RunExecutor(as_worker, test_settings, graphs, owner="lp:1").execute(run.id)
    assert done.status is RunStatus.COMPLETED


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

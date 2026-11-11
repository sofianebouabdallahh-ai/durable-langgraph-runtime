"""Integration fixtures. Need Postgres running (`make up`).

Tests never touch the development database: each session creates a throwaway
`<POSTGRES_DB>_test` database, so `downgrade` in a test can't wipe your dev data.

Missing services skip the tests during ad-hoc runs, but FAIL them when
REQUIRE_SERVICES=1 (set by `make test` and CI): a stopped database must never
turn into a green build.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import sql
from pydantic import SecretStr
from redis.exceptions import ConnectionError as RedisConnectionError

from agent_runtime.config import Settings, get_settings
from agent_runtime.db import Pool, create_pool
from agent_runtime.devtools.fake_mcp import FakeMcp
from agent_runtime.devtools.fake_mcp import create_app as create_mcp_app
from agent_runtime.queue import RedisWorkQueue, create_redis
from agent_runtime.sandbox import tools as sandbox_tools
from tests.integration.local_sandbox import SANDBOX_TOKEN, LocalBackend, local_sandboxd

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"  # backend/alembic.ini


def _unavailable(reason: str) -> NoReturn:
    if os.environ.get("REQUIRE_SERVICES") == "1":
        pytest.fail(f"required service unavailable: {reason}")
    pytest.skip(reason)


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["database_url"] = database_url
    return cfg


@pytest.fixture(scope="session")
def settings() -> Settings:
    try:
        return get_settings()
    except Exception as exc:  # missing POSTGRES_PASSWORD etc.
        _unavailable(f"integration settings unavailable ({exc}); run via `make test`")


@pytest.fixture(scope="session")
def test_settings(settings: Settings) -> Settings:
    # Queued runs accumulate in the shared test database, so admission control (R2.9)
    # is effectively off; tests of it set their own limit.
    return settings.model_copy(
        update={
            "postgres_db": f"{settings.postgres_db}_test",
            "queue_depth_limit": 1_000_000,
            "nuria_secret_key": SecretStr("test-master-key-" + "x" * 32),
        }
    )


@pytest.fixture(scope="session")
def test_db_url(settings: Settings, test_settings: Settings) -> Iterator[str]:
    """Create a fresh test database for the session; drop it afterwards."""
    test_db = test_settings.postgres_db
    admin_url = settings.database_url(driver="postgresql")
    try:
        admin = psycopg.connect(admin_url, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        _unavailable(f"Postgres not reachable ({exc}); run `make up`")

    drop = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(test_db))
    with admin:
        admin.execute(drop)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_db)))

    yield test_settings.database_url()

    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(drop)


@pytest.fixture(scope="session")
def alembic_cfg(test_db_url: str) -> Config:
    return _alembic_config(test_db_url)


@pytest.fixture
def migrated_db(alembic_cfg: Config, test_db_url: str) -> Iterator[psycopg.Connection]:
    """Schema at head; each test runs in a transaction that is rolled back."""
    command.upgrade(alembic_cfg, "head")
    conn = psycopg.connect(test_db_url.replace("postgresql+psycopg", "postgresql"))
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture(scope="session")
async def pool(alembic_cfg: Config, test_settings: Settings) -> AsyncIterator[Pool]:
    """An open async pool on the migrated test database, shared by the session."""
    command.upgrade(alembic_cfg, "head")
    async with create_pool(test_settings, max_size=20) as p:
        yield p


@pytest.fixture(scope="session")
async def checkpoint_tables(pool: Pool) -> None:
    """LangGraph creates and migrates its own tables (idempotent)."""
    await AsyncPostgresSaver(pool).setup()


@pytest.fixture
async def no_memory(pool: Pool) -> None:
    """Start with no notes. Memory is in every prompt (H8), so a test that counts tokens
    or cost mustn't depend on the notes earlier tests saved."""
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM notes")


@pytest.fixture
async def queue(settings: Settings) -> AsyncIterator[RedisWorkQueue]:
    """A real Redis work queue on its own stream (db 15), deleted afterwards."""
    redis = create_redis(settings.redis_url.rsplit("/", 1)[0] + "/15")
    try:
        await redis.ping()
    except RedisConnectionError as exc:
        _unavailable(f"Redis not reachable ({exc}); run `make up`")
    q = RedisWorkQueue(redis, stream=f"test:{uuid.uuid4()}", group="workers")
    await q.ensure_group()
    try:
        yield q
    finally:
        await redis.delete(q.stream)
        await redis.aclose()


@pytest.fixture(scope="session")
async def sandboxd() -> AsyncIterator[tuple[str, LocalBackend]]:
    """The real sandboxd app on a free port, over a local backend (tests only)."""
    async with local_sandboxd() as served:
        yield served


@pytest.fixture
def sandbox(
    sandboxd: tuple[str, LocalBackend], test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Settings:
    """Run Python, the terminal and the workspace files work in this test's turns."""
    url, _ = sandboxd
    with_sandbox = test_settings.model_copy(
        update={"sandboxd_url": url, "sandboxd_token": SecretStr(SANDBOX_TOKEN)}
    )
    monkeypatch.setattr(sandbox_tools, "get_settings", lambda: with_sandbox)
    return with_sandbox


# ------------------------------------------------------------- MCP (phase L8)

MCP_TOKEN = "fixture-token-" + "q" * 20


@dataclass
class ServedMcp:
    url: str
    admin: str
    fake: FakeMcp


@pytest.fixture
async def served_mcp() -> AsyncIterator[ServedMcp]:
    """The fake MCP server (devtools), over real HTTP, in this process."""
    import socket

    import uvicorn

    app, fake = create_mcp_app(token=MCP_TOKEN)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 — uvicorn offers no "started" event
        await asyncio.sleep(0.05)
    try:
        yield ServedMcp(f"http://127.0.0.1:{port}/mcp/", f"http://127.0.0.1:{port}/admin", fake)
    finally:
        server.should_exit = True
        await task

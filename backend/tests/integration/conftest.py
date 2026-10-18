"""Integration fixtures. Need Postgres running (`make up`).

Tests never touch the development database: each session creates a throwaway
`<POSTGRES_DB>_test` database, so `downgrade` in a test can't wipe your dev data.

Missing services skip the tests during ad-hoc runs, but FAIL them when
REQUIRE_SERVICES=1 (set by `make test` and CI): a stopped database must never
turn into a green build.
"""

import os
import uuid
from collections.abc import AsyncIterator, Iterator
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
from agent_runtime.queue import RedisWorkQueue, create_redis

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

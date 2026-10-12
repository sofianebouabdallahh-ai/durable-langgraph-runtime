"""Integration fixtures. Need Postgres running (`make up`).

Tests never touch the development database: each session creates a throwaway
`<POSTGRES_DB>_test` database, so `downgrade` in a test can't wipe your dev data.
"""

from collections.abc import Iterator

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

from runtime.config import Settings, get_settings


def _alembic_config(database_url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.attributes["database_url"] = database_url
    return cfg


@pytest.fixture(scope="session")
def settings() -> Settings:
    try:
        return get_settings()
    except Exception as exc:  # missing POSTGRES_PASSWORD etc.
        pytest.skip(f"integration settings unavailable ({exc}); run via `make test`")


@pytest.fixture(scope="session")
def test_db_url(settings: Settings) -> Iterator[str]:
    """Create a fresh test database for the session; drop it afterwards."""
    test_db = f"{settings.postgres_db}_test"
    admin_url = settings.database_url(driver="postgresql")
    try:
        admin = psycopg.connect(admin_url, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not reachable ({exc}); run `make up`")

    with admin:
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(test_db))
        )
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_db)))

    yield settings.model_copy(update={"postgres_db": test_db}).database_url()

    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(test_db))
        )


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

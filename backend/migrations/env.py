"""Alembic environment: connects using runtime settings and runs migrations online.

We write migrations by hand as explicit SQL (no autogenerate), so there is no
SQLAlchemy model metadata to compare against.
"""

from alembic import context
from sqlalchemy import create_engine, pool

from agent_runtime.config import get_settings


def run_migrations() -> None:
    url = context.config.attributes.get("database_url") or get_settings().database_url()
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("offline (SQL script) mode is not supported; run against a database")
run_migrations()

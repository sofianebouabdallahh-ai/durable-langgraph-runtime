"""Database administration run by the *migrator* (never by api/worker).

- `grant_checkpoint_tables`: LangGraph creates its own tables in `setup()`;
  grant them to app_worker explicitly (only the worker reads/writes checkpoints).
- `provision_users`: create or update one login user per component, member of
  its group role (migration 0005), from credentials in the environment. This is
  infrastructure's job, so passwords never live in migration files.
"""

from __future__ import annotations

import logging

from psycopg import sql

from agent_runtime.config import DbCredentials, component_credentials
from agent_runtime.db import Conn

log = logging.getLogger(__name__)

CHECKPOINT_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
COMPONENT_ROLES = {
    "api": "app_api",
    "worker": "app_worker",
    "ingest": "app_ingest",
    "sandboxd": "app_sandboxd",
}


async def grant_checkpoint_tables(conn: Conn) -> None:
    for table in CHECKPOINT_TABLES:
        await conn.execute(
            sql.SQL("GRANT SELECT, INSERT, UPDATE ON {} TO app_worker").format(
                sql.Identifier(table)
            )
        )


async def provision_users(conn: Conn) -> list[str]:
    """Idempotent. Returns the components provisioned; skips unconfigured ones."""
    done: list[str] = []
    for component, role in COMPONENT_ROLES.items():
        creds = component_credentials(component)
        if creds is None:
            continue
        await _upsert_login(conn, creds, role)
        done.append(component)
    return done


async def _upsert_login(conn: Conn, creds: DbCredentials, role: str) -> None:
    user = sql.Identifier(creds.user)
    # Utility statements can't take bind parameters; sql.Literal quotes safely.
    password = sql.Literal(creds.password.get_secret_value())
    cur = await conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (creds.user,))
    verb = "ALTER" if await cur.fetchone() else "CREATE"
    await conn.execute(
        sql.SQL("{} ROLE {} LOGIN PASSWORD {}").format(sql.SQL(verb), user, password)
    )
    await conn.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(role), user))
    log.info("provisioned database user %s (role %s)", creds.user, role)

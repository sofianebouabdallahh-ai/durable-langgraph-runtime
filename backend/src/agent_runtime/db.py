"""Postgres connection pool.

One pool per process, shared by our own queries and LangGraph's checkpointer.
Connections are autocommit: LangGraph's setup needs it (CREATE INDEX
CONCURRENTLY can't run in a transaction), and our code always opens explicit
transactions (`async with conn.transaction()`) wherever atomicity matters, so
nothing is ever left half-committed by accident.

Each connection is checked as it leaves the pool (H4): after Postgres restarts, the
idle connections are dead, and the next `pool.connection()` must get a live one
instead of failing the next query.
"""

from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from agent_runtime.config import Settings

Pool = AsyncConnectionPool[AsyncConnection[DictRow]]
Conn = AsyncConnection[DictRow]


def create_pool(settings: Settings, *, min_size: int = 1, max_size: int = 10) -> Pool:
    """A closed pool; open it with `await pool.open()` or `async with pool:`."""
    return AsyncConnectionPool(
        conninfo=settings.database_url(driver="postgresql"),
        connection_class=AsyncConnection[DictRow],
        kwargs={
            "autocommit": True,
            # Server-side prepared statements break behind transaction-mode
            # poolers (PgBouncer); LangGraph recommends disabling them.
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
        min_size=min_size,
        max_size=max_size,
        check=AsyncConnectionPool.check_connection,  # an empty round trip; reconnects
        open=False,
    )

"""MCP servers people add, and the tools they switch on (phase L8).

    add · change · remove           a server: its address and (sealed) token
    test                            asks the server for its tools: each is scanned and its
                                    latest definition recorded; new ones start switched off
    set_tool(enabled, …)            switching a tool on approves its definition (pinned by
                                    digest); "runs without asking" only for a read-only one
    approve_change                  a changed tool, looked at again: the new definition

A tool whose server now offers a different definition than the approved one is
**changed**: agents can't use it until someone approves the change (rug-pull protection).
Every change is audited in its transaction. Tokens are sealed like model keys and opened
only in memory, for one call (`endpoint`).

Patterns: Repository (`McpStore`) + Service; tool names are namespaced by server
(`mcp__<server>__<tool>`), so one server's tool can't pass for another's.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from agent_runtime.audit import AuditLog, key_change
from agent_runtime.config import Settings
from agent_runtime.db import Conn, Pool
from agent_runtime.ids import new_id
from agent_runtime.keys import Sealed, fingerprint, open_secret, seal, secret_aad
from agent_runtime.mcp.client import Endpoint, McpUnavailable, ToolDefinition, check_url, list_tools
from agent_runtime.models.connections import WORKSPACE, kek_for
from agent_runtime.skills.scan import scan_texts

PREFIX = "mcp"
MAX_NAME = 64  # what model APIs accept for a tool's name


class McpInvalid(ValueError):
    pass


class McpNotFound(LookupError):
    pass


def tool_name(server: str, tool: str) -> str:
    """The name an agent knows a server's tool by: namespaced, model-API safe."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", tool)
    return f"{PREFIX}__{server}__{safe}"[:MAX_NAME]


def split_name(name: str) -> tuple[str, str] | None:
    """`mcp__docs__search` → ("docs", "search"); None for a built-in tool."""
    parts = name.split("__", 2)
    return (parts[1], parts[2]) if len(parts) == 3 and parts[0] == PREFIX else None


@dataclass(frozen=True, slots=True)
class McpTool:
    server_id: uuid.UUID
    name: str  # as the server names it
    definition: ToolDefinition | None  # approved (None: never switched on)
    digest: str | None
    latest: ToolDefinition  # as the server last offered it
    latest_digest: str
    enabled: bool
    without_asking: bool
    scan: dict[str, Any]
    seen_at: datetime

    @property
    def changed(self) -> bool:
        return self.digest is not None and self.digest != self.latest_digest

    @property
    def usable(self) -> bool:
        return self.enabled and not self.changed


@dataclass(frozen=True, slots=True)
class McpServer:
    id: uuid.UUID
    name: str
    display_name: str
    url: str
    header_name: str
    sealed: Sealed | None
    key_fingerprint: str | None
    status: str
    status_detail: str | None
    protocol_version: str | None
    tested_at: datetime | None
    archived_at: datetime | None

    @property
    def has_token(self) -> bool:
        return self.sealed is not None

    @classmethod
    def of(cls, row: dict[str, Any]) -> McpServer:
        sealed = None
        if row["key_ciphertext"] is not None:
            sealed = Sealed(row["key_ciphertext"], row["key_nonce"], row["wrapped_key"],
                            row["wrapped_nonce"], row["kek_version"])  # fmt: skip
        return cls(row["id"], row["name"], row["display_name"], row["url"], row["header_name"],
                   sealed, row["key_fingerprint"], row["status"], row["status_detail"],
                   row["protocol_version"], row["tested_at"], row["archived_at"])  # fmt: skip


def _tool(row: dict[str, Any]) -> McpTool:
    return McpTool(
        row["server_id"], row["name"],
        ToolDefinition.of(row["definition"]) if row["definition"] else None, row["digest"],
        ToolDefinition.of(row["latest"]), row["latest_digest"], row["enabled"],
        row["without_asking"], row["scan"], row["seen_at"],
    )  # fmt: skip


class McpStore:
    def __init__(self, conn: Conn) -> None:
        self._conn = conn

    async def servers(self, *, archived: bool = False) -> list[McpServer]:
        cur = await self._conn.execute(
            "SELECT * FROM mcp_servers WHERE workspace_id = %s AND (archived_at IS NULL) = %s "
            "ORDER BY created_at", (WORKSPACE, not archived),
        )  # fmt: skip
        return [McpServer.of(r) for r in await cur.fetchall()]

    async def server(self, sid: uuid.UUID) -> McpServer:
        cur = await self._conn.execute("SELECT * FROM mcp_servers WHERE id = %s", (sid,))
        row = await cur.fetchone()
        if row is None:
            raise McpNotFound(f"no MCP server {sid}")
        return McpServer.of(row)

    async def by_name(self, name: str) -> McpServer | None:
        cur = await self._conn.execute(
            "SELECT * FROM mcp_servers WHERE workspace_id = %s AND name = %s", (WORKSPACE, name)
        )
        row = await cur.fetchone()
        return McpServer.of(row) if row else None

    async def tools(self, sid: uuid.UUID | None = None) -> list[McpTool]:
        cur = await self._conn.execute(
            "SELECT t.* FROM mcp_tools t JOIN mcp_servers s ON s.id = t.server_id "
            "WHERE s.workspace_id = %s AND s.archived_at IS NULL "
            "AND (%s::uuid IS NULL OR t.server_id = %s) ORDER BY t.name",
            (WORKSPACE, sid, sid),
        )  # fmt: skip
        return [_tool(r) for r in await cur.fetchall()]

    async def tool(self, sid: uuid.UUID, name: str) -> McpTool:
        cur = await self._conn.execute(
            "SELECT * FROM mcp_tools WHERE server_id = %s AND name = %s", (sid, name)
        )
        row = await cur.fetchone()
        if row is None:
            raise McpNotFound(f"no tool {name!r} on this server")
        return _tool(row)

    async def insert(self, server: dict[str, Any]) -> McpServer:
        columns = ", ".join(server)
        cur = await self._conn.execute(
            f"INSERT INTO mcp_servers (workspace_id, {columns}) "
            f"VALUES (%s, {', '.join(['%s'] * len(server))}) RETURNING *",
            (WORKSPACE, *server.values()),
        )
        row = await cur.fetchone()
        assert row is not None
        return McpServer.of(row)

    async def update(self, sid: uuid.UUID, **changes: Any) -> McpServer:
        sets = ", ".join(f"{c} = %s" for c in changes)
        cur = await self._conn.execute(
            f"UPDATE mcp_servers SET {sets}, updated_at = now() WHERE id = %s RETURNING *",
            (*changes.values(), sid),
        )
        row = await cur.fetchone()
        if row is None:
            raise McpNotFound(f"no MCP server {sid}")
        return McpServer.of(row)

    async def offered(self, sid: uuid.UUID, latest: ToolDefinition, scan: dict[str, Any]) -> None:
        """What the server offers now; an approved definition is kept as it was."""
        await self._conn.execute(
            """
            INSERT INTO mcp_tools (server_id, name, latest, latest_digest, scan)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (server_id, name) DO UPDATE SET latest = EXCLUDED.latest,
                latest_digest = EXCLUDED.latest_digest, scan = EXCLUDED.scan, seen_at = now(),
                updated_at = now()
            """,
            (sid, latest.name, Jsonb(latest.as_json()), latest.digest, Jsonb(scan)),
        )  # fmt: skip

    async def set_tool(self, sid: uuid.UUID, name: str, **changes: Any) -> McpTool:
        sets = ", ".join(f"{c} = %s" for c in changes)
        values = [Jsonb(v) if isinstance(v, dict) else v for v in changes.values()]
        cur = await self._conn.execute(
            f"UPDATE mcp_tools SET {sets}, updated_at = now() "
            "WHERE server_id = %s AND name = %s RETURNING *",
            (*values, sid, name),
        )
        row = await cur.fetchone()
        if row is None:
            raise McpNotFound(f"no tool {name!r} on this server")
        return _tool(row)


def _aad(server_id: uuid.UUID) -> str:
    return secret_aad(WORKSPACE, str(server_id), "mcp-token")


def _audited(s: McpServer) -> dict[str, Any]:
    """A server as the audit trail shows it: never the token, only that one is set."""
    return {"display_name": s.display_name, "url": s.url, "header": s.header_name,
            **key_change(s.key_fingerprint)}  # fmt: skip


def scan_definition(d: ToolDefinition) -> dict[str, Any]:
    """The skill scanner's text checks, on everything the model will read of a tool."""
    report = scan_texts([("description", d.description),
                         ("arguments", str(d.input_schema))])  # fmt: skip
    return report.as_json()


class McpService:
    def __init__(self, pool: Pool, settings: Settings) -> None:
        self._pool = pool
        self._settings = settings

    # ---------------------------------------------------------------- servers

    async def servers(self) -> list[tuple[McpServer, list[McpTool]]]:
        async with self._pool.connection() as conn:
            store = McpStore(conn)
            servers = await store.servers()
            tools = await store.tools()
        return [(s, [t for t in tools if t.server_id == s.id]) for s in servers]

    async def server(self, sid: uuid.UUID) -> tuple[McpServer, list[McpTool]]:
        async with self._pool.connection() as conn:
            store = McpStore(conn)
            return await store.server(sid), await store.tools(sid)

    async def add(self, *, display_name: str, url: str, token: str | None = None,
                  header_name: str = "Authorization") -> McpServer:  # fmt: skip
        try:
            url = check_url(url)
        except McpUnavailable as exc:
            raise McpInvalid(str(exc)) from exc
        sid = new_id()
        row: dict[str, Any] = {
            "id": sid,
            "display_name": display_name.strip()[:60],
            "url": url,
            "header_name": header_name or "Authorization",
        }
        row |= self._sealed(sid, token)
        async with self._pool.connection() as conn, conn.transaction():
            store = McpStore(conn)
            row["name"] = await self._free_name(store, display_name)
            added = await store.insert(row)
            await AuditLog(conn).record("mcp_server.added", "mcp_server", added.name,
                                        after=_audited(added))  # fmt: skip
        return added

    async def change(self, sid: uuid.UUID, *, display_name: str | None = None,
                     url: str | None = None, token: str | None = None,
                     header_name: str | None = None) -> McpServer:  # fmt: skip
        """A new address or token needs a new test. A token isn't removed by leaving it out."""
        changes: dict[str, Any] = {}
        if display_name is not None:
            changes["display_name"] = display_name.strip()[:60]
        if url is not None:
            try:
                changes["url"] = check_url(url)
            except McpUnavailable as exc:
                raise McpInvalid(str(exc)) from exc
        if header_name is not None:
            changes["header_name"] = header_name or "Authorization"
        if token:
            changes |= self._sealed(sid, token)
        if {"url", "key_ciphertext"} & set(changes):
            changes |= {"status": "untested", "status_detail": None}
        async with self._pool.connection() as conn, conn.transaction():
            store = McpStore(conn)
            before = await store.server(sid)
            if not changes:
                return before
            after = await store.update(sid, **changes)
            await AuditLog(conn).record("mcp_server.changed", "mcp_server", after.name,
                                        before=_audited(before), after=_audited(after))  # fmt: skip
        return after

    async def remove(self, sid: uuid.UUID) -> None:
        """Out of the list; its tools stop working for every agent."""
        async with self._pool.connection() as conn, conn.transaction():
            store = McpStore(conn)
            gone = await store.update(sid, archived_at=datetime.now().astimezone())
            await conn.execute("UPDATE mcp_tools SET enabled = false WHERE server_id = %s", (sid,))
            await AuditLog(conn).record("mcp_server.removed", "mcp_server", gone.name,
                                        before=_audited(gone))  # fmt: skip

    async def test(self, sid: uuid.UUID) -> tuple[McpServer, list[McpTool]]:
        """Ask the server for its tools: record each one's latest definition and scan."""
        async with self._pool.connection() as conn:
            server = await McpStore(conn).server(sid)
        try:
            offered, protocol = await list_tools(
                self.endpoint(server), self._settings.mcp_timeout_s
            )
            status, detail = "ready", f"{len(offered)} tools"
        except McpUnavailable as exc:
            offered, protocol, status, detail = [], None, "failed", str(exc)
        async with self._pool.connection() as conn, conn.transaction():
            store = McpStore(conn)
            for d in offered:
                await store.offered(sid, d, scan_definition(d))
            await store.update(
                sid,
                status=status,
                status_detail=detail[:500],
                protocol_version=protocol,
                tested_at=datetime.now().astimezone(),
            )
        return await self.server(sid)

    # ------------------------------------------------------------------ tools

    async def set_tool(self, sid: uuid.UUID, name: str, *, enabled: bool,
                       without_asking: bool = False) -> McpTool:  # fmt: skip
        """On: the definition the server offers now is the approved one. "Runs without
        asking" only for a tool its server says is read-only, and only if you choose it."""
        async with self._pool.connection() as conn, conn.transaction():
            store = McpStore(conn)
            server = await store.server(sid)
            tool = await store.tool(sid, name)
            if without_asking and not tool.latest.read_only:
                raise McpInvalid("Only a read-only tool can run without asking")
            if tool.scan.get("status") == "blocked" and enabled:
                raise McpInvalid("This tool's description was blocked by the check")
            changes: dict[str, Any] = {"enabled": enabled,
                                       "without_asking": enabled and without_asking}  # fmt: skip
            if enabled:
                changes |= {"definition": tool.latest.as_json(), "digest": tool.latest_digest}
            updated = await store.set_tool(sid, name, **changes)
            await AuditLog(conn).record(
                "mcp_tool.enabled" if enabled else "mcp_tool.disabled", "mcp_tool",
                tool_name(server.name, name),
                after={"without_asking": updated.without_asking, "digest": updated.digest},
            )  # fmt: skip
        return updated

    async def approve_change(self, sid: uuid.UUID, name: str) -> McpTool:
        """The server changed this tool and someone looked: its new definition is approved."""
        async with self._pool.connection() as conn, conn.transaction():
            store = McpStore(conn)
            server = await store.server(sid)
            tool = await store.tool(sid, name)
            if tool.scan.get("status") == "blocked":
                raise McpInvalid("This tool's new description was blocked by the check")
            without = tool.without_asking and tool.latest.read_only
            updated = await store.set_tool(
                sid,
                name,
                definition=tool.latest.as_json(),
                digest=tool.latest_digest,
                without_asking=without,
            )
            await AuditLog(conn).record(
                "mcp_tool.approved_change", "mcp_tool", tool_name(server.name, name),
                before={"digest": tool.digest}, after={"digest": updated.digest},
            )  # fmt: skip
        return updated

    # --------------------------------------------------------------- internals

    def endpoint(self, server: McpServer) -> Endpoint:
        """Where to call, with the token opened in memory for this call only."""
        if server.sealed is None:
            return Endpoint(server.url)
        token = open_secret(server.sealed, _aad(server.id), kek_for(self._settings))
        if server.header_name.lower() == "authorization" and " " not in token:
            token = f"Bearer {token}"
        return Endpoint(server.url, {server.header_name: token})

    def _sealed(self, sid: uuid.UUID, token: str | None) -> dict[str, Any]:
        token = (token or "").strip()
        if not token:
            return {}
        kek = kek_for(self._settings)
        s = seal(token, _aad(sid), kek)
        return {"key_ciphertext": s.ciphertext, "key_nonce": s.nonce, "wrapped_key": s.wrapped_key,
                "wrapped_nonce": s.wrapped_nonce, "kek_version": s.kek_version,
                "key_fingerprint": fingerprint(token, kek)}  # fmt: skip

    async def _free_name(self, store: McpStore, display_name: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "_", display_name.lower()).strip("_")[:24].strip("_")
        if not base or not base[0].isalpha():
            base = f"server_{base}" if base else "server"
        for n in range(1, 100):
            name = base if n == 1 else f"{base}_{n}"
            if await store.by_name(name) is None:
                return name
        raise McpInvalid("too many servers with this name")

"""MCP tools in agents (phase L8): locked, then run through the ToolPipeline.

    usable(conn)            the switched-on, unchanged tools, as agents name them
    lock(usable, granted)   what a bundle pins: each granted tool's approved definition
    specs(lock)             a ToolSpec per locked tool, for the run's registry
    call                    one call: still switched on? the server still offers exactly
                            the locked definition? then the request; is_error → a failure

Risk class: `read` when a person chose "runs without asking" (only offered for a tool
its server marks read-only), else `external_side_effect`, so the policy asks first
(R14.10). A call cut off by a crash isn't sent again unless the tool runs without
asking: the pipeline answers that it may have run once (`retry_after_crash`). Every call
carries its idempotency key in `_meta["io.nuria/idempotency-key"]` (H7), so a server can
do it once.

The definition a call checks against is the **locked** one: a published agent keeps
what was approved when it was published, and a server that changed the tool since gets
no call until someone approves the change and publishes again (rug-pull protection).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ConfigDict

from agent_runtime.config import get_settings
from agent_runtime.db import Conn
from agent_runtime.mcp.client import McpUnavailable, ToolDefinition, call_tool, list_tools
from agent_runtime.mcp.service import McpService, McpStore, split_name, tool_name
from agent_runtime.tools.spec import RiskClass, ToolArgs, ToolContext, ToolRegistry, ToolSpec

LIVE_CHECK_S = 60.0  # how long a server's offered definitions are trusted before asking again


class McpArgs(ToolArgs):
    """Any arguments: an MCP tool's are checked against its JSON Schema instead."""

    model_config = ConfigDict(extra="allow", strict=False, frozen=True)


class McpToolError(Exception):
    """The server ran the tool and reported an error (is_error)."""


@dataclass(frozen=True, slots=True)
class Locked:
    name: str  # as agents know it: mcp__<server>__<tool>
    server_id: uuid.UUID
    tool: str  # as the server names it
    definition: ToolDefinition
    without_asking: bool

    @property
    def risk(self) -> RiskClass:
        return "read" if self.without_asking else "external_side_effect"

    def as_json(self) -> dict[str, Any]:
        return {"server_id": str(self.server_id), "tool": self.tool,
                "definition": self.definition.as_json(),
                "without_asking": self.without_asking}  # fmt: skip

    @classmethod
    def of(cls, name: str, data: Mapping[str, Any]) -> Locked:
        return cls(name, uuid.UUID(str(data["server_id"])), str(data["tool"]),
                   ToolDefinition.of(data["definition"]), bool(data["without_asking"]))  # fmt: skip


async def usable(conn: Conn) -> dict[str, Locked]:
    """Every tool people switched on whose server hasn't changed it, by agent name."""
    store = McpStore(conn)
    servers = {s.id: s for s in await store.servers()}
    out: dict[str, Locked] = {}
    for t in await store.tools():
        if t.usable and t.definition is not None and (s := servers.get(t.server_id)):
            name = tool_name(s.name, t.name)
            out[name] = Locked(name, s.id, t.name, t.definition, t.without_asking)
    return out


def granted(agent: Any) -> set[str]:
    """The MCP tools an agent and its helpers are given."""
    names = {g.name for g in agent.frontmatter.tools}
    for sub in getattr(agent, "subagents", ()):
        names |= {g.name for g in sub.frontmatter.tools}
    return {n for n in names if split_name(n) is not None}


def lock(available: Mapping[str, Locked], names: Iterable[str]) -> dict[str, dict[str, Any]]:
    """What a bundle pins: the granted tools that exist, with their approved definitions."""
    return {n: available[n].as_json() for n in sorted(names) if n in available}


def unlock(locked: Mapping[str, Any] | None) -> dict[str, Locked]:
    return {n: Locked.of(n, d) for n, d in (locked or {}).items()}


def risks(available: Mapping[str, Locked]) -> dict[str, RiskClass]:
    """For the validator's catalog: an MCP tool is known by its name and risk class."""
    return {n: t.risk for n, t in available.items()}


# ------------------------------------------------------------------ calling

_offered: dict[uuid.UUID, tuple[float, dict[str, str]]] = {}  # server → (when, tool → digest)


async def _live_digest(service: McpService, conn: Conn, t: Locked, timeout_s: float) -> str | None:
    """What the server offers for this tool now (asked at most once a minute)."""
    seen = _offered.get(t.server_id)
    if seen is None or time.monotonic() - seen[0] > LIVE_CHECK_S:
        server = await McpStore(conn).server(t.server_id)
        offered, _ = await list_tools(service.endpoint(server), timeout_s)
        seen = (time.monotonic(), {d.name: d.digest for d in offered})
        _offered[t.server_id] = seen
    return seen[1].get(t.tool)


def _caller(t: Locked) -> Any:
    async def call(args: Any, ctx: ToolContext) -> Any:
        settings = ctx.settings or get_settings()  # the run's (its master key opens tokens)
        service = McpService(ctx.pool, settings)
        async with ctx.pool.connection() as conn:
            server = await McpStore(conn).server(t.server_id)
            current = await McpStore(conn).tool(t.server_id, t.tool)
            if server.archived_at is not None or not current.enabled:
                raise McpUnavailable("This tool was switched off in Settings → Tools")
            if await _live_digest(service, conn, t, settings.mcp_timeout_s) != t.definition.digest:
                raise McpUnavailable(
                    "This tool changed on its server since it was approved: review it in "
                    "Settings → Tools, then test and publish the agent again"
                )
        arguments = dict(args) if isinstance(args, Mapping) else args.model_dump()
        result = await call_tool(service.endpoint(server), t.tool, arguments,
                                 settings.mcp_timeout_s, idempotency_key=ctx.key)  # fmt: skip
        if result.is_error:
            raise McpToolError(result.text[:2000] or "the tool reported an error")
        return result.as_json()

    return call


def spec_of(t: Locked) -> ToolSpec:
    return ToolSpec(
        name=t.name,
        description=t.definition.description or f"{t.tool} (an MCP tool)",
        args_model=McpArgs,
        input_schema=dict(t.definition.input_schema),
        fn=_caller(t),
        risk_class=t.risk,
        side_effect=not t.without_asking,
        cache=True,  # a finished call is replayed from the record, never sent again
        retry_after_crash=t.without_asking,
        timeout_s=get_settings().mcp_timeout_s + 5,
    )


def registry_with(base: ToolRegistry, locked: Mapping[str, Locked]) -> ToolRegistry:
    """The built-in tools plus a run's locked MCP tools (a registry per bundle)."""
    return base.with_tools([spec_of(t) for t in locked.values()]) if locked else base

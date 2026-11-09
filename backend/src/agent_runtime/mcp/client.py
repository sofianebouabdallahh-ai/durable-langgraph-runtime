"""Talking to a remote MCP server (phase L8). The only module that uses the `mcp` SDK.

    list_tools(endpoint)               → the server's tools, as ToolDefinitions
    call_tool(endpoint, name, args)    → McpResult (text, structured content, is_error)

Pattern: Adapter. The rest of the runtime sees plain dataclasses and one error type,
`McpUnavailable`, with a message a person can act on, never the SDK's types or its
nested exception groups. Each call is stateless (the 2026-07-28 protocol; older servers
are handled by the SDK's fallback): connect, one request, close.

A definition's digest is the sha256 of its canonical JSON (name, description, schemas,
hints): what a person approves, and what a call checks the server still offers.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx2
from mcp import Client, MCPError
from mcp.client.streamable_http import streamable_http_client

from agent_runtime.net import DestinationRefused, Guard

USER_AGENT = "Nuria (MCP client)"
MAX_RESULT_CHARS = 200_000  # what we keep of a result; the pipeline truncates further
# The stack's own services, by their Compose and Kubernetes names: never an MCP server.
# The tool hints MCP defines, and the SDK's attribute for each.
HINTS = (
    ("readOnlyHint", "read_only_hint"), ("destructiveHint", "destructive_hint"),
    ("idempotentHint", "idempotent_hint"), ("openWorldHint", "open_world_hint"),
)  # fmt: skip


class McpUnavailable(Exception):
    """The server couldn't be used: the message says why, in plain words."""


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any] | None = None
    hints: Mapping[str, bool] = field(default_factory=dict)  # readOnlyHint, …: untrusted

    def as_json(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "input_schema": dict(self.input_schema),
                "output_schema": dict(self.output_schema) if self.output_schema else None,
                "hints": dict(self.hints)}  # fmt: skip

    @classmethod
    def of(cls, data: Mapping[str, Any]) -> ToolDefinition:
        return cls(data["name"], data["description"], data["input_schema"],
                   data.get("output_schema"), data.get("hints") or {})  # fmt: skip

    @property
    def digest(self) -> str:
        canonical = json.dumps(self.as_json(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    @property
    def read_only(self) -> bool:
        """What the server says. Never trusted for safety: it only decides whether a
        person may choose "runs without asking"."""
        return bool(self.hints.get("readOnlyHint")) and not self.hints.get("destructiveHint")


@dataclass(frozen=True, slots=True)
class McpResult:
    text: str
    structured: Any = None
    is_error: bool = False

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"text": self.text}
        if self.structured is not None:
            out["structured"] = self.structured
        return out


@dataclass(frozen=True, slots=True)
class Endpoint:
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)  # e.g. the token: never logged
    guard: Guard = field(default_factory=Guard)  # where it may be (checked on every call)


async def check_url(url: str, guard: Guard | None = None) -> str:
    """A URL an MCP server may be at (phase H3, `net.check_destination`): resolved, and
    never cloud metadata or the stack's own services. This machine and your network are
    allowed (a local server is common)."""
    try:
        return await (guard or Guard()).check(url)
    except DestinationRefused as exc:
        raise McpUnavailable(str(exc)) from exc


def _definition(tool: Any) -> ToolDefinition:
    hints: dict[str, bool] = {}
    if tool.annotations is not None:
        for key, attr in HINTS:
            value = getattr(tool.annotations, attr, None)
            if value is not None:
                hints[key] = bool(value)
    return ToolDefinition(
        name=tool.name, description=(tool.description or "").strip(),
        input_schema=tool.input_schema or {"type": "object"},
        output_schema=getattr(tool, "output_schema", None), hints=hints,
    )  # fmt: skip


def _result(result: Any) -> McpResult:
    texts: list[str] = []
    for block in result.content or []:
        kind = getattr(block, "type", "")
        if kind == "text":
            texts.append(block.text)
        elif kind == "resource_link":
            texts.append(f"[link: {getattr(block, 'name', '')} {getattr(block, 'uri', '')}]")
        else:
            texts.append(f"[{kind or 'content'} not shown]")  # images, audio: not for now
    text = "\n".join(texts)[:MAX_RESULT_CHARS]
    return McpResult(text, getattr(result, "structured_content", None), bool(result.is_error))


def _plain(exc: BaseException, status: int | None = None) -> str:
    """The first real cause, out of the SDK's exception groups, in plain words. `status`:
    the last HTTP status the server answered (the SDK doesn't keep it in its errors)."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    if isinstance(exc, httpx2.HTTPStatusError):
        status = exc.response.status_code
    if status is not None and status >= 400:
        code = status
        if code in (401, 403):
            return "The server refused the token (check it, or whether this server needs one)"
        if code == 404:
            return "Nothing answers at this address: check the path (often /mcp)"
        return f"The server answered HTTP {code}"
    if isinstance(exc, httpx2.TimeoutException | TimeoutError):
        return "The server didn't answer in time"
    if isinstance(exc, httpx2.ConnectError):
        return "Couldn't connect: is the server running, and is the address right?"
    if isinstance(exc, MCPError):
        return f"The server reported an error: {exc}"[:300]
    return f"{type(exc).__name__}: {exc}"[:300]


@asynccontextmanager
async def _connected(endpoint: Endpoint, timeout_s: float) -> AsyncIterator[Client]:
    """A client for one exchange; the SDK's errors become McpUnavailable."""
    url = await check_url(endpoint.url, endpoint.guard)
    statuses: list[int] = []

    async def seen(response: httpx2.Response) -> None:
        statuses.append(response.status_code)

    try:
        async with (
            httpx2.AsyncClient(
                headers={"User-Agent": USER_AGENT, **endpoint.headers},
                timeout=timeout_s, follow_redirects=False,  # a redirect elsewhere is refused
                event_hooks={"response": [seen]},
            ) as http,
            Client(streamable_http_client(url, http_client=http),
                   read_timeout_seconds=timeout_s) as client,
        ):  # fmt: skip
            yield client
    except McpUnavailable:
        raise
    except Exception as exc:  # groups of real errors; cancellation is a BaseException
        raise McpUnavailable(_plain(exc, statuses[-1] if statuses else None)) from exc


async def list_tools(
    endpoint: Endpoint, timeout_s: float = 30.0
) -> tuple[list[ToolDefinition], str | None]:
    """The server's tools (every page), and the protocol version it speaks."""
    async with _connected(endpoint, timeout_s) as client:
        tools: list[ToolDefinition] = []
        cursor: str | None = None
        while True:
            page = await client.list_tools(cursor=cursor, cache_mode="bypass")
            tools += [_definition(t) for t in page.tools]
            cursor = page.next_cursor
            if not cursor:
                return tools, client.protocol_version


async def call_tool(
    endpoint: Endpoint, name: str, arguments: Mapping[str, Any], timeout_s: float = 60.0
) -> McpResult:
    async with _connected(endpoint, timeout_s) as client:
        return _result(await client.call_tool(name, dict(arguments)))

"""The web tools agents use (phase L6a): `web_search`, `read_webpage`.

Through the full ToolPipeline like every tool: grants, budgets, idempotency (a repeated
search in a run is served from the ledger), and their results are marked as untrusted
data before a model sees them (R14.15).

Pages are read by the `fetcher` service when one is configured (the only service tools
reach the web through: on Kubernetes, the only one with internet egress); otherwise
in-process, with the same guard.
"""

from __future__ import annotations

from typing import Annotated, Any

import httpx
from pydantic import Field

from agent_runtime.config import get_settings
from agent_runtime.db import Pool
from agent_runtime.tools.spec import ToolArgs, ToolContext, ToolRegistry
from agent_runtime.web.fetch import FetchRefused, fetch
from agent_runtime.web.search import SearchUnavailable
from agent_runtime.web.settings import ToolSettings

WEB_TOOLS = ("web_search", "read_webpage")
_services: dict[int, ToolSettings] = {}


class WebToolError(Exception):
    """A plain-words reason the model can act on (the pipeline returns it as an error)."""


class SearchArgs(ToolArgs):
    query: Annotated[str, Field(min_length=1, max_length=400, description="What to search for")]
    k: Annotated[int, Field(ge=1, le=10, description="How many results")] = 5


class ReadArgs(ToolArgs):
    url: Annotated[
        str,
        Field(
            min_length=8,
            max_length=2000,
            description="A full http(s) address, e.g. from web_search",
        ),
    ]


def _settings_service(pool: Pool) -> ToolSettings:
    service = _services.get(id(pool))
    if service is None:
        service = _services[id(pool)] = ToolSettings(pool, get_settings())
    return service


async def web_search(args: SearchArgs, ctx: ToolContext) -> dict[str, Any]:
    """Search the web. Returns titles, addresses and snippets: read a page with
    read_webpage before relying on it, and cite the addresses you use."""
    try:
        provider = await _settings_service(ctx.pool).provider()
        hits = await provider.search(args.query, args.k)
    except SearchUnavailable as exc:
        raise WebToolError(f"Search isn't available: {exc}.") from exc
    return {"query": args.query, "results": [h.as_json() for h in hits], "source": provider.name}


async def read_webpage(args: ReadArgs, ctx: ToolContext) -> dict[str, Any]:
    """Read a web page (or a PDF) as text: its title and main content."""
    settings = get_settings()
    allowlist = await _settings_service(ctx.pool).allowlist()
    if settings.fetcher_url:
        return await _via_fetcher(settings.fetcher_url, args.url, allowlist)
    allow = [h.strip() for h in settings.fetch_allow_hosts.split(",")]
    try:
        page = await fetch(args.url, allowlist=allowlist, allow_hosts=allow)
    except FetchRefused as exc:
        raise WebToolError(f"Couldn't read {args.url}: {exc}.") from exc
    return page.as_json()


async def _via_fetcher(base: str, url: str, allowlist: list[str]) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=45.0, trust_env=False) as client:
            response = await client.post(
                base.rstrip("/") + "/fetch", json={"url": url, "allowlist": allowlist}
            )
    except httpx.HTTPError as exc:
        raise WebToolError("The page reader isn't reachable right now.") from exc
    body: dict[str, Any] = response.json()
    if response.status_code != 200:
        raise WebToolError(f"Couldn't read {url}: {body.get('detail', 'unknown error')}.")
    return body


def register(registry: ToolRegistry) -> ToolRegistry:
    registry.tool(
        "web_search", args=SearchArgs, risk_class="read", side_effect=False, timeout_s=30
    )(web_search)
    registry.tool(
        "read_webpage", args=ReadArgs, risk_class="read", side_effect=False, timeout_s=45
    )(read_webpage)
    return registry

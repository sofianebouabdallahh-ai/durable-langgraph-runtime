"""Settings → Tools (phase L6a): which search the agents use, and from which sites they read.

GET  /tools/settings          the search provider, whether a key is saved (never the
                              key), your SearXNG address, the sites allowed
PUT  /tools/settings          change them (a new key replaces the saved one)
POST /tools/search/test       a real search, to show it works
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.web.settings import ToolConfig, ToolSettings

tools_router = APIRouter(prefix="/tools", tags=["tools"])
ProviderName = Literal["searxng", "tavily", "brave"]


def _service(request: Request) -> ToolSettings:
    service: ToolSettings = request.app.state.tool_settings
    return service


ServiceDep = Annotated[ToolSettings, Depends(_service)]


class ToolSettingsView(BaseModel):
    search_provider: ProviderName
    searxng_url: str | None = Field(description="Your own SearXNG; none: the one in the stack")
    has_key: bool = Field(description="A key is saved for the keyed provider (never returned)")
    key_fingerprint: str | None
    web_allowlist: list[str] = Field(description="When set, pages are read only from these sites")
    updated_at: datetime | None
    sandbox: bool = Field(default=False, description="Run Python, the terminal and files are on")

    @classmethod
    def of(cls, c: ToolConfig) -> ToolSettingsView:
        return cls(
            search_provider=c.search_provider,
            searxng_url=c.searxng_url,
            has_key=c.has_key,
            key_fingerprint=c.key_fingerprint,
            web_allowlist=c.web_allowlist,
            updated_at=c.updated_at,
        )


Sites = Annotated[list[Annotated[str, Field(max_length=253)]], Field(max_length=200)]


class ToolSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search_provider: ProviderName | None = None
    api_key: Annotated[str, Field(max_length=500)] | None = None
    searxng_url: Annotated[str, Field(max_length=500)] | None = None
    web_allowlist: (
        Annotated[list[Annotated[str, Field(max_length=253)]], Field(max_length=200)] | None
    ) = None


class SearchTest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, Field(min_length=1, max_length=200)] = "weather today"


class SearchTestHit(BaseModel):
    title: str
    url: str
    snippet: str


class SearchTestView(BaseModel):
    ok: bool
    detail: str
    results: list[SearchTestHit]


def _view(request: Request, config: ToolConfig) -> ToolSettingsView:
    view = ToolSettingsView.of(config)
    view.sandbox = bool(request.app.state.settings.sandboxd_url)
    return view


@tools_router.get("/settings", response_model=ToolSettingsView, summary="Tool settings")
async def get_settings(request: Request, service: ServiceDep) -> ToolSettingsView:
    return _view(request, await service.current())


@tools_router.put("/settings", response_model=ToolSettingsView, summary="Change tool settings")
async def put_settings(
    body: ToolSettingsUpdate, request: Request, service: ServiceDep
) -> ToolSettingsView:
    return _view(
        request,
        await service.update(
            search_provider=body.search_provider,
            api_key=body.api_key,
            searxng_url=body.searxng_url,
            web_allowlist=body.web_allowlist,
        ),
    )


@tools_router.post("/search/test", response_model=SearchTestView, summary="Try the search")
async def test_search(body: SearchTest, service: ServiceDep) -> SearchTestView:
    ok, detail, hits = await service.test(body.query)
    return SearchTestView(
        ok=ok,
        detail=detail,
        results=[SearchTestHit(title=h.title, url=h.url, snippet=h.snippet) for h in hits],
    )

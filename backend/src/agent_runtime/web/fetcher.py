"""The page reader as a service (phase L6a): `runtime fetcher`.

The one place tools reach the web through, so a network policy can give internet
egress to it alone (and keep workers to Postgres, Redis and model providers). It runs
`fetch` (the guard is in the connection) and nothing else: no database, no secrets.

    POST /fetch {url, allowlist?}  →  the page as text, or 422 {detail} saying why not
    GET  /healthz
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.web.fetch import FetchRefused, fetch


class FetchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: Annotated[str, Field(min_length=8, max_length=2000)]
    allowlist: Annotated[list[Annotated[str, Field(max_length=253)]], Field(max_length=200)] = []


def create_app(allow_hosts: tuple[str, ...] = ()) -> FastAPI:
    app = FastAPI(title="Nuria page reader", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/fetch")
    async def read(body: FetchRequest) -> Any:
        try:
            page = await fetch(body.url, allowlist=body.allowlist, allow_hosts=allow_hosts)
        except FetchRefused as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        return page.as_json()

    return app

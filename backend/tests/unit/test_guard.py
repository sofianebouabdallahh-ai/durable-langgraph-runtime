"""Only Nuria's own pages drive the API (phase H3): the Fetch Metadata guard."""

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from agent_runtime.api.guard import BrowserOriginGuard, allowed_hosts


def client(extra: str = "") -> httpx.AsyncClient:
    async def ok(_: object) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/admin/cancel-all", ok, methods=["POST", "GET"])])
    guarded = BrowserOriginGuard(app, allowed_hosts(extra))
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=guarded), base_url="http://localhost:3000"
    )


@pytest.mark.parametrize(
    "headers",
    [
        {"sec-fetch-site": "same-origin", "origin": "http://localhost:3000"},  # Nuria's page
        {"sec-fetch-site": "none"},  # a typed address (the docs page)
        {},  # the CLI, scripts, tests: not a browser
        {"sec-fetch-site": "same-origin", "host": "ui:8080"},  # UI_HOSTNAMES=ui
    ],
)
async def test_nurias_own_pages_and_non_browsers_pass(headers: dict[str, str]) -> None:
    async with client("ui") as c:
        assert (await c.post("/admin/cancel-all", headers=headers)).status_code == 200


@pytest.mark.parametrize(
    ("headers", "why"),
    [
        ({"sec-fetch-site": "cross-site", "origin": "https://evil.example"}, "Another site"),
        ({"sec-fetch-site": "same-site"}, "Another site"),
        ({"origin": "https://evil.example"}, "evil.example"),  # an older browser: Origin only
        ({"sec-fetch-site": "same-origin", "host": "rebound.evil.example:3000"}, "isn't one"),
    ],
)
async def test_cross_site_and_rebinding_requests_are_refused(
    headers: dict[str, str], why: str
) -> None:
    async with client() as c:
        response = await c.post("/admin/cancel-all", headers=headers)
    assert response.status_code == 403 and why in response.json()["detail"]
    assert response.headers["content-type"] == "application/problem+json"


def test_allowed_hosts() -> None:
    hosts = allowed_hosts("nuria.example.com, ui")
    assert {"localhost", "127.0.0.1", "[::1]", "nuria.example.com", "ui"} <= hosts
    assert "evil.example" not in hosts

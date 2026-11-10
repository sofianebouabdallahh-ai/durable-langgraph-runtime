"""Only Nuria's own pages drive the API (phase H3): a Fetch Metadata guard.

Browsers say where a request comes from (`Sec-Fetch-Site`: same-origin, same-site,
cross-site, none) and, for most requests, its `Origin`. This middleware refuses, with
403, any browser request that isn't Nuria's own page:

- `Sec-Fetch-Site: cross-site` or `same-site`: another site (or a sibling subdomain)
  is making your browser call Nuria (CSRF);
- an `Origin` whose host isn't one of Nuria's (older browsers, without fetch metadata);
- a browser request whose `Host` isn't one of Nuria's: a page that rebound its domain to
  this address (DNS rebinding). nginx refuses those first (421); this covers the API
  run on its own in development.

Requests with no browser headers (the CLI, scripts, tests, Prometheus) are not a
browser's, so a page can't forge them: they pass. This is the OWASP / web.dev "resource
isolation policy". A login comes with accounts (tenancy), later.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

from agent_runtime.api.problems import MEDIA_TYPE, TYPE_BASE

# Always Nuria's: this machine, and the UI dev server's proxy (Docker Desktop's name for
# the host, which a page elsewhere can't make your browser send).
DEFAULT_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1", "host.docker.internal"})


def allowed_hosts(extra: str | Iterable[str]) -> frozenset[str]:
    """The default names plus UI_HOSTNAMES (space- or comma-separated)."""
    names = extra.replace(",", " ").split() if isinstance(extra, str) else list(extra)
    return DEFAULT_HOSTS | {n.strip().lower() for n in names if n.strip()}


def _hostname(value: str) -> str:
    """`localhost:3000` → `localhost`; `[::1]:3000` → `[::1]`."""
    value = value.strip().lower()
    if value.startswith("["):
        return value[: value.find("]") + 1] if "]" in value else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class BrowserOriginGuard:
    def __init__(self, app: ASGIApp, hosts: frozenset[str]) -> None:
        self.app = app
        self.hosts = hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
            if (reason := self._refuse(headers)) is not None:
                await _forbidden(send, reason)
                return
        await self.app(scope, receive, send)

    def _refuse(self, headers: dict[str, str]) -> str | None:
        site = headers.get("sec-fetch-site")
        if site in ("cross-site", "same-site"):
            return "Another site asked your browser to call Nuria. Only Nuria's own pages can."
        origin = headers.get("origin")
        if origin and origin != "null":
            host = urlsplit(origin).netloc
            if _hostname(host) not in self.hosts:
                return f"Requests from {origin} aren't Nuria's own pages."
        if site is not None and _hostname(headers.get("host", "")) not in self.hosts:
            return "This address isn't one of Nuria's (UI_HOSTNAMES)."
        return None


async def _forbidden(send: Send, detail: str) -> None:
    body = json.dumps({"type": TYPE_BASE + "not-nurias-page", "title": "Refused",
                       "status": 403, "detail": detail}).encode()  # fmt: skip
    await send({"type": "http.response.start", "status": 403,
                "headers": [(b"content-type", MEDIA_TYPE.encode()),
                            (b"content-length", str(len(body)).encode())]})  # fmt: skip
    await send({"type": "http.response.body", "body": body})

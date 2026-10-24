"""The API's access log (phase L7a): one line per request, and its request id.

    → X-Request-ID (ours, or the caller's when it looks like one)
    → binds request_id, and session_id / run_id from the path, for every line inside
    ← one `api.access` line: method, route template, status, duration_ms
      (a live stream also gets one when it opens: it may stay open for minutes, and
      which replica serves it matters while it does)

A pure ASGI middleware, not Starlette's BaseHTTPMiddleware: streaming responses (the chat
stream) pass through untouched and the context variables reach the endpoint. Probes and
scrapes are left out. The route is the template (`/sessions/{session_id}`), so lines group
by endpoint and carry no ids in the path; the ids are fields.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agent_runtime import logs

log = logging.getLogger("api.access")

SKIP = frozenset({"/healthz", "/readyz", "/metrics"})
REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_SESSION = re.compile(rf"/sessions/({_UUID})")
_RUN = re.compile(rf"/(?:runs|activity/turns)/({_UUID})")


class AccessLog:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        rid = _request_id(scope)
        status = [500]  # if the app fails before it answers

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                status[0] = message["status"]
                headers = message.get("headers", [])
                message["headers"] = [*headers, (b"x-request-id", rid.encode())]
                if _streaming(headers):
                    _line(scope, status[0], time.monotonic() - t0, stream="open")
            await send(message)

        session, run = _SESSION.search(path), _RUN.search(path)
        t0 = time.monotonic()
        with logs.bind(request_id=rid, session_id=session and session[1], run_id=run and run[1]):
            try:
                await self.app(scope, receive, send_with_id)
            finally:
                if path not in SKIP:
                    _line(scope, status[0], time.monotonic() - t0)


def _request_id(scope: Scope) -> str:
    for name, value in scope.get("headers", []):
        if name == b"x-request-id":
            given = bytes(value).decode("latin-1")
            if REQUEST_ID.match(given):
                return given
    return uuid.uuid4().hex


def _streaming(headers: Any) -> bool:
    return any(
        bytes(k).lower() == b"content-type" and bytes(v).startswith(b"text/event-stream")
        for k, v in headers
    )


def _line(scope: Scope, status: int, seconds: float, stream: str | None = None) -> None:
    route: Any = scope.get("route")
    template = getattr(route, "path", None) or "(no route)"
    suffix = f" (stream {stream})" if stream else ""
    logs.event(
        log, f"{scope['method']} {template} {status}{suffix}", method=scope["method"],
        route=template, status=status, duration_ms=round(seconds * 1000), stream=stream,
        level=logging.WARNING if status >= 500 else logging.INFO,
    )  # fmt: skip

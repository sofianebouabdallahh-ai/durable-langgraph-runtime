"""Errors from the browser (phase L7a), logged with the server's lines.

    POST /client-errors   {kind, message, stack, route, failed_request_id, version}

The UI's error boundary and `window.onerror` / `unhandledrejection` send them here; they
become one WARNING line with `component=ui`, redacted like every other line. Nothing
leaves the machine. Bounded (field sizes) and rate-limited (a token bucket per API
process), so a page stuck in a loop can't flood the logs.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from agent_runtime import logs

log = logging.getLogger("ui")

client_errors_router = APIRouter(prefix="/client-errors", tags=["telemetry"])


class ClientError(BaseModel):
    kind: Literal["error", "unhandledrejection", "render"]
    message: str = Field(max_length=2000)
    stack: str | None = Field(default=None, max_length=8000)
    route: str | None = Field(default=None, max_length=200, description="e.g. #/activity")
    failed_request_id: str | None = Field(
        default=None, max_length=64, description="The X-Request-ID of the API call that failed"
    )
    version: str | None = Field(default=None, max_length=32)


class TokenBucket:
    """`rate` per minute, bursts up to `burst`. Thread-safe; one per API process."""

    def __init__(self, rate: float, burst: int) -> None:
        self._per_s, self._burst = rate / 60, burst
        self._tokens, self._at = float(burst), time.monotonic()
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(self._burst, self._tokens + (now - self._at) * self._per_s)
            self._at = now
            if self._tokens < 1:
                return False
            self._tokens -= 1
            return True


def _bucket(request: Request) -> TokenBucket:
    state = request.app.state
    if getattr(state, "client_errors", None) is None:
        state.client_errors = TokenBucket(rate=30, burst=10)
    bucket: TokenBucket = state.client_errors
    return bucket


@client_errors_router.post("", status_code=202, summary="Log an error from the browser")
async def client_error(body: ClientError, bucket: Annotated[TokenBucket, Depends(_bucket)]) -> None:
    if not bucket.take():
        raise HTTPException(429, "too many errors reported; try again in a minute")
    logs.event(
        log, f"ui {body.kind}: {body.message[:300]}", level=logging.WARNING, component="ui",
        kind=body.kind, route=body.route, stack=body.stack,
        failed_request_id=body.failed_request_id, version=body.version,
    )  # fmt: skip

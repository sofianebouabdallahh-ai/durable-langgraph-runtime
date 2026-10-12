"""Errors as RFC 9457 Problem Details (`application/problem+json`).

Every error response has the same machine-readable shape:
`{type, title, status, detail, ...extensions}`. Clients branch on `type`, never
on human-readable text, and internal details of 500s never leak.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from agent_runtime.graphs import UnknownGraph
from agent_runtime.runs.limits import LimitAboveCeiling
from agent_runtime.runs.store import RunNotFound

log = logging.getLogger(__name__)


class ResultNotReady(Exception):
    def __init__(self, run_id: uuid.UUID) -> None:
        super().__init__(f"run {run_id} has no result yet")
        self.run_id = run_id


MEDIA_TYPE = "application/problem+json"
TYPE_BASE = "https://agent-runtime.dev/problems/"  # documentation namespace, not fetched


def problem(status: int, slug: str, title: str, detail: str, **extensions: Any) -> JSONResponse:
    body = {"type": TYPE_BASE + slug, "title": title, "status": status, "detail": detail}
    return JSONResponse(body | extensions, status_code=status, media_type=MEDIA_TYPE)


def _errors(exc: ValidationError | RequestValidationError) -> list[dict[str, Any]]:
    return [
        {"loc": [str(p) for p in e["loc"]], "msg": e["msg"], "type": e["type"]}
        for e in exc.errors()
    ]


def install(app: FastAPI) -> None:
    @app.exception_handler(RunNotFound)
    async def _run_not_found(_: Request, exc: RunNotFound) -> JSONResponse:
        return problem(404, "run-not-found", "Run not found", str(exc), run_id=str(exc.run_id))

    @app.exception_handler(ResultNotReady)
    async def _no_result(_: Request, exc: ResultNotReady) -> JSONResponse:
        return problem(404, "result-not-ready", "No result yet", str(exc), run_id=str(exc.run_id))

    @app.exception_handler(UnknownGraph)
    async def _unknown_graph(_: Request, exc: UnknownGraph) -> JSONResponse:
        return problem(404, "unknown-graph", "Unknown graph", str(exc))

    @app.exception_handler(LimitAboveCeiling)
    async def _ceiling(_: Request, exc: LimitAboveCeiling) -> JSONResponse:
        return problem(
            422, "limit-above-ceiling", "Option exceeds server maximum", str(exc),
            field=f"options.{exc.field}", maximum=exc.ceiling,
        )  # fmt: skip

    @app.exception_handler(RequestValidationError)
    async def _request_invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        detail = "The request body or parameters are invalid."
        return problem(422, "invalid-request", "Invalid request", detail, errors=_errors(exc))

    @app.exception_handler(ValidationError)
    async def _input_invalid(_: Request, exc: ValidationError) -> JSONResponse:
        return problem(
            422, "invalid-input", "Invalid run input or options", f"{exc.title} is invalid.",
            errors=_errors(exc),
        )  # fmt: skip

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return problem(500, "internal", "Internal error", "An unexpected error occurred.")

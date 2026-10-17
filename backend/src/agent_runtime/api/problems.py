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

from agent_runtime.agents.document import ImportRejected
from agent_runtime.agents.resolver import AgentUnavailable
from agent_runtime.agents.studio import PublishBlocked
from agent_runtime.agents.studio_store import AgentNotFound, NameTaken
from agent_runtime.graphs import UnknownGraph
from agent_runtime.runs.limits import LimitAboveCeiling
from agent_runtime.runs.service import AdmissionPaused, Overloaded
from agent_runtime.runs.store import NotWaitingForApproval, RunNotFound, RunTerminal
from agent_runtime.sessions.service import DuplicateSend, NotAnAgent
from agent_runtime.sessions.store import NoActiveTurn, SessionArchived, SessionNotFound, TurnActive

log = logging.getLogger(__name__)


class ApiDraining(Exception):
    """This replica is shutting down (R10.7); the client should use another one."""


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
    # ------------------------------------------------------------ Studio (L3a)
    @app.exception_handler(AgentNotFound)
    async def _agent_not_found(_: Request, exc: AgentNotFound) -> JSONResponse:
        return problem(404, "agent-not-found", "Agent not found", str(exc))

    @app.exception_handler(AgentUnavailable)
    async def _agent_unavailable(_: Request, exc: AgentUnavailable) -> JSONResponse:
        return problem(409, "agent-unavailable", "This agent can't run right now", str(exc))

    @app.exception_handler(PublishBlocked)
    async def _publish_blocked(_: Request, exc: PublishBlocked) -> JSONResponse:
        return problem(409, "publish-blocked", "Not ready to publish", str(exc),
                       blockers=exc.blockers)  # fmt: skip

    @app.exception_handler(NameTaken)
    async def _name_taken(_: Request, exc: NameTaken) -> JSONResponse:
        return problem(409, "name-taken", "That name is taken", str(exc))

    @app.exception_handler(ImportRejected)
    async def _import_rejected(_: Request, exc: ImportRejected) -> JSONResponse:
        return problem(422, "import-rejected", "This file can't be imported", str(exc))

    @app.exception_handler(DuplicateSend)
    async def _duplicate_send(_: Request, exc: DuplicateSend) -> JSONResponse:
        return problem(409, "duplicate-send", "This message is already being sent",
                       "Retry with the same Idempotency-Key to get its turn.")  # fmt: skip

    @app.exception_handler(RunNotFound)
    async def _run_not_found(_: Request, exc: RunNotFound) -> JSONResponse:
        return problem(404, "run-not-found", "Run not found", str(exc), run_id=str(exc.run_id))

    @app.exception_handler(ApiDraining)
    async def _draining(_: Request, exc: ApiDraining) -> JSONResponse:
        response = problem(503, "draining", "Replica shutting down", "Retry on another replica.")
        response.headers["Retry-After"] = "1"
        return response

    @app.exception_handler(ResultNotReady)
    async def _no_result(_: Request, exc: ResultNotReady) -> JSONResponse:
        return problem(404, "result-not-ready", "No result yet", str(exc), run_id=str(exc.run_id))

    @app.exception_handler(RunTerminal)
    async def _terminal(_: Request, exc: RunTerminal) -> JSONResponse:
        return problem(
            409, "run-terminal", "Run has already ended", str(exc),
            run_id=str(exc.run.id), status_now=str(exc.run.status),
        )  # fmt: skip

    @app.exception_handler(NotWaitingForApproval)
    async def _not_waiting(_: Request, exc: NotWaitingForApproval) -> JSONResponse:
        return problem(
            409, "not-waiting-for-approval", "Run is not waiting for approval", str(exc),
            run_id=str(exc.run.id), status_now=str(exc.run.status),
        )  # fmt: skip

    @app.exception_handler(AdmissionPaused)
    async def _paused(_: Request, exc: AdmissionPaused) -> JSONResponse:
        response = problem(503, "paused", "Runtime paused", str(exc))
        response.headers["Retry-After"] = "30"
        return response

    @app.exception_handler(Overloaded)
    async def _overloaded(_: Request, exc: Overloaded) -> JSONResponse:
        response = problem(
            429, "overloaded", "Too many requests", str(exc),
            reason=exc.reason, queue_depth=exc.depth, limit=exc.limit,
        )  # fmt: skip
        response.headers["Retry-After"] = str(exc.retry_after_s)
        return response

    @app.exception_handler(SessionNotFound)
    async def _session_not_found(_: Request, exc: SessionNotFound) -> JSONResponse:
        return problem(404, "session-not-found", "Session not found", str(exc),
                       session_id=str(exc.session_id))  # fmt: skip

    @app.exception_handler(SessionArchived)
    async def _archived(_: Request, exc: SessionArchived) -> JSONResponse:
        return problem(409, "session-archived", "Session is archived", str(exc),
                       session_id=str(exc.session_id))  # fmt: skip

    @app.exception_handler(TurnActive)
    async def _turn_active(_: Request, exc: TurnActive) -> JSONResponse:
        return problem(409, "turn-active", "A turn is already active", str(exc),
                       session_id=str(exc.session_id), run_id=str(exc.run_id),
                       status_now=exc.status)  # fmt: skip

    @app.exception_handler(NoActiveTurn)
    async def _no_turn(_: Request, exc: NoActiveTurn) -> JSONResponse:
        return problem(409, "no-active-turn", "No active turn", str(exc),
                       session_id=str(exc.session_id))  # fmt: skip

    @app.exception_handler(NotAnAgent)
    async def _not_an_agent(_: Request, exc: NotAnAgent) -> JSONResponse:
        return problem(422, "not-an-agent", "Not an agent", str(exc), name=exc.name)

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

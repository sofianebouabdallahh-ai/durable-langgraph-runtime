"""FastAPI application.

Patterns:
- Application Factory: `create_app()` builds a fresh app (no import-time global
  state), so tests and the server each get their own.
- Dependency Injection: handlers receive the pool, service and registry through
  `Depends`. Tests inject an already-open pool; the server opens its own in the
  lifespan.

`POST /runs` creates a `queued` run and sends its work message; workers
(`runtime worker`) execute it. Admin endpoints (kill switch, R14.18) are internal:
the Ingress never routes `/admin` (phase 12).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from agent_runtime import __doc__ as package_doc
from agent_runtime import metrics, report, telemetry
from agent_runtime.admin import AdminRepository, AdminState
from agent_runtime.agents.studio import StudioService
from agent_runtime.api import problems
from agent_runtime.api.access import AccessLog
from agent_runtime.api.activity import activity_router
from agent_runtime.api.audit import audit_router
from agent_runtime.api.client_errors import client_errors_router
from agent_runtime.api.guard import BrowserOriginGuard, allowed_hosts
from agent_runtime.api.kill_switch import kill_switch_router
from agent_runtime.api.mcp import mcp_router
from agent_runtime.api.memory import memory_router
from agent_runtime.api.models import models_router
from agent_runtime.api.notifications import notifications_router
from agent_runtime.api.onboarding import onboarding_router
from agent_runtime.api.problems import ApiDraining, ResultNotReady
from agent_runtime.api.schemas import (
    AboutView,
    AdminStatus,
    ApprovalRequest,
    CreateRunRequest,
    CreateRunResponse,
    EventsPage,
    EventView,
    GraphEdge,
    GraphView,
    Health,
    PauseRequest,
    ResultView,
    RunView,
)
from agent_runtime.api.sessions import agents as agents_router
from agent_runtime.api.sessions import sessions as sessions_router
from agent_runtime.api.skills import skills_router
from agent_runtime.api.studio import studio as studio_router
from agent_runtime.api.telemetry import telemetry_router
from agent_runtime.api.tests import tests_router
from agent_runtime.api.tools import tools_router
from agent_runtime.config import Settings, get_agent_settings, get_settings
from agent_runtime.db import Pool, create_pool
from agent_runtime.evals.service import EvalService
from agent_runtime.graphs import GraphRegistry, GraphSpec, default_registry
from agent_runtime.mcp.service import McpService
from agent_runtime.models.connections import ConnectionService
from agent_runtime.queue import RedisWorkQueue, WorkQueue, create_redis
from agent_runtime.runs.kill_switch import KillSwitch
from agent_runtime.runs.relay import OutboxRelay
from agent_runtime.runs.service import RunService
from agent_runtime.runs.store import RunRepository
from agent_runtime.sessions.service import SessionService
from agent_runtime.skills.service import SkillService
from agent_runtime.streaming.broker import Broker
from agent_runtime.streaming.bus import EventBus, RedisEventBus
from agent_runtime.streaming.session import RunStream
from agent_runtime.subagents.store import SubagentRepository
from agent_runtime.web.settings import ToolSettings

log = logging.getLogger(__name__)

# ----------------------------------------------------------------- dependencies


def get_pool(request: Request) -> Pool:
    pool: Pool = request.app.state.pool
    return pool


def get_graphs(request: Request) -> GraphRegistry:
    graphs: GraphRegistry = request.app.state.graphs
    return graphs


def get_service(request: Request) -> RunService:
    service: RunService = request.app.state.service
    return service


PoolDep = Annotated[Pool, Depends(get_pool)]
GraphsDep = Annotated[GraphRegistry, Depends(get_graphs)]
ServiceDep = Annotated[RunService, Depends(get_service)]

# ----------------------------------------------------------------------- routes

runs = APIRouter(prefix="/runs", tags=["runs"])


@runs.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CreateRunResponse,
    summary="Create a run",
    description="Validates the graph, input and options, then creates a `queued` run. "
    "202 Accepted: the run executes asynchronously; poll `Location`.",
)
async def create_run(
    body: CreateRunRequest, service: ServiceDep, response: Response
) -> CreateRunResponse:
    run = await service.create_run(body.graph, body.input, body.options)
    response.headers["Location"] = f"/runs/{run.id}"
    return CreateRunResponse(run_id=run.id)


@runs.get("/{run_id}", response_model=RunView, summary="Run status")
async def get_run(run_id: uuid.UUID, pool: PoolDep) -> RunView:
    async with pool.connection() as conn:
        run = await RunRepository(conn).get(run_id)
        subagents = await SubagentRepository(conn).list(run_id)
    return RunView.of(run, subagents)


@runs.get("/{run_id}/events", response_model=EventsPage, summary="Replay persisted events")
async def list_events(
    run_id: uuid.UUID,
    pool: PoolDep,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> EventsPage:
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        await repo.get(run_id)  # 404 for unknown runs rather than an empty page
        events = await repo.list_events(run_id, after_seq=after_seq, limit=limit)
    return EventsPage(
        events=[EventView.of(e) for e in events],
        next_after_seq=events[-1].seq if events else after_seq,
    )


@runs.get("/{run_id}/result", response_model=ResultView, summary="Final output")
async def get_result(run_id: uuid.UUID, pool: PoolDep) -> ResultView:
    async with pool.connection() as conn:
        repo = RunRepository(conn)
        await repo.get(run_id)
        result = await repo.get_result(run_id)
    if result is None:
        raise ResultNotReady(run_id)  # spec §5: 404 until completed
    return ResultView(run_id=run_id, output=result["output"], partial=result["partial"])


@runs.get(
    "/{run_id}/report",
    summary="A zip to attach to a bug report (phase L5)",
    description="README, the timeline (structural fields only unless `include_chat`), the "
    "agent's definition when it's one you made, and the chat only if `include_chat`. Nothing "
    "is uploaded anywhere: the person downloads it.",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}},
)
async def run_report(
    run_id: uuid.UUID, request: Request, pool: PoolDep, include_chat: bool = False
) -> Response:
    name, data = await report.build(pool, request.app.state.studio, run_id,
                                    include_chat=include_chat)  # fmt: skip
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})  # fmt: skip


@runs.post(
    "/{run_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RunView,
    summary="Cancel a run (cooperative)",
    description="A queued or waiting run is cancelled now; a running run stops before its "
    "next node (R1.6). 409 if the run has already ended.",
)
async def cancel_run(run_id: uuid.UUID, service: ServiceDep) -> RunView:
    return RunView.of(await service.cancel(run_id))


@runs.post(
    "/{run_id}/redrive",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RunView,
    summary="Try a failed run again (from its last checkpoint)",
    description="H4. `failed` → `queued`: it resumes from its last saved step, and tool calls "
    "already done aren't run again. For failures that might not happen again (`error`, "
    "`infrastructure`, `max_reclaims`, `timeout`) of a top-level run; a chat turn only if "
    "it is the chat's latest. The budgets already used still count. 409 otherwise.",
)
async def redrive_run(run_id: uuid.UUID, service: ServiceDep) -> RunView:
    return RunView.of(await service.redrive(run_id))


@runs.post(
    "/{run_id}/approve",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RunView,
    summary="Approve or reject a paused run (human-in-the-loop)",
    description="R1.4. Decides one pending approval (`approval_id`). `approve`: once none is "
    "left, the run is re-queued and each approved call runs, with its edited arguments if "
    "given; `reject` cancels the run with reason `rejected`. Works with no worker alive. 409 "
    "unless the run is `waiting_approval`, or if the approval isn't pending.",
)
async def approve_run(run_id: uuid.UUID, body: ApprovalRequest, service: ServiceDep) -> RunView:
    edits = body.edits.model_dump(exclude_none=True) if body.edits else None
    return RunView.of(
        await service.decide_approval(
            run_id, body.decision, edits, body.reason, approval_id=body.approval_id
        )
    )


@runs.post(
    "/{run_id}/resume",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RunView,
    summary="Resume a run (idempotent)",
    description="Re-sends work for a queued run or one whose worker died; does nothing for a "
    "run a live worker is executing (R1.3). 409 if the run has already ended.",
)
async def resume_run(run_id: uuid.UUID, service: ServiceDep) -> RunView:
    return RunView.of(await service.resume(run_id))


@runs.get(
    "/{run_id}/stream",
    summary="Live event stream (SSE)",
    description="Replays persisted events after `Last-Event-ID` (or `after_seq`), then streams "
    "live ones from any replica (R2.5). Persisted events carry `id: <seq>`. A `: ping` comment "
    "is sent when idle; the stream closes after the run's terminal event; on replica shutdown "
    "an `event: reconnect` tells the client to reconnect with its Last-Event-ID.",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}, 503: {"description": "Draining"}},
)
async def stream_run(
    run_id: uuid.UUID,
    request: Request,
    pool: PoolDep,
    after_seq: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    if request.app.state.draining.is_set():
        raise ApiDraining
    async with pool.connection() as conn:
        await RunRepository(conn).get(run_id)  # 404 before opening a stream
    start = after_seq or 0
    if last_event_id is not None and last_event_id.isdigit():
        start = int(last_event_id)  # a browser reconnect wins over the query parameter
    stream = RunStream(
        pool, request.app.state.broker, request.app.state.settings, run_id,
        after_seq=start, draining=request.app.state.draining,
    )  # fmt: skip
    return StreamingResponse(
        stream.events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",  # never cache a live stream
            "X-Accel-Buffering": "no",  # nginx / Ingress: don't buffer (R10.3)
        },
    )


graphs_router = APIRouter(prefix="/graphs", tags=["graphs"])


def _describe(spec: GraphSpec) -> GraphView:
    drawable = spec.compile(None).get_graph()
    return GraphView(
        name=spec.name,
        description=spec.description,
        nodes=list(drawable.nodes),
        edges=[
            GraphEdge(source=e.source, target=e.target, conditional=e.conditional)
            for e in drawable.edges
        ],
        input_schema=spec.input_model.model_json_schema(),
    )


@graphs_router.get("", response_model=list[GraphView], summary="List graphs")
async def list_graphs(graphs: GraphsDep) -> list[GraphView]:
    return [_describe(spec) for spec in graphs]


@graphs_router.get("/{name}", response_model=GraphView, summary="Describe a graph")
async def get_graph(name: str, graphs: GraphsDep) -> GraphView:
    return _describe(graphs.get(name))


health = APIRouter(tags=["health"])


@health.get("/healthz", response_model=Health, summary="Liveness: the process is up")
async def healthz() -> Health:
    # Never checks dependencies (R10.5): a Postgres blip must not restart every pod.
    return Health(status="ok")


@health.get("/about", response_model=AboutView, summary="Version and model, for the UI")
async def about(request: Request) -> AboutView:
    from importlib import metadata

    settings: Settings = request.app.state.settings
    try:
        version: str | None = metadata.version("durable-agent-runtime")
    except metadata.PackageNotFoundError:
        version = None
    tracing = bool(settings.otel_exporter_otlp_endpoint)
    return AboutView(
        version=version, model_provider=settings.model_provider,
        demo_model=settings.model_provider == "scripted", chat_model=settings.model_chat or None,
        tracing=tracing, trace_ui_url=(settings.trace_ui_url or None) if tracing else None,
        dashboard_url=settings.dashboard_url or None,
    )  # fmt: skip


@health.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    """Prometheus scrape endpoint (R7.2)."""
    body, content_type = metrics.render()
    return Response(body, media_type=content_type)


@health.get(
    "/readyz",
    response_model=Health,
    summary="Readiness: dependencies reachable",
    responses={503: {"description": "Not ready"}},
)
async def readyz(request: Request, pool: PoolDep, response: Response) -> Health:
    if request.app.state.draining.is_set():  # R10.7: stop receiving new traffic
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return Health(status="draining")
    try:
        async with pool.connection(timeout=2) as conn:
            await conn.execute("SELECT 1")
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return Health(status="unavailable: postgres")
    redis = request.app.state.redis
    if redis is not None:
        try:
            await redis.ping()
        except Exception:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return Health(status="unavailable: redis")
    return Health(status="ok")


admin = APIRouter(prefix="/admin", tags=["admin (internal)"])


@admin.get("/state", summary="Kill-switch state and queue depth")
async def admin_state(pool: PoolDep) -> AdminStatus:
    async with pool.connection() as conn:
        state = await AdminRepository(conn).get()
        depth = await RunRepository(conn).queue_depth()
    return AdminStatus(
        paused=state.paused, reason=state.reason, updated_at=state.updated_at, queue_depth=depth
    )


@admin.post("/pause", summary="Stop admission and claiming (R14.18)")
async def admin_pause(body: PauseRequest, pool: PoolDep) -> AdminState:
    async with pool.connection() as conn:
        return await AdminRepository(conn).set_paused(True, body.reason)


@admin.post("/resume", summary="Resume admission and claiming")
async def admin_resume(pool: PoolDep) -> AdminState:
    async with pool.connection() as conn:
        return await AdminRepository(conn).set_paused(False)


@admin.post("/cancel-all", summary="Cooperatively cancel every non-terminal run")
async def admin_cancel_all(service: ServiceDep) -> dict[str, int]:
    return {"cancel_requested": await service.cancel_all()}


# ---------------------------------------------------------------------- factory


def create_app(
    settings: Settings | None = None,
    *,
    pool: Pool | None = None,
    queue: WorkQueue | None = None,
    bus: EventBus | None = None,
    graphs: GraphRegistry | None = None,
) -> FastAPI:
    """Build the app. Pass `pool` / `queue` to reuse open ones (tests); otherwise
    the app opens and closes its own in the lifespan."""
    settings = settings or get_settings()
    graphs = graphs or default_registry()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        redis = None
        work_queue, event_bus = queue, bus
        if work_queue is None or event_bus is None:
            redis = create_redis(settings.redis_url)
            work_queue = work_queue or RedisWorkQueue(
                redis, settings.work_stream, settings.work_group
            )
            event_bus = event_bus or RedisEventBus(redis)
        app.state.redis = redis
        broker = Broker(
            event_bus if settings.stream_live_enabled else None,
            queue_size=settings.stream_queue_size,
        )
        await broker.start()
        app.state.broker = broker
        metrics.SUBSCRIBERS.set_function(broker.subscribers)
        app.state.loop = asyncio.get_running_loop()  # for the signal handler (cli._api)
        try:
            if pool is not None:
                _wire(app, pool, work_queue, event_bus)
                await _skills_ready(app)
                yield
                return
            async with create_pool(settings) as owned:
                _wire(app, owned, work_queue, event_bus)
                await _skills_ready(app)
                poller = metrics.StatePoller(owned, work_queue)  # the state gauges (R7.2)
                poller.start()
                try:
                    yield
                finally:
                    await poller.stop()
        finally:
            await broker.stop()
            if redis is not None:
                await redis.aclose()

    async def _skills_ready(app: FastAPI) -> None:
        """Built-in skills up to date, and stored ones checked with the current rules."""
        await app.state.skills.sync_builtins(get_agent_settings().skills_dir)
        try:
            await app.state.skills.rescan()
        except Exception:  # the old results stay shown; the next start tries again
            log.warning("couldn't check stored skills with the current rules", exc_info=True)

    def _wire(app: FastAPI, p: Pool, q: WorkQueue, b: EventBus) -> None:
        app.state.pool = p
        relay = OutboxRelay(p, q, stale_s=settings.relay_stale_s)
        app.state.service = RunService(p, settings, graphs, relay, b)
        app.state.sessions = SessionService(p, settings, graphs, app.state.service, relay, b)
        app.state.studio = StudioService(
            p,
            app.state.service.agents,
            app.state.sessions,
            settings,
            app.state.service,
            sandbox=bool(settings.sandboxd_url),
        )
        app.state.evals = EvalService(p, app.state.sessions)  # the Tests tab (H6)
        app.state.connections = ConnectionService(p, settings)
        app.state.skills = SkillService(p)
        app.state.tool_settings = ToolSettings(p, settings)
        app.state.kill_switch = KillSwitch(p, app.state.service)
        app.state.mcp = McpService(p, settings)

    app = FastAPI(
        title="Agent Runtime API",
        version="0.2.0",
        description=package_doc or "",
        lifespan=lifespan,
    )
    app.state.graphs = graphs
    app.state.settings = settings
    app.state.redis = None
    # Set when the server is asked to stop (R10.7): readyz fails, new streams are
    # refused, open streams send `reconnect` and close.
    app.state.draining = asyncio.Event()
    app.state.loop = None
    problems.install(app)
    # A cross-site or rebinding browser request never reaches a route (H3); the access
    # log (added after, so outside it) still records the refusal.
    app.add_middleware(BrowserOriginGuard, hosts=allowed_hosts(settings.ui_hostnames))
    app.add_middleware(AccessLog)
    app.include_router(runs)
    app.include_router(sessions_router)
    app.include_router(agents_router)
    app.include_router(memory_router)
    app.include_router(studio_router)
    app.include_router(models_router)
    app.include_router(skills_router)
    app.include_router(onboarding_router)
    app.include_router(tools_router)
    app.include_router(kill_switch_router)
    app.include_router(activity_router)
    app.include_router(audit_router)
    app.include_router(mcp_router)
    app.include_router(notifications_router)
    app.include_router(tests_router)
    app.include_router(telemetry_router)
    app.include_router(client_errors_router)
    app.include_router(graphs_router)
    app.include_router(health)
    if settings.admin_api_enabled:
        app.include_router(admin)
    return app


def create_api_app() -> FastAPI:
    """Server entry point (`runtime api`): connects as the API's own DB user.
    With an OTLP endpoint, requests are traced (FastAPI) and so are outgoing calls
    (httpx); a run created by a request continues its trace (R2.7)."""
    settings = get_settings().for_component("api")
    app = create_app(settings)
    if telemetry.configure("api", settings.otel_exporter_otlp_endpoint):
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        FastAPIInstrumentor.instrument_app(
            app, excluded_urls="healthz,readyz,metrics,stream", exclude_spans=["receive", "send"]
        )
        HTTPXClientInstrumentor().instrument()
    return app

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

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response, status

from agent_runtime import __doc__ as package_doc
from agent_runtime.admin import AdminRepository, AdminState
from agent_runtime.api import problems
from agent_runtime.api.problems import ResultNotReady
from agent_runtime.api.schemas import (
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
from agent_runtime.config import Settings, get_settings
from agent_runtime.db import Pool, create_pool
from agent_runtime.graphs import GraphRegistry, GraphSpec, default_registry
from agent_runtime.queue import RedisWorkQueue, WorkQueue, create_redis
from agent_runtime.runs.relay import OutboxRelay
from agent_runtime.runs.service import RunService
from agent_runtime.runs.store import RunRepository

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
        return RunView.of(await RunRepository(conn).get(run_id))


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
    "/{run_id}/resume",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RunView,
    summary="Resume a run (idempotent)",
    description="Re-sends work for a queued run or one whose worker died; does nothing for a "
    "run a live worker is executing (R1.3). 409 if the run has already ended.",
)
async def resume_run(run_id: uuid.UUID, service: ServiceDep) -> RunView:
    return RunView.of(await service.resume(run_id))


graphs_router = APIRouter(prefix="/graphs", tags=["graphs"])


def _describe(spec: GraphSpec) -> GraphView:
    drawable = spec.build().compile().get_graph()
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


@health.get(
    "/readyz",
    response_model=Health,
    summary="Readiness: dependencies reachable",
    responses={503: {"description": "Not ready"}},
)
async def readyz(request: Request, pool: PoolDep, response: Response) -> Health:
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


@admin.get("/state", summary="Kill-switch state")
async def admin_state(pool: PoolDep) -> AdminState:
    async with pool.connection() as conn:
        return await AdminRepository(conn).get()


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
    graphs: GraphRegistry | None = None,
) -> FastAPI:
    """Build the app. Pass `pool` / `queue` to reuse open ones (tests); otherwise
    the app opens and closes its own in the lifespan."""
    settings = settings or get_settings()
    graphs = graphs or default_registry()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        redis = None
        work_queue = queue
        if work_queue is None:
            redis = create_redis(settings.redis_url)
            work_queue = RedisWorkQueue(redis, settings.work_stream, settings.work_group)
        app.state.redis = redis
        try:
            if pool is not None:
                _wire(app, pool, work_queue)
                yield
                return
            async with create_pool(settings) as owned:
                _wire(app, owned, work_queue)
                yield
        finally:
            if redis is not None:
                await redis.aclose()

    def _wire(app: FastAPI, p: Pool, q: WorkQueue) -> None:
        app.state.pool = p
        relay = OutboxRelay(p, q, stale_s=settings.relay_stale_s)
        app.state.service = RunService(p, settings, graphs, relay)

    app = FastAPI(
        title="Agent Runtime API",
        version="0.2.0",
        description=package_doc or "",
        lifespan=lifespan,
    )
    app.state.graphs = graphs
    app.state.redis = None
    problems.install(app)
    app.include_router(runs)
    app.include_router(graphs_router)
    app.include_router(health)
    if settings.admin_api_enabled:
        app.include_router(admin)
    return app

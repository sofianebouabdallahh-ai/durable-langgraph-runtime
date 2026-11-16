"""sandboxd (phase L6b, CR-002 §13; Kubernetes: L6c): the one service that can start sandboxes.

Workers never start containers: they ask sandboxd, over the internal network, with a
shared token. sandboxd alone can start them, through its backend (SANDBOX_DRIVER):

    docker       the Docker socket (Compose)
    kubernetes   Pods in the sandboxes' namespace, with its own ServiceAccount (Helm)

and offers exactly this:

    PUT    /sandboxes/{run}?epoch=N        the run's sandbox (created on first use)
    POST   /sandboxes/{run}/exec           run argv in it: exit code, stdout, stderr
    DELETE /sandboxes/{run}?epoch=N        gone, up to that epoch (the run left `running`)
    GET    /healthz                        the backend reachable, and the isolation level

Every sandbox is the same locked-down one (backend.py, R13.3), at the isolation level
this installation asked for and sandboxd proved (isolation.py, H9). Until it has, and
if it can't, it starts none for runs: the code tools say why. One per run and epoch
(R13.2): a reclaimed run gets a fresh one and the old epoch's is removed; an older epoch
asking again is refused (409), never obeyed. Old ones are swept, in case a worker died
without saying goodbye.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import os
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime import logs
from agent_runtime.sandbox import isolation
from agent_runtime.sandbox.backend import Backend, Isolation, Limits

log = logging.getLogger(__name__)

MAX_AGE_S = 2 * 3600  # nothing a run does takes longer (its own timeout is shorter)
SWEEP_EVERY_S = 60
RETRY_S = 5  # establishing the isolation level, while it fails
RUN_ID = re.compile(r"^[0-9a-f-]{36}$")


def backend_from_env() -> Backend:
    """The driver this installation uses (Strategy, chosen once at start)."""
    driver = os.environ.get("SANDBOX_DRIVER", "docker")
    if driver == "kubernetes":
        from agent_runtime.sandbox.kubernetes import Kubernetes

        return Kubernetes(
            os.environ.get("SANDBOX_NAMESPACE") or None,
            runtime_class=os.environ.get("SANDBOX_RUNTIME_CLASS") or None,
            pull_policy=os.environ.get("SANDBOX_IMAGE_PULL_POLICY", "IfNotPresent"),
            user_namespaces=os.environ.get("SANDBOX_USER_NAMESPACES", "") == "true",
        )
    if driver == "docker":
        from agent_runtime.sandbox.docker import Docker

        return Docker(
            os.environ.get("SANDBOX_DOCKER_SOCKET", "/var/run/docker.sock"),
            runtime=os.environ.get("SANDBOX_DOCKER_RUNTIME", "runsc"),
        )
    raise ValueError(f"SANDBOX_DRIVER must be docker or kubernetes, not {driver!r}")


class ExecRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    epoch: Annotated[int, Field(ge=0)]
    argv: Annotated[
        list[Annotated[str, Field(max_length=200_000)]], Field(min_length=1, max_length=64)
    ]
    timeout_s: Annotated[float, Field(gt=0, le=300)] = 30


def create_app(
    backend: Backend | None = None,
    image: str | None = None,
    token: str | None = None,
    limits: Limits | None = None,
    wanted: isolation.Wanted | None = None,
) -> FastAPI:
    sandboxes = backend or backend_from_env()
    level = isolation.Level(wanted or isolation.wanted_from_env())
    image = image or os.environ.get("SANDBOX_IMAGE", "nuria-sandbox:dev")
    token = token if token is not None else os.environ.get("SANDBOXD_TOKEN", "")
    limits = limits or Limits()
    locks: dict[str, asyncio.Lock] = {}

    async def authorised(authorization: str = Header(default="")) -> None:
        # Compared in constant time (as delivery.py does): a `!=` leaks, byte by byte, how
        # much of a guess was right. No token configured still refuses everything.
        expected = f"Bearer {token}".encode()
        if not token or not hmac.compare_digest(authorization.encode(), expected):
            raise HTTPException(401, "a sandboxd token is required")

    def valid(run: str) -> str:
        if not RUN_ID.match(run):
            raise HTTPException(422, "not a run id")
        return run

    settling = asyncio.Lock()

    async def settle() -> None:
        """One check of the level. An error leaves it unsettled (tried again), never
        taken as "lower"; a check that finished settles it, with a level or without."""
        async with settling:
            if level.settled:
                return
            try:
                found = await isolation.establish(sandboxes, level.wanted, image, limits)
            except Exception as exc:
                log.warning("isolation not established yet", exc_info=True)
                level.reason = f"The sandbox is starting ({type(exc).__name__})."
                return
            level.isolation, level.reason, level.settled = found.isolation, found.reason, True
            logs.event(log, "sandbox isolation", **level.view())

    async def isolated() -> Isolation:
        if not level.settled:
            await settle()  # a request before the background check got there
        if level.isolation is None:
            raise HTTPException(503, level.reason)
        return level.isolation

    async def ensure(run: str, epoch: int) -> str:
        """The run's sandbox for this epoch: reused, or created (older epochs removed).

        The fence is on the database (fencing.py), and the sandbox follows it: it belongs
        to the newest epoch that asked. An older epoch is told so (409) and removes
        nothing. Removing every other epoch's, as before, let a stale worker (frozen
        between a tool's begin and finish) destroy the sandbox and workspace of the
        worker that took the run over (the review of 2026-11-12)."""
        at = await isolated()
        async with locks.setdefault(run, asyncio.Lock()):
            existing = await sandboxes.sandboxes(run)
            newest = max((s.epoch for s in existing), default=epoch)
            if epoch < newest:
                raise HTTPException(409, f"this run has moved to a newer worker (epoch {newest})")
            for s in existing:
                if s.epoch == epoch and s.state == "running":
                    return s.id
                if s.epoch < epoch or s.state == "gone":
                    await sandboxes.remove(s.id)  # an older epoch's, or a stopped one
            # Starting (another sandboxd replica's): create() waits for that one.
            created = await sandboxes.create(run, epoch, image, limits, at)
            logs.event(log, f"sandbox created for run {run}", run_id=run, epoch=epoch)
            return created

    async def establish() -> None:
        """At start, so the first run doesn't wait; again while there's no level (gVisor
        may be installed meanwhile)."""
        while level.isolation is None:
            await settle()
            if level.isolation is None:
                await asyncio.sleep(SWEEP_EVERY_S if level.settled else RETRY_S)
                level.settled = False

    async def sweep() -> None:
        while True:
            await asyncio.sleep(SWEEP_EVERY_S)
            try:
                now = time.time()
                for s in await sandboxes.sandboxes():
                    age = now - s.created
                    if age > MAX_AGE_S or (s.state == "gone" and age > SWEEP_EVERY_S):
                        await sandboxes.remove(s.id)
                        logs.event(
                            log, "sandbox swept", why="too old" if age > MAX_AGE_S else "stopped"
                        )
            except Exception:
                log.warning("sandbox sweep failed", exc_info=True)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        tasks = [asyncio.create_task(sweep()), asyncio.create_task(establish())]
        yield
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await sandboxes.close()

    app = FastAPI(
        title="Nuria sandboxd",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        try:
            reachable = await sandboxes.ping()
        except Exception:
            log.warning("sandbox backend unreachable", exc_info=True)
            reachable = False
        if not reachable:
            raise HTTPException(503, "the sandbox backend isn't reachable")
        return {"status": "ok", **level.view()}

    @app.put("/sandboxes/{run}", dependencies=[Depends(authorised)])
    async def put(run: str, epoch: int) -> dict[str, str]:
        return {"container": await ensure(valid(run), epoch)}

    @app.post("/sandboxes/{run}/exec", dependencies=[Depends(authorised)])
    async def run_in(run: str, body: ExecRequest) -> dict[str, Any]:
        container = await ensure(valid(run), body.epoch)
        # Under gVisor the code's process limit is set inside the sandbox (backend.py).
        inside = limits.pids if level.isolation == "gvisor" else None
        done = await sandboxes.exec(container, body.argv, body.timeout_s, processes=inside)
        return done | {"isolation": level.isolation}

    @app.delete("/sandboxes/{run}", status_code=204, dependencies=[Depends(authorised)])
    async def delete(run: str, epoch: int | None = None) -> None:
        """The goodbye of the worker that held the run at `epoch`: that epoch's sandbox
        goes, and older ones. A newer epoch's stays, by the rule `ensure` follows: the
        worker may be a stale one (frozen between its run pausing and this call) and the
        run another worker's by now. Without an epoch (a worker from before this rule,
        during a rolling update), every sandbox of the run goes, as before."""
        existing = await sandboxes.sandboxes(valid(run))
        gone = [s for s in existing if epoch is None or s.epoch <= epoch]
        for s in gone:
            await sandboxes.remove(s.id)
        if len(gone) == len(existing):
            locks.pop(run, None)
        if gone:
            logs.event(log, f"sandbox removed for run {run}", run_id=run)

    return app

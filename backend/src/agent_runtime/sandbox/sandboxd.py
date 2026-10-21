"""sandboxd (phase L6b, CR-002 §13; Kubernetes: L6c): the one service that can start sandboxes.

Workers never start containers: they ask sandboxd, over the internal network, with a
shared token. sandboxd alone can start them, through its backend (SANDBOX_DRIVER):

    docker       the Docker socket (Compose)
    kubernetes   Pods in the sandboxes' namespace, with its own ServiceAccount (Helm)

and offers exactly this:

    PUT    /sandboxes/{run}?epoch=N        the run's sandbox (created on first use)
    POST   /sandboxes/{run}/exec           run argv in it: exit code, stdout, stderr
    DELETE /sandboxes/{run}                gone (the run left `running`)
    GET    /healthz                        the backend reachable

Every sandbox is the same locked-down one (backend.py, R13.3). One per run and epoch
(R13.2): a reclaimed run gets a fresh one and the old epoch's is removed. Old ones are
swept, in case a worker died without saying goodbye.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.sandbox.backend import Backend, Limits

log = logging.getLogger(__name__)

MAX_AGE_S = 2 * 3600  # nothing a run does takes longer (its own timeout is shorter)
SWEEP_EVERY_S = 60
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

        return Docker()
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
) -> FastAPI:
    sandboxes = backend or backend_from_env()
    image = image or os.environ.get("SANDBOX_IMAGE", "nuria-sandbox:dev")
    token = token if token is not None else os.environ.get("SANDBOXD_TOKEN", "")
    limits = limits or Limits()
    locks: dict[str, asyncio.Lock] = {}

    async def authorised(authorization: str = Header(default="")) -> None:
        if not token or authorization != f"Bearer {token}":
            raise HTTPException(401, "a sandboxd token is required")

    def valid(run: str) -> str:
        if not RUN_ID.match(run):
            raise HTTPException(422, "not a run id")
        return run

    async def ensure(run: str, epoch: int) -> str:
        """The run's sandbox for this epoch: reused, or created (older epochs removed)."""
        async with locks.setdefault(run, asyncio.Lock()):
            for s in await sandboxes.sandboxes(run):
                if s.epoch == epoch and s.state == "running":
                    return s.id
                if s.epoch != epoch or s.state == "gone":
                    await sandboxes.remove(s.id)  # an old epoch's, or a stopped one
            # Starting (another sandboxd replica's): create() waits for that one.
            return await sandboxes.create(run, epoch, image, limits)

    async def sweep() -> None:
        while True:
            await asyncio.sleep(SWEEP_EVERY_S)
            try:
                now = time.time()
                for s in await sandboxes.sandboxes():
                    age = now - s.created
                    if age > MAX_AGE_S or (s.state == "gone" and age > SWEEP_EVERY_S):
                        await sandboxes.remove(s.id)
            except Exception:
                log.warning("sandbox sweep failed", exc_info=True)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(sweep())
        yield
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
    async def healthz() -> dict[str, str]:
        try:
            reachable = await sandboxes.ping()
        except Exception:
            log.warning("sandbox backend unreachable", exc_info=True)
            reachable = False
        if not reachable:
            raise HTTPException(503, "the sandbox backend isn't reachable")
        return {"status": "ok"}

    @app.put("/sandboxes/{run}", dependencies=[Depends(authorised)])
    async def put(run: str, epoch: int) -> dict[str, str]:
        return {"container": await ensure(valid(run), epoch)}

    @app.post("/sandboxes/{run}/exec", dependencies=[Depends(authorised)])
    async def run_in(run: str, body: ExecRequest) -> dict[str, Any]:
        container = await ensure(valid(run), body.epoch)
        return await sandboxes.exec(container, body.argv, body.timeout_s)

    @app.delete("/sandboxes/{run}", status_code=204, dependencies=[Depends(authorised)])
    async def delete(run: str) -> None:
        for s in await sandboxes.sandboxes(valid(run)):
            await sandboxes.remove(s.id)
        locks.pop(run, None)

    return app

"""sandboxd (phase L6b, CR-002 §13): the one service that can start containers.

Workers never touch Docker: they ask sandboxd, over the internal network, with a shared
token. sandboxd holds the Docker socket and offers exactly this:

    PUT    /sandboxes/{run}?epoch=N        the run's sandbox (created on first use)
    POST   /sandboxes/{run}/exec           run argv in it: exit code, stdout, stderr
    DELETE /sandboxes/{run}                gone (the run left `running`)
    GET    /healthz                        Docker reachable

Every sandbox is the same locked-down container (R13.3): the sandbox image, a non-root
user, read-only root, `/workspace` and `/tmp` as small tmpfs, **no network**, no
capabilities, no-new-privileges, CPU, memory and process limits. One per run and epoch
(R13.2): a reclaimed run gets a fresh one and the old epoch's is removed. Old ones are
swept, in case a worker died without saying goodbye.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import struct
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

LABEL = "nuria.sandbox"
MAX_OUTPUT = 20_000
MAX_AGE_S = 2 * 3600  # nothing a run does takes longer (its own timeout is shorter)
SWEEP_EVERY_S = 60
RUN_ID = re.compile(r"^[0-9a-f-]{36}$")


class Limits(BaseModel):
    memory_mb: int = 256
    cpus: float = 0.5
    pids: int = 64
    workspace_mb: int = 64


class Docker:
    """The few Docker Engine API calls sandboxd needs (Adapter), over the socket."""

    def __init__(self, socket_path: str = "/var/run/docker.sock") -> None:
        self._client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=socket_path),
            base_url="http://docker/v1.43",
            timeout=httpx.Timeout(30.0, read=None),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, path: str, **kw: Any) -> httpx.Response:
        response = await self._client.request(method, path, **kw)
        if response.status_code >= 400 and response.status_code != 404:
            raise RuntimeError(
                f"docker {method} {path}: {response.status_code} {response.text[:300]}"
            )
        return response

    async def ping(self) -> bool:
        return (await self._call("GET", "/_ping")).status_code == 200

    async def sandboxes(self, run: str | None = None) -> list[dict[str, Any]]:
        labels = [f"{LABEL}=1"] + ([f"{LABEL}.run={run}"] if run else [])
        response = await self._call(
            "GET",
            "/containers/json",
            params={"all": "true", "filters": json.dumps({"label": labels})},
        )
        found: list[dict[str, Any]] = response.json()
        return found

    async def create(self, run: str, epoch: int, image: str, limits: Limits) -> str:
        body = {
            "Image": image,
            "Cmd": ["sleep", "infinity"],
            "User": "10002",
            "WorkingDir": "/workspace",
            "Env": ["HOME=/workspace", "PYTHONUNBUFFERED=1", "MPLCONFIGDIR=/tmp"],
            "Labels": {
                LABEL: "1",
                f"{LABEL}.run": run,
                f"{LABEL}.epoch": str(epoch),
                f"{LABEL}.created": str(int(time.time())),
            },
            "NetworkDisabled": True,
            "HostConfig": {
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "Tmpfs": {
                    "/workspace": f"size={limits.workspace_mb}m,uid=10002,gid=10002,mode=0700",
                    "/tmp": "size=64m,mode=1777",
                },
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "PidsLimit": limits.pids,
                "Memory": limits.memory_mb * 1024 * 1024,
                "MemorySwap": limits.memory_mb * 1024 * 1024,
                "NanoCpus": int(limits.cpus * 1e9),
                "Init": True,
            },
        }
        response = await self._call(
            "POST",
            "/containers/create",
            params={"name": f"nuria-sbx-{run[:8]}-{epoch}-{int(time.time())}"},
            json=body,
        )
        container = str(response.json()["Id"])
        await self._call("POST", f"/containers/{container}/start")
        return container

    async def remove(self, container: str) -> None:
        await self._call("DELETE", f"/containers/{container}", params={"force": "true"})

    async def exec(self, container: str, argv: list[str], timeout_s: float) -> dict[str, Any]:
        created = await self._call(
            "POST",
            f"/containers/{container}/exec",
            json={
                "AttachStdout": True,
                "AttachStderr": True,
                "Tty": False,
                "Cmd": ["timeout", "-s", "KILL", f"{timeout_s:g}s", *argv],
                "User": "10002",
                "WorkingDir": "/workspace",
            },
        )
        exec_id = created.json()["Id"]
        out, err = bytearray(), bytearray()
        async with self._client.stream(
            "POST",
            f"/exec/{exec_id}/start",
            json={"Detach": False, "Tty": False},
            timeout=httpx.Timeout(timeout_s + 15),
        ) as stream:
            buffer = bytearray()
            async for chunk in stream.aiter_bytes():
                buffer += chunk
                while len(buffer) >= 8:
                    kind, size = buffer[0], struct.unpack(">I", bytes(buffer[4:8]))[0]
                    if len(buffer) < 8 + size:
                        break
                    target = out if kind == 1 else err
                    if len(target) < MAX_OUTPUT * 4:
                        target += buffer[8 : 8 + size]
                    del buffer[: 8 + size]
        state = (await self._call("GET", f"/exec/{exec_id}/json")).json()
        code = state.get("ExitCode")
        return {
            "exit_code": code,
            "timed_out": code == 137,
            "stdout": _text(out),
            "stderr": _text(err),
            "truncated": len(out) > MAX_OUTPUT or len(err) > MAX_OUTPUT,
        }


def _text(raw: bytearray) -> str:
    return bytes(raw).decode("utf-8", errors="replace")[:MAX_OUTPUT]


Arg = Annotated[str, Field(max_length=200_000)]


class ExecRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    epoch: Annotated[int, Field(ge=0)]
    argv: Annotated[
        list[Annotated[str, Field(max_length=200_000)]], Field(min_length=1, max_length=64)
    ]
    timeout_s: Annotated[float, Field(gt=0, le=300)] = 30


def create_app(
    docker: Docker | None = None,
    image: str | None = None,
    token: str | None = None,
    limits: Limits | None = None,
) -> FastAPI:
    docker = docker or Docker()
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
            current = None
            for c in await docker.sandboxes(run):
                if int(c["Labels"].get(f"{LABEL}.epoch", -1)) == epoch and c["State"] == "running":
                    current = c["Id"]
                else:
                    await docker.remove(c["Id"])  # an old epoch's, or a stopped one
            return current or await docker.create(run, epoch, image, limits)

    async def sweep() -> None:
        while True:
            await asyncio.sleep(SWEEP_EVERY_S)
            with contextlib.suppress(Exception):
                now = time.time()
                for c in await docker.sandboxes():
                    if now - int(c["Labels"].get(f"{LABEL}.created", now)) > MAX_AGE_S:
                        await docker.remove(c["Id"])

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(sweep())
        yield
        task.cancel()
        await docker.close()

    app = FastAPI(
        title="Nuria sandboxd",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
        dependencies=[],
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        if not await docker.ping():
            raise HTTPException(503, "docker isn't reachable")
        return {"status": "ok"}

    @app.put("/sandboxes/{run}", dependencies=[Depends(authorised)])
    async def put(run: str, epoch: int) -> dict[str, str]:
        return {"container": await ensure(valid(run), epoch)}

    @app.post("/sandboxes/{run}/exec", dependencies=[Depends(authorised)])
    async def run_in(run: str, body: ExecRequest) -> dict[str, Any]:
        container = await ensure(valid(run), body.epoch)
        return await docker.exec(container, body.argv, body.timeout_s)

    @app.delete("/sandboxes/{run}", status_code=204, dependencies=[Depends(authorised)])
    async def delete(run: str) -> None:
        for c in await docker.sandboxes(valid(run)):
            await docker.remove(c["Id"])
        locks.pop(run, None)

    return app

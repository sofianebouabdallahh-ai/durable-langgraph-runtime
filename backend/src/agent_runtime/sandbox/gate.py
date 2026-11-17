"""sandbox-gate (phase H9, CR-002 R13.4): the only service with the Docker socket.

sandboxd answers the workers over the network, so whoever takes it over shouldn't hold
anything root-equivalent. It reaches Docker through this gate instead, on a Unix socket
in a volume only the two of them share, and the gate lets through what a sandbox needs
and nothing else:

    GET    /_ping /version /info                 always
    GET    /containers/json                      only filtered to sandboxes
    POST   /containers/create                    only our sandbox, exactly (CREATE)
    POST   /containers/{id}/start, DELETE …      only a sandbox (by its label)
    POST   /containers/{id}/exec                 only in a sandbox, as its user (EXEC)
    POST   /exec/{id}/start, GET /exec/{id}/json only an exec in a sandbox

A path-and-method filter isn't enough: `POST /containers/create` with `Privileged` and
the host's `/` mounted is the same path. So the create body is checked field by field,
and a field the gate doesn't know is refused (Specification). Under
`SANDBOX_ISOLATION=gvisor` a create without gVisor's runtime is refused too.
"""

from __future__ import annotations

import json
import os
import re
import socket
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from agent_runtime.sandbox.backend import ENV, GVISOR_HOST_PIDS, LABEL, USER_ID, Limits

MAX_BODY = 16 * 1024 * 1024  # an exec carries code and file contents (sandboxd caps them)
VERSION = re.compile(r"^/v\d+\.\d+(?=/)")
ID = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
NAME = re.compile(r"^nuria-sbx-[0-9a-f-]{1,36}-\d+-\d+$")
TMPFS = {"/workspace", "/tmp"}
TMPFS_OPTIONS = {"size", "uid", "gid", "mode"}  # never exec, suid or dev
HOST_KEYS = {
    "NetworkMode", "ReadonlyRootfs", "Tmpfs", "CapDrop", "SecurityOpt", "PidsLimit",
    "Memory", "MemorySwap", "NanoCpus", "Init", "Runtime",
}  # fmt: skip
CREATE_KEYS = {"Image", "Cmd", "User", "WorkingDir", "Env", "Labels", "NetworkDisabled",
               "HostConfig"}  # fmt: skip
EXEC_KEYS = {"AttachStdout", "AttachStderr", "Tty", "Cmd", "User", "WorkingDir"}


class Refused(Exception):
    """Why the gate said no, in words that end up in sandboxd's log."""


def _check(ok: bool, why: str) -> None:
    if not ok:
        raise Refused(why)


class Rules:
    """What a sandbox is (CREATE) and how code runs in one (EXEC)."""

    def __init__(self, image: str, limits: Limits, runtime: str, gvisor_only: bool) -> None:
        self.image, self.limits, self.runtime, self.gvisor_only = (
            image,
            limits,
            runtime,
            gvisor_only,
        )

    def create(self, name: str, body: Any) -> None:
        _check(isinstance(body, dict), "the body isn't an object")
        _check(bool(NAME.match(name)), f"not a sandbox's name: {name!r}")
        _check(
            set(body) <= CREATE_KEYS, f"fields a sandbox doesn't have: {set(body) - CREATE_KEYS}"
        )
        _check(body.get("Image") == self.image, f"only the sandbox image ({self.image})")
        _check(body.get("User") == str(USER_ID), "only the sandbox's user")
        _check(body.get("NetworkDisabled") is True, "a sandbox has no network")
        labels = body.get("Labels") or {}
        _check(labels.get(LABEL) == "1", "a sandbox carries its label")
        _check(all(k.startswith(LABEL) for k in labels), "only the sandbox's labels")
        env = body.get("Env") or []
        _check(all(isinstance(e, str) and e.split("=")[0] in ENV for e in env),
               "only the sandbox's environment")  # fmt: skip
        self._host(body.get("HostConfig"))

    def _host(self, host: Any) -> None:
        _check(isinstance(host, dict), "a sandbox has its limits")
        _check(set(host) <= HOST_KEYS, f"settings a sandbox doesn't have: {set(host) - HOST_KEYS}")
        _check(host.get("NetworkMode") == "none", "a sandbox has no network")
        _check(host.get("ReadonlyRootfs") is True, "a sandbox's system is read-only")
        _check(host.get("CapDrop") == ["ALL"], "a sandbox has no capabilities")
        _check(host.get("SecurityOpt") == ["no-new-privileges:true"], "no new privileges")
        _check(host.get("Init") is True, "a sandbox reaps its processes")
        runtime = host.get("Runtime")
        _check(runtime in (None, self.runtime), f"only gVisor's runtime ({self.runtime})")
        _check(runtime == self.runtime or not self.gvisor_only, "gVisor is required here")
        pids = host.get("PidsLimit")
        most = GVISOR_HOST_PIDS if runtime else self.limits.pids
        _check(isinstance(pids, int) and 0 < pids <= most, f"at most {most} processes")
        memory = self.limits.memory_mb * 1024 * 1024
        _check(isinstance(host.get("Memory"), int) and 0 < host["Memory"] <= memory,
               f"at most {self.limits.memory_mb} MB")  # fmt: skip
        _check(host.get("MemorySwap") == host.get("Memory"), "no swap beyond the memory")
        cpus = int(self.limits.cpus * 1e9)
        _check(isinstance(host.get("NanoCpus"), int) and 0 < host["NanoCpus"] <= cpus,
               f"at most {self.limits.cpus:g} CPUs")  # fmt: skip
        tmpfs = host.get("Tmpfs")
        _check(isinstance(tmpfs, dict) and set(tmpfs) == TMPFS, "only the workspace and /tmp")
        for options in tmpfs.values():
            keys = {o.split("=")[0] for o in str(options).split(",")}
            _check(keys <= TMPFS_OPTIONS, f"tmpfs options a sandbox doesn't have: {keys}")

    def exec(self, body: Any) -> None:
        _check(isinstance(body, dict) and set(body) <= EXEC_KEYS, "not a sandbox's exec")
        _check(body.get("User") == str(USER_ID), "code runs as the sandbox's user")
        _check(body.get("Tty") is False, "no terminal")
        _check(isinstance(body.get("Cmd"), list) and len(body["Cmd"]) > 0, "a command")

    @staticmethod
    def exec_start(body: Any) -> None:
        _check(body == {"Detach": False, "Tty": False}, "an exec runs attached, no terminal")

    @staticmethod
    def listing(filters: str) -> None:
        try:
            labels = json.loads(filters or "{}").get("label", [])
        except (ValueError, AttributeError):
            labels = []
        _check(f"{LABEL}=1" in labels, "only the sandboxes are listed")


def create_app(
    docker: httpx.AsyncBaseTransport | None = None,
    rules: Rules | None = None,
    socket_path: str = "/var/run/docker.sock",
) -> Starlette:
    if rules is None:
        rules = Rules(
            image=os.environ.get("SANDBOX_IMAGE", "nuria-sandbox:dev"),
            limits=Limits(),
            runtime=os.environ.get("SANDBOX_DOCKER_RUNTIME", "runsc"),
            gvisor_only=os.environ.get("SANDBOX_ISOLATION") == "gvisor",
        )
    client = httpx.AsyncClient(
        transport=docker or httpx.AsyncHTTPTransport(uds=socket_path),
        base_url="http://docker",
        timeout=httpx.Timeout(30.0, read=None),
    )

    async def labelled(container: str, version: str) -> None:
        found = await client.get(f"{version}/containers/{container}/json")
        _check(found.status_code == 200, "no such sandbox")
        _check((found.json().get("Config") or {}).get("Labels", {}).get(LABEL) == "1",
               "not a sandbox")  # fmt: skip

    async def exec_of_sandbox(exec_id: str, version: str) -> None:
        found = await client.get(f"{version}/exec/{exec_id}/json")
        _check(found.status_code == 200, "no such exec")
        await labelled(str(found.json().get("ContainerID", "")), version)

    async def body_of(request: Request) -> Any:
        raw = await request.body()
        _check(len(raw) <= MAX_BODY, "too big")
        try:
            return json.loads(raw) if raw else None
        except ValueError as exc:
            raise Refused("not JSON") from exc

    Check = Callable[[Request, str, dict[str, str]], Any]

    async def plain(request: Request, version: str, ids: dict[str, str]) -> None:
        return None

    async def listing(request: Request, version: str, ids: dict[str, str]) -> None:
        rules.listing(request.query_params.get("filters", ""))

    async def create(request: Request, version: str, ids: dict[str, str]) -> None:
        rules.create(request.query_params.get("name", ""), await body_of(request))

    async def container(request: Request, version: str, ids: dict[str, str]) -> None:
        await labelled(ids["id"], version)

    async def exec_create(request: Request, version: str, ids: dict[str, str]) -> None:
        rules.exec(await body_of(request))
        await labelled(ids["id"], version)

    async def exec_start(request: Request, version: str, ids: dict[str, str]) -> None:
        rules.exec_start(await body_of(request))
        await exec_of_sandbox(ids["id"], version)

    async def exec_state(request: Request, version: str, ids: dict[str, str]) -> None:
        await exec_of_sandbox(ids["id"], version)

    allowed: list[tuple[str, re.Pattern[str], Check]] = [
        (m, re.compile(p), c)
        for m, p, c in (
            ("GET", r"^/_ping$", plain),
            ("HEAD", r"^/_ping$", plain),
            ("GET", r"^/version$", plain),
            ("GET", r"^/info$", plain),
            ("GET", r"^/containers/json$", listing),
            ("POST", r"^/containers/create$", create),
            ("POST", rf"^/containers/(?P<id>{ID})/start$", container),
            ("DELETE", rf"^/containers/(?P<id>{ID})$", container),
            ("POST", rf"^/containers/(?P<id>{ID})/exec$", exec_create),
            ("POST", rf"^/exec/(?P<id>{ID})/start$", exec_start),
            ("GET", rf"^/exec/(?P<id>{ID})/json$", exec_state),
        )
    ]

    async def gate(request: Request) -> Response:
        # The path as sent: request.url is rebuilt from a Host header, which a Unix-socket
        # client may not send (it then holds the socket's own path).
        path: str = request.scope["path"]
        prefix = VERSION.match(path)
        version = prefix.group(0) if prefix else ""
        rest = path[len(version) :]
        try:
            for method, pattern, check in allowed:
                if request.method == method and (found := pattern.match(rest)):
                    await check(request, version, found.groupdict())
                    break
            else:
                raise Refused(f"{request.method} {rest} isn't something a sandbox needs")
        except Refused as why:
            return JSONResponse({"message": f"sandbox-gate: {why}"}, status_code=403)
        upstream = client.build_request(
            request.method,
            path,
            params=request.query_params,
            content=await request.body(),
            headers={"Content-Type": request.headers.get("content-type", "application/json")},
        )
        answer = await client.send(upstream, stream=True)
        return StreamingResponse(
            answer.aiter_raw(),
            status_code=answer.status_code,
            headers={"Content-Type": answer.headers.get("content-type", "application/json")},
            background=BackgroundTask(answer.aclose),
        )

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        yield
        await client.aclose()

    methods = ["GET", "HEAD", "POST", "DELETE", "PUT", "PATCH"]
    return Starlette(routes=[Route("/{path:path}", gate, methods=methods)], lifespan=lifespan)


def listen(path: str, owner: int) -> socket.socket:
    """The gate's socket, for sandboxd's user only (the volume holds nothing else)."""
    if os.path.exists(path):
        os.unlink(path)  # a previous start's
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    os.chown(path, owner, owner)
    os.chmod(path, 0o600)
    return server

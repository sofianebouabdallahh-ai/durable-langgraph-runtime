"""Sandboxes as Docker containers (Adapter; Compose, L6b): the Engine API over the socket.

The API version is the daemon's to say (`/version`): Docker 29 refuses anything older
than 1.44, older engines anything newer than theirs. At the `gvisor` level a sandbox runs
under the `runsc` runtime (H9).
"""

from __future__ import annotations

import asyncio
import json
import struct
import time
from typing import Any

import httpx

from agent_runtime.sandbox.backend import (
    ENV,
    GVISOR_HOST_PIDS,
    LABEL,
    USER_ID,
    Isolation,
    Limits,
    Output,
    Sandbox,
    killed_after,
    labels,
    result,
)

API_VERSION = (1, 44)  # what this adapter is written for, where the daemon allows it


def api_version(daemon: dict[str, Any]) -> str:
    """The version to speak: ours, within what the daemon accepts (its /version)."""

    def parse(v: str) -> tuple[int, int]:
        major, minor = v.split(".")[:2]
        return int(major), int(minor)

    newest = parse(daemon["ApiVersion"])
    oldest = parse(daemon.get("MinAPIVersion", daemon["ApiVersion"]))
    chosen = max(oldest, min(newest, API_VERSION))
    return f"{chosen[0]}.{chosen[1]}"


class Docker:
    def __init__(
        self,
        socket_path: str = "/var/run/docker.sock",
        *,
        runtime: str = "runsc",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            transport=transport or httpx.AsyncHTTPTransport(uds=socket_path),
            base_url="http://docker",
            timeout=httpx.Timeout(30.0, read=None),
        )
        self._runtime = runtime  # gVisor's runtime, as named in the daemon's config
        self._version: str | None = None
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self._client.aclose()

    async def _prefix(self) -> str:
        async with self._lock:
            if self._version is None:
                response = await self._client.get("/version")  # unversioned: any engine
                response.raise_for_status()
                self._version = api_version(response.json())
        return f"/v{self._version}"

    async def _call(self, method: str, path: str, **kw: Any) -> httpx.Response:
        response = await self._client.request(method, await self._prefix() + path, **kw)
        if response.status_code >= 400 and response.status_code != 404:
            raise RuntimeError(
                f"docker {method} {path}: {response.status_code} {response.text[:300]}"
            )
        return response

    async def ping(self) -> bool:
        return (await self._call("GET", "/_ping")).status_code == 200

    async def supports(self, isolation: Isolation) -> bool:
        if isolation == "container":
            return True
        runtimes = (await self._call("GET", "/info")).json().get("Runtimes") or {}
        return self._runtime in runtimes

    async def sandboxes(self, run: str | None = None) -> list[Sandbox]:
        wanted = [f"{LABEL}=1"] + ([f"{LABEL}.run={run}"] if run else [])
        response = await self._call(
            "GET",
            "/containers/json",
            params={"all": "true", "filters": json.dumps({"label": wanted})},
        )
        return [
            Sandbox(
                id=c["Id"],
                epoch=int(c["Labels"].get(f"{LABEL}.epoch", -1)),
                created=int(c["Labels"].get(f"{LABEL}.created", 0)),
                state="running" if c["State"] == "running" else "gone",
            )
            for c in response.json()
        ]

    async def create(
        self, run: str, epoch: int, image: str, limits: Limits, isolation: Isolation
    ) -> str:
        now = int(time.time())
        gvisor = isolation == "gvisor"
        body = {
            "Image": image,
            "Cmd": ["sleep", "infinity"],
            "User": str(USER_ID),
            "WorkingDir": "/workspace",
            "Env": [f"{k}={v}" for k, v in ENV.items()],
            "Labels": labels(run, epoch, now),
            "NetworkDisabled": True,
            "HostConfig": {
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "Tmpfs": {
                    "/workspace": (
                        f"size={limits.workspace_mb}m,uid={USER_ID},gid={USER_ID},mode=0700"
                    ),
                    "/tmp": "size=64m,mode=1777",
                },
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                # Under gVisor the code's limit is inside (exec), this one bounds gVisor.
                "PidsLimit": GVISOR_HOST_PIDS if gvisor else limits.pids,
                "Memory": limits.memory_mb * 1024 * 1024,
                "MemorySwap": limits.memory_mb * 1024 * 1024,
                "NanoCpus": int(limits.cpus * 1e9),
                "Init": True,
                **({"Runtime": self._runtime} if gvisor else {}),
            },
        }
        response = await self._call(
            "POST",
            "/containers/create",
            params={"name": f"nuria-sbx-{run[:8]}-{epoch}-{now}"},
            json=body,
        )
        container = str(response.json()["Id"])
        await self._call("POST", f"/containers/{container}/start")
        return container

    async def remove(self, sandbox: str) -> None:
        await self._call("DELETE", f"/containers/{sandbox}", params={"force": "true"})

    async def exec(
        self, sandbox: str, argv: list[str], timeout_s: float, *, processes: int | None = None
    ) -> dict[str, Any]:
        created = await self._call(
            "POST",
            f"/containers/{sandbox}/exec",
            json={
                "AttachStdout": True,
                "AttachStderr": True,
                "Tty": False,
                "Cmd": killed_after(argv, timeout_s, processes),
                "User": str(USER_ID),
                "WorkingDir": "/workspace",
            },
        )
        exec_id = created.json()["Id"]
        out, err = Output(), Output()
        async with self._client.stream(
            "POST",
            f"{await self._prefix()}/exec/{exec_id}/start",
            json={"Detach": False, "Tty": False},
            timeout=httpx.Timeout(timeout_s + 15),
        ) as stream:
            # Docker's multiplexed stream: an 8-byte header (stream, size), then the bytes.
            buffer = bytearray()
            async for chunk in stream.aiter_bytes():
                buffer += chunk
                while len(buffer) >= 8:
                    kind, size = buffer[0], struct.unpack(">I", bytes(buffer[4:8]))[0]
                    if len(buffer) < 8 + size:
                        break
                    (out if kind == 1 else err).add(bytes(buffer[8 : 8 + size]))
                    del buffer[: 8 + size]
        state = (await self._call("GET", f"/exec/{exec_id}/json")).json()
        return result(state.get("ExitCode"), out, err)

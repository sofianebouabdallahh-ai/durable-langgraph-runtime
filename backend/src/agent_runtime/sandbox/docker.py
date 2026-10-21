"""Sandboxes as Docker containers (Adapter; Compose, L6b): the Engine API over the socket."""

from __future__ import annotations

import json
import struct
import time
from typing import Any

import httpx

from agent_runtime.sandbox.backend import (
    ENV,
    LABEL,
    USER_ID,
    Limits,
    Output,
    Sandbox,
    killed_after,
    labels,
    result,
)


class Docker:
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

    async def create(self, run: str, epoch: int, image: str, limits: Limits) -> str:
        now = int(time.time())
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
            params={"name": f"nuria-sbx-{run[:8]}-{epoch}-{now}"},
            json=body,
        )
        container = str(response.json()["Id"])
        await self._call("POST", f"/containers/{container}/start")
        return container

    async def remove(self, sandbox: str) -> None:
        await self._call("DELETE", f"/containers/{sandbox}", params={"force": "true"})

    async def exec(self, sandbox: str, argv: list[str], timeout_s: float) -> dict[str, Any]:
        created = await self._call(
            "POST",
            f"/containers/{sandbox}/exec",
            json={
                "AttachStdout": True,
                "AttachStderr": True,
                "Tty": False,
                "Cmd": killed_after(argv, timeout_s),
                "User": str(USER_ID),
                "WorkingDir": "/workspace",
            },
        )
        exec_id = created.json()["Id"]
        out, err = Output(), Output()
        async with self._client.stream(
            "POST",
            f"/exec/{exec_id}/start",
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

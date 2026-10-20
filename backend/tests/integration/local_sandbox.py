"""A sandbox backend for tests: temporary folders and local processes, behind the real
sandboxd app (its token, its runs and epochs, its HTTP API, the tools' client).

No isolation at all: it only ever runs the fixed code the scripted model sends in
tests. CI's integration job has no Docker, so this is how Run Python, the terminal and
the workspace files run there. The real backends: sandbox/docker.py, kubernetes.py.
"""

from __future__ import annotations

import asyncio
import shutil
import socket
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn

from agent_runtime.sandbox.backend import Limits, Output, Sandbox, result
from agent_runtime.sandbox.sandboxd import create_app

WORKSPACE = "/workspace"  # what the tools say; here, each sandbox's own folder
SANDBOX_TOKEN = "test-sandbox-token"


class LocalBackend:
    def __init__(self) -> None:
        self._boxes: dict[str, tuple[Path, int, int]] = {}  # id → (folder, epoch, created)
        self.removed: list[str] = []

    async def ping(self) -> bool:
        return True

    async def sandboxes(self, run: str | None = None) -> list[Sandbox]:
        return [
            Sandbox(id=box, epoch=epoch, created=created, state="running")
            for box, (_, epoch, created) in self._boxes.items()
            if run is None or box.startswith(f"{run}:")
        ]

    async def create(self, run: str, epoch: int, image: str, limits: Limits) -> str:
        box = f"{run}:{epoch}"
        self._boxes[box] = (Path(tempfile.mkdtemp(prefix="sbx-")), epoch, int(time.time()))
        return box

    async def remove(self, sandbox: str) -> None:
        if found := self._boxes.pop(sandbox, None):
            shutil.rmtree(found[0], ignore_errors=True)
            self.removed.append(sandbox)

    async def exec(self, sandbox: str, argv: list[str], timeout_s: float) -> dict[str, Any]:
        folder = self._boxes[sandbox][0]
        argv = [a.replace(WORKSPACE, str(folder)) for a in argv]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=folder,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = Output(), Output()
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout_s)
            code = proc.returncode
        except TimeoutError:
            proc.kill()
            stdout, stderr = await proc.communicate()
            code = 137  # as `timeout -s KILL` reports it
        out.add(stdout)
        err.add(stderr.replace(str(folder).encode(), WORKSPACE.encode()))
        return result(code, out, err)

    async def close(self) -> None:
        for box in list(self._boxes):
            await self.remove(box)


@asynccontextmanager
async def local_sandboxd() -> AsyncIterator[tuple[str, LocalBackend]]:
    """The real sandboxd app, over a LocalBackend, on a free port: (its URL, the backend)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    backend = LocalBackend()
    app = create_app(backend=backend, image="local", token=SANDBOX_TOKEN)
    server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110
        await asyncio.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}", backend
    finally:
        server.should_exit = True
        await task

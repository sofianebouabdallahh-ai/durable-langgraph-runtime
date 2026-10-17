"""A throw-away cluster: fresh database, own Redis stream, API + N worker processes."""

from __future__ import annotations

import asyncio
import functools
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx
import psycopg
import psycopg.rows
from psycopg import sql

from agent_runtime.config import get_settings

BACKEND = Path(__file__).resolve().parents[2]

# Short timings so a scenario takes seconds, not minutes. Same code, same ratios.
TIMINGS = {
    "LEASE_TTL_S": "3",
    "HEARTBEAT_S": "1",
    "REAPER_INTERVAL_S": "1",
    "WORKER_BLOCK_MS": "300",
    "RELAY_INTERVAL_S": "2",
    "RELAY_STALE_S": "5",
    "WORKER_GRACE_S": "20",
    "STREAM_POLL_S": "3",  # safety-net poll; visible as a "stall" when Pub/Sub is off
    "API_GRACE_S": "10",
    "LOG_LEVEL": "INFO",
}
LEASE_TTL_S = float(TIMINGS["LEASE_TTL_S"])
REAPER_INTERVAL_S = float(TIMINGS["REAPER_INTERVAL_S"])


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Cluster:
    def __init__(
        self,
        *,
        workers: int = 2,
        concurrency: int = 2,
        api_replicas: list[dict[str, str]] | None = None,
    ) -> None:
        settings = get_settings()
        self._admin_url = settings.database_url(driver="postgresql")
        self.db = f"agent_runtime_e2e_{uuid.uuid4().hex[:8]}"
        # One dict of extra environment per API replica (e.g. live streaming off).
        self.replica_envs = api_replicas or [{}]
        self.workers_n = workers
        self.concurrency = concurrency
        self.logs = Path(tempfile.mkdtemp(prefix="e2e-"))
        self.env = (
            os.environ
            | TIMINGS
            | {
                "POSTGRES_DB": self.db,
                "REDIS_URL": settings.redis_url.rsplit("/", 1)[0] + "/14",
                "WORK_STREAM": f"e2e:{self.db}",
                "PYTHONUNBUFFERED": "1",
            }
        )
        self._log_paths: dict[int, Path] = {}
        self.apis: list[subprocess.Popen[bytes]] = []
        self.clients: list[httpx.AsyncClient] = []
        self.workers: list[subprocess.Popen[bytes]] = []

    # --------------------------------------------------------------- lifecycle

    async def __aenter__(self) -> Cluster:
        # Blocking setup work runs in a thread so the event loop stays responsive.
        await asyncio.to_thread(self._prepare_database)
        for i, extra in enumerate(self.replica_envs):
            port = _free_port()
            self.apis.append(self._spawn(f"api-{i}", "api", "--port", str(port), extra_env=extra))
            self.clients.append(httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=10))
        for i in range(self.workers_n):
            self.start_worker(f"worker-{i}")
        for client in self.clients:
            await self.wait(
                functools.partial(self._api_ready, client), timeout_s=30, what="API ready"
            )
        return self

    @property
    def client(self) -> httpx.AsyncClient:
        """Replica 0, for scenarios that don't care which replica they use."""
        return self.clients[0]

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        for client in self.clients:
            await client.aclose()
        await asyncio.to_thread(self._teardown)

    def _prepare_database(self) -> None:
        with psycopg.connect(self._admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.db)))
        for cmd in (["db", "upgrade"], ["db", "provision-users"]):
            done = subprocess.run(self._cmd(*cmd), cwd=BACKEND, env=self.env, capture_output=True)
            if done.returncode != 0:
                raise RuntimeError(f"runtime {' '.join(cmd)} failed: {done.stderr.decode()}")

    def _teardown(self) -> None:
        procs = [*self.apis, *self.workers]
        for p in procs:
            if p.poll() is None:
                try:
                    p.send_signal(signal.SIGCONT)  # in case a scenario left one stopped
                    p.terminate()
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + 15
        for p in procs:
            try:
                p.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        with psycopg.connect(self._admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(self.db))
            )

    def start_worker(self, name: str) -> subprocess.Popen[bytes]:
        p = self._spawn(name, "worker", "--concurrency", str(self.concurrency))
        self.workers.append(p)
        return p

    def _cmd(self, *args: str) -> list[str]:
        return [sys.executable, "-m", "agent_runtime.cli", *args]

    def _spawn(
        self, name: str, *args: str, extra_env: dict[str, str] | None = None
    ) -> subprocess.Popen[bytes]:
        path = self.logs / f"{name}.log"
        log = path.open("wb")
        env = self.env | (extra_env or {})
        proc = subprocess.Popen(self._cmd(*args), cwd=BACKEND, env=env, stdout=log, stderr=log)
        self._log_paths[proc.pid] = path
        return proc

    def log_of(self, pid: int) -> str:
        return self._log_paths[pid].read_text(errors="replace")

    @staticmethod
    async def _api_ready(client: httpx.AsyncClient) -> bool:
        try:
            return (await client.get("/readyz")).status_code == 200
        except httpx.TransportError:
            return False

    # ----------------------------------------------------------------- the API

    async def create_run(self, **input: Any) -> str:
        resp = await self.client.post("/runs", json={"graph": "toy", "input": input})
        resp.raise_for_status()
        return str(resp.json()["run_id"])

    async def run(self, run_id: str) -> dict[str, Any]:
        resp = await self.client.get(f"/runs/{run_id}")
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        return body

    async def events(self, run_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        after = 0
        while True:
            page = (
                await self.client.get(f"/runs/{run_id}/events", params={"after_seq": after})
            ).json()
            out += page["events"]
            if not page["events"]:
                return out
            after = page["next_after_seq"]

    async def result(self, run_id: str) -> httpx.Response:
        return await self.client.get(f"/runs/{run_id}/result")

    # ----------------------------------------------------------------- helpers

    async def wait(
        self, predicate: Callable[[], Awaitable[bool]], *, timeout_s: float, what: str
    ) -> float:
        """Poll until `predicate` holds; returns the seconds it took."""
        t0 = time.monotonic()
        while not await predicate():
            if time.monotonic() - t0 > timeout_s:
                raise TimeoutError(f"timed out after {timeout_s}s waiting for: {what}")
            await asyncio.sleep(0.1)
        return time.monotonic() - t0

    async def rows(self, query: str, *params: Any) -> list[dict[str, Any]]:
        """Read from this cluster's database (for rows the API doesn't expose)."""

        def run() -> list[dict[str, Any]]:
            url = self._admin_url.rsplit("/", 1)[0] + f"/{self.db}"
            with psycopg.connect(url, row_factory=psycopg.rows.dict_row) as conn:
                return list(conn.execute(query, params).fetchall())

        return await asyncio.to_thread(run)

    async def node_completed(self, run_id: str, node: str) -> bool:
        return any(
            e["type"] == "node.completed" and e["payload"].get("node") == node
            for e in await self.events(run_id)
        )

    async def status_is(self, run_id: str, *statuses: str) -> bool:
        return (await self.run(run_id))["status"] in statuses

    @staticmethod
    def pid_of(owner: str) -> int:
        """Owners are `{hostname}:{pid}` (R2.2), so the lease names the process."""
        return int(owner.rsplit(":", 1)[1])

    def process(self, pid: int) -> subprocess.Popen[bytes]:
        return next(p for p in self.workers if p.pid == pid)

    def log_tail(self, lines: int = 15) -> str:
        parts = []
        for f in sorted(self.logs.glob("*.log")):
            text = f.read_text(errors="replace").splitlines()[-lines:]
            parts.append(f"--- {f.name}\n" + "\n".join(text))
        return "\n".join(parts)

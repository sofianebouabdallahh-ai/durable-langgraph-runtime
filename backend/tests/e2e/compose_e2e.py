"""End-to-end checks against the containerised stack (`./setup.sh`), phase L1.

Unlike tests/e2e (processes on the host), these drive the real images: the API
replicas behind the UI's proxy (as a browser reaches them), the worker containers
under their least-privilege database logins.

    crash      docker kill the worker running a chat turn, mid tool call (AC19)
    graceful   docker stop it instead: SIGTERM → released → resumed elsewhere (R10.7)
    privilege  the worker's login can't drop a table or delete runs (R14.13)

Usage (the stack must be up):
    COMPOSE_PROJECT_NAME=agent-runtime UI_PORT=3000 \\
        uv run python -m tests.e2e.compose_e2e [crash|graceful|privilege|all] [--repeat N]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from typing import Any

import httpx

ROOT = os.environ.get("STACK_DIR") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)  # the checkout whose stack (and .env) to test
API = f"http://127.0.0.1:{os.environ.get('UI_PORT', '3000')}/api"
DOCKER = os.environ.get("DOCKER", "docker")


def compose(*args: str, check: bool = True) -> str:
    out = subprocess.run(
        [DOCKER, "compose", "--file", f"{ROOT}/infra/compose/docker-compose.yml",
         "--env-file", f"{ROOT}/.env", "--profile", "app", *args],
        capture_output=True, text=True, check=check,
    )  # fmt: skip
    return out.stdout


def sql(query: str) -> str:
    psql = f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "{query}"'
    return compose("exec", "-T", "postgres", "sh", "-c", psql).strip()


def wait(cond: Any, timeout_s: float, what: str) -> Any:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if value := cond():
            return value
        time.sleep(0.3)
    raise TimeoutError(f"timed out waiting for {what}")


class Check:
    def __init__(self, name: str) -> None:
        self.name, self.failed = name, False
        print(f"\n== {name}")

    def __call__(self, label: str, ok: bool, detail: str = "") -> None:
        self.failed |= not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def turn_with_slow_tool(client: httpx.Client) -> tuple[str, str]:
    sid = client.post("/sessions", json={"agent": "chat"}).json()["id"]
    resp = client.post(f"/sessions/{sid}/messages", json={"content": "keep this", "script": [
        {"tool_calls": [{"name": "save_note", "args": {"text": "kept", "linger_s": 6}}]},
        {"content": "Kept."},
    ]})  # fmt: skip
    resp.raise_for_status()
    return sid, resp.json()["run_id"]


def owner_container(client: httpx.Client, run_id: str) -> str:
    def owner() -> str | None:
        run = client.get(f"/runs/{run_id}").json()
        return run["owner"] if run["status"] == "running" and run["owner"] else None

    hostname = wait(owner, 30, "a worker to take the turn").split(":")[0]
    # A container's hostname is the first 12 characters of its ID.
    return next(cid for cid in compose("ps", "-q", "worker").split() if cid.startswith(hostname))


def finish(client: httpx.Client, sid: str, run_id: str, c: Check) -> dict[str, Any]:
    wait(lambda: client.get(f"/runs/{run_id}").json()["status"] in ("completed", "failed"),
         120, "the turn to finish")  # fmt: skip
    run = client.get(f"/runs/{run_id}").json()
    events = client.get(f"/runs/{run_id}/events", params={"limit": 500}).json()["events"]
    msgs = client.get(f"/sessions/{sid}/messages").json()["messages"]
    ids = [m["message_id"] for m in msgs]
    notes = sql(f"SELECT count(*) FROM notes WHERE run_id = '{run_id}'")
    c("the turn completed", run["status"] == "completed", run["status"])
    c("zero duplicate messages", len(ids) == len(set(ids)), f"{len(ids)} messages")
    c("the side effect happened once", notes == "1", f"{notes} note(s)")
    return {"run": run, "events": events}


def crash() -> bool:
    c = Check("docker kill a worker mid-turn (AC19 in containers)")
    with httpx.Client(base_url=API, timeout=30) as client:
        sid, run_id = turn_with_slow_tool(client)
        victim = owner_container(client, run_id)
        time.sleep(1.5)  # inside the 6 s tool call
        subprocess.run([DOCKER, "kill", victim], check=True, capture_output=True)
        try:
            got = finish(client, sid, run_id, c)
            types = [e["type"] for e in got["events"]]
            c("exactly one run.reclaimed", types.count("run.reclaimed") == 1)
        finally:
            subprocess.run([DOCKER, "start", victim], capture_output=True)  # back to 2 workers
    return not c.failed


def graceful() -> bool:
    c = Check("docker stop a worker mid-turn: released, resumed elsewhere (R10.7)")
    with httpx.Client(base_url=API, timeout=30) as client:
        sid, run_id = turn_with_slow_tool(client)
        victim = owner_container(client, run_id)
        time.sleep(1.5)
        stopped = time.monotonic()
        subprocess.run(
            [DOCKER, "stop", victim], check=True, capture_output=True
        )  # SIGTERM via tini
        c("the worker shut down within its grace period", time.monotonic() - stopped < 40,
          f"{time.monotonic() - stopped:.1f}s")  # fmt: skip
        try:
            got = finish(client, sid, run_id, c)
            types = [e["type"] for e in got["events"]]
            handed_off = "run.released" in types and "run.reclaimed" not in types
            c("handed off (run.released), not reclaimed", handed_off, str(types[-6:]))
        finally:
            subprocess.run([DOCKER, "start", victim], capture_output=True)
    return not c.failed


def privilege() -> bool:
    c = Check("least privilege at runtime (R14.13)")
    whoami = compose("exec", "-T", "worker", "python", "-c",
                     "import os; print(os.environ['POSTGRES_USER'])").strip()  # fmt: skip
    c("workers connect as their own login", whoami == os.environ.get("WORKER_USER", "agent_worker"),
      whoami)  # fmt: skip
    probe = ("import asyncio, psycopg\n"
             "from agent_runtime.config import get_settings\n"
             "async def go(q):\n"
             "    async with await psycopg.AsyncConnection.connect("
             "get_settings().database_url('postgresql')) as c:\n"
             "        try:\n            await c.execute(q); print('ALLOWED')\n"
             "        except Exception as e: print('DENIED', type(e).__name__)\n"
             "asyncio.run(go(__import__('sys').argv[1]))\n")  # fmt: skip
    for statement in ("DROP TABLE runs", "DELETE FROM runs"):
        out = compose("exec", "-T", "worker", "python", "-c", probe, statement, check=False)
        c(f"the worker can't: {statement}", out.strip().startswith("DENIED"), out.strip())
    return not c.failed


SCENARIOS = {"crash": crash, "graceful": graceful, "privilege": privilege}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", nargs="?", default="all", choices=[*SCENARIOS, "all"])
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    results = [SCENARIOS[n]() for _ in range(args.repeat) for n in names]
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())

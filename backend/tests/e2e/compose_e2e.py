"""End-to-end checks against the containerised stack (`./setup.sh`), phase L1.

Unlike tests/e2e (processes on the host), these drive the real images: the API
replicas behind the UI's proxy (as a browser reaches them), the worker containers
under their least-privilege database logins.

    crash      docker kill the worker running a chat turn, mid tool call (AC19)
    graceful   docker stop it instead: SIGTERM → released → resumed elsewhere (R10.7)
    privilege  the worker's login can't drop a table or delete runs (R14.13)
    sandbox    docker kill the worker while its turn runs Python in the sandbox (L6 SC5)
    mcp        docker kill the worker during an MCP tool call (L8 SC5; profile `test`)
    outsiders  only Nuria's own pages drive it: a foreign Host, a cross-site request (H3)
    outage     docker restart Postgres mid-turn: the turn completes, its side effect once (H4)
    notify     an approved notification reaches the webhook once, signed, after a retry
               (H4; profile `test`; NOTIFY_WEBHOOK_URL=http://fake-model:9999/webhook)

Usage (the stack must be up):
    COMPOSE_PROJECT_NAME=agent-runtime UI_PORT=3000 \\
        uv run python -m tests.e2e.compose_e2e [<scenario>|all] [--repeat N]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
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


def through_the_ui() -> bool:
    """Whether the API answers through the UI proxy, the path every scenario takes.

    The API being healthy isn't enough: when every API container was just recreated
    (CI does, to set the webhook), the proxy can keep their old addresses for a while
    after a failed lookup. A scenario that starts then gets a 502 and tests nothing.
    """
    try:
        return httpx.get(f"{API}/readyz", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


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
        # Its own text: the same note saved again is kept once (H8), and the checks count
        # this run's notes.
        {"tool_calls": [{"name": "save_note",
                         "args": {"text": f"kept {uuid.uuid4().hex[:8]}", "linger_s": 6}}]},
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


def sandbox() -> bool:
    """L6 SC5: the worker dies while its turn's code runs in the sandbox. The turn is
    reclaimed and completes; its result is recorded once; no sandbox outlives it."""
    c = Check("docker kill a worker while its turn runs Python (L6 SC5)")
    project = os.environ.get("COMPOSE_PROJECT_NAME", "agent-runtime")
    running = subprocess.run(
        [DOCKER, "ps", "-q", "--filter", f"label=com.docker.compose.project={project}",
         "--filter", "label=com.docker.compose.service=sandboxd"],
        capture_output=True, text=True,
    ).stdout.strip()  # fmt: skip
    if not running:  # the `sandbox` profile: not in this helper's `compose`
        c("sandboxd runs (setup without --no-sandbox)", False)
        return False
    with httpx.Client(base_url=API, timeout=30) as client:
        sid = client.post("/sessions", json={"agent": "chat"}).json()["id"]
        code = "import time; time.sleep(6); print('done')"
        sent = client.post(f"/sessions/{sid}/messages", json={"content": "slow code", "script": [
            {"tool_calls": [{"name": "run_python", "args": {"code": code}}]},
            {"content": "Ran it."},
        ]})  # fmt: skip
        sent.raise_for_status()
        run_id = sent.json()["run_id"]
        victim = owner_container(client, run_id)
        time.sleep(2.5)  # inside the 6 s of code
        subprocess.run([DOCKER, "kill", victim], check=True, capture_output=True)
        try:
            wait(lambda: client.get(f"/runs/{run_id}").json()["status"] in ("completed", "failed"),
                 120, "the turn to finish")  # fmt: skip
            run = client.get(f"/runs/{run_id}").json()
            events = [
                e["type"]
                for e in client.get(f"/runs/{run_id}/events", params={"limit": 500}).json()[
                    "events"
                ]
            ]
            msgs = client.get(f"/sessions/{sid}/messages").json()["messages"]
            results = [m["content"] for m in msgs if m["type"] == "tool_result"]
            c("the turn completed", run["status"] == "completed", run["status"])
            c("exactly one run.reclaimed", events.count("run.reclaimed") == 1)
            c("its result recorded once, from a finished run",
              len(results) == 1 and (results[0].get("result") or {}).get("stdout") == "done\n",
              str(results)[:200])  # fmt: skip

            def sandboxes() -> list[str]:
                return subprocess.run(
                    [DOCKER, "ps", "-aq", "--filter", f"label=nuria.sandbox.run={run_id}"],
                    capture_output=True, text=True,
                ).stdout.split()  # fmt: skip

            deadline = time.monotonic() + 30  # released as the run ends; swept otherwise
            while sandboxes() and time.monotonic() < deadline:
                time.sleep(0.5)
            left = sandboxes()
            c("no sandbox outlives the turn", not left, f"{len(left)} left")
        finally:
            subprocess.run([DOCKER, "start", victim], capture_output=True)  # back to 2 workers
    return not c.failed


FIXTURE = "http://fake-model:9999"  # the fixture MCP server (profile `test`)


def fixture_calls(tool: str, *, wait_for: int = 0) -> int:
    """How many calls of `tool` the fixture has seen; with `wait_for`, block until that
    many (inside its container, so the worker can be killed while the call is slow)."""
    probe = (
        "import json, time, urllib.request\n"
        f"def n(): return sum(c['tool'] == '{tool}' for c in json.load(urllib.request.urlopen("
        "'http://127.0.0.1:9999/mcp-admin/calls')))\n"
        "end = time.monotonic() + 60\n"
        f"while n() < {wait_for} and time.monotonic() < end: time.sleep(0.05)\n"
        "print(n())\n"
    )
    return int(compose("--profile", "test", "exec", "-T", "fake-model", "python", "-c", probe))


def mcp() -> bool:
    """L8 SC5: the worker dies during an MCP call. The turn completes; a read-only call is
    sent again (it's safe); an approved ask-first call is never sent twice."""
    c = Check("docker kill a worker mid MCP call (L8 SC5)")
    compose("--profile", "test", "up", "-d", "--wait", "fake-model")
    reset = ("import urllib.request; urllib.request.urlopen(urllib.request.Request("
             "'http://127.0.0.1:9999/mcp-admin/reset', method='POST'))")  # fmt: skip

    def reset_fixture() -> bool:
        try:
            compose("--profile", "test", "exec", "-T", "fake-model", "python", "-c", reset)
        except subprocess.CalledProcessError:
            return False
        return True

    # It has no health check: `up --wait` can return before it listens.
    wait(reset_fixture, 60, "the fixture MCP server")
    with httpx.Client(base_url=API, timeout=30) as client:
        server = client.post("/mcp/servers", json={
            "display_name": f"Crash {time.time_ns() % 10**6}", "url": f"{FIXTURE}/mcp/",
            "token": "fake-mcp-token"}).json()  # fmt: skip
        c("the fixture server is ready", server.get("status") == "ready", str(server)[:200])
        tools = f"/mcp/servers/{server['id']}/tools"
        client.put(f"{tools}/lookup", json={"enabled": True, "without_asking": True})
        client.put(f"{tools}/send_message", json={"enabled": True}).raise_for_status()
        lookup, send = (f"mcp__{server['name']}__{t}" for t in ("lookup", "send_message"))

        agent = client.post("/studio/agents", json={"display_name": server["display_name"]}).json()
        doc = {**agent["draft"]["document"], "description": "Checks ferries.",
               "tools": [{"name": lookup}, {"name": send}]}  # fmt: skip
        client.put(f"/studio/agents/{agent['id']}/draft", json=doc).raise_for_status()
        test = client.post(f"/studio/agents/{agent['id']}/test-chat").json()
        hello = {"content": "hi", "script": [{"content": "hi"}]}
        tried = client.post(f"/sessions/{test['id']}/messages", json=hello).json()
        wait(lambda: client.get(f"/runs/{tried['run_id']}").json()["status"] == "completed",
             60, "the test chat")  # fmt: skip
        name = client.post(f"/studio/agents/{agent['id']}/publish", json={}).json()["name"]
        sid = client.post("/sessions", json={"agent": name}).json()["id"]

        def killed_mid_call(script: list[dict[str, Any]], tool: str, approve: bool) -> str:
            before = fixture_calls(tool)  # before the turn: its call may start at once
            sent = client.post(f"/sessions/{sid}/messages", json={"content": "go",
                                                                    "script": script})  # fmt: skip
            sent.raise_for_status()
            run_id: str = sent.json()["run_id"]
            if approve:
                wait(lambda: client.get(f"/runs/{run_id}").json()["status"] == "waiting_approval",
                     60, "the approval")  # fmt: skip
                client.post(f"/sessions/{sid}/approve", json={"decision": "approve"})
            victim = owner_container(client, run_id)
            fixture_calls(tool, wait_for=before + 1)  # the call is in flight (3 s)
            subprocess.run([DOCKER, "kill", victim], check=True, capture_output=True)
            try:
                wait(lambda: client.get(f"/runs/{run_id}").json()["status"]
                     in ("completed", "failed"), 120, "the turn to finish")  # fmt: skip
            finally:
                subprocess.run([DOCKER, "start", victim], capture_output=True)
            c(f"{tool}: the turn completed", client.get(f"/runs/{run_id}").json()["status"]
              == "completed")  # fmt: skip
            return run_id

        def last_result() -> dict[str, Any]:
            msgs = client.get(f"/sessions/{sid}/messages").json()["messages"]
            result: dict[str, Any] = [m for m in msgs if m["type"] == "tool_result"][-1]["content"]
            return result

        def call(tool: str, **args: str) -> dict[str, Any]:
            return {"tool_calls": [{"name": tool, "args": args}]}

        killed_mid_call([call(lookup, topic="Naxos [slow]"), {"content": "ok"}], "lookup", False)
        sent = fixture_calls("lookup")
        c("read-only: sent again after the crash", sent == 2, f"{sent} calls")
        c("read-only: its result reached the chat", "07:30" in str(last_result()))
        killed_mid_call([call(send, to="ops", text="hi [slow]"), {"content": "ok"}],
                        "send_message", True)  # fmt: skip
        sent = fixture_calls("send_message")
        c("ask-first: never sent twice", sent == 1, f"{sent} calls")
        c("ask-first: the chat says it may have run once",
          "may have run once" in str(last_result()), str(last_result())[:200])  # fmt: skip
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


def outsiders() -> bool:
    """H3: only Nuria's own pages drive it. A rebinding page (a foreign Host) gets 421
    from nginx; a cross-site browser request gets 403 from the API and changes nothing;
    the CLI (no browser headers) still works; a model server in Nuria's container's own
    loopback is refused."""
    c = Check("only Nuria's own pages drive it (H3)")
    ui = API.removesuffix("/api")
    with httpx.Client(timeout=10) as raw:
        rebound = raw.get(f"{ui}/api/sessions", headers={"Host": "rebound.evil.example"})
        c("a foreign Host name gets 421 (DNS rebinding)", rebound.status_code == 421,
          str(rebound.status_code))  # fmt: skip
        probe = raw.get(f"{ui}/healthz", headers={"Host": "10.0.0.7"})
        c("the health check answers any name (probes)", probe.status_code == 200)
        before = sql("SELECT count(*) FROM runs WHERE status = 'cancelled'")
        forged = raw.post(f"{API}/admin/cancel-all", headers={
            "Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"})  # fmt: skip
        c("a cross-site request gets 403", forged.status_code == 403, str(forged.status_code))
        after = sql("SELECT count(*) FROM runs WHERE status = 'cancelled'")
        c("…and changed nothing", before == after, f"{before} → {after}")
        mine = raw.get(f"{API}/sessions", headers={"Sec-Fetch-Site": "same-origin"})
        c("Nuria's own page is served", mine.status_code == 200, str(mine.status_code))
        cli = raw.get(f"{API}/sessions")
        c("the CLI (no browser headers) is served", cli.status_code == 200, str(cli.status_code))
        local = raw.post(f"{API}/models/connections", json={
            "display_name": "Itself", "kind": "compatible",
            "base_url": "http://127.0.0.1:8000/v1", "models": ["x"]})  # fmt: skip
        c("127.0.0.1 inside Nuria's container is refused", local.status_code == 422
          and "host.docker.internal" in local.text, local.text[:160])  # fmt: skip
    return not c.failed


def _status(client: httpx.Client, run_id: str) -> str | None:
    """The run's status, or None while the API can't answer (its database restarts)."""
    try:
        resp = client.get(f"/runs/{run_id}")
    except httpx.HTTPError:
        return None
    return str(resp.json()["status"]) if resp.status_code == 200 else None


def outage() -> bool:
    """H4: Postgres restarts while a turn's tool call runs (a failover, an upgrade).
    Nothing fails for good: the turn completes, its side effect once."""
    c = Check("docker restart Postgres mid-turn (H4)")
    with httpx.Client(base_url=API, timeout=30) as client:
        sid, run_id = turn_with_slow_tool(client)
        owner_container(client, run_id)
        time.sleep(1.5)  # inside the 6 s tool call
        restarted = time.monotonic()
        compose("restart", "postgres")
        wait(lambda: _status(client, run_id) is not None, 120, "the API to reach Postgres again")
        c("Postgres was back within a minute", time.monotonic() - restarted < 60,
          f"{time.monotonic() - restarted:.1f}s")  # fmt: skip
        got = finish(client, sid, run_id, c)
        types = [e["type"] for e in got["events"]]
        c("the run never failed", "run.failed" not in types, str(types[-8:]))
    return not c.failed


def _receiver(path: str, method: str = "GET") -> Any:
    """The fixture webhook receiver (inside its container: it has no host port)."""
    probe = (
        "import json, urllib.request\n"
        f"r = urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:9999{path}', "
        f"method='{method}'))\n"
        "print(r.read().decode())\n"
    )
    try:
        out = compose("--profile", "test", "exec", "-T", "fake-model", "python", "-c", probe)
    except subprocess.CalledProcessError:
        return None
    return json.loads(out)


def notify() -> bool:
    """H4: an approved notification goes to the webhook. The receiver is down for the
    first attempt: it gets it again, with the same webhook-id, signed, and never a third
    time."""
    c = Check("an approved notification reaches the webhook once, signed (H4)")
    compose("--profile", "test", "up", "-d", "--wait", "fake-model")
    wait(lambda: _receiver("/webhook/received", "DELETE") is not None, 60, "the receiver")
    _receiver("/webhook/fail?times=1", "POST")
    with httpx.Client(base_url=API, timeout=30) as client:
        state = client.get("/notifications").json()
        c("the stack sends to the fixture receiver, signed",
          state["webhook"] == "fake-model" and state["signed"], str(state)[:160])  # fmt: skip
        if c.failed:
            return False
        sid = client.post("/sessions", json={"agent": "chat"}).json()["id"]
        sent = client.post(f"/sessions/{sid}/messages", json={"content": "tell ops", "script": [
            {"tool_calls": [{"name": "notify", "args": {"to": "ops", "message": "deploy done"}}]},
            {"content": "Told them."},
        ]}).json()  # fmt: skip
        run_id = sent["run_id"]
        wait(lambda: _status(client, run_id) == "waiting_approval", 60, "the approval")
        c("nothing is sent before you approve", _receiver("/webhook/received") == [])
        client.post(f"/sessions/{sid}/approve", json={"decision": "approve"}).raise_for_status()
        wait(lambda: _status(client, run_id) == "completed", 60, "the turn")
        wait(lambda: any(r["answered"] == 200 for r in _receiver("/webhook/received") or []),
             90, "the delivery")  # fmt: skip
        time.sleep(5)  # more sweeps: it must not be sent again
        got = _receiver("/webhook/received") or []
        c("tried twice: down, then delivered", [r["answered"] for r in got] == [500, 200],
          str([r["answered"] for r in got]))  # fmt: skip
        c("the same webhook-id both times", len({r["id"] for r in got}) == 1)
        c("the signature verifies", bool(got) and all(r["verified"] for r in got))
        data = got[-1]["body"]["data"] if got else {}
        c("it says who and what", (data.get("to"), data.get("message")) == ("ops", "deploy done"))
        listed = client.get("/notifications").json()["notifications"][0]
        c("Settings shows it delivered", (listed["status"], listed["attempts"]) == (
            "delivered", 2), str(listed)[:160])  # fmt: skip
    return not c.failed


SCENARIOS = {
    "crash": crash,
    "graceful": graceful,
    "sandbox": sandbox,
    "mcp": mcp,
    "privilege": privilege,
    "outsiders": outsiders,
    "outage": outage,
    "notify": notify,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", nargs="?", default="all", choices=[*SCENARIOS, "all"])
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    wait(through_the_ui, 60, "the API through the UI")
    results = [SCENARIOS[n]() for _ in range(args.repeat) for n in names]
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())

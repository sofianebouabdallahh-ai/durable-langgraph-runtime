"""The phase 2 acceptance scenarios, each a list of named checks.

    crash   AC2 / SC3: SIGKILL the owning worker mid-run
    zombie  AC5 / SC4: SIGSTOP the owner past its lease, then SIGCONT
    release SC5:       SIGTERM the owner; it hands off after its current step
All three also prove SC1: runs are created over HTTP and nobody runs `execute`.
"""

from __future__ import annotations

import asyncio
import json
import signal
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from tests.e2e.harness import LEASE_TTL_S, REAPER_INTERVAL_S, Cluster
from tests.sse import Sse, read_sse

STEP_S = 1.5  # each toy node sleeps this long


@dataclass
class Report:
    scenario: str
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, bool(ok), detail))

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(ok for _, ok, _ in self.checks)


def _count(events: list[dict[str, Any]], type_: str, node: str | None = None) -> int:
    return sum(
        1
        for e in events
        if e["type"] == type_ and (node is None or e["payload"].get("node") == node)
    )


def _ts(event: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(event["ts"])


async def _owned_run_after_plan(c: Cluster) -> tuple[str, str]:
    """Create a run over HTTP; wait until a worker has committed `plan`."""
    run_id = await c.create_run(question="e2e", delay_s=STEP_S)
    await c.wait(lambda: c.node_completed(run_id, "plan"), timeout_s=30, what="plan committed")
    owner = (await c.run(run_id))["owner"]
    assert owner, "run has no owner after plan"
    return run_id, owner


async def crash(c: Cluster) -> Report:
    r = Report("crash (AC2)")
    run_id, owner = await _owned_run_after_plan(c)
    victim = c.pid_of(owner)
    c.process(victim).send_signal(signal.SIGKILL)
    t_kill = time.monotonic()
    await c.wait(
        lambda: c.status_is(run_id, "completed", "failed"), timeout_s=60, what="completion"
    )
    recovered_s = time.monotonic() - t_kill

    run, events = await c.run(run_id), await c.events(run_id)
    budget = LEASE_TTL_S + 2 * REAPER_INTERVAL_S + 2 * STEP_S + 2
    r.check("run completed (no manual command)", run["status"] == "completed", run["status"])
    r.check("exactly one run.reclaimed", _count(events, "run.reclaimed") == 1)
    r.check("epoch incremented 1 → 2", run["epoch"] == 2, f"epoch={run['epoch']}")
    r.check("committed step not re-executed", _count(events, "node.completed", "plan") == 1)
    resumer = next(e for e in events if e["type"] == "run.reclaimed")["payload"]["owner"]
    r.check("finished on another worker", c.pid_of(resumer) != victim, f"{owner} → {resumer}")
    r.check(f"recovered within {budget:.0f}s", recovered_s < budget, f"{recovered_s:.1f}s")
    r.check("result available", (await c.result(run_id)).status_code == 200)
    return r


async def zombie(c: Cluster) -> Report:
    r = Report("zombie (AC5)")
    run_id, owner = await _owned_run_after_plan(c)
    zombie_proc = c.process(c.pid_of(owner))
    zombie_proc.send_signal(signal.SIGSTOP)  # frozen: no heartbeats, no writes

    async def taken_over() -> bool:
        return int((await c.run(run_id))["epoch"]) >= 2

    await c.wait(taken_over, timeout_s=30, what="another worker reclaims")
    zombie_proc.send_signal(signal.SIGCONT)  # wakes up still believing it owns the run
    await c.wait(
        lambda: c.status_is(run_id, "completed", "failed"), timeout_s=60, what="completion"
    )
    await asyncio.sleep(STEP_S + 1)  # give the zombie time to try to write

    run, events = await c.run(run_id), await c.events(run_id)
    takeover = next(e for e in events if e["type"] == "run.reclaimed")
    stale = [e for e in events if e["seq"] > takeover["seq"] and e["epoch"] < takeover["epoch"]]
    r.check("run completed", run["status"] == "completed", run["status"])
    r.check("reclaimed while the owner was frozen", run["epoch"] >= 2, f"epoch={run['epoch']}")
    r.check("zombie wrote nothing after the takeover", not stale, f"{len(stale)} stale event(s)")
    r.check("completed exactly once", _count(events, "run.completed") == 1)
    r.check("one result", (await c.result(run_id)).status_code == 200)
    r.check("zombie process survived and kept serving", zombie_proc.poll() is None)
    r.check(
        "zombie noticed it lost the run (heartbeat/fence) instead of writing",
        "lost ownership" in c.log_of(zombie_proc.pid),
    )
    return r


async def release(c: Cluster) -> Report:
    r = Report("graceful release (SC5)")
    run_id, owner = await _owned_run_after_plan(c)
    leaving = c.process(c.pid_of(owner))
    leaving.send_signal(signal.SIGTERM)  # what Kubernetes sends first
    await c.wait(
        lambda: c.status_is(run_id, "completed", "failed"), timeout_s=60, what="completion"
    )
    exit_code = await _exit_code(leaving, timeout_s=30)

    run, events = await c.run(run_id), await c.events(run_id)
    released = [e for e in events if e["type"] == "run.released"]
    r.check("run completed", run["status"] == "completed", run["status"])
    r.check("handed off with run.released", len(released) == 1)
    r.check(
        "counted as a release, not a reclaim",
        (run["releases"], run["reclaims"], _count(events, "run.reclaimed")) == (1, 0, 0),
        f"releases={run['releases']} reclaims={run['reclaims']}",
    )
    if released:
        restart = next(
            e for e in events if e["type"] == "run.started" and e["seq"] > released[0]["seq"]
        )
        handoff = (_ts(restart) - _ts(released[0])).total_seconds()
        r.check(
            "other worker restarted it in < 5 s",
            handoff < 5,
            f"{handoff:.2f}s (crash path ≥ {LEASE_TTL_S:.0f}s)",
        )
        r.check("restarted by a different worker", restart["payload"]["owner"] != owner)
    r.check("committed step not re-executed", _count(events, "node.completed", "plan") == 1)
    r.check("leaving worker exited cleanly", exit_code == 0, f"exit code {exit_code}")
    return r


async def _exit_code(proc: object, timeout_s: float) -> int | None:
    import subprocess

    assert isinstance(proc, subprocess.Popen)
    t0 = time.monotonic()
    while proc.poll() is None and time.monotonic() - t0 < timeout_s:  # noqa: ASYNC110
        await asyncio.sleep(0.1)
    return proc.poll()


# --------------------------------------------------------------- phase 3: streaming


def _latencies(stream: Sse, opened_at: float) -> list[float]:
    """Commit → client delay for events committed after the stream opened (live ones)."""
    out = []
    for e in stream.events:
        if not e.get("id"):
            continue
        committed = datetime.fromisoformat(json.loads(e["data"])["ts"]).timestamp()
        if committed >= opened_at:
            out.append(e["_received_at"] - committed)
    return sorted(out)


def _p(values: list[float], pct: float) -> float:
    return values[min(len(values) - 1, int(len(values) * pct))] if values else float("nan")


async def replicas(c: Cluster) -> Report:
    """AC3 / SC2: create on replica A, stream from replica B (neither hosts a worker)."""
    r = Report("stream from any replica (AC3)")
    a, b = c.clients
    run_id = (
        await a.post("/runs", json={"graph": "toy", "input": {"question": "ac3", "delay_s": 0.5}})
    ).json()["run_id"]
    opened = time.time()
    stream = await read_sse(b, f"/runs/{run_id}/stream", timeout_s=60)
    in_db = [e["seq"] for e in await c.events(run_id)]
    lat = _latencies(stream, opened)
    r.check(
        "every event arrived on replica B", stream.seqs == in_db, f"{len(stream.seqs)}/{len(in_db)}"
    )
    r.check("in order, no duplicates", stream.seqs == sorted(set(stream.seqs)))
    r.check("stream closed after run.completed", stream.events[-1].get("event") == "run.completed")
    detail = f"p50 {_p(lat, 0.5) * 1000:.0f} ms, p95 {_p(lat, 0.95) * 1000:.0f} ms"
    r.check("p95 delivery latency < 250 ms", _p(lat, 0.95) < 0.25, f"{detail}, {len(lat)} events")
    return r


async def stall(c: Cluster) -> Report:
    """AC3 part 2 / SC5: replica C has Pub/Sub disabled; the same run streamed from B
    (live) and C side by side. C still gets everything, but only at the safety-net
    poll cadence: the stream visibly stalls."""
    r = Report("Pub/Sub disabled: the stream stalls (AC3)")
    _, b, cc = c.clients
    run_id = (
        await b.post("/runs", json={"graph": "toy", "input": {"question": "stall", "delay_s": 1.0}})
    ).json()["run_id"]
    opened = time.time()
    live, polled = await asyncio.gather(
        read_sse(b, f"/runs/{run_id}/stream", timeout_s=60),
        read_sse(cc, f"/runs/{run_id}/stream", timeout_s=60),
    )
    in_db = [e["seq"] for e in await c.events(run_id)]
    lat_live, lat_polled = _latencies(live, opened), _latencies(polled, opened)
    r.check("live replica: every event, in order", live.seqs == in_db)
    r.check("no-Pub/Sub replica: still every event, in order (from Postgres)", polled.seqs == in_db)
    p95_live = _p(lat_live, 0.95)
    r.check(
        "live replica is real-time (p95 < 250 ms)", p95_live < 0.25, f"p95 {p95_live * 1000:.0f} ms"
    )
    median, worst = _p(lat_polled, 0.5), max(lat_polled, default=0)
    r.check(
        "no-Pub/Sub replica visibly stalls (median ≥ 0.5 s)",
        median >= 0.5,
        f"median {median:.2f} s, max {worst:.2f} s (poll every 3 s)",
    )
    return r


async def api_shutdown(c: Cluster) -> Report:
    """SC9 / R10.7: SIGTERM the replica a client is streaming from."""
    r = Report("API replica shutdown mid-stream (R10.7)")
    a, b = c.clients
    run_id = (
        await a.post("/runs", json={"graph": "toy", "input": {"question": "drain", "delay_s": 1.0}})
    ).json()["run_id"]
    reader = asyncio.create_task(read_sse(b, f"/runs/{run_id}/stream", timeout_s=60))
    await c.wait(lambda: c.node_completed(run_id, "plan"), timeout_s=30, what="plan committed")
    replica_b = c.apis[1]
    t0 = time.monotonic()
    replica_b.send_signal(signal.SIGTERM)
    first = await reader
    told = first.events[-1].get("event") == "reconnect" if first.events else False
    last_id = str(first.seqs[-1]) if first.seqs else "0"
    second = await read_sse(
        a, f"/runs/{run_id}/stream", headers={"Last-Event-ID": last_id}, timeout_s=60
    )
    exit_code = await _exit_code(replica_b, timeout_s=15)
    drained_s = time.monotonic() - t0
    in_db = [e["seq"] for e in await c.events(run_id)]
    r.check(
        "client told to reconnect",
        told,
        first.events[-1].get("event", "?") if first.events else "no events",
    )
    r.check(
        "reconnected elsewhere; nothing lost, nothing duplicated",
        first.seqs + second.seqs == in_db,
        f"{len(first.seqs)} + {len(second.seqs)} = {len(in_db)}",
    )
    # uvicorn re-raises the captured SIGTERM after a graceful shutdown (so supervisors
    # see why it stopped): exit status -15 *with* a completed shutdown is clean.
    graceful = "Application shutdown complete" in c.log_of(replica_b.pid)
    r.check(
        "replica shut down gracefully",
        graceful and exit_code in (0, -signal.SIGTERM),
        f"exit {exit_code}, shutdown {'complete' if graceful else 'INCOMPLETE'}",
    )
    r.check("replica drained within its grace period (10 s)", drained_s < 10, f"{drained_s:.1f} s")
    return r


# ------------------------------------------------------ phase 4: tools & approval


async def _assistant_run(c: Cluster, script: list[dict[str, Any]]) -> str:
    resp = await c.client.post(
        "/runs", json={"graph": "assistant", "input": {"message": "e2e", "script": script}}
    )
    resp.raise_for_status()
    return str(resp.json()["run_id"])


async def tool_crash(c: Cluster) -> Report:
    """SC2, window (a): SIGKILL the worker after the tool's side effect but before the
    ledger records the result. The new owner re-executes with the same idempotency key
    and the tool dedupes. (Window (b), killed after the ledger recorded it, replays the
    cached result: tests/integration/test_approval.py.)"""
    r = Report("side effect once across a crash (R2.6)")
    run_id = await _assistant_run(
        c,
        [
            {"tool_calls": [{"name": "save_note", "args": {"text": "keep me", "linger_s": 4}}]},
            {"content": "Saved."},
        ],
    )

    async def note_written() -> bool:
        return bool(await c.rows("SELECT 1 FROM notes WHERE run_id = %s", run_id))

    await c.wait(note_written, timeout_s=30, what="the note is written")  # the effect happened …
    owner = (await c.run(run_id))["owner"]
    c.process(c.pid_of(owner)).send_signal(signal.SIGKILL)  # … and the worker dies mid-step
    await c.wait(
        lambda: c.status_is(run_id, "completed", "failed"), timeout_s=60, what="completion"
    )

    run, events = await c.run(run_id), await c.events(run_id)
    notes = await c.rows("SELECT text FROM notes WHERE run_id = %s", run_id)
    called = [e["payload"] for e in events if e["type"] == "tool.called"]
    r.check("run completed on another worker", run["status"] == "completed", run["status"])
    r.check("exactly one note (no duplicate side effect)", len(notes) == 1, f"{len(notes)} row(s)")
    takeovers = [p["taken_over"] for p in called]
    # [True], not [False, True]: the dead worker's tool.called was staged in its outbox,
    # which commits only with the step's checkpoint, so it died with the worker.
    r.check("the new owner took the call over", takeovers == [True], str(takeovers))
    r.check("one reclaim", _count(events, "run.reclaimed") == 1)
    calls = await c.rows("SELECT tool_calls_total FROM runs WHERE id = %s", run_id)
    r.check("charged once against the tool budget", calls[0]["tool_calls_total"] == 1)
    return r


async def approval_restart(c: Cluster) -> Report:
    """AC4 / SC8: a run waits for approval; EVERY worker is killed; the approval (with
    edits) is given while no worker exists; fresh workers finish it with the edits."""
    r = Report("approval survives a full restart (AC4)")
    run_id = await _assistant_run(
        c,
        [
            {"tool_calls": [{"name": "notify", "args": {"to": "ceo", "message": "draft"}}]},
            {"content": "Notified."},
        ],
    )
    await c.wait(lambda: c.status_is(run_id, "waiting_approval"), timeout_s=30, what="pause")
    paused = await c.run(run_id)
    for worker in c.workers:  # no worker survives
        worker.send_signal(signal.SIGKILL)
        worker.wait()

    edits = {"args": {"to": "ops", "message": "final (edited by a human)"}}
    resp = await c.client.post(
        f"/runs/{run_id}/approve", json={"decision": "approve", "edits": edits}
    )
    approved_without_workers = resp.status_code == 202 and resp.json()["status"] == "queued"

    c.start_worker("fresh-0")
    c.start_worker("fresh-1")
    await c.wait(
        lambda: c.status_is(run_id, "completed", "failed"), timeout_s=60, what="completion"
    )
    run = await c.run(run_id)
    sent = await c.rows(
        "SELECT recipient, message FROM outbox_notifications WHERE run_id = %s", run_id
    )
    r.check(
        "paused with no lease held",
        paused["owner"] is None and paused["interrupt_payload"] is not None,
    )
    r.check(
        "approved while no worker was alive", approved_without_workers, f"HTTP {resp.status_code}"
    )
    r.check("fresh workers completed it", run["status"] == "completed", run["status"])
    expected = [{"recipient": "ops", "message": "final (edited by a human)"}]
    r.check("exactly one notification, with the edits", sent == expected, str(sent))
    return r


SCENARIOS: dict[str, tuple[Callable[[Cluster], Awaitable[Report]], dict[str, Any]]] = {
    "crash": (crash, {}),
    "zombie": (zombie, {}),
    "release": (release, {}),
    "replicas": (replicas, {"api_replicas": [{}, {}]}),
    "stall": (stall, {"api_replicas": [{}, {}, {"STREAM_LIVE_ENABLED": "false"}]}),
    "api-shutdown": (api_shutdown, {"api_replicas": [{}, {}]}),
    "tool-crash": (tool_crash, {}),
    "approval-restart": (approval_restart, {}),
}


async def run_scenario(name: str) -> tuple[Report, str]:
    """Run one scenario in a fresh cluster; returns the report and the logs' tail."""
    scenario, cluster_kwargs = SCENARIOS[name]
    async with Cluster(workers=2, concurrency=2, **cluster_kwargs) as c:
        try:
            report = await scenario(c)
        except Exception as exc:
            report = Report(name)
            report.check("scenario ran to the end", False, repr(exc))
        return report, c.log_tail()

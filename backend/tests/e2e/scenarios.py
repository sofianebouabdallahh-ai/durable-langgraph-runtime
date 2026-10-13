"""The phase 2 acceptance scenarios, each a list of named checks.

    crash   AC2 / SC3: SIGKILL the owning worker mid-run
    zombie  AC5 / SC4: SIGSTOP the owner past its lease, then SIGCONT
    release SC5:       SIGTERM the owner; it hands off after its current step
All three also prove SC1: runs are created over HTTP and nobody runs `execute`.
"""

from __future__ import annotations

import asyncio
import signal
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from tests.e2e.harness import LEASE_TTL_S, REAPER_INTERVAL_S, Cluster

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


SCENARIOS: dict[str, Callable[[Cluster], Awaitable[Report]]] = {
    "crash": crash,
    "zombie": zombie,
    "release": release,
}


async def run_scenario(name: str) -> tuple[Report, str]:
    """Run one scenario in a fresh cluster; returns the report and the logs' tail."""
    async with Cluster(workers=2, concurrency=2) as c:
        try:
            report = await SCENARIOS[name](c)
        except Exception as exc:
            report = Report(name)
            report.check("scenario ran to the end", False, repr(exc))
        return report, c.log_tail()

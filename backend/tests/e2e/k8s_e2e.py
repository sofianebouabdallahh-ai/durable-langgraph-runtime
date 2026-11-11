"""Nuria on the local cluster (kind), phase L4b: demos that print PASS/FAIL.

Each one disturbs the cluster while a chat turn is running, then checks the turn
finished correctly: completed, no duplicate message, its side effect done once.

    smoke     a chat turn through the Ingress
    podkill   force-delete the worker pod running a turn (SIGKILL, no grace): another
              worker reclaims it (AC19 on Kubernetes)
    drain     drain the node of the worker running a turn: the worker hands the run
              off (R10.7), the PDBs keep the API up, no request fails (SC9)
    scale     queue a backlog: KEDA adds workers, then removes them, and every run
              completes (R10.8, SC10)
    upgrade   `helm upgrade` to a new image while a turn runs, then `helm rollback`:
              the migrate Job runs first, no request fails (R10.6, SC11)
    security  the namespace enforces the restricted Pod Security Standard; a pod that
              isn't the API, a worker or the migrate Job can't reach Postgres (SC12)

Usage (the cluster must be up: infra/kind/cluster.sh all):
    uv run python -m tests.e2e.k8s_e2e [scenario|all] [--repeat N]
Settings: K8S_PORT (8090), NAMESPACE (nuria), KUBECTL / HELM (default: .tools/bin).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
API = f"http://127.0.0.1:{os.environ.get('K8S_PORT', '8090')}/api"
NS = os.environ.get("NAMESPACE", "nuria")
RELEASE = "nuria"
KUBECONFIG = os.environ.get("KUBECONFIG", f"{ROOT}/.tools/kubeconfig")  # see cluster.sh
KUBECTL = [os.environ.get("KUBECTL", f"{ROOT}/.tools/bin/kubectl"), "--kubeconfig", KUBECONFIG,
           "--context", "kind-nuria"]  # fmt: skip
HELM = [os.environ.get("HELM", f"{ROOT}/.tools/bin/helm"), "--kubeconfig", KUBECONFIG,
        "--kube-context", "kind-nuria"]  # fmt: skip


def kubectl(*args: str, check: bool = True, ns: bool = True) -> str:
    cmd = [*KUBECTL, *(["-n", NS] if ns else []), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=check).stdout


def sql(query: str) -> str:
    psql = f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "{query}"'
    return kubectl("exec", "postgres-0", "--", "sh", "-c", psql).strip()


def wait(cond: Callable[[], Any], timeout_s: float, what: str) -> Any:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if value := cond():
            return value
        time.sleep(0.3)
    raise TimeoutError(f"timed out waiting for {what}")


class Check:
    def __init__(self, name: str) -> None:
        self.name, self.failed = name, False
        print(f"\n== {name}", flush=True)

    def __call__(self, label: str, ok: bool, detail: str = "") -> None:
        self.failed |= not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""),
              flush=True)  # fmt: skip


class Prober:
    """Polls the API through the Ingress every 200 ms, as a browser would, and counts
    the requests that fail while something is being disrupted."""

    def __init__(self) -> None:
        self.ok = self.failed = 0
        self.errors: list[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> Prober:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        with httpx.Client(base_url=API, timeout=5) as client:
            while not self._stop.is_set():
                try:
                    status = client.get("/about").status_code
                except httpx.HTTPError as exc:
                    status, detail = 0, type(exc).__name__
                else:
                    detail = str(status)
                if status == 200:
                    self.ok += 1
                else:
                    self.failed += 1
                    self.errors.append(detail)
                self._stop.wait(0.2)


def turn_with_slow_tool(client: httpx.Client, linger_s: float = 6) -> tuple[str, str]:
    sid = client.post("/sessions", json={"agent": "chat"}).json()["id"]
    resp = client.post(f"/sessions/{sid}/messages", json={"content": "keep this", "script": [
        {"tool_calls": [{"name": "save_note",  # its own text: a note is kept once (H8)
                         "args": {"text": f"kept {uuid.uuid4().hex[:8]}", "linger_s": linger_s}}]},
        {"content": "Kept."},
    ]})  # fmt: skip
    resp.raise_for_status()
    return sid, resp.json()["run_id"]


def owner_pod(client: httpx.Client, run_id: str) -> str:
    def owner() -> str | None:
        run = client.get(f"/runs/{run_id}").json()
        return run["owner"] if run["status"] == "running" and run["owner"] else None

    return str(wait(owner, 60, "a worker to take the turn"))  # WORKER_ID = the pod's name


def finish(client: httpx.Client, sid: str, run_id: str, c: Check) -> dict[str, Any]:
    wait(lambda: client.get(f"/runs/{run_id}").json()["status"] in ("completed", "failed"),
         180, "the turn to finish")  # fmt: skip
    run = client.get(f"/runs/{run_id}").json()
    events = client.get(f"/runs/{run_id}/events", params={"limit": 500}).json()["events"]
    msgs = client.get(f"/sessions/{sid}/messages").json()["messages"]
    ids = [m["message_id"] for m in msgs]
    notes = sql(f"SELECT count(*) FROM notes WHERE run_id = '{run_id}'")
    c("the turn completed", run["status"] == "completed", run["status"])
    c("zero duplicate messages", len(ids) == len(set(ids)), f"{len(ids)} messages")
    c("the side effect happened once", notes == "1", f"{notes} note(s)")
    return {"run": run, "events": events}


def gap_s(events: list[dict[str, Any]], before: str, after: str) -> float | None:
    """Seconds from the first `before` event to the first `after` event after it."""
    ts = [(e["type"], datetime.fromisoformat(e["ts"])) for e in events]
    start = next((t for typ, t in ts if typ == before), None)
    end = next((t for typ, t in ts if typ == after and start and t > start), None)
    return (end - start).total_seconds() if start and end else None


def pods(component: str) -> list[dict[str, Any]]:
    out = kubectl("get", "pods", "-l", f"app.kubernetes.io/name={component}", "-o", "json")
    return [p for p in json.loads(out)["items"] if not p["metadata"].get("deletionTimestamp")]


def ready(component: str) -> int:
    return sum(
        all(cs.get("ready") for cs in p["status"].get("containerStatuses", []))
        and p["status"].get("phase") == "Running"
        for p in pods(component)
    )


# ------------------------------------------------------------------ scenarios


def smoke() -> bool:
    c = Check("a chat turn through the Ingress")
    with httpx.Client(base_url=API, timeout=30) as client:
        sid, run_id = turn_with_slow_tool(client, linger_s=0)
        finish(client, sid, run_id, c)
        run = client.get(f"/runs/{run_id}").json()
        c("a worker pod owned it (WORKER_ID = pod name)",
          any(e["payload"].get("owner", "").startswith(f"{RELEASE}-worker-")
              for e in client.get(f"/runs/{run_id}/events").json()["events"]),
          str(run.get("owner")))  # fmt: skip
    return not c.failed


def podkill() -> bool:
    c = Check("force-delete the worker pod mid-turn: reclaimed by another (AC19)")
    with httpx.Client(base_url=API, timeout=30) as client:
        sid, run_id = turn_with_slow_tool(client)
        victim = owner_pod(client, run_id)
        time.sleep(1.5)  # inside the 6 s tool call
        kubectl("delete", "pod", victim, "--grace-period=0", "--force", "--wait=false")
        got = finish(client, sid, run_id, c)
        types = [e["type"] for e in got["events"]]
        c("exactly one run.reclaimed", types.count("run.reclaimed") == 1)
        reclaimer = next((e["payload"].get("owner") for e in got["events"]
                          if e["type"] == "run.reclaimed"), None)  # fmt: skip
        c("another pod took it over", reclaimer not in (None, victim), f"{victim} → {reclaimer}")
        took = gap_s(got["events"], "node.started", "run.reclaimed")
        print(f"  info  kill → reclaimed: {took} s (bounded by the lease TTL, 30 s)")
    wait(lambda: ready("worker") >= 2, 120, "the worker Deployment to be whole again")
    return not c.failed


def drain() -> bool:
    c = Check("drain the node of the worker running a turn (SC9)")
    with httpx.Client(base_url=API, timeout=30) as client, Prober() as probe:
        sid, run_id = turn_with_slow_tool(client, linger_s=8)
        victim = owner_pod(client, run_id)
        node = kubectl("get", "pod", victim, "-o", "jsonpath={.spec.nodeName}")
        api_there = [p["metadata"]["name"] for p in pods("api") if p["spec"]["nodeName"] == node]
        time.sleep(1.5)
        started = time.monotonic()
        try:
            kubectl("drain", node, "--ignore-daemonsets", "--delete-emptydir-data",
                    "--timeout=180s", ns=False)  # fmt: skip
            c("the drain completed (PDBs respected)", True, f"{time.monotonic() - started:.1f}s")
            got = finish(client, sid, run_id, c)
        finally:
            kubectl("uncordon", node, ns=False, check=False)
        types = [e["type"] for e in got["events"]]
        c("handed off (run.released), not reclaimed",
          "run.released" in types and "run.reclaimed" not in types, str(types[-6:]))  # fmt: skip
        handoff = gap_s(got["events"], "run.released", "run.started")
        print(f"  info  node {node} had API pod(s) {api_there or 'none'}; hand-off "
              f"released → started elsewhere: {handoff} s")  # fmt: skip
    c("no request failed during the drain", probe.failed == 0,
      f"{probe.ok} ok, {probe.failed} failed {probe.errors[:5]}")  # fmt: skip
    wait(lambda: ready("worker") >= 2 and ready("api") >= 2, 180, "the pods to be back")
    return not c.failed


def scale() -> bool:
    c = Check("a backlog: KEDA adds workers, then removes them (SC10)")
    with httpx.Client(base_url=API, timeout=30) as client:
        before = ready("worker")
        ids = []
        for i in range(24):
            r = client.post(
                "/runs", json={"graph": "toy", "input": {"question": f"q{i}", "delay_s": 8}}
            )
            r.raise_for_status()
            ids.append(r.json()["run_id"])
        peak = wait(lambda: (n := ready("worker")) > before and n, 180, "KEDA to add workers")
        c("KEDA added workers", peak > before, f"{before} → {peak}")
        wait(lambda: all(client.get(f"/runs/{i}").json()["status"] == "completed" for i in ids),
             600, "every queued run to complete")  # fmt: skip
        statuses = [client.get(f"/runs/{i}").json()["status"] for i in ids]
        c("every run completed", statuses.count("completed") == len(ids),
          f"{statuses.count('completed')}/{len(ids)}")  # fmt: skip
        peak = max(peak, ready("worker"))
        wait(lambda: ready("worker") <= before, 420, "KEDA to scale back down")
        c("scaled back down after the cooldown", ready("worker") <= before,
          f"peak {peak} → {ready('worker')}")  # fmt: skip
    return not c.failed


def _helm_revision() -> int:
    return int(json.loads(subprocess.run([*HELM, "-n", NS, "status", RELEASE, "-o", "json"],
               capture_output=True, text=True, check=True).stdout)["version"])  # fmt: skip


def _runtime_images() -> set[str]:
    return {p["spec"]["containers"][0]["image"] for p in pods("api") + pods("worker")}


def upgrade() -> bool:
    c = Check("helm upgrade to a new image mid-turn, then helm rollback (SC11)")
    tag = os.environ.get("TAG", "dev")
    new = f"{tag}-next"
    subprocess.run(["docker", "tag", f"nuria/runtime:{tag}", f"nuria/runtime:{new}"], check=True)
    subprocess.run([f"{ROOT}/.tools/bin/kind", "load", "docker-image", "--name", "nuria",
                    f"nuria/runtime:{new}"], check=True, capture_output=True)  # fmt: skip
    rev = _helm_revision()
    with httpx.Client(base_url=API, timeout=30) as client, Prober() as probe:
        sid, run_id = turn_with_slow_tool(client, linger_s=8)
        owner_pod(client, run_id)
        started = datetime.now().astimezone()
        subprocess.run([*HELM, "-n", NS, "upgrade", RELEASE, f"{ROOT}/infra/helm/agent-runtime",
                        "--reuse-values", "--set", f"image.runtime.tag={new}", "--wait",
                        "--timeout", "10m"], check=True, capture_output=True)  # fmt: skip
        c("the release moved on one revision", _helm_revision() == rev + 1)
        job = json.loads(kubectl("get", "job", f"{RELEASE}-migrate", "-o", "json"))
        created = datetime.fromisoformat(
            job["metadata"]["creationTimestamp"].replace("Z", "+00:00")
        )
        ran = created >= started.replace(microsecond=0) and job["status"].get("succeeded") == 1
        c("the migrate Job ran for this upgrade", ran, job["metadata"]["creationTimestamp"])
        c("the API and workers run the new image", _runtime_images() == {f"nuria/runtime:{new}"},
          str(_runtime_images()))  # fmt: skip
        finish(client, sid, run_id, c)
        subprocess.run([*HELM, "-n", NS, "rollback", RELEASE, str(rev), "--wait",
                        "--timeout", "10m"], check=True, capture_output=True)  # fmt: skip
        wait(lambda: _runtime_images() == {f"nuria/runtime:{tag}"}, 180, "the old pods to go")
        c("rollback restored the previous image", _runtime_images() == {f"nuria/runtime:{tag}"})
    c("no request failed during upgrade and rollback", probe.failed == 0,
      f"{probe.ok} ok, {probe.failed} failed {probe.errors[:5]}")  # fmt: skip
    return not c.failed


def security() -> bool:
    c = Check("restricted Pod Security; NetworkPolicies around Postgres (SC12)")
    labels = json.loads(kubectl("get", "namespace", NS, "-o", "json", ns=False))["metadata"][
        "labels"
    ]
    c("the namespace enforces 'restricted'",
      labels.get("pod-security.kubernetes.io/enforce") == "restricted")  # fmt: skip
    image = "nuria/runtime:dev"
    escalated = {"name": "p", "image": image, "securityContext": {"privileged": True}}
    privileged = subprocess.run(
        [*KUBECTL, "-n", NS, "run", "privileged-probe", f"--image={image}", "--restart=Never",
         "--overrides", json.dumps({"spec": {"containers": [escalated]}})],
        capture_output=True, text=True,
    )  # fmt: skip
    c("a privileged pod is refused", privileged.returncode != 0
      and "violates PodSecurity" in privileged.stderr, privileged.stderr.strip()[:120])  # fmt: skip
    for component in ("ui", "api", "worker", "postgres", "redis"):
        p = pods(component)[0]
        sc = p["spec"]["containers"][0]["securityContext"]
        c(f"{component}: non-root, read-only root, no capabilities, no token",
          sc.get("readOnlyRootFilesystem") is True and sc["capabilities"]["drop"] == ["ALL"]
          and p["spec"]["securityContext"].get("runAsNonRoot") is True
          and not p["spec"].get("automountServiceAccountToken", True))  # fmt: skip

    probe = (
        "import socket\ntry:\n socket.create_connection(('postgres', 5432), 3); print('OPEN')\n"
        "except OSError as e:\n print('BLOCKED', type(e).__name__)"
    )
    api_pod = pods("api")[0]["metadata"]["name"]
    out = kubectl("exec", api_pod, "--", "python", "-c", probe, check=False).strip()
    c("the API reaches Postgres", out == "OPEN", out)
    restricted = {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}}
    container = {
        "name": "intruder",
        "image": "nuria/runtime:dev",
        "imagePullPolicy": "Never",
        "command": ["python", "-c", probe],
        "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}},
    }
    kubectl("delete", "pod", "intruder", "--ignore-not-found", "--wait=true")
    spec = {"spec": {"securityContext": restricted, "containers": [container]}}
    as_intruder = "--labels=app.kubernetes.io/name=intruder"
    kubectl("run", "intruder", f"--image={image}", "--restart=Never", as_intruder,
            "--overrides", json.dumps(spec))  # fmt: skip
    wait(lambda: kubectl("get", "pod", "intruder", "-o", "jsonpath={.status.phase}")
         in ("Succeeded", "Failed"), 90, "the intruder pod to finish")  # fmt: skip
    out = kubectl("logs", "intruder", check=False).strip()
    c("a pod outside the policy can't reach Postgres", out.startswith("BLOCKED"), out)
    kubectl("delete", "pod", "intruder", "--wait=false", check=False)
    return not c.failed


SCENARIOS: dict[str, Callable[[], bool]] = {
    "smoke": smoke, "podkill": podkill, "drain": drain, "scale": scale,
    "upgrade": upgrade, "security": security,
}  # fmt: skip


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

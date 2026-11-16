"""The code sandbox (L6b, L6c, H9): sandboxd's rules over any backend, its isolation
level and the proof of it, what the Docker and Kubernetes adapters ask for, and the
tools' own parts (the notebook-like runner, big files)."""

from __future__ import annotations

import json
import ssl
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from agent_runtime.fencing import Fence, FencedError
from agent_runtime.sandbox import docker as dock
from agent_runtime.sandbox import kubernetes as k8s
from agent_runtime.sandbox import tools as sandbox_tools
from agent_runtime.sandbox.backend import (
    MAX_OUTPUT,
    Isolation,
    Limits,
    Output,
    Sandbox,
    killed_after,
    result,
)
from agent_runtime.sandbox.isolation import KERNEL, PROBE_RUN, Wanted
from agent_runtime.sandbox.sandboxd import create_app
from agent_runtime.tools.pipeline import ToolPipeline
from agent_runtime.tools.policy import RiskClassPolicy
from agent_runtime.tools.spec import ToolContext, ToolRegistry

RUN = str(uuid.uuid4())
TOKEN = {"Authorization": "Bearer t"}

# --------------------------------------------------------------------- shared


def test_every_command_is_killed_at_its_time_limit() -> None:
    assert killed_after(["python", "-c", "x"], 30) == ["timeout", "-s", "KILL", "30s", "python",
                                                       "-c", "x"]  # fmt: skip
    assert killed_after(["ls"], 2.5)[3] == "2.5s"


def test_under_gvisor_the_process_limit_is_set_inside() -> None:
    """RLIMIT_NPROC, set by bash before the command (gVisor counts it in the sandbox)."""
    argv = killed_after(["python", "-c", "x"], 30, processes=64)
    assert argv[:5] == ["bash", "-c", 'ulimit -u "$1" && shift && exec "$@"', "bash", "64"]
    assert argv[5:] == killed_after(["python", "-c", "x"], 30)
    ran = subprocess.run([*argv[:5], "sh", "-c", "ulimit -u"], capture_output=True, text=True)
    assert ran.stdout.strip() == "64"


def test_output_is_bounded_and_a_kill_is_a_timeout() -> None:
    out, err = Output(), Output()
    for _ in range(10):
        out.add(b"x" * MAX_OUTPUT)
    assert len(out.data) <= MAX_OUTPUT * 5  # a flood is cut, not buffered
    r = result(137, out, err)
    assert r["timed_out"] and r["truncated"] and len(r["stdout"]) == MAX_OUTPUT
    assert not result(0, Output(), Output())["timed_out"]


# ----------------------------------------------------------------- sandboxd


class FakeBackend:
    """Records what sandboxd asks a backend for."""

    def __init__(self) -> None:
        self.boxes: dict[str, Sandbox] = {}
        self.created: list[tuple[str, int]] = []
        self.removed: list[str] = []
        self.ran: list[tuple[str, list[str]]] = []
        self.reachable: bool | None = True  # None: the check itself fails
        self.gvisor = False  # this Docker (or cluster) has gVisor
        self.kernel = "Linux version 4.19.0-gvisor #1 SMP"  # what /proc/version says
        self.broken = False  # every create fails (Docker not up yet)
        self.levels: list[Isolation] = []  # the level of each create
        self.processes: list[int | None] = []

    async def ping(self) -> bool:
        if self.reachable is None:
            raise RuntimeError("socket gone")
        return self.reachable

    async def sandboxes(self, run: str | None = None) -> list[Sandbox]:
        return [s for s in self.boxes.values() if run is None or s.id.startswith(run)]

    async def supports(self, isolation: Isolation) -> bool:
        return isolation == "container" or self.gvisor

    async def create(
        self, run: str, epoch: int, image: str, limits: Limits, isolation: Isolation
    ) -> str:
        if self.broken:
            raise RuntimeError("docker isn't up")
        box = f"{run}/{epoch}/{len(self.created)}"
        self.boxes[box] = Sandbox(box, epoch, 0, "running")
        self.created.append((run, epoch))
        self.levels.append(isolation)
        return box

    def runs(self) -> list[tuple[str, int]]:
        """What was created for runs, not for the isolation probe."""
        return [c for c in self.created if c[0] != PROBE_RUN]

    async def remove(self, sandbox: str) -> None:
        self.boxes.pop(sandbox, None)
        self.removed.append(sandbox)

    async def exec(
        self, sandbox: str, argv: list[str], timeout_s: float, *, processes: int | None = None
    ) -> dict[str, Any]:
        self.ran.append((sandbox, argv))
        self.processes.append(processes)
        out = Output()
        if argv == KERNEL:
            out.add(self.kernel.encode())
        return result(0, out, Output())

    async def close(self) -> None:
        pass


def client(backend: FakeBackend, wanted: Wanted = "auto") -> httpx.AsyncClient:
    app = create_app(backend=backend, image="img", token="t", wanted=wanted)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://sbx")


async def test_sandboxd_needs_its_token_and_a_run_id() -> None:
    async with client(FakeBackend()) as c:
        body = {"epoch": 1, "argv": ["ls"]}
        assert (await c.post(f"/sandboxes/{RUN}/exec", json=body)).status_code == 401
        wrong = {"Authorization": "Bearer nope"}
        assert (await c.post(f"/sandboxes/{RUN}/exec", json=body, headers=wrong)).status_code == 401
        bad = await c.post("/sandboxes/../etc/exec", json=body, headers=TOKEN)
        assert bad.status_code in (404, 422)
        assert (
            await c.post("/sandboxes/not-a-run/exec", json=body, headers=TOKEN)
        ).status_code == 422


async def test_one_sandbox_per_run_and_epoch() -> None:
    backend = FakeBackend()
    async with client(backend) as c:
        for _ in range(2):
            r = await c.post(f"/sandboxes/{RUN}/exec", json={"epoch": 1, "argv": ["ls"]},
                             headers=TOKEN)  # fmt: skip
            assert r.status_code == 200
        assert backend.runs() == [(RUN, 1)]  # reused
        await c.post(f"/sandboxes/{RUN}/exec", json={"epoch": 2, "argv": ["ls"]}, headers=TOKEN)
        assert backend.runs() == [(RUN, 1), (RUN, 2)]  # a reclaimed run: a fresh one
        assert [r for r in backend.removed if r.startswith(RUN)] == [f"{RUN}/1/1"]  # gone
        assert (await c.delete(f"/sandboxes/{RUN}", headers=TOKEN)).status_code == 204
        assert backend.boxes == {}


async def test_an_older_epoch_cannot_remove_a_newer_sandbox() -> None:
    """The review of 2026-11-12: a worker frozen between a tool's begin and finish asks
    with its old epoch. It must not take down the sandbox (and workspace) of the worker
    that took the run over: the sandbox follows the newest epoch, as the database does."""
    backend = FakeBackend()
    async with client(backend) as c:
        assert (await c.put(f"/sandboxes/{RUN}?epoch=2", headers=TOKEN)).status_code == 200
        (box,) = backend.boxes
        stale = await c.put(f"/sandboxes/{RUN}?epoch=1", headers=TOKEN)
        assert stale.status_code == 409 and "epoch 2" in stale.json()["detail"]
        assert box in backend.boxes and not any(r.startswith(RUN) for r in backend.removed)
        again = await c.put(f"/sandboxes/{RUN}?epoch=2", headers=TOKEN)
        assert again.json()["container"] == box and backend.runs() == [(RUN, 2)]  # kept, reused


async def test_a_stale_goodbye_leaves_the_newer_sandbox() -> None:
    """The same rule for the goodbye (DELETE). A worker frozen between its run pausing and
    its goodbye wakes after the run was resumed elsewhere: its goodbye removes its own
    epoch's sandbox at most, never the new owner's. The owner's removes it. One without an
    epoch (a worker from before this rule) removes every sandbox of the run, as before."""
    backend = FakeBackend()
    async with client(backend) as c:
        await c.put(f"/sandboxes/{RUN}?epoch=2", headers=TOKEN)
        (box,) = backend.boxes
        assert (await c.delete(f"/sandboxes/{RUN}?epoch=1", headers=TOKEN)).status_code == 204
        assert box in backend.boxes and box not in backend.removed  # the stale one's
        again = await c.put(f"/sandboxes/{RUN}?epoch=2", headers=TOKEN)
        assert again.json()["container"] == box  # still the owner's, reused
        assert (await c.delete(f"/sandboxes/{RUN}?epoch=2", headers=TOKEN)).status_code == 204
        assert backend.boxes == {}  # the owner's
        await c.put(f"/sandboxes/{RUN}?epoch=3", headers=TOKEN)
        assert (await c.delete(f"/sandboxes/{RUN}", headers=TOKEN)).status_code == 204
        assert backend.boxes == {}  # no epoch: all of them


async def test_exec_at_a_stale_epoch_is_refused() -> None:
    """exec goes through the same rule: nothing runs, and no sandbox is made, for it."""
    backend = FakeBackend()
    async with client(backend) as c:

        async def ls(epoch: int) -> httpx.Response:
            body = {"epoch": epoch, "argv": ["ls"]}
            return await c.post(f"/sandboxes/{RUN}/exec", json=body, headers=TOKEN)

        assert (await ls(3)).status_code == 200
        assert (await ls(2)).status_code == 409
        ran = [box for box, _ in backend.ran if box.startswith(RUN)]
        assert len(ran) == 1 and ran[0].startswith(f"{RUN}/3/")
        assert backend.runs() == [(RUN, 3)]


async def test_a_stopped_sandbox_is_replaced() -> None:
    backend = FakeBackend()
    async with client(backend) as c:
        await c.put(f"/sandboxes/{RUN}?epoch=1", headers=TOKEN)
        (box,) = backend.boxes
        backend.boxes[box] = Sandbox(box, 1, 0, "gone")
        await c.put(f"/sandboxes/{RUN}?epoch=1", headers=TOKEN)
        assert len(backend.runs()) == 2 and box in backend.removed


async def test_health_says_whether_the_backend_answers() -> None:
    backend = FakeBackend()
    async with client(backend) as c:
        assert (await c.get("/healthz")).status_code == 200
        backend.reachable = False
        assert (await c.get("/healthz")).status_code == 503
        backend.reachable = None  # raises
        assert (await c.get("/healthz")).status_code == 503


async def exec_ls(c: httpx.AsyncClient) -> httpx.Response:
    return await c.post(f"/sandboxes/{RUN}/exec", json={"epoch": 1, "argv": ["ls"]}, headers=TOKEN)


async def test_with_gvisor_every_sandbox_runs_under_it_and_is_limited_inside() -> None:
    backend = FakeBackend()
    backend.gvisor = True
    async with client(backend) as c:
        r = await exec_ls(c)
        assert r.status_code == 200 and r.json()["isolation"] == "gvisor"
        assert set(backend.levels) == {"gvisor"}  # the probe's, and the run's
        assert backend.ran[0][1] == KERNEL and backend.processes[-1] == Limits().pids
        assert (PROBE_RUN, 0) in backend.created and not any(
            b.startswith(PROBE_RUN) for b in backend.boxes
        )  # the probe's sandbox is gone
        health = (await c.get("/healthz")).json()
        assert health["isolation"] == "gvisor" and health["wanted"] == "auto"


async def test_without_gvisor_auto_says_the_kernel_is_shared() -> None:
    backend = FakeBackend()
    async with client(backend) as c:
        r = await exec_ls(c)
        assert r.status_code == 200 and r.json()["isolation"] == "container"
        assert set(backend.levels) == {"container"} and backend.processes[-1] is None
        assert "sharing this computer's kernel" in (await c.get("/healthz")).json()["reason"]


async def test_gvisor_required_without_it_runs_nothing() -> None:
    """Fails closed: no sandbox for the run, at any level, and the reason in plain words."""
    backend = FakeBackend()
    async with client(backend, "gvisor") as c:
        r = await exec_ls(c)
        assert r.status_code == 503 and "gVisor is required" in r.json()["detail"]
        assert backend.created == []
        assert (await c.get("/healthz")).json()["isolation"] is None


async def test_a_runtime_only_named_gvisor_doesnt_count() -> None:
    backend = FakeBackend()
    backend.gvisor, backend.kernel = True, "Linux version 6.8.0-49-generic"
    async with client(backend, "gvisor") as c:
        r = await exec_ls(c)
        assert r.status_code == 503 and "didn't run gVisor's kernel" in r.json()["detail"]
        assert backend.runs() == []
    async with client(backend) as c:  # auto: the shared kernel, and it says so
        assert (await exec_ls(c)).json()["isolation"] == "container"


async def test_a_failed_check_is_tried_again_never_taken_as_lower() -> None:
    backend = FakeBackend()
    backend.gvisor, backend.broken = True, True
    async with client(backend, "gvisor") as c:
        r = await exec_ls(c)
        assert r.status_code == 503 and "starting" in r.json()["detail"]
        backend.broken = False
        r = await exec_ls(c)
        assert r.status_code == 200 and r.json()["isolation"] == "gvisor"


@pytest.mark.parametrize(
    ("daemon", "spoken"),
    [
        ({"ApiVersion": "1.52", "MinAPIVersion": "1.44"}, "1.44"),  # Docker 29
        ({"ApiVersion": "1.48", "MinAPIVersion": "1.24"}, "1.44"),  # Docker 28
        ({"ApiVersion": "1.43", "MinAPIVersion": "1.12"}, "1.43"),  # Docker 24: its newest
        ({"ApiVersion": "1.60", "MinAPIVersion": "1.50"}, "1.50"),  # later: its oldest
    ],
)
def test_the_docker_api_version_is_the_daemons_to_allow(
    daemon: dict[str, str], spoken: str
) -> None:
    assert dock.api_version(daemon) == spoken


class FakeDocker:
    """The Engine API, as far as the adapter uses it: it records every request."""

    def __init__(self, daemon: dict[str, Any], runtimes: dict[str, Any]) -> None:
        self.daemon, self.runtimes = daemon, runtimes
        self.requests: list[tuple[str, str, Any]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        path = request.url.path
        if path == "/version":
            return httpx.Response(200, json=self.daemon)
        if path.endswith("/_ping"):
            return httpx.Response(200, text="OK")
        if not path.startswith("/v1.44/"):
            return httpx.Response(400, json={"message": "client version is too old"})
        if path.endswith("/info"):
            return httpx.Response(200, json={"Runtimes": self.runtimes})
        if path.endswith("/containers/create"):
            return httpx.Response(201, json={"Id": "c1"})
        if path.endswith("/exec") and request.method == "POST":
            return httpx.Response(201, json={"Id": "e1"})
        if path.endswith("/exec/e1/start"):
            return httpx.Response(200, content=b"\x01\x00\x00\x00\x00\x00\x00\x02ok")
        if path.endswith("/exec/e1/json"):
            return httpx.Response(200, json={"ExitCode": 0})
        return httpx.Response(204)

    def adapter(self) -> dock.Docker:
        return dock.Docker(transport=httpx.MockTransport(self.handle))

    def sent(self, path_end: str) -> Any:
        return next(b for _, p, b in self.requests if p.endswith(path_end))


DOCKER_29 = {"ApiVersion": "1.52", "MinAPIVersion": "1.44"}


async def test_docker_29_is_spoken_to_in_a_version_it_accepts() -> None:
    """The bug H9 found: v1.43, pinned, was refused by Docker 29 (400, "too old")."""
    fake = FakeDocker(DOCKER_29, {"runc": {}})
    docker = fake.adapter()
    assert await docker.ping()
    await docker.create(RUN, 1, "img", Limits(), "container")
    assert all(p.startswith("/v1.44/") for _, p, _ in fake.requests if p != "/version")
    assert sum(p == "/version" for _, p, _ in fake.requests) == 1  # asked once
    await docker.close()


async def test_docker_under_gvisor_bounds_gvisor_and_limits_the_code_inside() -> None:
    fake = FakeDocker(DOCKER_29, {"runc": {}, "runsc": {"path": "/usr/local/bin/runsc"}})
    docker = fake.adapter()
    assert await docker.supports("gvisor") and await docker.supports("container")
    await docker.create(RUN, 1, "img", Limits(), "gvisor")
    host = fake.sent("/containers/create")["HostConfig"]
    assert host["Runtime"] == "runsc" and host["PidsLimit"] == 512
    assert host["NetworkMode"] == "none" and host["ReadonlyRootfs"] and host["CapDrop"] == ["ALL"]
    done = await docker.exec("c1", ["ls"], 10, processes=64)
    assert done["stdout"] == "ok" and done["exit_code"] == 0
    assert fake.sent("/containers/c1/exec")["Cmd"] == killed_after(["ls"], 10, 64)
    await docker.close()


async def test_docker_without_gvisor_keeps_the_host_process_limit() -> None:
    fake = FakeDocker(DOCKER_29, {"runc": {}})
    docker = fake.adapter()
    assert not await docker.supports("gvisor")
    await docker.create(RUN, 1, "img", Limits(), "container")
    host = fake.sent("/containers/create")["HostConfig"]
    assert "Runtime" not in host and host["PidsLimit"] == Limits().pids
    await docker.close()


# --------------------------------------------------------------- Kubernetes


@pytest.fixture
def cluster(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A pod's service account folder, as the kubelet mounts it."""
    for name, text in (("token", "tok"), ("ca.crt", "-"), ("namespace", "nuria-sandboxes")):
        (tmp_path / name).write_text(text)
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.96.0.1")
    plain = ssl.create_default_context()  # the CA file above isn't a real one
    monkeypatch.setattr(ssl, "create_default_context", lambda **_: plain)
    return tmp_path


def test_a_sandbox_pod_is_locked_down(cluster: Path) -> None:
    pod = k8s.Kubernetes(account=cluster)._pod("nuria-sbx-x-1", RUN, 1, "img", Limits(),
                                               "container")  # fmt: skip
    spec = pod["spec"]
    (box,) = spec["containers"]
    assert spec["automountServiceAccountToken"] is False and spec["enableServiceLinks"] is False
    assert spec["securityContext"]["runAsNonRoot"] and spec["securityContext"]["runAsUser"] == 10002
    assert spec["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
    assert box["securityContext"] == {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
    }
    assert box["resources"]["limits"] == {"cpu": "0.5", "memory": "256Mi"}
    assert all(v["emptyDir"]["medium"] == "Memory" for v in spec["volumes"])
    assert "hostNetwork" not in spec and "runtimeClassName" not in spec and "hostUsers" not in spec
    assert pod["metadata"]["labels"]["nuria.sandbox.run"] == RUN
    stronger = k8s.Kubernetes(account=cluster, user_namespaces=True)
    spec = stronger._pod("p", RUN, 1, "img", Limits(), "gvisor")["spec"]
    assert spec["runtimeClassName"] == "gvisor" and spec["hostUsers"] is False
    named = k8s.Kubernetes(account=cluster, runtime_class="gvisor-systrap")
    assert named._pod("p", RUN, 1, "img", Limits(), "gvisor")["spec"]["runtimeClassName"] == (
        "gvisor-systrap"
    )


@pytest.mark.parametrize(
    ("status", "text", "has"),
    [
        (201, "{}", True),
        (403, 'pods "x" is forbidden: pod rejected: RuntimeClass "gvisor" not found', False),
    ],
)
async def test_kubernetes_asks_admission_whether_gvisor_is_there(
    cluster: Path, status: int, text: str, has: bool
) -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, text=text)

    kube = k8s.Kubernetes(account=cluster)
    kube._client = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="https://k")
    assert await kube.supports("gvisor") is has
    assert seen[0].url.params["dryRun"] == "All"  # nothing is created
    assert json.loads(seen[0].content)["spec"]["runtimeClassName"] == "gvisor"
    assert await kube.supports("container")


async def test_kubernetes_says_nothing_about_gvisor_when_it_cant_tell(cluster: Path) -> None:
    """A quota or an outage isn't "no gVisor": sandboxd tries again, never settles lower."""
    kube = k8s.Kubernetes(account=cluster)
    kube._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(403, text="exceeded quota")),
        base_url="https://k",
    )
    with pytest.raises(RuntimeError):
        await kube.supports("gvisor")


def test_pod_states_and_exit_statuses() -> None:
    def pod(phase: str, **meta: Any) -> dict[str, Any]:
        labels = {"nuria.sandbox.epoch": "3", "nuria.sandbox.created": "7"}
        return {"metadata": {"name": "p", "labels": labels, **meta}, "status": {"phase": phase}}

    assert k8s._sandbox(pod("Running")) == Sandbox("p", 3, 7, "running")
    assert k8s._sandbox(pod("Pending")).state == "starting"
    assert k8s._sandbox(pod("Failed")).state == "gone"
    assert k8s._sandbox(pod("Running", deletionTimestamp="now")).state == "gone"
    assert k8s._exit_code({"status": "Success"}) == 0
    failed = {"status": "Failure", "details": {"causes": [{"reason": "ExitCode", "message": "3"}]}}
    assert k8s._exit_code(failed) == 3
    with pytest.raises(RuntimeError):
        k8s._exit_code(None)
    with pytest.raises(RuntimeError, match="couldn't run"):
        k8s._exit_code({"status": "Failure", "message": "container not found"})


def test_the_launcher_runs_the_argv_from_stdin_with_an_empty_stdin() -> None:
    """Large arguments travel on the exec's stdin, not in the URL (L6c)."""
    big = "x" * 100_000  # Linux caps one argument at 128 KiB; the URL would be the problem
    argv = [sys.executable, "-c", "import sys; print(len(sys.argv[1]), repr(sys.stdin.read()))",
            big]  # fmt: skip
    done = subprocess.run([sys.executable, "-c", k8s.LAUNCHER], input=json.dumps(argv) + "\n",
                          capture_output=True, text=True, timeout=30, check=True)  # fmt: skip
    assert done.stdout.strip() == "100000 ''"


# -------------------------------------------------------------------- tools


def runner(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-c", sandbox_tools.RUN, code], capture_output=True,
                          text=True, timeout=30)  # fmt: skip


def test_run_python_shows_a_last_expression_like_a_notebook() -> None:
    assert (
        runner("prices = [22.0, 87.7]\n[round(p * 4, 2) for p in prices]").stdout
        == "[88.0, 350.8]\n"
    )
    assert runner("print(6 * 7)").stdout == "42\n"  # printing: not shown twice
    assert runner("x = 5").stdout == ""
    assert runner("def f(n):\n    return n * 2\nf(21)").stdout == "42\n"
    assert runner("if __name__ == '__main__':\n    print('main')").stdout == "main\n"
    assert runner("import sys\nsys.exit(3)").returncode == 3


def test_run_python_errors_point_at_the_codes_own_lines() -> None:
    err = runner("a = 1\nb = 0\na / b")
    assert err.returncode == 1 and 'File "<code>", line 3' in err.stderr
    assert "ZeroDivisionError" in err.stderr and "<string>" not in err.stderr
    syntax = runner("def f(:\n  pass")
    assert syntax.returncode == 1 and "SyntaxError" in syntax.stderr


async def test_files_go_in_pieces_and_long_ones_are_read_in_part(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One argument is capped at 128 KiB (Linux): a 100 KB file goes in pieces; a read
    returns what fits in sandboxd's output, and says how to read the rest."""
    sent: list[list[str]] = []

    async def fake_exec(ctx: ToolContext, argv: list[str], timeout_s: float) -> dict[str, Any]:
        sent.append(argv)
        if sandbox_tools.READ in argv:
            body = "y" * sandbox_tools.READ_BYTES
            import base64

            return {"exit_code": 0, "stdout": f"60000\n{base64.b64encode(body.encode()).decode()}",
                    "stderr": ""}  # fmt: skip
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(sandbox_tools, "_exec", fake_exec)
    ctx = ToolContext(run_id=uuid.uuid4(), epoch=1, key="k", pool=None)  # type: ignore[arg-type]
    content = "z" * sandbox_tools.MAX_FILE_BYTES
    write = sandbox_tools.FilesArgs(action="write", path="data/big.txt", content=content)
    assert (await sandbox_tools.workspace_files(write, ctx))["written"] == len(content)
    pieces = sent[-1][4:]
    assert len(pieces) > 1 and all(len(p) <= sandbox_tools.ARG_CHUNK for p in pieces)
    read = await sandbox_tools.workspace_files(
        sandbox_tools.FilesArgs(action="read", path="data/big.txt"), ctx
    )
    assert read["size"] == 60000 and len(read["content"]) == sandbox_tools.READ_BYTES
    assert "run_shell" in read["note"]
    with pytest.raises(sandbox_tools.SandboxError, match="workspace"):
        await sandbox_tools.workspace_files(
            sandbox_tools.FilesArgs(action="read", path="../../etc/passwd"), ctx
        )


async def test_a_stale_workers_sandbox_call_ends_as_fenced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sandboxd's 409 is the fence, seen from the sandbox: `_exec` raises FencedError (with
    the epoch that owns the run now), and the pipeline's execute stage lets it through, so
    the executor stops this worker. Any other refusal stays a tool error the model reads."""
    backend = FakeBackend()
    app = create_app(backend=backend, image="img", token="t", wanted="auto")

    class Through(httpx.AsyncClient):
        """The client `_exec` builds for itself, pointed at the test app."""

        def __init__(self, **kwargs: Any) -> None:
            super().__init__(transport=httpx.ASGITransport(app=app), **kwargs)

    settings = SimpleNamespace(sandboxd_url="http://sbx", sandboxd_token=SecretStr("t"))
    monkeypatch.setattr(httpx, "AsyncClient", Through)
    monkeypatch.setattr(sandbox_tools, "get_settings", lambda: settings)
    run_id = uuid.uuid4()
    owner = ToolContext(run_id=run_id, epoch=2, key="k", pool=None)  # type: ignore[arg-type]
    stale = ToolContext(run_id=run_id, epoch=1, key="k", pool=None)  # type: ignore[arg-type]
    ls = sandbox_tools.ShellArgs(command="ls")
    assert (await sandbox_tools.run_shell(ls, owner))["exit_code"] == 0
    with pytest.raises(FencedError) as fenced:
        await sandbox_tools.run_shell(ls, stale)
    assert fenced.value.fence == Fence(run_id, 1) and fenced.value.current_epoch == 2
    assert backend.runs() == [(str(run_id), 2)]  # the owner's sandbox, untouched
    await sandbox_tools.release(str(run_id), stale.epoch)  # its goodbye, as the executor's
    assert await backend.sandboxes(str(run_id))  # the owner's sandbox, still there

    registry = sandbox_tools.register(ToolRegistry())
    pipeline = ToolPipeline(registry, RiskClassPolicy(), interrupt=lambda _: None)
    spec = registry.get("run_shell")
    with pytest.raises(FencedError):  # not a "failed" result: this worker stops
        await pipeline._execute(spec, {"command": "ls"}, stale)
    settings.sandboxd_url = ""
    status, result = await pipeline._execute(spec, {"command": "ls"}, owner)
    assert status == "failed" and result["error"].startswith("SandboxError")

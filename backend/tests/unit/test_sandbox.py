"""The code sandbox (L6b, L6c): sandboxd's rules over any backend, the Kubernetes Pod it
asks for, and the tools' own parts (the notebook-like runner, big files)."""

from __future__ import annotations

import json
import ssl
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_runtime.sandbox import kubernetes as k8s
from agent_runtime.sandbox import tools as sandbox_tools
from agent_runtime.sandbox.backend import (
    MAX_OUTPUT,
    Limits,
    Output,
    Sandbox,
    killed_after,
    result,
)
from agent_runtime.sandbox.sandboxd import create_app
from agent_runtime.tools.spec import ToolContext

RUN = str(uuid.uuid4())
TOKEN = {"Authorization": "Bearer t"}

# --------------------------------------------------------------------- shared


def test_every_command_is_killed_at_its_time_limit() -> None:
    assert killed_after(["python", "-c", "x"], 30) == ["timeout", "-s", "KILL", "30s", "python",
                                                       "-c", "x"]  # fmt: skip
    assert killed_after(["ls"], 2.5)[3] == "2.5s"


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

    async def ping(self) -> bool:
        if self.reachable is None:
            raise RuntimeError("socket gone")
        return self.reachable

    async def sandboxes(self, run: str | None = None) -> list[Sandbox]:
        return [s for s in self.boxes.values() if run is None or s.id.startswith(run)]

    async def create(self, run: str, epoch: int, image: str, limits: Limits) -> str:
        box = f"{run}/{epoch}/{len(self.created)}"
        self.boxes[box] = Sandbox(box, epoch, 0, "running")
        self.created.append((run, epoch))
        return box

    async def remove(self, sandbox: str) -> None:
        self.boxes.pop(sandbox, None)
        self.removed.append(sandbox)

    async def exec(self, sandbox: str, argv: list[str], timeout_s: float) -> dict[str, Any]:
        self.ran.append((sandbox, argv))
        return result(0, Output(), Output())

    async def close(self) -> None:
        pass


def client(backend: FakeBackend) -> httpx.AsyncClient:
    app = create_app(backend=backend, image="img", token="t")
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
        assert backend.created == [(RUN, 1)]  # reused
        await c.post(f"/sandboxes/{RUN}/exec", json={"epoch": 2, "argv": ["ls"]}, headers=TOKEN)
        assert backend.created == [(RUN, 1), (RUN, 2)]  # a reclaimed run: a fresh one
        assert backend.removed == [f"{RUN}/1/0"]  # and the old epoch's is gone
        assert (await c.delete(f"/sandboxes/{RUN}", headers=TOKEN)).status_code == 204
        assert backend.boxes == {}


async def test_a_stopped_sandbox_is_replaced() -> None:
    backend = FakeBackend()
    async with client(backend) as c:
        await c.put(f"/sandboxes/{RUN}?epoch=1", headers=TOKEN)
        (box,) = backend.boxes
        backend.boxes[box] = Sandbox(box, 1, 0, "gone")
        await c.put(f"/sandboxes/{RUN}?epoch=1", headers=TOKEN)
        assert len(backend.created) == 2 and box in backend.removed


async def test_health_says_whether_the_backend_answers() -> None:
    backend = FakeBackend()
    async with client(backend) as c:
        assert (await c.get("/healthz")).status_code == 200
        backend.reachable = False
        assert (await c.get("/healthz")).status_code == 503
        backend.reachable = None  # raises
        assert (await c.get("/healthz")).status_code == 503


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
    pod = k8s.Kubernetes(account=cluster)._pod("nuria-sbx-x-1", RUN, 1, "img", Limits())
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
    stronger = k8s.Kubernetes(account=cluster, runtime_class="gvisor", user_namespaces=True)
    spec = stronger._pod("p", RUN, 1, "img", Limits())["spec"]
    assert spec["runtimeClassName"] == "gvisor" and spec["hostUsers"] is False


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
    big = "x" * 200_000
    argv = [sys.executable, "-c", "import sys; print(len(sys.argv[1]), repr(sys.stdin.read()))",
            big]  # fmt: skip
    done = subprocess.run([sys.executable, "-c", k8s.LAUNCHER], input=json.dumps(argv) + "\n",
                          capture_output=True, text=True, timeout=30, check=True)  # fmt: skip
    assert done.stdout.strip() == "200000 ''"


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

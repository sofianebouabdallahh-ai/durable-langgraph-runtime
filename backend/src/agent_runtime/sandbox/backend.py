"""What sandboxd needs from wherever sandboxes run (Port; adapters: docker.py, kubernetes.py).

The same locked-down sandbox either way (R13.3): the sandbox image, a non-root user,
read-only root, `/workspace` and `/tmp` in memory, no network, no capabilities, CPU and
memory limits, every command under `timeout -s KILL`. Docker on one machine (Compose);
Pods in their own namespace on Kubernetes.

Two isolation levels (phase H9): `container` shares the host's kernel (runc); `gvisor`
puts gVisor's own kernel, in user space, between the code and the host's. sandboxd
decides which one this installation runs (`SANDBOX_ISOLATION`) and proves it (isolation.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic_settings import BaseSettings, SettingsConfigDict

Isolation = Literal["gvisor", "container"]

LABEL = "nuria.sandbox"
MAX_OUTPUT = 20_000
USER_ID = 10002  # the sandbox image's `sandbox` user
ENV = {"HOME": "/workspace", "PYTHONUNBUFFERED": "1", "MPLCONFIGDIR": "/tmp"}
# Under gVisor every process inside needs a helper process on the host, so a host limit
# that a fork bomb reaches stops gVisor itself, and the sandbox with it. The host limit
# only bounds gVisor; the code's own limit is RLIMIT_NPROC, which gVisor's kernel counts
# inside the sandbox (never under runc: there it counts the user across the whole host).
GVISOR_HOST_PIDS = 512


class Limits(BaseSettings):
    """Each sandbox's share (SANDBOX_MEMORY_MB, SANDBOX_CPUS, ...)."""

    model_config = SettingsConfigDict(env_prefix="SANDBOX_")

    memory_mb: int = 256
    cpus: float = 0.5
    pids: int = 64  # Docker only: on Kubernetes it's the kubelet's podPidsLimit
    workspace_mb: int = 64


@dataclass(frozen=True)
class Sandbox:
    id: str
    epoch: int
    created: int  # unix seconds
    # starting: being created (Kubernetes: Pending); gone: stopped, failed or being removed
    state: Literal["running", "starting", "gone"]


class Backend(Protocol):
    async def ping(self) -> bool: ...

    async def sandboxes(self, run: str | None = None) -> list[Sandbox]: ...

    async def supports(self, isolation: Isolation) -> bool:
        """Whether this Docker (or cluster) can start sandboxes at that level at all."""
        ...

    async def create(
        self, run: str, epoch: int, image: str, limits: Limits, isolation: Isolation
    ) -> str:
        """The run's sandbox for this epoch, running. Safe to call twice (the second
        call gets the first's) where the adapter can tell; sandboxd also locks per run."""
        ...

    async def remove(self, sandbox: str) -> None: ...

    async def exec(
        self, sandbox: str, argv: list[str], timeout_s: float, *, processes: int | None = None
    ) -> dict[str, Any]:
        """`processes`: the code's own process limit (gVisor only, see GVISOR_HOST_PIDS)."""
        ...

    async def close(self) -> None: ...


def labels(run: str, epoch: int, created: int) -> dict[str, str]:
    return {
        LABEL: "1",
        f"{LABEL}.run": run,
        f"{LABEL}.epoch": str(epoch),
        f"{LABEL}.created": str(created),
    }


def killed_after(argv: list[str], timeout_s: float, processes: int | None = None) -> list[str]:
    """Killed outright at the time limit: nothing it starts can outlive it. With
    `processes`, it and what it starts can't run more than that many at once."""
    timed = ["timeout", "-s", "KILL", f"{timeout_s:g}s", *argv]
    if processes is None:
        return timed
    # $1 is the limit; the rest is the command (bash: its `ulimit -u` is RLIMIT_NPROC).
    return ["bash", "-c", 'ulimit -u "$1" && shift && exec "$@"', "bash", str(processes), *timed]


class Output:
    """A stream's bytes, kept up to a bound (a flood is cut, not buffered)."""

    def __init__(self) -> None:
        self.data = bytearray()

    def add(self, chunk: bytes) -> None:
        if len(self.data) < MAX_OUTPUT * 4:
            self.data += chunk

    def text(self) -> str:
        return bytes(self.data).decode("utf-8", errors="replace")[:MAX_OUTPUT]


def result(code: int | None, out: Output, err: Output) -> dict[str, Any]:
    return {
        "exit_code": code,
        "timed_out": code == 137,
        "stdout": out.text(),
        "stderr": err.text(),
        "truncated": len(out.data) > MAX_OUTPUT or len(err.data) > MAX_OUTPUT,
    }

"""What sandboxd needs from wherever sandboxes run (Port; adapters: docker.py, kubernetes.py).

The same locked-down sandbox either way (R13.3): the sandbox image, a non-root user,
read-only root, `/workspace` and `/tmp` in memory, no network, no capabilities, CPU and
memory limits, every command under `timeout -s KILL`. Docker on one machine (Compose);
Pods in their own namespace on Kubernetes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic_settings import BaseSettings, SettingsConfigDict

LABEL = "nuria.sandbox"
MAX_OUTPUT = 20_000
USER_ID = 10002  # the sandbox image's `sandbox` user
ENV = {"HOME": "/workspace", "PYTHONUNBUFFERED": "1", "MPLCONFIGDIR": "/tmp"}


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

    async def create(self, run: str, epoch: int, image: str, limits: Limits) -> str:
        """The run's sandbox for this epoch, running. Safe to call twice (the second
        call gets the first's) where the adapter can tell; sandboxd also locks per run."""
        ...

    async def remove(self, sandbox: str) -> None: ...

    async def exec(self, sandbox: str, argv: list[str], timeout_s: float) -> dict[str, Any]: ...

    async def close(self) -> None: ...


def labels(run: str, epoch: int, created: int) -> dict[str, str]:
    return {
        LABEL: "1",
        f"{LABEL}.run": run,
        f"{LABEL}.epoch": str(epoch),
        f"{LABEL}.created": str(created),
    }


def killed_after(argv: list[str], timeout_s: float) -> list[str]:
    """Killed outright at the time limit: nothing it starts can outlive it."""
    return ["timeout", "-s", "KILL", f"{timeout_s:g}s", *argv]


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

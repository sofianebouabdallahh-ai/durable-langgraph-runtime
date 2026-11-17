"""How strongly this installation isolates code, and the proof (phase H9).

`SANDBOX_ISOLATION` asks for a level:

    gvisor      every sandbox under gVisor; without it, no sandbox at all (fails closed)
    container   runc: locked down, but sharing the host's kernel
    auto        gvisor where this Docker (or cluster) has it, otherwise container

A runtime that is only *named* gVisor doesn't count: sandboxd starts a sandbox at the
level it chose and reads the kernel from inside it. Until that has worked, sandboxd
starts none for runs, and says why.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, get_args

from agent_runtime.sandbox.backend import Backend, Isolation, Limits

Wanted = Literal["auto", "gvisor", "container"]
PROBE_RUN = "00000000-0000-0000-0000-000000000000"  # no real run has this id
KERNEL = ["cat", "/proc/version"]
RUNS = ["true"]  # at the container level: a sandbox starts and runs a command


def wanted_from_env() -> Wanted:
    wanted = os.environ.get("SANDBOX_ISOLATION", "auto") or "auto"
    if wanted not in get_args(Wanted):
        raise ValueError(f"SANDBOX_ISOLATION must be auto, gvisor or container, not {wanted!r}")
    return wanted  # type: ignore[return-value]


@dataclass
class Level:
    """The level sandboxd runs at (None: not yet, or not possible), in plain words."""

    wanted: Wanted
    isolation: Isolation | None = None
    reason: str = "Checking how code is isolated."
    settled: bool = False  # True once a check finished (with a level, or without one)

    def view(self) -> dict[str, Any]:
        return {"wanted": self.wanted, "isolation": self.isolation, "reason": self.reason}


def gvisor_kernel(proc_version: str) -> bool:
    """gVisor's kernel says so in /proc/version (`Linux version 4.19.0-gvisor …`)."""
    return "gvisor" in proc_version.lower()


async def probe(
    backend: Backend, isolation: Isolation, image: str, limits: Limits, argv: list[str]
) -> str:
    """What `argv` prints in a fresh sandbox at that level, which is then removed."""
    sandbox = await backend.create(PROBE_RUN, 0, image, limits, isolation)
    try:
        seen = await backend.exec(sandbox, argv, 30)
    finally:
        await backend.remove(sandbox)
    if seen.get("exit_code") != 0:
        raise RuntimeError(f"the isolation probe failed: {seen.get('stderr', '')[:200]}")
    return str(seen.get("stdout", ""))


async def establish(backend: Backend, wanted: Wanted, image: str, limits: Limits) -> Level:
    """The strongest level allowed and possible, proven (Policy). An error (Docker not up
    yet, an image missing) propagates: the caller tries again, never settles lower."""
    missing = "gVisor isn't installed here"
    if wanted in ("gvisor", "auto"):
        if await backend.supports("gvisor"):
            if gvisor_kernel(await probe(backend, "gvisor", image, limits, KERNEL)):
                return Level(wanted, "gvisor", "Code runs under gVisor, with its own kernel.", True)
            missing = "the runtime for gVisor didn't run gVisor's kernel"
        if wanted == "gvisor":
            required = f"Code can't run: gVisor is required, and {missing}."
            return Level(wanted, None, required, True)
    await probe(backend, "container", image, limits, RUNS)
    shared = "Code runs in a container: locked down, but sharing this computer's kernel."
    reason = shared if wanted == "container" else f"{shared} ({missing}.)"
    return Level(wanted, "container", reason, True)

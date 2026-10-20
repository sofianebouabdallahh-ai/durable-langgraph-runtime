"""The sandbox tools (phase L6b): run Python, use a terminal, work with files.

They run in the run's sandbox (sandboxd: no network, no secrets, read-only system, CPU,
memory, process and time limits), never in the worker. They go through the full
ToolPipeline: grants, budgets, idempotency, data marking (R14.15). Risk class
`execute`, isolation `sandbox` (the registry refuses one without the other).

The workspace lives as long as the run: files made in one call are there for the next
call of the same turn; a new turn (or a reclaimed run) starts from an empty one.
Anything worth keeping goes in the answer.
"""

from __future__ import annotations

import base64
import posixpath
from typing import Annotated, Any, Literal

import httpx
from pydantic import Field

from agent_runtime.config import get_settings
from agent_runtime.tools.spec import ToolArgs, ToolContext, ToolRegistry

SANDBOX_TOOLS = ("run_python", "run_shell", "workspace_files")
MAX_FILE_BYTES = 100_000
WORKSPACE = "/workspace"


class SandboxError(Exception):
    """A plain-words reason (the model reads it): unavailable, a bad path, too big."""


class CodeArgs(ToolArgs):
    code: Annotated[
        str,
        Field(min_length=1, max_length=20_000, description="Python 3.12 code; print what you need"),
    ]
    timeout_s: Annotated[int, Field(ge=1, le=120)] = 30


class ShellArgs(ToolArgs):
    command: Annotated[
        str, Field(min_length=1, max_length=5_000, description="A bash command line")
    ]
    timeout_s: Annotated[int, Field(ge=1, le=120)] = 30


class FilesArgs(ToolArgs):
    action: Literal["list", "read", "write"]
    path: Annotated[
        str, Field(max_length=300, description="Relative to the workspace, e.g. data.csv")
    ] = "."
    content: Annotated[str, Field(max_length=MAX_FILE_BYTES)] | None = Field(
        default=None, description="For write: the whole new content"
    )


def _token() -> str:
    token = get_settings().sandboxd_token
    return token.get_secret_value() if token else ""


async def _exec(ctx: ToolContext, argv: list[str], timeout_s: float) -> dict[str, Any]:
    settings = get_settings()
    if not settings.sandboxd_url:
        raise SandboxError("Running code isn't available on this installation.")
    url = f"{settings.sandboxd_url.rstrip('/')}/sandboxes/{ctx.run_id}/exec"
    try:
        async with httpx.AsyncClient(timeout=timeout_s + 30, trust_env=False) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {_token()}"},
                json={"epoch": ctx.epoch, "argv": argv, "timeout_s": timeout_s},
            )
    except httpx.HTTPError as exc:
        raise SandboxError("The sandbox isn't reachable right now.") from exc
    if response.status_code != 200:
        raise SandboxError(f"The sandbox refused the call ({response.status_code}).")
    result: dict[str, Any] = response.json()
    if result.get("timed_out"):
        result["note"] = f"Stopped after {timeout_s:g} s."
    return result


def _path(path: str) -> str:
    joined = posixpath.normpath(posixpath.join(WORKSPACE, path.strip() or "."))
    if joined != WORKSPACE and not joined.startswith(WORKSPACE + "/"):
        raise SandboxError("Files live in the workspace: use a path inside it.")
    return joined


async def run_python(args: CodeArgs, ctx: ToolContext) -> dict[str, Any]:
    """Run Python code in a sandbox (no internet; numpy and pandas installed). Print
    results; files you write stay in the workspace for this turn."""
    return await _exec(ctx, ["python", "-c", args.code], args.timeout_s)


async def run_shell(args: ShellArgs, ctx: ToolContext) -> dict[str, Any]:
    """Run a bash command in the sandbox's workspace (no internet; coreutils, python)."""
    return await _exec(ctx, ["bash", "-c", args.command], args.timeout_s)


READ = (
    "import base64,os,sys\n"
    "p = sys.argv[1]\n"
    "if os.path.getsize(p) > int(sys.argv[2]): sys.exit(3)\n"
    "print(base64.b64encode(open(p, 'rb').read()).decode())\n"
)
WRITE = (
    "import base64,os,sys\n"
    "p = sys.argv[1]\n"
    "os.makedirs(os.path.dirname(p), exist_ok=True)\n"
    "open(p, 'wb').write(base64.b64decode(sys.argv[2]))\n"
)


async def workspace_files(args: FilesArgs, ctx: ToolContext) -> dict[str, Any]:
    """List, read or write files in the sandbox's workspace."""
    path = _path(args.path)
    if args.action == "list":
        found = await _exec(ctx, ["find", path, "-maxdepth", "3", "-printf", "%y %s %P\n"], 15)
        rows = [line.split(" ", 2) for line in found["stdout"].splitlines()]
        entries = [
            {"kind": "dir" if row[0] == "d" else "file", "size": int(row[1]), "name": row[2]}
            for row in rows
            if len(row) == 3 and row[2]
        ]
        return {"path": path, "entries": entries}
    if args.action == "read":
        result = await _exec(ctx, ["python", "-c", READ, path, str(MAX_FILE_BYTES)], 15)
        if result["exit_code"] == 3:
            raise SandboxError(
                f"{args.path} is bigger than {MAX_FILE_BYTES // 1000} KB: read part of it "
                "with run_shell (head, grep)."
            )
        if result["exit_code"] != 0:
            raise SandboxError(f"Couldn't read {args.path}: {result['stderr'][-300:].strip()}")
        data = base64.b64decode(result["stdout"].strip() or b"")
        return {"path": path, "size": len(data), "content": data.decode("utf-8", errors="replace")}
    if args.content is None:
        raise SandboxError("Writing needs the content.")
    encoded = base64.b64encode(args.content.encode("utf-8")).decode()
    result = await _exec(ctx, ["python", "-c", WRITE, path, encoded], 15)
    if result["exit_code"] != 0:
        raise SandboxError(f"Couldn't write {args.path}: {result['stderr'][-300:].strip()}")
    return {"path": path, "written": len(args.content.encode("utf-8"))}


def register(registry: ToolRegistry) -> ToolRegistry:
    for name, fn, model in (
        ("run_python", run_python, CodeArgs),
        ("run_shell", run_shell, ShellArgs),
        ("workspace_files", workspace_files, FilesArgs),
    ):
        registry.tool(
            name,
            args=model,
            risk_class="execute",
            side_effect=False,
            cache=True,
            isolation="sandbox",
            timeout_s=180,
        )(fn)
    return registry


async def release(run_id: str) -> None:
    """The run left `running`: its sandbox goes (best effort; sandboxd sweeps the rest)."""
    settings = get_settings()
    if not settings.sandboxd_url:
        return
    token = settings.sandboxd_token.get_secret_value() if settings.sandboxd_token else ""
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            await client.delete(
                f"{settings.sandboxd_url.rstrip('/')}/sandboxes/{run_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError:
        pass

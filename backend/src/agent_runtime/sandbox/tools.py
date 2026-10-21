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


# Like a notebook: a last line that is an expression has its value shown. Models often
# end with `total` instead of `print(total)`, and plain `python -c` drops the value.
# Errors are reported from the code's own lines, not this wrapper's.
RUN = """\
import ast, sys, traceback
try:
    tree = ast.parse(sys.argv[1], "<code>")
except SyntaxError as e:
    traceback.print_exception(type(e), e, None)
    sys.exit(1)
last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
env = {"__name__": "__main__"}
try:
    exec(compile(tree, "<code>", "exec"), env)
    if last is not None:
        value = eval(compile(ast.Expression(last.value), "<code>", "eval"), env)
        if value is not None:
            print(repr(value))
except Exception as e:
    tb = e.__traceback__
    while tb is not None and tb.tb_frame.f_code.co_filename != "<code>":
        tb = tb.tb_next
    traceback.print_exception(type(e), e, tb)
    sys.exit(1)
"""


async def run_python(args: CodeArgs, ctx: ToolContext) -> dict[str, Any]:
    """Run Python code in a sandbox (no internet; numpy and pandas installed). The value
    of a last line that is an expression is shown, as in a notebook; print anything else.
    Files you write stay in the workspace for this turn."""
    return await _exec(ctx, ["python", "-c", RUN, args.code], args.timeout_s)


async def run_shell(args: ShellArgs, ctx: ToolContext) -> dict[str, Any]:
    """Run a bash command in the sandbox's workspace (no internet; coreutils, python)."""
    return await _exec(ctx, ["bash", "-c", args.command], args.timeout_s)


# What one read returns: its base64 fits in sandboxd's output (20,000 characters).
READ_BYTES = 14_000
READ = (
    "import base64,os,sys\n"
    "p = sys.argv[1]\n"
    "print(os.path.getsize(p))\n"
    "print(base64.b64encode(open(p, 'rb').read(int(sys.argv[2]))).decode())\n"
)
# Linux caps one argument at 128 KiB (MAX_ARG_STRLEN): the content goes in pieces.
ARG_CHUNK = 64 * 1024
WRITE = (
    "import base64,os,sys\n"
    "p = sys.argv[1]\n"
    "os.makedirs(os.path.dirname(p), exist_ok=True)\n"
    "open(p, 'wb').write(base64.b64decode(''.join(sys.argv[2:])))\n"
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
        result = await _exec(ctx, ["python", "-c", READ, path, str(READ_BYTES)], 15)
        if result["exit_code"] != 0:
            raise SandboxError(f"Couldn't read {args.path}: {result['stderr'][-300:].strip()}")
        size, _, encoded = result["stdout"].partition("\n")
        data = base64.b64decode(encoded.strip() or b"")
        read: dict[str, Any] = {
            "path": path,
            "size": int(size),
            "content": data.decode("utf-8", errors="replace"),
        }
        if int(size) > READ_BYTES:
            read["note"] = (
                f"The first {READ_BYTES // 1000} KB of {int(size) // 1000} KB: read the rest "
                "with run_shell (tail -c, sed -n, grep)."
            )
        return read
    if args.content is None:
        raise SandboxError("Writing needs the content.")
    encoded = base64.b64encode(args.content.encode("utf-8")).decode()
    pieces = [encoded[i : i + ARG_CHUNK] for i in range(0, len(encoded), ARG_CHUNK)]
    result = await _exec(ctx, ["python", "-c", WRITE, path, *pieces], 15)
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

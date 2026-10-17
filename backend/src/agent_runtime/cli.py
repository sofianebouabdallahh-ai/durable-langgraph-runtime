"""`runtime` command-line interface.

Pattern: Command. Each subcommand is a small handler bound to its own parser
(`set_defaults(handler=...)`); `main` only parses and dispatches. Handlers
return a process exit code: 0 success, 1 failure, 2 usage / invalid state.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from agent_runtime.agents.loader import (
    AgentValidationError,
    Ceilings,
    UnknownAgent,
    load_agents,
)
from agent_runtime.catalog import default_catalog
from agent_runtime.config import Settings, get_agent_settings, get_settings
from agent_runtime.runs.state import RunStatus
from agent_runtime.runs.store import Event, Run, RunRepository, RunTerminal

Handler = Callable[[argparse.Namespace], int]
BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/ (holds alembic.ini)


def _setup_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


# ----------------------------------------------------------------------- db


def _db_upgrade(args: argparse.Namespace) -> int:
    """Our schema (Alembic) + LangGraph's checkpoint tables (its own migrations).

    One command, run before any new api/worker version starts (R10.6: the
    Kubernetes migrate Job runs exactly this).
    """
    from alembic import command
    from alembic.config import Config
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from agent_runtime.db import create_pool

    settings = get_settings()
    _setup_logging(settings)
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = settings.database_url()
    command.upgrade(cfg, "head")

    async def checkpointer_setup() -> None:
        from agent_runtime.dbadmin import grant_checkpoint_tables

        async with create_pool(settings, max_size=1) as pool:
            await AsyncPostgresSaver(pool).setup()
            async with pool.connection() as conn:
                await grant_checkpoint_tables(conn)

    asyncio.run(checkpointer_setup())
    print("ok: schema at head; LangGraph checkpoint tables ready")
    return 0


def _db_provision_users(args: argparse.Namespace) -> int:
    """Create/update each component's login user from <COMPONENT>_POSTGRES_* (R14.13)."""
    from agent_runtime.db import create_pool
    from agent_runtime.dbadmin import provision_users

    settings = get_settings()
    _setup_logging(settings)

    async def run() -> list[str]:
        async with create_pool(settings, max_size=1) as pool, pool.connection() as conn:
            return await provision_users(conn)

    done = asyncio.run(run())
    print(f"ok: provisioned {', '.join(done) or 'no'} database user(s)")
    return 0


# --------------------------------------------------------------------- runs


def _print_run(run: Run, events: list[Event]) -> None:
    print(f"run {run.id}: {run.status}" + (f" ({run.reason})" if run.reason else ""))
    print(f"  epoch={run.epoch} steps={run.steps} owner={run.owner}")
    for e in events:
        detail = e.payload.get("node") or e.payload.get("reason") or ""
        print(f"  {e.seq:>3} e{e.epoch} {e.type:<16} {detail}")


async def _execute_and_report(
    settings: Settings, run_id: uuid.UUID, *, local_fanout: bool = False
) -> int:
    from agent_runtime.db import create_pool
    from agent_runtime.graphs import default_registry
    from agent_runtime.runs.executor import RunExecutor

    async with create_pool(settings) as pool:
        try:
            executor = RunExecutor(pool, settings, default_registry(), local_fanout=local_fanout)
            run = await executor.execute(run_id)
        except RunTerminal as exc:
            print(exc, file=sys.stderr)
            return 2  # like HTTP 409: valid request, wrong state
        async with pool.connection() as conn:
            events = await RunRepository(conn).list_events(run_id, limit=1000)
    _print_run(run, events)
    return 0 if run.status is not RunStatus.FAILED else 1


def _run(args: argparse.Namespace) -> int:
    """Create a run and execute it in this process."""
    from pydantic import ValidationError

    from agent_runtime.db import create_pool
    from agent_runtime.graphs import UnknownGraph, default_registry
    from agent_runtime.runs.limits import LimitAboveCeiling
    from agent_runtime.runs.service import RunService

    settings = get_settings()
    _setup_logging(settings)

    async def create() -> uuid.UUID:
        async with create_pool(settings, max_size=1) as pool:
            service = RunService(pool, settings, default_registry())
            # executes in this process, so don't also hand it to the workers
            run = await service.create_run(args.graph, args.input, args.options, enqueue=False)
            return run.id

    try:
        run_id = asyncio.run(create())
    except (UnknownGraph, ValidationError, LimitAboveCeiling) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"created run {run_id}", file=sys.stderr)
    return asyncio.run(_execute_and_report(settings, run_id, local_fanout=args.local_fanout))


def _chat(args: argparse.Namespace) -> int:
    """Chat with an agent in this terminal: a session, one in-process run per turn, the
    model's tokens printed as they stream (CR-001). `--message` (repeatable) makes it
    non-interactive; otherwise it reads lines until EOF or `/quit`."""
    settings = get_settings()
    logging.basicConfig(level=logging.WARNING)
    return asyncio.run(_chat_session(settings, args.agent, args.message))


async def _chat_session(settings: Settings, agent: str, messages: list[str] | None) -> int:
    import time

    from agent_runtime.db import create_pool
    from agent_runtime.graphs import default_registry
    from agent_runtime.runs.executor import RunExecutor
    from agent_runtime.runs.service import RunService
    from agent_runtime.sessions.service import SessionService
    from agent_runtime.streaming.bus import InMemoryEventBus, session_channel

    graphs = default_registry()
    bus = InMemoryEventBus()
    async with create_pool(settings) as pool:
        runs = RunService(pool, settings, graphs)
        sessions = SessionService(pool, settings, graphs, runs, bus=bus)
        session = await sessions.create(agent)
        print(f"session {session.id} with {agent} (provider: {settings.model_provider})\n")
        queue = list(messages) if messages else None
        while True:
            if queue is not None:
                if not queue:
                    break
                text = queue.pop(0)
                print(f"you> {text}")
            else:
                try:
                    text = (await asyncio.to_thread(input, "you> ")).strip()
                except EOFError:
                    break
                if text in ("/quit", "/exit"):
                    break
                if not text:
                    continue
            sub = bus.subscription()
            await sub.subscribe(session_channel(session.id))
            started = time.monotonic()
            turn = await sessions.send(session.id, text)
            task = asyncio.create_task(
                RunExecutor(pool, settings, graphs, bus=bus).execute(turn.run.id)
            )
            print(f"{agent}> ", end="", flush=True)
            while True:  # print live events until the turn is over and none are left
                got = await sub.get(0.05)
                if got is not None:
                    _print_live(got[1].type, got[1].payload)
                elif task.done():
                    break
            run = task.result()
            async with pool.connection() as conn:
                cur = await conn.execute(
                    "SELECT tokens, cost, model_calls, tool_calls_total FROM runs WHERE id = %s",
                    (run.id,),
                )
                usage = await cur.fetchone()
            assert usage is not None
            print(f"\n  [{run.status}{f' {run.reason}' if run.reason else ''}"
                  f" · {usage['model_calls']} model calls · {usage['tool_calls_total']} tools"
                  f" · {usage['tokens']} tokens · ${float(usage['cost']):.4f}"
                  f" · {time.monotonic() - started:.1f}s]\n")  # fmt: skip
            await sub.close()
    return 0


def _print_live(type_: str, payload: dict[str, Any]) -> None:
    if type_ == "token":
        print(payload["text"], end="", flush=True)
    elif type_ == "message.created":
        kind, content = payload["type"], payload["content"]
        if kind == "tool_call":
            print(f"\n  ⚙ {content['tool']}({json.dumps(content['args'])[:120]})", flush=True)
        elif kind == "tool_result":
            body = content.get("result", content.get("error"))
            print(f"  ↳ {json.dumps(body, default=str)[:160]}", flush=True)
    elif type_.startswith("subagent."):
        agent = payload.get("agent", "")
        detail = payload.get("message") or payload.get("status") or ""
        print(f"\n  ◇ {type_.removeprefix('subagent.')} {agent} {detail}", flush=True)


def _execute(args: argparse.Namespace) -> int:
    """Execute a queued run, or resume one whose worker died (R1.3)."""
    settings = get_settings()
    _setup_logging(settings)
    return asyncio.run(_execute_and_report(settings, args.run_id))


# ------------------------------------------------------------------ worker


async def _serve_worker(settings: Settings, concurrency: int) -> None:
    """One worker process. First SIGTERM/SIGINT: drain gracefully (R10.7).
    Second: exit immediately, like Kubernetes' SIGKILL after the grace period."""
    import os
    import signal

    from agent_runtime.db import create_pool
    from agent_runtime.graphs import default_registry
    from agent_runtime.queue import RedisWorkQueue, create_redis
    from agent_runtime.streaming.bus import RedisEventBus
    from agent_runtime.worker import Worker

    stop = asyncio.Event()

    def on_signal(signum: int) -> None:
        if stop.is_set():
            logging.getLogger(__name__).warning("second signal: exiting now")
            os._exit(128 + signum)
        logging.getLogger(__name__).info("signal %d: draining", signum)
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, on_signal, sig)

    redis = create_redis(settings.redis_url)
    try:
        async with create_pool(settings, max_size=concurrency + 4) as pool:
            queue = RedisWorkQueue(redis, settings.work_stream, settings.work_group)
            worker = Worker(
                pool, queue, settings, default_registry(), concurrency=concurrency,
                bus=RedisEventBus(redis),
            )  # fmt: skip
            await worker.run(stop)
    finally:
        await redis.aclose()


def _worker(args: argparse.Namespace) -> int:
    settings = get_settings()
    _setup_logging(settings)
    concurrency = args.concurrency or settings.worker_concurrency
    if args.workers == 1:
        settings = settings.for_component("worker")  # least-privilege DB user (R14.13)
    if args.workers > 1:
        return _supervise(args.workers, concurrency)
    asyncio.run(_serve_worker(settings, concurrency))
    return 0


def _supervise(n: int, concurrency: int) -> int:
    """Pattern: Supervisor. Start N worker processes and forward stop signals.

    It deliberately does not restart crashed children: locally, a demo kills a
    worker to prove another one takes over; in Kubernetes, the kubelet restarts
    containers (each pod runs a single worker process).
    """
    import signal
    import subprocess

    cmd = [sys.executable, "-m", "agent_runtime.cli", "worker", "--concurrency", str(concurrency)]
    children = [subprocess.Popen(cmd) for _ in range(n)]

    def forward(signum: int, _frame: object) -> None:
        for child in children:
            if child.poll() is None:
                child.send_signal(signum)

    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    print(f"supervising {n} workers: pids {[c.pid for c in children]}", file=sys.stderr)
    return max(child.wait() for child in children)


def _api(args: argparse.Namespace) -> int:
    """Serve the API. On SIGTERM/SIGINT, flag the app as draining *before* uvicorn
    starts its shutdown, so open streams can send `reconnect` and close on their
    own within the grace period (R10.7) instead of blocking shutdown."""
    from types import FrameType

    import uvicorn

    from agent_runtime.api.app import create_api_app

    settings = get_settings()
    app = create_api_app()
    config = uvicorn.Config(
        app,
        host=args.host,
        port=args.port,
        log_level=settings.log_level.lower(),
        timeout_graceful_shutdown=int(settings.api_grace_s),
    )

    class DrainingServer(uvicorn.Server):
        def handle_exit(self, sig: int, frame: FrameType | None) -> None:
            loop = app.state.loop
            if loop is not None:
                loop.call_soon_threadsafe(app.state.draining.set)
            super().handle_exit(sig, frame)

    DrainingServer(config).run()
    return 0


def _agents_validate(args: argparse.Namespace) -> int:
    settings = get_agent_settings()
    root = args.path or settings.agents_dir
    try:
        registry = load_agents(root, default_catalog(), Ceilings.from_settings(settings))
    except AgentValidationError as exc:
        print(exc, file=sys.stderr)
        return 1
    subs = sum(len(a.subagents) for a in registry)
    print(f"ok: {len(registry)} agent(s), {subs} sub-agent(s) in {root}")
    return 0


def _agents_show(args: argparse.Namespace) -> int:
    settings = get_agent_settings()
    try:
        agent = load_agents(
            settings.agents_dir, default_catalog(), Ceilings.from_settings(settings)
        ).get(args.name)
    except (AgentValidationError, UnknownAgent) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(json.dumps(agent.model_dump(mode="json"), indent=2))
    return 0


# --------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="runtime", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(title="commands", required=True, metavar="COMMAND")

    agents = commands.add_parser("agents", help="agent definitions").add_subparsers(
        required=True, metavar="ACTION"
    )
    validate = agents.add_parser("validate", help="validate every agent definition")
    validate.add_argument("--path", type=Path, help="agents directory (default: AGENTS_DIR)")
    validate.set_defaults(handler=_agents_validate)
    show = agents.add_parser("show", help="print an agent's resolved definition")
    show.add_argument("name")
    show.set_defaults(handler=_agents_show)

    db = commands.add_parser("db", help="database").add_subparsers(required=True, metavar="ACTION")
    db.add_parser("upgrade", help="migrate our schema and LangGraph's tables").set_defaults(
        handler=_db_upgrade
    )
    db.add_parser(
        "provision-users", help="create per-component least-privilege login users"
    ).set_defaults(handler=_db_provision_users)

    api = commands.add_parser("api", help="serve the HTTP API")
    # 127.0.0.1 by default: never expose a dev server on the LAN by accident.
    # Containers pass --host 0.0.0.0 explicitly.
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    api.set_defaults(handler=_api)

    run = commands.add_parser("run", help="create a run and execute it in this process")
    run.add_argument("--graph", required=True)
    run.add_argument("--input", type=_json_object, required=True, help="JSON object")
    run.add_argument("--options", type=_json_object, default=None, help="JSON object")
    run.add_argument(
        "--local-fanout",
        action="store_true",
        help="run child runs in this process instead of queueing them (R2.8)",
    )
    run.set_defaults(handler=_run)

    worker = commands.add_parser("worker", help="run worker process(es) that execute queued runs")
    worker.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="runs in flight per process (default: WORKER_CONCURRENCY)",
    )
    worker.add_argument("--workers", type=int, default=1, help="number of worker processes")
    worker.set_defaults(handler=_worker)

    chat = commands.add_parser("chat", help="chat with an agent in this terminal")
    chat.add_argument("--agent", default="chat")
    chat.add_argument("--message", action="append", help="send this (repeatable); no prompt")
    chat.set_defaults(handler=_chat)

    execute = commands.add_parser(
        "execute", aliases=["resume"], help="execute a queued run or resume a crashed one"
    )
    execute.add_argument("run_id", type=uuid.UUID)
    execute.set_defaults(handler=_execute)

    return parser


def _json_object(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("must be a JSON object")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Handler = args.handler
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

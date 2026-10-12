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

from agent_runtime.agents.loader import (
    AgentValidationError,
    Catalog,
    Ceilings,
    UnknownAgent,
    load_agents,
)
from agent_runtime.config import Settings, get_agent_settings, get_settings
from agent_runtime.runs.state import RunStatus
from agent_runtime.runs.store import Event, Run, RunRepository

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
        async with create_pool(settings, max_size=1) as pool:
            await AsyncPostgresSaver(pool).setup()

    asyncio.run(checkpointer_setup())
    print("ok: schema at head; LangGraph checkpoint tables ready")
    return 0


# --------------------------------------------------------------------- runs


def _print_run(run: Run, events: list[Event]) -> None:
    print(f"run {run.id}: {run.status}" + (f" ({run.reason})" if run.reason else ""))
    print(f"  epoch={run.epoch} steps={run.steps} owner={run.owner}")
    for e in events:
        detail = e.payload.get("node") or e.payload.get("reason") or ""
        print(f"  {e.seq:>3} e{e.epoch} {e.type:<16} {detail}")


async def _execute_and_report(settings: Settings, run_id: uuid.UUID) -> int:
    from agent_runtime.db import create_pool
    from agent_runtime.graphs import default_registry
    from agent_runtime.runs.executor import RunExecutor, RunNotRunnable

    async with create_pool(settings) as pool:
        try:
            run = await RunExecutor(pool, settings, default_registry()).execute(run_id)
        except RunNotRunnable as exc:
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
            run = await service.create_run(args.graph, args.input, args.options)
            return run.id

    try:
        run_id = asyncio.run(create())
    except (UnknownGraph, ValidationError, LimitAboveCeiling) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"created run {run_id}", file=sys.stderr)
    return asyncio.run(_execute_and_report(settings, run_id))


def _execute(args: argparse.Namespace) -> int:
    """Execute a queued run, or resume one whose worker died (R1.3)."""
    settings = get_settings()
    _setup_logging(settings)
    return asyncio.run(_execute_and_report(settings, args.run_id))


def _api(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "agent_runtime.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        log_level=get_settings().log_level.lower(),
    )
    return 0


# ------------------------------------------------------------------- agents


def _agents_validate(args: argparse.Namespace) -> int:
    settings = get_agent_settings()
    root = args.path or settings.agents_dir
    try:
        registry = load_agents(root, Catalog(), Ceilings.from_settings(settings))
    except AgentValidationError as exc:
        print(exc, file=sys.stderr)
        return 1
    subs = sum(len(a.subagents) for a in registry)
    print(f"ok: {len(registry)} agent(s), {subs} sub-agent(s) in {root}")
    return 0


def _agents_show(args: argparse.Namespace) -> int:
    settings = get_agent_settings()
    try:
        agent = load_agents(settings.agents_dir, Catalog(), Ceilings.from_settings(settings)).get(
            args.name
        )
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
    run.set_defaults(handler=_run)

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

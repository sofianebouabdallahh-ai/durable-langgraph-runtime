"""`runtime` command-line interface.

Pattern: Command. Each subcommand is a small handler bound to its own parser
(`set_defaults(handler=...)`); `main` only parses and dispatches. Handlers
return a process exit code: 0 success, 1 failure, 2 usage / invalid state.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from agent_runtime.agents.loader import (
    AgentValidationError,
    Catalog,
    Ceilings,
    UnknownAgent,
    load_agents,
)
from agent_runtime.config import get_agent_settings

Handler = Callable[[argparse.Namespace], int]


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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Handler = args.handler
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

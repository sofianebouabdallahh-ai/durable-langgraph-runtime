"""The skill tools (CR-006 R17.4): progressive disclosure, through the full pipeline.

An agent's prompt lists only its skills' names and descriptions. When one fits the
task, the agent calls:

- `load_skill(name)`: the skill's instructions, and the files it can read;
- `read_skill_file(skill, path)`: one reference or asset, as text.

The harness grants both to any agent or helper that has skills, and they see **only
the caller's own skills** (`ToolContext.skills`, R16.7): a helper can't load its main
agent's skill, nor the other way round. Their results, like every tool result, reach
the model marked as data (R14.15). Scripts are never readable or runnable here: the
sandbox doesn't exist yet (CR-002).

They read pinned, immutable versions (the run's bundle), so they are deterministic:
cached like any read, and safe to re-run after a crash.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import Field

from agent_runtime.skills.store import SkillStore, SkillVersion
from agent_runtime.tools.spec import ToolArgs, ToolContext, ToolRegistry

SKILL_TOOLS = ("load_skill", "read_skill_file")
READABLE_KINDS = ("reference", "asset", "other")


class SkillToolError(Exception):
    """A plain-words refusal the model can act on (the pipeline returns it as an error)."""


class LoadArgs(ToolArgs):
    name: Annotated[str, Field(min_length=1, max_length=64, description="The skill's name")]


class ReadArgs(ToolArgs):
    skill: Annotated[str, Field(min_length=1, max_length=64)]
    path: Annotated[
        str,
        Field(min_length=1, max_length=300, description="As listed by load_skill, e.g. a.md"),
    ]


def _own(ctx: ToolContext, name: str) -> SkillVersion:
    skills: Mapping[str, SkillVersion] = ctx.skills or {}
    found = skills.get(name)
    if found is None:
        mine = ", ".join(sorted(skills)) or "none"
        raise SkillToolError(f"No skill called {name!r} here. Your skills: {mine}.")
    return found


async def load_skill(args: LoadArgs, ctx: ToolContext) -> dict[str, Any]:
    """Load one of your skills: its instructions, and the files it can read."""
    skill = _own(ctx, args.name)
    readable = [f["path"] for f in skill.files if f["kind"] in READABLE_KINDS]
    return {
        "skill": skill.name,
        "instructions": skill.instructions,
        "files": readable,
        "note": "Reference material for your task. Read a file with read_skill_file if needed.",
    }


async def read_skill_file(args: ReadArgs, ctx: ToolContext) -> dict[str, Any]:
    """Read a reference or asset file of one of your skills."""
    skill = _own(ctx, args.skill)
    entry = skill.entry(args.path)
    if entry is None:
        listed = ", ".join(f["path"] for f in skill.files if f["kind"] in READABLE_KINDS)
        raise SkillToolError(
            f"{args.skill} has no file {args.path!r}. Its files: {listed or 'none'}."
        )
    if entry["kind"] not in READABLE_KINDS:
        raise SkillToolError("Skill scripts can't be read or run here.")
    async with ctx.pool.connection() as conn:
        data = await SkillStore(conn).file(entry["sha256"])
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {"path": args.path, "binary": True, "size": len(data),
                "note": "A binary file: it can't be shown as text."}  # fmt: skip
    return {"path": args.path, "text": text}


def register(registry: ToolRegistry) -> ToolRegistry:
    registry.tool(
        "load_skill",
        args=LoadArgs,
        risk_class="read",
        side_effect=False,
    )(load_skill)
    registry.tool(
        "read_skill_file",
        args=ReadArgs,
        risk_class="read",
        side_effect=False,
    )(read_skill_file)
    return registry

"""Skills at run time (L3c.5, SC3): progressive disclosure, own skills only, scripts inert."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from agent_runtime.agents.schema import AgentDefinition
from agent_runtime.graphs import default_registry
from agent_runtime.graphs.assistant import granted_tools, render_prompt
from agent_runtime.skills.store import SkillVersion
from agent_runtime.skills.tools import (
    LoadArgs,
    ReadArgs,
    SkillToolError,
    load_skill,
    read_skill_file,
)
from agent_runtime.tools.spec import ToolContext

CHAT = default_registry().get("chat").agent
SECRET_SAUCE = "Always check the ferry timetable first."


def version(name: str, files: list[dict[str, Any]] | None = None) -> SkillVersion:
    return SkillVersion(
        "a" * 64, name, f"{name}: use when planning.", SECRET_SAUCE, {}, files or [], {},
        datetime.now(UTC),
    )  # fmt: skip


def ctx(*skills: SkillVersion) -> ToolContext:
    return ToolContext(
        run_id=uuid.uuid4(), epoch=1, key="k", pool=None,  # type: ignore[arg-type]
        skills={s.name: s for s in skills},
    )  # fmt: skip


def with_skills(defn: AgentDefinition, main: list[str], helper: list[str]) -> AgentDefinition:
    fm = defn.frontmatter.model_copy(update={"skills": main})
    sub = defn.subagents[0]
    subs = (sub.model_copy(update={"frontmatter": sub.frontmatter.model_copy(update={
        "skills": helper})}), *defn.subagents[1:])  # fmt: skip
    return defn.model_copy(update={"frontmatter": fm, "subagents": subs})


def test_the_prompt_lists_names_and_descriptions_only() -> None:
    assert isinstance(CHAT, AgentDefinition)
    prompt = render_prompt(CHAT, [version("trip-tips")])
    assert "## Your skills" in prompt and "- `trip-tips`: trip-tips: use when planning." in prompt
    assert SECRET_SAUCE not in prompt  # the body arrives only on load_skill
    assert "## Your skills" not in render_prompt(CHAT)


def test_skill_tools_are_granted_only_to_whoever_has_skills() -> None:
    assert isinstance(CHAT, AgentDefinition)
    agent = with_skills(CHAT, ["trip-tips"], [])
    assert "load_skill" in granted_tools(agent) and "read_skill_file" in granted_tools(agent)
    assert "load_skill" not in granted_tools(agent.subagents[0])
    helper_only = with_skills(CHAT, [], ["maps"])
    assert "load_skill" not in granted_tools(helper_only)
    assert "load_skill" in granted_tools(helper_only.subagents[0])


async def test_an_agent_loads_only_its_own_skills() -> None:
    file = {"path": "references/a.md", "sha256": "0", "size": 1, "kind": "reference"}
    mine = ctx(version("trip-tips", [file]))
    loaded = await load_skill(LoadArgs(name="trip-tips"), mine)
    assert loaded["instructions"] == SECRET_SAUCE and loaded["files"] == ["references/a.md"]
    refused = r"No skill called 'maps' here\. Your skills: trip-tips"
    with pytest.raises(SkillToolError, match=refused):
        await load_skill(LoadArgs(name="maps"), mine)
    with pytest.raises(SkillToolError, match="Your skills: none"):
        await load_skill(LoadArgs(name="trip-tips"), ctx())


async def test_scripts_are_never_readable_and_unknown_files_are_named() -> None:
    files = [
        {"path": "scripts/run.sh", "sha256": "0", "size": 1, "kind": "script"},
        {"path": "references/a.md", "sha256": "1", "size": 1, "kind": "reference"},
    ]
    mine = ctx(version("trip-tips", files))
    loaded = await load_skill(LoadArgs(name="trip-tips"), mine)
    assert loaded["files"] == ["references/a.md"]  # scripts aren't even offered
    with pytest.raises(SkillToolError, match="can't be read or run"):
        await read_skill_file(ReadArgs(skill="trip-tips", path="scripts/run.sh"), mine)
    with pytest.raises(SkillToolError, match=r"Its files: references/a\.md"):
        await read_skill_file(ReadArgs(skill="trip-tips", path="../../etc/passwd"), mine)

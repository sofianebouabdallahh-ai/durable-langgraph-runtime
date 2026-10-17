"""Typed, strict schema for `agent.md` frontmatter (R15.1, R15.2, R16.2).

"Parse, don't validate": a definition file becomes one of these immutable
objects at load time, or loading fails. Unknown keys are errors
(`extra="forbid"`), so a typo such as `max_turn:` can't be silently ignored.

Sub-agents use a *restricted* schema rather than the main one with fields
left empty: keys that make no sense for a leaf (`subagents`, session hooks)
are rejected as unknown, by construction.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NAME_PATTERN = r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$"  # kebab-case


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Limits(_Strict):
    """Per-agent profile: the middle layer of R14.3 (can only tighten ceilings)."""

    max_tool_calls: Annotated[int, Field(gt=0)] | None = None
    max_tokens: Annotated[int, Field(gt=0)] | None = None
    max_cost_usd: Annotated[float, Field(gt=0)] | None = None
    timeout_s: Annotated[int, Field(gt=0)] | None = None


class ToolGrant(_Strict):
    name: str
    max_calls: Annotated[int, Field(gt=0)] | None = None


def _normalise_tools(value: Any) -> Any:
    """Accept `[search, {run_python: {max_calls: 10}}]` and return ToolGrant dicts."""
    if not isinstance(value, list):
        return value
    out: list[Any] = []
    for item in value:
        if isinstance(item, str):
            out.append({"name": item})
        elif isinstance(item, dict) and len(item) == 1:
            ((name, opts),) = item.items()
            out.append({"name": name, **(opts or {})})
        else:
            out.append(item)  # let pydantic report the error
    return out


class SubAgentHooks(_Strict):
    pre_tool: list[str] = []
    post_tool: list[str] = []
    pre_model: list[str] = []
    post_model: list[str] = []


class MainAgentHooks(SubAgentHooks):
    session_start: list[str] = []
    turn_start: list[str] = []
    turn_end: list[str] = []
    session_end: list[str] = []
    on_error: list[str] = []


class _AgentFields(_Strict):
    name: Annotated[str, Field(pattern=NAME_PATTERN)]
    description: Annotated[str, Field(min_length=1, max_length=500)]
    version: Annotated[int, Field(gt=0)]
    model: Annotated[str, Field(min_length=1)]
    temperature: Annotated[float, Field(ge=0, le=2)] = 0.2
    max_turns: Annotated[int, Field(gt=0)]
    limits: Limits = Limits()
    tools: list[ToolGrant] = []
    output_schema: str | None = None

    @field_validator("tools", mode="before")
    @classmethod
    def _tools(cls, value: Any) -> Any:
        return _normalise_tools(value)

    @model_validator(mode="after")
    def _unique_tools(self) -> _AgentFields:
        names = [t.name for t in self.tools]
        if duplicates := sorted({n for n in names if names.count(n) > 1}):
            raise ValueError(f"tools listed more than once: {', '.join(duplicates)}")
        return self


class SubAgentFrontmatter(_AgentFields):
    hooks: SubAgentHooks = SubAgentHooks()


class MainAgentFrontmatter(_AgentFields):
    max_session_turns: Annotated[int, Field(gt=0)] | None = None
    # Test and example agents: served by the API, not offered to people in the UI.
    hidden: bool = False
    hooks: MainAgentHooks = MainAgentHooks()


# ---------------------------------------------------------------- resolved form

PLACEHOLDER = re.compile(r"{{\s*([a-zA-Z_.]+)\s*}}")
MAIN_PLACEHOLDERS = frozenset({"date", "agent.name", "session.title", "tools"})
SUB_PLACEHOLDERS = frozenset({"date", "agent.name", "tools"})


class SubAgentDefinition(_Strict):
    kind: Literal["sub"] = "sub"
    id: str  # "<main>/<sub>"
    frontmatter: SubAgentFrontmatter
    prompt: str


class AgentDefinition(_Strict):
    kind: Literal["main"] = "main"
    id: str  # "<main>"
    frontmatter: MainAgentFrontmatter
    prompt: str
    subagents: tuple[SubAgentDefinition, ...] = ()

"""A test case for an agent (phase H6), and what a turn did, to check it against.

A case is a message (and, optionally, the scripted model's replies, which make it
deterministic: no model, no key), what the test answers when the agent asks for approval,
and what's expected of the turn. It's validated strictly (an unknown key is an error, not
a silently skipped check) and hashed canonically: a result belongs to one version of a
case, so editing a case makes its earlier results stale.

    name: tells the team, after you approve
    message: Tell the team lunch is here
    script: [{tool_calls: [{name: notify, args: {to: team, message: Lunch}}]},
             {content: Done, I told the team.}]
    approve: true
    expect: {tools: [notify], approvals: [notify], answer_contains: [told]}
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.models.scripted import ScriptTurn

Name = Annotated[str, Field(min_length=1, max_length=120)]
ToolName = Annotated[str, Field(min_length=1, max_length=200)]


class Expect(BaseModel):
    """What the turn must do. Every field set is one check; none set: it completed."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "failed", "cancelled"] = "completed"
    tools: list[ToolName] = Field(default_factory=list, description="all of these were called")
    not_tools: list[ToolName] = Field(default_factory=list, description="none of these was")
    approvals: list[ToolName] = Field(
        default_factory=list, description="it asked before calling each of these"
    )
    max_tool_calls: Annotated[int, Field(ge=0)] | None = None
    answer_contains: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, description="case-insensitive"
    )
    answer_not_contains: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list
    )
    answer_matches: Annotated[str, Field(max_length=500)] | None = Field(
        default=None, description="a regular expression the answer matches (search)"
    )
    answer_schema: dict[str, Any] | None = Field(
        default=None, description="the answer is JSON, valid against this JSON Schema"
    )
    judge: Annotated[str, Field(min_length=1, max_length=2000)] | None = Field(
        default=None, description="a rubric the agent's own model grades the answer against"
    )


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    message: Annotated[str, Field(min_length=1, max_length=8000)]
    script: list[ScriptTurn] = Field(default_factory=list)
    subagent_scripts: dict[str, list[ScriptTurn]] = Field(default_factory=dict)
    approve: bool = Field(default=True, description="the test's answer when the agent asks")
    expect: Expect = Field(default_factory=Expect)

    def digest(self) -> str:
        """sha256 of the case, canonically (key order and defaults don't matter)."""
        body = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode()).hexdigest()


def load_dir(path: Path) -> list[tuple[str, Case]]:
    """Every `*.yaml` case in `path`, by file name (sorted); a bad file raises, naming it."""
    out: list[tuple[str, Case]] = []
    for file in sorted(path.glob("*.yaml")):
        try:
            out.append((file.stem, Case.model_validate(yaml.safe_load(file.read_text()))))
        except Exception as exc:
            raise ValueError(f"{file}: {exc}") from exc
    return out


@dataclass(frozen=True, slots=True)
class Trajectory:
    """What a turn did, as its events and transcript say."""

    status: str
    reason: str | None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)  # in order
    asked: list[str] = field(default_factory=list)  # tools it asked approval for
    answer: str = ""  # its last reply

    @property
    def tools(self) -> set[str]:
        return {name for name, _ in self.calls}

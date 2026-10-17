"""Per-run limits (R1.7), resolved once at creation (R14.3).

Three layers, each allowed only to tighten the one above it:

    server ceilings (Settings)  ≥  graph/agent profile  ≥  per-run `options`

An option above its ceiling is rejected with the field and the maximum, never
silently clamped: a silently ignored option is a debugging trap. The resolved
limits are stored on the run (`runs.limits`), so a run keeps the limits it was
created with even if the server's settings change during a rolling upgrade.

Budgets for model calls, tool calls, tokens and cost (R14.1) join this model
in phases 4 and 6, with the same rules.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.config import AgentSettings
from agent_runtime.graphs import GraphSpec


class RunOptions(BaseModel):
    """What a caller may set in `POST /runs {options}`. Unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timeout_s: Annotated[int, Field(gt=0)] | None = None
    max_steps: Annotated[int, Field(gt=0)] | None = None
    max_model_calls: Annotated[int, Field(gt=0)] | None = None
    max_tool_calls: Annotated[int, Field(gt=0)] | None = None


class RunLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeout_s: Annotated[int, Field(gt=0)]
    max_steps: Annotated[int, Field(gt=0)]
    max_model_calls: Annotated[int, Field(gt=0)] | None = None  # agent graphs (R14.1)
    max_tool_calls: Annotated[int, Field(gt=0)] | None = None


class Profile(BaseModel):
    """The graph's own limits (for agents: from the definition); the middle layer."""

    model_config = ConfigDict(frozen=True)

    timeout_s: int | None = None
    max_model_calls: int | None = None
    max_tool_calls: int | None = None


class LimitAboveCeiling(ValueError):
    def __init__(self, field: str, value: float, ceiling: float) -> None:
        super().__init__(f"options.{field}={value} exceeds the server maximum {ceiling}")
        self.field = field
        self.value = value
        self.ceiling = ceiling


def resolve_limits(
    settings: AgentSettings, options: RunOptions, profile: Profile | None = None
) -> RunLimits:
    """ceiling ≥ profile ≥ options. An option above its CEILING is rejected (422);
    otherwise the effective limit is the tightest of the three that are set."""
    profile = profile or Profile()
    ceilings: dict[str, int | None] = {
        "timeout_s": settings.run_timeout_s,
        "max_steps": settings.run_max_steps,
        "max_model_calls": settings.ceiling_model_calls if profile.max_model_calls else None,
        "max_tool_calls": settings.ceiling_tool_calls if profile.max_tool_calls else None,
    }
    resolved: dict[str, Any] = {}
    for field, ceiling in ceilings.items():
        requested = getattr(options, field)
        if requested is not None and ceiling is not None and requested > ceiling:
            raise LimitAboveCeiling(field, requested, ceiling)
        candidates = [v for v in (ceiling, getattr(profile, field, None), requested) if v]
        resolved[field] = min(candidates) if candidates else None
    return RunLimits(**resolved)


def profile_of(spec: GraphSpec) -> Profile | None:
    """An agent graph's limits come from its definition (max_turns, limits)."""
    if spec.agent is None:
        return None
    fm = spec.agent.frontmatter
    return Profile(
        timeout_s=fm.limits.timeout_s,
        max_model_calls=fm.max_turns,
        max_tool_calls=fm.limits.max_tool_calls,
    )

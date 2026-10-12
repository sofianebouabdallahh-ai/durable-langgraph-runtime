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


class RunOptions(BaseModel):
    """What a caller may set in `POST /runs {options}`. Unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timeout_s: Annotated[int, Field(gt=0)] | None = None
    max_steps: Annotated[int, Field(gt=0)] | None = None


class RunLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeout_s: Annotated[int, Field(gt=0)]
    max_steps: Annotated[int, Field(gt=0)]


class LimitAboveCeiling(ValueError):
    def __init__(self, field: str, value: float, ceiling: float) -> None:
        super().__init__(f"options.{field}={value} exceeds the server maximum {ceiling}")
        self.field = field
        self.value = value
        self.ceiling = ceiling


def resolve_limits(settings: AgentSettings, options: RunOptions) -> RunLimits:
    ceilings = {"timeout_s": settings.run_timeout_s, "max_steps": settings.run_max_steps}
    resolved: dict[str, Any] = {}
    for field, ceiling in ceilings.items():
        requested = getattr(options, field)
        if requested is not None and requested > ceiling:
            raise LimitAboveCeiling(field, requested, ceiling)
        resolved[field] = requested if requested is not None else ceiling
    return RunLimits(**resolved)

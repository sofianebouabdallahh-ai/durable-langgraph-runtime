"""Tool declarations and the tool registry (R3.4, R14.10, R14.11, R13.1).

Patterns:
- Registry: `ToolRegistry` is the only source of tools. Agent definitions are
  validated against it (the loader's `Catalog`), and the pipeline resolves
  tools from it.
- Decorator: `@registry.tool(...)` declares a tool next to its code, with every
  property the pipeline needs, so no tool can skip a safety step by accident.

A tool never sees policy, idempotency, budgets, hooks or auditing: the
pipeline does all of that around it (R3.4: "agent code never sees these
concerns"). It receives validated arguments and a `ToolContext`.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from agent_runtime.db import Pool

RiskClass = Literal["read", "write_internal", "execute", "external_side_effect"]
Isolation = Literal["in_process", "sandbox"]


class ToolArgs(BaseModel):
    """Base for tool argument models: strict (R14.11). Unknown fields are rejected
    and values are not coerced ("3" is not an int), so the model gets a precise
    error it can correct."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


@dataclass(frozen=True)
class ToolContext:
    """What a tool may use. The idempotency key doubles as the primary key of any
    row a side-effecting tool writes (R2.6), so re-execution can't duplicate it."""

    run_id: uuid.UUID
    epoch: int
    key: str  # sha256 idempotency key of this call
    pool: Pool
    # Sub-agent tools (CR-005) only: the run's orchestrator, and the calling
    # sub-agent when the caller is one. Typed loosely to keep tools free of imports.
    orchestrator: Any = None
    subagent: Any = None


ToolFn = Callable[[Any, ToolContext], Awaitable[Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[ToolArgs]
    fn: ToolFn
    risk_class: RiskClass
    side_effect: bool  # writes outside the run's own state: keyed by the idempotency key
    cache: bool = True  # a completed call with the same key returns the stored result
    max_calls: int | None = None  # per run, across all executions (R14.1)
    isolation: Isolation = "in_process"  # "sandbox" executes in sandboxd (phase 7, CR-002)
    timeout_s: float | None = None  # overrides the pipeline's default (e.g. wait_subagents)

    def json_schema(self) -> dict[str, Any]:
        return self.args_model.model_json_schema()


class UnknownTool(LookupError):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._tools:
            raise ValueError(f"tool {spec.name!r} registered twice")
        if spec.risk_class == "execute" and spec.isolation != "sandbox":
            raise ValueError(f"tool {spec.name!r}: risk class 'execute' requires the sandbox")
        self._tools[spec.name] = spec
        return spec

    def tool(
        self,
        name: str,
        *,
        args: type[ToolArgs],
        risk_class: RiskClass,
        side_effect: bool,
        cache: bool = True,
        max_calls: int | None = None,
        isolation: Isolation = "in_process",
        timeout_s: float | None = None,
    ) -> Callable[[ToolFn], ToolFn]:
        """Decorator: declare a tool next to its implementation."""

        def decorate(fn: ToolFn) -> ToolFn:
            self.register(
                ToolSpec(
                    name=name,
                    description=(fn.__doc__ or "").strip(),
                    args_model=args,
                    fn=fn,
                    risk_class=risk_class,
                    side_effect=side_effect,
                    cache=cache,
                    max_calls=max_calls,
                    isolation=isolation,
                    timeout_s=timeout_s,
                )
            )
            return fn

        return decorate

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError:
            raise UnknownTool(name) from None

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(self._tools[n] for n in sorted(self._tools))

    def catalog(self) -> dict[str, RiskClass]:
        """For the agent loader: which tools exist and how risky they are."""
        return {spec.name: spec.risk_class for spec in self}

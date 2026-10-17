"""ToolPolicy (R3.2): Allow | Deny(reason) | RequireApproval(payload).

Evaluated by the pipeline after grants and pre_tool hooks, before budgets and
idempotency. It's the adapter point for an external policy engine (P2); the
default enforces the risk-class defaults of CR-003 R14.10.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_runtime.tools.spec import ToolSpec


@dataclass(frozen=True)
class Allow:
    pass


@dataclass(frozen=True)
class Deny:
    reason: str


@dataclass(frozen=True)
class RequireApproval:
    reason: str


PolicyDecision = Allow | Deny | RequireApproval


class ToolPolicy(Protocol):
    async def check(self, tool: ToolSpec, args: dict[str, Any]) -> PolicyDecision: ...


@dataclass(frozen=True)
class RiskClassPolicy:
    """Defaults per risk class, plus an optional static deny-list from configuration.
    Configuration can make it stricter, never looser (R14.10)."""

    denied_tools: frozenset[str] = field(default_factory=frozenset)

    async def check(self, tool: ToolSpec, args: dict[str, Any]) -> PolicyDecision:
        if tool.name in self.denied_tools:
            return Deny(f"tool {tool.name!r} is disabled by configuration")
        if tool.risk_class == "external_side_effect":
            return RequireApproval(f"{tool.name} has an external side effect")
        return Allow()

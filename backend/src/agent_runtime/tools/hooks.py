"""Hooks (CR-004 R15.5, R15.7-R15.9): registered code run around tool calls.

Rules enforced here:
- Hooks are code, referenced by name from agent definitions; a definition can
  never contain code (R15.9).
- They can only tighten: continue, modify (args before / result after), deny,
  or ask for human approval (pre_tool only). They can never grant or skip.
- In order; the first deny/ask wins (R15.7).
- Bounded and FAIL CLOSED (R15.8): an exception or a timeout is a deny. A broken
  redaction hook must withhold data, not leak it.
- Deterministic: on resume LangGraph re-runs the tool step, so hooks run again
  and must decide the same way.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any, Literal

HookPoint = Literal[
    "session_start", "turn_start", "pre_model", "post_model",
    "pre_tool", "post_tool", "turn_end", "session_end", "on_error",
]  # fmt: skip


@dataclass(frozen=True)
class Continue:
    pass


@dataclass(frozen=True)
class Modify:
    value: Any  # new args (pre_tool) or new result (post_tool)


@dataclass(frozen=True)
class Deny:
    reason: str


@dataclass(frozen=True)
class Ask:
    payload: dict[str, Any]


HookDecision = Continue | Modify | Deny | Ask


@dataclass(frozen=True)
class ToolHookInput:
    tool: str
    args: dict[str, Any]
    result: Any = None  # post_tool only
    cached: bool = False  # post_tool: the result came from an earlier execution


HookFn = Callable[[ToolHookInput], Awaitable[HookDecision]]


@dataclass(frozen=True)
class HookSpec:
    name: str
    point: HookPoint
    fn: HookFn
    timeout_s: float = 5.0


@dataclass(frozen=True)
class HookOutcome:
    decision: Continue | Deny | Ask
    input: ToolHookInput  # with args/result as modified by the hooks
    audit: list[dict[str, Any]] = field(default_factory=list)  # one entry per non-continue


class UnknownHook(LookupError):
    pass


class HookRegistry:
    def __init__(self) -> None:
        self._hooks: dict[str, HookSpec] = {}

    def hook(
        self, name: str, *, point: HookPoint, timeout_s: float = 5.0
    ) -> Callable[[HookFn], HookFn]:
        def decorate(fn: HookFn) -> HookFn:
            if name in self._hooks:
                raise ValueError(f"hook {name!r} registered twice")
            self._hooks[name] = HookSpec(name, point, fn, min(timeout_s, 30.0))
            return fn

        return decorate

    def get(self, name: str) -> HookSpec:
        try:
            return self._hooks[name]
        except KeyError:
            raise UnknownHook(name) from None

    def catalog(self) -> dict[str, HookPoint]:
        return {name: spec.point for name, spec in self._hooks.items()}


async def run_hooks(specs: list[HookSpec], inp: ToolHookInput) -> HookOutcome:
    """Run `specs` in order (Chain of Responsibility) and return the combined outcome."""
    audit: list[dict[str, Any]] = []
    for spec in specs:
        try:
            decision = await asyncio.wait_for(spec.fn(inp), timeout=spec.timeout_s)
        except Exception as exc:  # incl. TimeoutError: fail closed (R15.8)
            decision = Deny(f"hook_error:{spec.name}:{type(exc).__name__}")
        if spec.point == "post_tool" and isinstance(decision, Ask):
            decision = Deny(f"hook_error:{spec.name}:ask_not_allowed_after_execution")
        if isinstance(decision, Continue):
            continue
        record = {
            "hook": spec.name,
            "point": spec.point,
            "decision": type(decision).__name__.lower(),
        }
        if isinstance(decision, Modify):
            inp = (
                replace(inp, result=decision.value)
                if spec.point == "post_tool"
                else replace(inp, args=decision.value)
            )
            audit.append(record)
            continue
        if isinstance(decision, Deny):
            audit.append(record | {"reason": decision.reason})
        else:
            audit.append(record | {"payload": decision.payload})
        return HookOutcome(decision, inp, audit)  # the first deny / ask wins
    return HookOutcome(Continue(), inp, audit)


# ------------------------------------------------------------- built-in hooks

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),  # OpenAI-style API keys
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key ids
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),  # GitHub tokens
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-.=]{16,}"),
    re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),  # user:password in URLs
]
REDACTED = "[REDACTED]"


def redact(value: Any) -> Any:
    """Recursively replace secret-looking substrings."""
    if isinstance(value, str):
        for pattern in SECRET_PATTERNS:
            value = pattern.sub(REDACTED, value)
        return value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def default_hooks() -> HookRegistry:
    registry = HookRegistry()

    @registry.hook("redact_secrets_in_args", point="pre_tool")
    async def redact_args(inp: ToolHookInput) -> HookDecision:
        cleaned = redact(inp.args)
        return Modify(cleaned) if cleaned != inp.args else Continue()

    @registry.hook("redact_secrets_in_result", point="post_tool")
    async def redact_result(inp: ToolHookInput) -> HookDecision:
        cleaned = redact(inp.result)
        return Modify(cleaned) if cleaned != inp.result else Continue()

    return registry

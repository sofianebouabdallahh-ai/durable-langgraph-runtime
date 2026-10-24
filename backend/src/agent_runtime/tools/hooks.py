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
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal

from agent_runtime.redaction import redact

log = logging.getLogger(__name__)

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


HookFn = Callable[[Any], Awaitable[Any]]  # tool hooks: ToolHookInput → HookDecision


# ------------------------------------------------- session & turn hooks (R15.5, R15.6)


@dataclass(frozen=True)
class Context:
    """session_start / turn_start: context to add to the agent's state."""

    texts: list[str]


@dataclass(frozen=True)
class Summary:
    """session_end: the summary stored on the session."""

    text: str


@dataclass(frozen=True)
class SessionHookInput:
    session_id: str
    agent: str


@dataclass(frozen=True)
class TurnHookInput:
    run_id: str
    session_id: str | None
    agent: str
    message: str


@dataclass(frozen=True)
class TurnEndInput:
    run_id: str
    session_id: str | None
    agent: str
    status: str  # completed | failed | cancelled
    reason: str | None


@dataclass(frozen=True)
class SessionEndInput:
    session_id: str
    agent: str
    stats: dict[str, int]  # messages per type, turns
    last_answer: str | None


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


async def run_context_hooks(specs: list[HookSpec], inp: Any) -> Context | Deny:
    """session_start / turn_start: in order; contexts accumulate; the first deny wins.
    Fail closed: an exception or a timeout denies (R15.8)."""
    texts: list[str] = []
    for spec in specs:
        try:
            decision = await asyncio.wait_for(spec.fn(inp), timeout=spec.timeout_s)
        except Exception as exc:
            return Deny(f"hook_error:{spec.name}:{type(exc).__name__}")
        if isinstance(decision, Deny):
            return decision
        if isinstance(decision, Context):
            texts += decision.texts
    return Context(texts)


async def run_observers(specs: list[HookSpec], inp: Any) -> list[Any]:
    """turn_end / session_end: observe only. A failing hook is logged, never fatal."""
    results: list[Any] = []
    for spec in specs:
        try:
            results.append(await asyncio.wait_for(spec.fn(inp), timeout=spec.timeout_s))
        except Exception:
            log.warning("hook %s failed (observe-only: ignored)", spec.name, exc_info=True)
    return results


# ------------------------------------------------------------- built-in hooks


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

    @registry.hook("session_clock", point="session_start")
    async def session_clock(inp: SessionHookInput) -> Context:
        """Tells the agent when the conversation started (an example of session context)."""
        return Context([f"This conversation started at {datetime.now(UTC):%Y-%m-%d %H:%M} UTC."])

    @registry.hook("summarize_session", point="session_end")
    async def summarize_session(inp: SessionEndInput) -> Summary:
        """A deterministic summary: what happened, and the last answer (no model call)."""
        s = inp.stats
        last = (inp.last_answer or "")[:300]
        return Summary(
            f"{s.get('turns', 0)} turn(s), {s.get('tool_call', 0)} tool call(s), "
            f"{s.get('error', 0)} error(s). Last answer: {last or '(none)'}"
        )

    return registry

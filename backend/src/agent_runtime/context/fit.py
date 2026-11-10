"""Fit one model request inside the model's context window (phase H5).

Non-destructive: it returns the messages to SEND; the agent's state (the checkpoint, the
transcript) keeps everything. Applied before every model call, main agents and helpers.

Strategies, in order, each only while the request is still too big:

    1 clear old tool results   oldest first, the latest KEEP_RESULTS kept, and never the
                               results of the latest step (the model hasn't seen them
                               yet: cleared, it would only call the tools again); the
                               call / result pairing stays, so the request is still valid
    2 head and tail            the longest older messages shortened to their start and
                               end; the latest exchange too only after a refusal

Tokens are estimated (characters / 4 plus a little per message, and the tools' schemas):
cheap, provider-neutral, and erring high. The budget leaves room for the reply.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately

TRIM_AT = 0.60  # share of the window past which old tool results are cleared
SHORTEN_AT = 0.85  # past which older long messages are cut to their head and tail
KEEP_RESULTS = 2  # the latest tool results are always sent whole
REPLY_RESERVE = 1_024  # tokens left for the model's answer
HEAD_TAIL_CHARS = 600  # what a shortened message keeps at each end
CLEARED = (
    "[runtime] This tool result was cleared to make room ({n} characters). "
    "Call the tool again if you need it."
)


def estimate(messages: Sequence[BaseMessage], tools: Sequence[Any] = ()) -> int:
    """An over-estimate of what `messages` (and the tools' schemas) cost in tokens."""
    return count_tokens_approximately(messages, tools=list(tools) or None)


@dataclass(frozen=True, slots=True)
class Fitted:
    messages: list[Any]  # the request's own message types, some replaced
    tokens_before: int
    tokens_after: int
    cleared: int = 0  # tool results cleared
    shortened: int = 0  # messages cut to head and tail
    notes: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.cleared or self.shortened)


def fit(
    messages: Sequence[Any],
    window: int,
    tools: Sequence[Any] = (),
    *,
    trim_at: float = TRIM_AT,
    shorten_at: float = SHORTEN_AT,
    keep_results: int = KEEP_RESULTS,
    protect_latest: bool = True,
) -> Fitted:
    """The messages to send so the request fits `window` tokens (see the module doc).
    After the model refused a request as too long, the caller fits again with nothing
    protected: no result kept whole, the latest exchange shortened too."""
    out = list(messages)
    before = estimate(out, tools)
    tools_cost = estimate([], tools) if tools else 0
    budget = max(window - REPLY_RESERVE, window // 2)

    def cost() -> int:
        return estimate(out, tools)

    if before <= trim_at * budget:
        return Fitted(out, before, before)
    cleared = 0
    latest = _latest_exchange(out)
    results = [i for i, m in enumerate(out) if isinstance(m, ToolMessage) and i < latest]
    for i in results[: max(len(results) - keep_results, 0)]:
        if cost() <= trim_at * budget:
            break
        m = out[i]
        assert isinstance(m, ToolMessage)
        text = _text(m.content)
        if text.startswith("[runtime] This tool result was cleared"):
            continue
        out[i] = m.model_copy(update={"content": CLEARED.format(n=len(text))})
        cleared += 1
    shortened = 0
    if cost() > shorten_at * budget:
        upto = latest if protect_latest else len(out)
        # Longest first: the fewest messages cut for the most room.
        for i in sorted(range(upto), key=lambda k: -len(_text(out[k].content))):
            if cost() <= shorten_at * budget:
                break
            m = out[i]
            text = _text(m.content)
            if len(text) <= 3 * HEAD_TAIL_CHARS or (isinstance(m, AIMessage) and m.tool_calls):
                continue
            cut = len(text) - 2 * HEAD_TAIL_CHARS
            out[i] = m.model_copy(update={"content": (
                f"{text[:HEAD_TAIL_CHARS]}\n…[runtime: {cut} characters left out to make "
                f"room]…\n{text[-HEAD_TAIL_CHARS:]}")})  # fmt: skip
            shortened += 1
    after = cost()
    notes = [] if after <= budget else [f"still {after} of {budget} tokens ({tools_cost} tools)"]
    return Fitted(out, before, after, cleared, shortened, notes)


def _latest_exchange(messages: list[BaseMessage]) -> int:
    """Index of the last AI message with tool calls (its results follow it), or of the
    last message: from there on, nothing is shortened."""
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if isinstance(m, AIMessage) and m.tool_calls:
            return i
    return max(len(messages) - 1, 0)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b if isinstance(b, str) else str(b.get("text", "")) if isinstance(b, dict) else ""
            for b in content
        )
    return str(content)


class ContextOverflow(Exception):
    """The model refused the request as too long, even fitted again (→ the turn fails
    `context_overflow`; the next message starts compacted)."""


_OVERFLOW = re.compile(
    r"context_length_exceeded|maximum context length|context (?:length|window)|"
    r"too many tokens|prompt is too long|reduce the length of the messages",
    re.IGNORECASE,
)
_LIMIT = re.compile(
    r"(?:maximum context length is|context (?:length|window) (?:is|of)|limit of)\s*"
    r"(\d[\d,]*)\s*tokens",
    re.IGNORECASE,
)


def overflow(exc: BaseException) -> tuple[bool, int | None]:
    """Is `exc` a provider saying the request is too long, and the window it states."""
    text = " ".join(str(x) for x in (getattr(exc, "code", None), exc, getattr(exc, "body", None))
                    if x)  # fmt: skip
    if not _OVERFLOW.search(text):
        return False, None
    found = _LIMIT.search(text)
    return True, int(found.group(1).replace(",", "")) if found else None

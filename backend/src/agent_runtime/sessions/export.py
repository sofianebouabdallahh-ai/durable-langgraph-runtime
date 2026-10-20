"""A chat as Markdown (phase L5, local-release §4.7): to keep, move or attach to a
report. Everything the transcript holds, in order: messages, tool calls and their
results, approvals, errors. Pattern: a pure function of the transcript."""

from __future__ import annotations

import json
import re
from typing import Any

from agent_runtime.sessions.store import Message, Session

MAX_RESULT = 2000  # a tool result is cut here: the reply around it is what matters


def _block(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False)
    if len(text) > MAX_RESULT:
        text = text[:MAX_RESULT] + "\n… (cut)"
    # A fence longer than any run of backticks inside, so the content can't close it.
    fence = "`" * max(3, 1 + max((len(r) for r in re.findall(r"`+", text)), default=0))
    return f"{fence}\n{text}\n{fence}"


def _line(m: Message) -> str | None:
    c = m.content
    match m.type:
        case "user":
            return f"**You** · {m.created_at:%Y-%m-%d %H:%M}\n\n{c.get('text', '')}"
        case "assistant":
            text = str(c.get("text", ""))
            return f"**Assistant**{' (stopped)' if c.get('interrupted') else ''}\n\n{text}"
        case "tool_call":
            return f"*Used {c.get('tool')}*\n\n{_block(c.get('args', {}))}"
        case "tool_result":
            if "error" in c:
                return f"*{c.get('tool')} failed:* {c['error']}"
            replay = " (replayed)" if c.get("cached") else ""
            return f"*{c.get('tool')} returned{replay}*\n\n{_block(c.get('result'))}"
        case "interrupt":
            return f"*Waiting for your approval ({c.get('interrupt_type') or 'approval'})*"
        case "approval":
            return f"*You {c.get('decision', 'decided')}*" + (
                f": {c['reason']}" if c.get("reason") else ""
            )
        case "error":
            return f"*The turn stopped: {c.get('reason')}*"
        case _:
            return None  # system context isn't part of the conversation


def to_markdown(session: Session, messages: list[Message]) -> str:
    head = [
        f"# {session.title or 'Chat'}",
        "",
        f"Agent: {session.agent_name or session.graph_name} · "
        f"started {session.created_at:%Y-%m-%d %H:%M} UTC · exported from Nuria",
        "",
    ]
    body = [line for m in messages if (line := _line(m)) is not None]
    return "\n".join(head) + "\n\n---\n\n".join(body) + "\n"

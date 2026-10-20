"""A chat as Markdown (phase L5; fuller in L6): to keep, move, study or attach to a report.

Everything the conversation holds, turn by turn and in order:
- what you wrote, and each reply with the model that wrote it and its tokens;
- the model's **reasoning**, when its provider returns it (reasoning models do);
- every **tool call** with its arguments, and every **result**, in full (up to the
  tool-result limit the model itself saw);
- what each **helper** did (its task, its steps and how it ended), from the run's events;
- approvals, stops and errors.

Pattern: a pure function of the transcript and the run events (no I/O here).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from agent_runtime.runs.events import EventType
from agent_runtime.sessions.store import Message, Session

MAX_RESULT = 20_000  # the tool-result limit (R14.5): what the model saw, at most


def _block(value: Any, language: str = "") -> str:
    text = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False)
    if len(text) > MAX_RESULT:
        text = text[:MAX_RESULT] + "\n… (cut)"
    # A fence longer than any run of backticks inside, so the content can't close it.
    fence = "`" * max(3, 1 + max((len(r) for r in re.findall(r"`+", text)), default=0))
    return f"{fence}{language}\n{text}\n{fence}"


def _thinking(reasoning: Any) -> str:
    if not isinstance(reasoning, str) or not reasoning.strip():
        return ""
    quoted = "\n".join(f"> {line}" if line else ">" for line in reasoning.strip().splitlines())
    return f"> 💭 **Reasoning**\n>\n{quoted}\n\n"


def _assistant(c: dict[str, Any]) -> str:
    facts = [str(c["model"])] if c.get("model") else []
    if c.get("tokens"):
        facts.append(f"{c['tokens']} tokens")
    state = " (stopped)" if c.get("interrupted") else ""
    state += " (wrapped up at its limit)" if c.get("budget_limited") else ""
    head = f"### 🤖 Assistant{state}" + (f" · {' · '.join(facts)}" if facts else "")
    return f"{head}\n\n{_thinking(c.get('reasoning'))}{c.get('text', '')}"


def _line(m: Message) -> str | None:
    c = m.content
    match m.type:
        case "user":
            return f"### 🧑 You · {m.created_at:%H:%M}\n\n{c.get('text', '')}"
        case "assistant":
            return _assistant(c)
        case "tool_call":
            args = _block(c.get("args", {}), "json")
            return (
                f"#### 🔧 Tool call: `{c.get('tool')}`\n\n"
                f"{_thinking(c.get('reasoning'))}Arguments:\n\n{args}"
            )
        case "tool_result":
            if "error" in c:
                return f"#### ❌ `{c.get('tool')}` failed\n\n{_block(c['error'])}"
            replay = " (served from the first call)" if c.get("cached") else ""
            took = f" · {c['duration_ms']} ms" if c.get("duration_ms") else ""
            result = _block(c.get("result"), "json")
            return f"#### 📥 Result of `{c.get('tool')}`{replay}{took}\n\n{result}"
        case "interrupt":
            return f"#### ⏸ Waiting for your approval ({c.get('interrupt_type') or 'approval'})"
        case "approval":
            why = f": {c['reason']}" if c.get("reason") else ""
            return f"#### ✋ You {c.get('decision', 'decided')}{why}"
        case "error":
            return f"#### ⚠️ The turn stopped: {c.get('reason')}"
        case _:
            return None  # system context isn't part of the conversation


def _helpers(events: list[dict[str, Any]]) -> str:
    """What each helper did in a turn: its task, its tool steps, how it ended."""
    tasks: dict[str, dict[str, Any]] = {}
    steps: dict[str, list[str]] = defaultdict(list)
    for e in events:
        p, kind = e.get("payload") or {}, e.get("type")
        handle = str(p.get("handle") or p.get("subagent") or "")
        if kind == EventType.SUBAGENT_SPAWNED:
            tasks[handle] = {"agent": p.get("agent"), "task": p.get("task"), "status": "running"}
        elif kind == EventType.SUBAGENT_PROGRESS and handle:
            percent = f" ({p['percent']}%)" if p.get("percent") is not None else ""
            steps[handle].append(f"- progress: {p.get('message')}{percent}")
        elif kind == EventType.TOOL_CALLED and p.get("subagent"):
            args = json.dumps(p.get("args"), ensure_ascii=False)[:300]
            steps[handle].append(f"- called `{p.get('tool')}` with {args}")
        elif kind == EventType.TOOL_COMPLETED and p.get("subagent"):
            steps[handle].append(f"- `{p.get('tool')}`: {p.get('status')}")
        elif kind == EventType.SUBAGENT_COMPLETED and handle in tasks:
            tasks[handle]["status"] = p.get("result_status") or p.get("status")
    if not tasks:
        return ""
    parts = ["#### 👥 Helpers"]
    for handle, t in tasks.items():
        done = "\n".join(steps[handle]) or "- (no steps recorded)"
        parts.append(f"**{t['agent']}** ({t['status']})\n\nTask: {t['task']}\n\n{done}")
    return "\n\n".join(parts)


def to_markdown(
    session: Session,
    messages: list[Message],
    events: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    """`events`: each turn's run events by run id (for the helpers' work)."""
    events = events or {}
    models = sorted(
        {
            str(m.content["model"])
            for m in messages
            if m.type == "assistant" and m.content.get("model")
        }
    )
    head = [
        f"# {session.title or 'Chat'}",
        "",
        f"- **Agent:** {session.agent_name or session.graph_name}",
        f"- **Started:** {session.created_at:%Y-%m-%d %H:%M} UTC",
        f"- **Models:** {', '.join(models) or '—'}",
        f"- **Tokens:** {session.tokens} · **cost:** ${session.cost:.4f}",
        "- Exported from Nuria: replies, the models' reasoning (when they give it), every "
        "tool call with its arguments and result, and what helpers did.",
        "",
    ]
    turns: list[tuple[str | None, list[str]]] = []
    for m in messages:
        line = _line(m)
        if line is None:
            continue
        if m.type == "user" or not turns:
            turns.append((str(m.run_id) if m.run_id else None, []))
        turns[-1][1].append(line)
    body = []
    for i, (run, parts) in enumerate(turns, 1):
        helpers = _helpers(events.get(run, [])) if run else ""
        body.append(f"## Turn {i}\n\n" + "\n\n".join([*parts, *([helpers] if helpers else [])]))
    return "\n".join(head) + "\n---\n\n" + "\n\n---\n\n".join(body) + "\n"

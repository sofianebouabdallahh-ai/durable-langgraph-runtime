"""A chat turn's place in its session's thread (CR-001 D4: session = thread, turn = run).

Every turn's user message carries a stable id, `user:<run_id>`. Its position in
the thread's messages is therefore this turn's *baseline* on every execution,
including after a reclaim, and needs no extra storage: everything after it was
produced by this run.

A turn that ended mid-tool (cancelled, failed) leaves an AI message whose tool
calls have no results. Providers reject such a conversation, so the next turn's
input first closes them with a "not executed" tool result.
"""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

INTERRUPTED_TOOL_RESULT = "Error: this tool call did not run (the previous turn ended first)."
REPAIR_PREFIX = "repair:"


def user_message_id(run_id: uuid.UUID) -> str:
    return f"user:{run_id}"


def repair_id(run_id: uuid.UUID, tool_call_id: str) -> str:
    """Repairs belong to the turn that adds them (they precede its user message)."""
    return f"{REPAIR_PREFIX}{run_id}:{tool_call_id}"


def baseline(messages: list[BaseMessage], run_id: uuid.UUID) -> int | None:
    """Index of this turn's user message in the thread, or None if it isn't there."""
    wanted = user_message_id(run_id)
    return next((i for i, m in enumerate(messages) if m.id == wanted), None)


def turn_input(
    prior: list[BaseMessage], text: str, run_id: uuid.UUID
) -> dict[str, list[BaseMessage]]:
    """The graph input that starts a turn on an existing (or empty) thread."""
    answered = {m.tool_call_id for m in prior if isinstance(m, ToolMessage)}
    repairs: list[BaseMessage] = [
        ToolMessage(content=INTERRUPTED_TOOL_RESULT, tool_call_id=tc["id"], name=tc["name"],
                    status="error", id=repair_id(run_id, str(tc["id"])))
        for m in prior
        if isinstance(m, AIMessage)
        for tc in m.tool_calls
        if tc["id"] not in answered
    ]  # fmt: skip
    return {"messages": [*repairs, HumanMessage(content=text, id=user_message_id(run_id))]}


def script_offset(messages: list[Any]) -> int:
    """The scripted model's turn index starts at this turn's user message: AI
    messages of earlier turns don't count (the script lives in the run's input)."""
    last_user = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
    return sum(isinstance(m, AIMessage) for m in messages[: max(last_user, 0)])

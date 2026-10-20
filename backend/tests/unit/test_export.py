"""A chat as Markdown (L5): code blocks can't be closed by what they contain."""

from agent_runtime.sessions.export import MAX_RESULT, _block


def test_a_block_is_fenced_longer_than_any_backticks_inside() -> None:
    assert _block({"a": 1}).startswith("```\n{")
    tricky = _block("before ```` after")
    assert tricky.startswith("`````\n") and tricky.endswith("\n`````")


def test_a_long_result_is_cut() -> None:
    assert _block("x" * (MAX_RESULT + 50)).count("x") == MAX_RESULT
    assert "… (cut)" in _block("x" * (MAX_RESULT + 1))


def test_a_turn_reads_in_order_with_its_reasoning_tools_and_helpers() -> None:
    """L6: the whole turn: you, the model's reasoning, each tool call with its arguments,
    its result, the reply with its model and tokens, and what each helper did."""
    import uuid
    from datetime import UTC, datetime
    from typing import Any

    from agent_runtime.runs.events import EventType
    from agent_runtime.sessions.export import to_markdown
    from agent_runtime.sessions.store import Message, Session

    now = datetime(2026, 10, 20, 9, 30, tzinfo=UTC)
    sid, run = uuid.uuid4(), uuid.uuid4()
    session = Session(sid, "chat", "chat", "Ferries", "active", 6, 900, 0.0012, None, now, now,
                      None)  # fmt: skip

    def msg(seq: int, type_: Any, content: dict[str, Any]) -> Message:
        return Message(sid, seq, f"m{seq}", run, 1, type_, "assistant", content, now)

    messages = [
        msg(1, "user", {"text": "Ferry price?"}),
        msg(2, "system", {"text": "This conversation started at …"}),
        msg(3, "tool_call", {"tool": "run_python", "args": {"code": "print(22*4)"},
                             "reasoning": "Four tickets: multiply."}),
        msg(4, "tool_result", {"tool": "run_python", "result": {"stdout": "88\n"},
                               "duration_ms": 120}),
        msg(5, "assistant", {"text": "€88 in total.", "model": "qwen2.5:7b", "tokens": 512,
                             "reasoning": "The sum is done."}),
    ]  # fmt: skip
    events = {str(run): [
        {"type": EventType.SUBAGENT_SPAWNED,
         "payload": {"handle": "h1", "agent": "price-checker", "task": "Check Seajets"}},
        {"type": EventType.TOOL_CALLED,
         "payload": {"subagent": "h1", "tool": "web_search", "args": {"query": "seajets"}}},
        {"type": EventType.SUBAGENT_COMPLETED,
         "payload": {"handle": "h1", "result_status": "success"}},
    ]}  # fmt: skip
    md = to_markdown(session, messages, events)
    assert md.startswith("# Ferries\n") and "- **Models:** qwen2.5:7b" in md
    assert "This conversation started" not in md  # system context isn't the conversation
    order = [md.index(s) for s in (
        "## Turn 1", "### 🧑 You · 09:30", "Ferry price?",
        "#### 🔧 Tool call: `run_python`", "> 💭 **Reasoning**", "> Four tickets: multiply.",
        '"code": "print(22*4)"',
        "#### 📥 Result of `run_python` · 120 ms", '"stdout": "88\\n"',
        "### 🤖 Assistant · qwen2.5:7b · 512 tokens", "> The sum is done.", "€88 in total.",
        "#### 👥 Helpers", "**price-checker** (success)", "Task: Check Seajets",
        '- called `web_search` with {"query": "seajets"}',
    )]  # fmt: skip
    assert order == sorted(order)

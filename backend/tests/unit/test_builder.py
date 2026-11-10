"""The builder's pure parts (L3c.6): the demo drafter, the proposal checks."""

from __future__ import annotations

import uuid

import pytest

from agent_runtime.agents.builder import (
    BuilderError,
    DraftProposal,
    HelperProposal,
    InstructionsProposal,
    demo_draft,
    demo_improve,
    describe_message,
    only_offered,
    propose_draft,
    propose_instructions,
)
from agent_runtime.tools.spec import ToolContext

CTX = ToolContext(run_id=uuid.uuid4(), epoch=1, key="k", pool=None)  # type: ignore[arg-type]
LIBRARY = [("trip-planning", "Plan trips."), ("plain-writing", "Write plainly.")]


def test_the_demo_drafter_is_deterministic_and_reads_the_description() -> None:
    text = "Remember my notes and email the team when a deadline is near"
    one, two = demo_draft(text, LIBRARY), demo_draft(text, LIBRARY)
    assert one == two
    assert one.tools == ["save_note", "notify"] and one.helpers == [] and one.skills == []
    assert one.display_name == "Remember Notes assistant"  # filler words dropped


async def test_every_demo_draft_is_valid() -> None:
    for text in ("x" * 10, "Plan a trip and a helper that books trains", "Search, cite, sum"):
        accepted = await propose_draft(demo_draft(text, LIBRARY), CTX)
        assert accepted["accepted"] is True


async def test_a_bad_draft_comes_back_with_its_problems() -> None:
    draft = DraftProposal(
        display_name="X", description="d", instructions="You are X. {{secret}}",
        tools=["web_search"],
        helpers=[HelperProposal(display_name="Pinger", description="d", instructions="i")],
    )  # fmt: skip
    with pytest.raises(BuilderError) as found:
        await propose_draft(draft, CTX)
    assert "secret" in str(found.value)  # the one validator's placeholder rule


async def test_what_a_person_would_fix_is_fixed_with_a_note() -> None:
    """A small model rarely manages a second proposal: an unknown tool is left out, and
    a tool that asks first moves from a helper to the agent itself."""
    draft = DraftProposal(
        display_name="X", description="d", instructions="You are X.",
        tools=["teleport", "web_search"],
        helpers=[HelperProposal(display_name="Pinger", description="d", instructions="i",
                                tools=["notify", "read_webpage"])],
    )  # fmt: skip
    done = await propose_draft(draft, CTX)
    assert done["accepted"] is True
    proposal = done["proposal"]
    assert proposal["tools"] == ["web_search", "read_webpage", "notify"]
    assert proposal["helpers"][0]["tools"] == ["read_webpage"]
    assert done["repairs"] == [
        "Left out “teleport”: there's no such tool here.",
        "Added “read_webpage”: with “web_search” it reads the pages it relies on, not just "
        "their snippets.",
        "Moved “notify” from Pinger to the agent itself: it asks you first, and only the "
        "agent can ask.",
    ]


async def test_improved_instructions_keep_to_the_placeholders() -> None:
    ok = InstructionsProposal(instructions="You help. Today is {{date}}.", what_changed="x")
    assert (await propose_instructions(ok, CTX))["accepted"] is True
    bad = InstructionsProposal(instructions="You help {{user.email}}.", what_changed="x")
    with pytest.raises(BuilderError, match=r"user\.email"):
        await propose_instructions(bad, CTX)


def test_the_demo_coach_adds_only_what_is_missing() -> None:
    clear = "You are X. Today is {{date}}. Ask a question when unsure. Never make up facts."
    assert demo_improve(clear, "X").instructions == clear
    assert "no changes needed" in demo_improve(clear, "X").what_changed
    short = demo_improve("You answer questions.", "X")
    assert short.instructions.count("\n- ") == 2  # the date and "never make up"


def test_the_drafter_only_offers_tools_this_installation_has() -> None:
    """Without a sandbox (setup --no-sandbox) no draft gets Run Python: the Studio
    wouldn't show it, and the agent couldn't use it (L6)."""
    text = "Work out the budget for a trip and a helper that compares prices"
    everything = demo_draft(text, LIBRARY)
    assert "run_python" in everything.tools and "run_python" in everything.helpers[0].tools
    no_sandbox = ["web_search", "read_webpage", "save_note", "notify"]
    assert "run_python" not in demo_draft(text, LIBRARY, no_sandbox).tools
    trimmed = only_offered(everything, no_sandbox)
    assert "run_python" not in trimmed.tools and "run_python" not in trimmed.helpers[0].tools
    assert "run_python" not in describe_message(text, LIBRARY, no_sandbox)
    assert "run_python" in describe_message(text, LIBRARY)


def test_mcp_tools_switched_on_can_be_drafted() -> None:
    from agent_runtime.agents.builder import describe_message, repair

    mcp = {"mcp__travel__lookup": "read", "mcp__travel__send_message": "external_side_effect"}
    draft = DraftProposal(
        display_name="X", description="d", instructions="You are X.",
        tools=["mcp__travel__lookup"],
        helpers=[HelperProposal(display_name="Scout", description="d", instructions="i",
                                tools=["mcp__travel__lookup", "mcp__travel__send_message"])],
    )  # fmt: skip
    fixed, notes = repair(draft, mcp)  # type: ignore[arg-type]
    assert fixed.tools == ["mcp__travel__lookup", "mcp__travel__send_message"]
    assert fixed.helpers[0].tools == ["mcp__travel__lookup"]  # runs without asking: fine
    assert notes == ["Moved “mcp__travel__send_message” from Scout to the agent itself: it asks "
                     "you first, and only the agent can ask."]  # fmt: skip
    message = describe_message(
        "Plans trips.", [], None, {"mcp__travel__lookup": "Looks up a fact."}
    )
    assert "- mcp__travel__lookup: Looks up a fact. (from an MCP server)" in message


def test_searching_the_web_comes_with_reading_pages() -> None:
    # A drafted trip planner searched but couldn't read a page: web_search tells the
    # model to read one before relying on it, with a tool it didn't have.
    from agent_runtime.agents.builder import repair

    draft = DraftProposal(
        display_name="X", description="d", instructions="You are X.", tools=["web_search"],
        helpers=[HelperProposal(display_name="Scout", description="d", instructions="i",
                                tools=["web_search", "read_webpage"])],
    )  # fmt: skip
    fixed, notes = repair(draft)
    assert fixed.tools == ["web_search", "read_webpage"]
    assert fixed.helpers[0].tools == ["web_search", "read_webpage"]  # had both: unchanged
    assert notes == ["Added “read_webpage”: with “web_search” it reads the pages it relies "
                     "on, not just their snippets."]  # fmt: skip

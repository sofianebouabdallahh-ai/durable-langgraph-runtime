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
        tools=["teleport"],
        helpers=[HelperProposal(display_name="Pinger", description="d", instructions="i",
                                tools=["notify"])],
    )  # fmt: skip
    with pytest.raises(BuilderError) as found:
        await propose_draft(draft, CTX)
    message = str(found.value)
    assert "unknown tool “teleport”" in message
    assert "can't send notifications" in message
    assert "secret" in message  # the one validator's placeholder rule


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

"""Which tool a reply says did something it didn't (the claim check, small-model repairs)."""

import pytest
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent_runtime.tools.middleware import _claims_undone

TOOLS = {"save_note", "notify", "web_search"}


def reply(text: str) -> ModelResponse[None]:
    return ModelResponse(result=[AIMessage(content=text)])


@pytest.mark.parametrize(
    ("text", "tool"),
    [
        ("I've saved that in my notes.", "save_note"),
        ("I noted that Sam prefers tea.", "save_note"),
        ("Note: it has been saved.", "save_note"),
        ("I\u2019ve sent it to the team.", "notify"),  # a curly apostrophe
        ("The demo is on Friday.", None),  # no claim
        ("You sent me the file yesterday.", None),  # not the agent's own
    ],
)
def test_the_claimed_tool(text: str, tool: str | None) -> None:
    assert _claims_undone([HumanMessage("go")], reply(text), TOOLS) == tool


def test_a_tool_that_ran_since_the_message_or_one_it_lacks_is_no_claim() -> None:
    ran = [HumanMessage("go"), ToolMessage("ok", tool_call_id="c1", name="save_note")]
    assert _claims_undone(ran, reply("I've saved it."), TOOLS) is None
    failed = [HumanMessage("go"), ToolMessage("Error", tool_call_id="c1", name="save_note",
                                              status="error")]  # fmt: skip
    assert _claims_undone(failed, reply("I've saved it."), TOOLS) == "save_note"
    before = [ToolMessage("ok", tool_call_id="c0", name="save_note"), HumanMessage("again")]
    assert _claims_undone(before, reply("I've saved it."), TOOLS) == "save_note"
    assert _claims_undone([HumanMessage("go")], reply("I've saved it."), {"web_search"}) is None

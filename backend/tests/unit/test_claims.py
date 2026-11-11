"""The small-model repairs' readers: which tool a reply says did something it didn't (the
claim check), and which replies are tool calls written out as text."""

import pytest
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from agent_runtime.tools.middleware import _claims_undone, _from_text_calls, _text_calls

TOOLS = {"save_note", "notify", "recall_notes", "forget_note", "web_search"}
REMEMBER = HumanMessage("Remember that the demo is on Friday")
SEND = HumanMessage("Tell the team the build is green")
FORGET = HumanMessage("Forget my locker code")


def reply(text: str) -> ModelResponse[None]:
    return ModelResponse(result=[AIMessage(content=text)])


def claim(messages: list[BaseMessage], text: str, tools: set[str] = TOOLS) -> str | None:
    return _claims_undone(messages, reply(text), tools)


@pytest.mark.parametrize(
    ("asked", "text", "tool"),
    [
        (REMEMBER, "I've saved that in my notes.", "save_note"),
        (REMEMBER, "I noted that the demo is on Friday.", "save_note"),
        (REMEMBER, 'Note: "the demo is on Friday" has been saved.', "save_note"),
        (REMEMBER, 'save_note called with the message: "Sam prefers tea."', "save_note"),
        (SEND, "I\u2019ve sent it to the team.", "notify"),  # a curly apostrophe
        (REMEMBER, "The demo is on Friday.", None),  # no claim
        # Sentences that only look like claims (found by the review):
        (REMEMBER, "Nothing has been saved yet.", None),
        (REMEMBER, "I haven't saved it: should I?", None),
        (REMEMBER, "As I noted earlier, it's on Friday.", None),
        (HumanMessage("Where is it hottest?"), "The record has been noted in Death Valley.", None),
        (HumanMessage("What did I send?"), "The link I sent you is below.", None),
        # The second review: claims it missed…
        (REMEMBER, "Got it \u2014 I've saved that.", "save_note"),
        (REMEMBER, "Got it - I've saved that.", "save_note"),
        (REMEMBER, "No problem, I've saved that.", "save_note"),
        (REMEMBER, "Don't worry, I've saved it.", "save_note"),
        (REMEMBER, 'Note: "Sam does not eat meat" has been saved.', "save_note"),
        (REMEMBER, "I've successfully saved it.", "save_note"),
        (REMEMBER, "I've recorded that.", "save_note"),
        (SEND, "The team has been notified.", "notify"),
        (SEND, "Message sent to the team.", "notify"),
        (SEND, "Done! I've let the team know.", "notify"),
        # …and what it took for a claim:
        (HumanMessage("Did you save that?"), "Yes, I saved it.", None),
        (HumanMessage("Do you remember when the demo is?"), "Yes, I noted it's Friday.", None),
        (HumanMessage("Did you send the message to Sam?"), "Yes, it has been sent.", None),
        (HumanMessage("Send me a summary of the article"), "Sure, I've sent it below.", None),
        (HumanMessage("Tell me what you found"), "I've sent the findings below.", None),
        (HumanMessage("Keep it short: what's 2+2?"), "4. I've noted you like short answers.", None),
        # Forgetting (H8): "I've forgotten it", with no forget_note call, isn't true either.
        (FORGET, "I've forgotten your locker code.", "forget_note"),
        (FORGET, "Done, I deleted it.", None),  # deleted what? not said: no claim
        (HumanMessage("Please remove that note"), "The note has been removed.", "forget_note"),
        (FORGET, "I have not forgotten it: which code?", None),
        (HumanMessage("Don't forget the demo is Friday"), "I've saved that.", "save_note"),
        (HumanMessage("Remove the onions from the recipe"), "I've removed the onions.", None),
        (HumanMessage("Did you forget my code?"), "Yes, I've forgotten it.", None),
        # …and what the review found would have made it forget a real note:
        (
            HumanMessage("Forget the onions, take them off my shopping list"),
            "Sure, I've removed the onions.",
            None,
        ),
        (
            HumanMessage("Never mind, forget it. Delete the draft email"),
            "OK, I deleted the draft.",
            None,
        ),
        (
            HumanMessage("I always forget my locker code, it's 4321"),
            "I've saved it. I removed the old one.",
            None,  # nothing was asked to be kept or forgotten
        ),
        (HumanMessage("dont forget my locker code"), "I've forgotten it.", None),
        (HumanMessage("do not  forget my locker code"), "I've forgotten it.", None),
        (HumanMessage("Never forget my locker code"), "I've forgotten it.", None),
        (FORGET, "Done, I deleted it from my notes.", "forget_note"),
    ],
)
def test_the_claimed_tool(asked: HumanMessage, text: str, tool: str | None) -> None:
    assert claim([asked], text) == tool


def test_a_tool_that_ran_since_the_message_or_one_it_lacks_is_no_claim() -> None:
    ran = [REMEMBER, ToolMessage("ok", tool_call_id="c1", name="save_note")]
    assert claim(ran, "I've saved it.") is None
    failed = [REMEMBER, ToolMessage("Error", tool_call_id="c1", name="save_note", status="error")]
    assert claim(failed, "I've saved it.") == "save_note"
    before = [ToolMessage("ok", tool_call_id="c0", name="save_note"), REMEMBER]
    assert claim(before, "I've saved it.") == "save_note"
    assert claim([REMEMBER], "I've saved it.", {"web_search"}) is None


def test_a_forget_that_ran_is_no_claim() -> None:
    ran = [FORGET, ToolMessage("ok", tool_call_id="c1", name="forget_note")]
    assert claim(ran, "I've forgotten it.") is None


def test_an_answer_from_notes_read_back_is_no_claim() -> None:
    # "What did I tell you?": it reads its notes, and answers "I saved a note that…".
    # Asked again, it would save the note twice.
    read = [HumanMessage("Remember what I said about the demo?"),
            ToolMessage('{"notes": []}', tool_call_id="c1", name="recall_notes")]  # fmt: skip
    assert claim(read, "I saved a note that the demo is on Friday.") is None
    # Only the notes: a message it says it sent, it didn't (the second review).
    sent = [HumanMessage("Look up my notes and send them to the team"),
            ToolMessage('{"notes": []}', tool_call_id="c1", name="recall_notes")]  # fmt: skip
    assert claim(sent, "I've sent your notes to the team.") == "notify"


@pytest.mark.parametrize(
    ("text", "calls"),
    [
        ('save_note({"text": "x"})', [("save_note", {"text": "x"})]),
        ("recall_notes()", [("recall_notes", {})]),
        ('<tool_call>{"name": "save_note", "arguments": {"text": "a <tool_call> b"}}</tool_call>',
         [("save_note", {"text": "a <tool_call> b"})]),  # tags inside the text are kept
        ('```\n{"name": "save_note", "arguments": "{\\"text\\": \\"y\\"}"}\n```',
         [("save_note", {"text": "y"})]),
        ('{"name": {"first": "Ada", "last": "Lovelace"}, "born": 1815}', None),  # an answer
        ('["save_note"]', None),
        ('Sure: <tool_call>{"name": "save_note", "arguments": {}}</tool_call>', None),
        ('<tool_call>\n{"name": "save_note", "arguments": {"text": "x"}}',  # never closed
         [("save_note", {"text": "x"})]),
    ],
)  # fmt: skip
def test_what_reads_as_a_tool_call(
    text: str, calls: list[tuple[str, dict[str, str]]] | None
) -> None:
    found = _text_calls(text, TOOLS)
    assert (None if found is None else [(c["name"], c["args"]) for c in found]) == calls


def test_a_json_answer_never_fails_the_turn() -> None:
    answer = '{"name": {"first": "Ada"}}'
    repaired = _from_text_calls(reply(answer), TOOLS)
    assert repaired.result[0].content == answer  # the review: TypeError before


class _Asked:
    """The middleware's second ask, with the model call stubbed to raise."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def _call(self, *_: object) -> ModelResponse[None]:
        raise self.error


async def ask_once_more(error: Exception) -> ModelResponse[None]:
    from types import SimpleNamespace
    from typing import Any, cast

    from agent_runtime.tools.middleware import RuntimeMiddleware

    first = reply("I've saved it.")
    request = cast(Any, SimpleNamespace(messages=[REMEMBER], override=lambda **_: None))
    return await RuntimeMiddleware._honest(
        cast(Any, _Asked(error)), cast(Any, None), request, cast(Any, None), cast(Any, None),
        None, first, "save_note", cast(Any, None), [0],
    )  # fmt: skip


async def test_stop_during_the_second_ask_stops_the_turn() -> None:
    # The second review: Stop raises CancelRequested from the token stream; caught as a
    # failed call, the turn completed with the false claim.
    from agent_runtime.runs.executor import CancelRequested, LeaseLost

    for control in (CancelRequested("stop"), LeaseLost("taken over")):
        with pytest.raises(type(control)):
            await ask_once_more(control)


async def test_a_budget_on_the_second_ask_keeps_the_first_reply() -> None:
    from agent_runtime.tools.invocations import BudgetExceeded

    kept = await ask_once_more(BudgetExceeded("budget:tokens", "tokens: 1001 of 1000"))
    assert kept.result[0].content == "I've saved it."

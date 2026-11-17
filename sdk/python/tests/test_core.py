"""Reading a turn's events and building its result, tolerantly (CR-007 R19.4)."""

import json
from typing import Any

from nuria import _core
from nuria._sse import Event
from nuria.types import (
    AwaitingApproval,
    Cancelled,
    Completed,
    Failed,
    HelperEvent,
    Message,
    MessageEvent,
    StatusEvent,
    TokenEvent,
)

RUN = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


def sse(kind: str, payload: dict[str, Any], *, run: str = RUN, seq: int | None = None) -> Event:
    wire = {"run_id": run, "seq": seq, "after_seq": None, "ts": "2026-11-15T00:00:00+00:00",
            "epoch": 1, "type": kind, "payload": payload}  # fmt: skip
    return Event(event=kind, data=json.dumps(wire), id=None if seq is None else str(seq))


def message(
    seq: int, kind: str = "assistant", text: str | None = "hi", run: str | None = RUN
) -> dict[str, Any]:
    content: dict[str, Any] = {} if text is None else {"text": text}
    return {"seq": seq, "message_id": f"m{seq}", "run_id": run, "type": kind, "role": "x",
            "content": content, "created_at": "2026-11-15T00:00:00+00:00"}  # fmt: skip


def test_each_event_of_the_turn() -> None:
    assert _core.turn_event(sse("token", {"text": "4"}), RUN) == TokenEvent("4")
    payload = {"run_id": RUN, "status": "completed", "event": "run.completed", "reason": None}
    got = _core.turn_event(sse("turn.status", payload), RUN)
    assert got == StatusEvent("completed", None)
    spawned = _core.turn_event(sse("subagent.spawned", {"handle": "h", "agent": "a", "task": "t",
                                                        "worker": "w"}), RUN)  # fmt: skip
    assert spawned == HelperEvent(kind="spawned", handle="h", agent="a", task="t")
    stored = _core.turn_event(sse("message.created", message(3), seq=3), RUN)
    assert isinstance(stored, MessageEvent) and stored.message.seq == 3


def test_another_turns_events_are_not_this_turns() -> None:
    assert _core.turn_event(sse("token", {"text": "x"}, run=OTHER), RUN) is None
    other_message = message(4, run=OTHER)
    assert _core.turn_event(sse("message.created", other_message, seq=4), RUN) is None


def test_unknown_types_fields_and_garbage_are_ignored_never_raised() -> None:
    assert _core.turn_event(sse("something.new", {"x": 1}), RUN) is None
    assert _core.turn_event(sse("token", {"text": "x", "new_field": 1}), RUN) == TokenEvent("x")
    assert _core.turn_event(Event(event="token", data="not json", id=None), RUN) is None
    assert _core.turn_event(Event(event="token", data="[1, 2]", id=None), RUN) is None
    assert _core.turn_event(sse("token", {"text": 5}), RUN) is None
    assert _core.turn_event(sse("message.created", {"no": "seq"}, seq=1), RUN) is None


def test_the_stream_stops_on_an_end_and_on_waiting_for_approval_only() -> None:
    for status in ("completed", "failed", "cancelled", "waiting_approval"):
        assert _core.stops(StatusEvent(status, None))
    for status in ("queued", "running", "waiting_children", "something_new"):
        assert not _core.stops(StatusEvent(status, None))
    assert not _core.stops(TokenEvent("x"))


def test_the_results() -> None:
    rows = [message(1, "user", "q"), message(2, "assistant", "first"),
            message(3, "tool_call", None), message(4, "assistant", "42")]  # fmt: skip
    msgs = tuple(Message.of(r) for r in rows)
    completed = _core.result("s", {"id": RUN, "status": "completed"}, msgs)
    assert completed == Completed("s", RUN, "42", msgs)
    failed = _core.result("s", {"id": RUN, "status": "failed", "reason": "budget:cost"}, msgs)
    assert failed == Failed("s", RUN, "budget:cost", "42", msgs)
    cancelled = _core.result(
        "s", {"id": RUN, "status": "cancelled", "reason": "cancel_requested"}, ()
    )
    assert cancelled == Cancelled("s", RUN, "cancel_requested")
    payload = {"approval_id": "a1", "tool": "notify", "args": {"text": "[REDACTED]"}, "hidden": 1,
               "call_id": "c", "reason": "external side effect"}  # fmt: skip
    waiting = _core.result(
        "s", {"id": RUN, "status": "waiting_approval", "interrupt_payload": payload}, ()
    )
    assert isinstance(waiting, AwaitingApproval)
    assert (waiting.approval.approval_id, waiting.approval.tool, waiting.approval.hidden) == (
        "a1",
        "notify",
        1,
    )


def test_every_other_status_means_keep_waiting() -> None:
    for status in ("queued", "running", "waiting_children", "a_status_from_a_newer_nuria", None):
        assert _core.result("s", {"id": RUN, "status": status}, ()) is None


def test_a_malformed_pending_approval_still_reads() -> None:
    waiting = _core.result(
        "s", {"id": RUN, "status": "waiting_approval", "interrupt_payload": None}, ()
    )
    assert isinstance(waiting, AwaitingApproval)
    assert waiting.approval.args == {} and waiting.approval.hidden == 0


def test_messages_pages_keep_this_turns() -> None:
    page = {"messages": [message(1), message(2, run=OTHER), "junk"], "next_after_seq": 2}
    found, after = _core.of_run(page, RUN)
    assert [m.seq for m in found] == [1] and after == 2
    assert _core.of_run({"messages": [], "next_after_seq": None}, RUN) == ([], None)


def stored(text: str) -> MessageEvent:
    return MessageEvent(Message.of(message(9, "assistant", text)))


def test_text_is_the_tokens_as_they_come() -> None:
    whole = _core.TextStream()
    assert [whole.text(TokenEvent(t)) for t in ("The ", "answer")] == ["The ", "answer"]
    assert whole.text(stored("The answer")) is None  # nothing was missed


def test_text_lost_tokens_are_added_from_the_stored_message() -> None:
    whole = _core.TextStream()
    whole.text(TokenEvent("The "))  # then a reconnect: "answer is 42." never arrived
    assert whole.text(stored("The answer is 42.")) == "answer is 42."


def test_text_a_new_reply_starts_after_a_stored_message() -> None:
    whole = _core.TextStream()
    whole.text(TokenEvent("first"))
    whole.text(stored("first"))
    assert whole.text(TokenEvent("second")) == "second"
    assert whole.text(stored("second reply")) == " reply"


def test_text_a_reply_with_no_tokens_at_all_comes_whole() -> None:
    assert _core.TextStream().text(stored("all at once")) == "all at once"

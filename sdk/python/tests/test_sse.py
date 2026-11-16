"""The event-stream parser against the WHATWG standard's rules (HTML §9.2.6)."""

import pytest

from nuria._sse import Decoder, Event


def feed_all(*chunks: str) -> tuple[Decoder, list[Event]]:
    decoder = Decoder()
    out: list[Event] = []
    for chunk in chunks:
        out += decoder.feed(chunk)
    return decoder, out


def test_an_event_ends_at_a_blank_line_and_its_data_lines_join_with_newlines() -> None:
    _, events = feed_all("event: token\ndata: one\ndata: two\nid: 7\n\n")
    assert events == [Event(event="token", data="one\ntwo", id="7")]


def test_nothing_is_dispatched_before_the_blank_line() -> None:
    decoder, events = feed_all("data: half")
    assert events == []
    assert decoder.feed("\n\n") == [Event(event="message", data="half", id=None)]


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
def test_every_line_ending(ending: str) -> None:
    _, events = feed_all(f"data: x{ending}{ending}")
    assert [e.data for e in events] == ["x"]


def test_a_crlf_split_across_two_chunks_is_one_line_end() -> None:
    _, events = feed_all("data: a\r", "\n", "data: b\r\n\r\n")
    assert [e.data for e in events] == ["a\nb"]  # one event, not two


def test_chunks_of_any_size() -> None:
    stream = 'event: message.created\nid: 3\ndata: {"a": 1}\n\n: ping\n\ndata: t\n\n'
    _, whole = feed_all(stream)
    _, by_char = feed_all(*stream)
    assert whole == by_char
    assert [e.id for e in whole] == ["3", None]


def test_comments_are_counted_not_dispatched() -> None:
    decoder, events = feed_all(": stream open\n\n: ping\n\n")
    assert events == []
    assert decoder.comments == 2


def test_the_space_after_the_colon_is_optional_and_only_one_is_dropped() -> None:
    _, events = feed_all("data:no-space\n\ndata:  two-spaces\n\n")
    assert [e.data for e in events] == ["no-space", " two-spaces"]


def test_a_field_with_no_colon_has_an_empty_value() -> None:
    _, events = feed_all("data\n\n")
    assert [e.data for e in events] == [""]


def test_an_event_with_no_data_is_not_dispatched() -> None:
    decoder, events = feed_all("event: x\nid: 4\n\n")
    assert events == []
    assert decoder.last_event_id == "4"  # but its id still counts, as the standard says


def test_the_own_id_and_the_last_event_id_differ_for_an_event_without_one() -> None:
    decoder, events = feed_all("id: 5\ndata: persisted\n\ndata: transient\n\n")
    assert [e.id for e in events] == ["5", None]  # Nuria: transient events carry no id
    assert decoder.last_event_id == "5"  # what goes back as Last-Event-ID


def test_an_id_with_a_nul_is_ignored() -> None:
    decoder, events = feed_all("id: 1\0\ndata: x\n\n")
    assert events[0].id is None
    assert decoder.last_event_id == ""


def test_retry_takes_digits_only() -> None:
    decoder, _ = feed_all("retry: 2000\n\n")
    assert decoder.retry_ms == 2000
    decoder.feed("retry: soon\n\n")
    assert decoder.retry_ms == 2000


def test_unknown_fields_are_ignored() -> None:
    _, events = feed_all("whatever: 1\ndata: x\n\n")
    assert events == [Event(event="message", data="x", id=None)]

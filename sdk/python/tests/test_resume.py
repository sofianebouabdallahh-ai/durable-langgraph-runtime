"""R19.5's rules, one test each (CR-007), on the state machine alone."""

import pytest

from nuria._resume import Fatal, Proceed, Resumption, Retry, Verdict, reconnect_after_seq
from nuria._sse import Event


def persisted(seq: int) -> Event:
    return Event(event="message.created", data="{}", id=str(seq))


def transient() -> Event:
    return Event(event="token", data='{"payload": {"text": "x"}}', id=None)


def machine(cursor: int | None = None) -> Resumption:
    return Resumption(cursor, jitter=lambda: 1.0)  # no randomness: the full backoff


def test_the_cursor_moves_only_on_events_with_an_id() -> None:
    m = machine()
    assert m.accept(persisted(3)) is Verdict.NEW
    assert m.accept(transient()) is Verdict.NEW
    assert m.cursor == 3
    assert m.headers() == {"Last-Event-ID": "3"}


def test_no_cursor_no_header() -> None:
    assert machine().headers() == {}
    assert machine(0).headers() == {"Last-Event-ID": "0"}


def test_a_replayed_event_at_or_below_the_cursor_is_dropped() -> None:
    m = machine(5)
    assert m.accept(persisted(4)) is Verdict.DUPLICATE
    assert m.accept(persisted(5)) is Verdict.DUPLICATE
    assert m.accept(persisted(6)) is Verdict.NEW
    assert m.cursor == 6


def test_reconnect_means_now_and_resumes_from_the_cursor_not_the_servers_number() -> None:
    m = machine(9)
    drain = Event(event="reconnect", data='{"after_seq": 12}', id=None)
    assert m.accept(drain) is Verdict.RECONNECT
    assert m.drains == 1
    assert m.cursor == 9  # what this client saw: resuming from it can only replay
    assert reconnect_after_seq(drain) == 12


@pytest.mark.parametrize("status", [401, 403, 404])
def test_401_403_404_are_fatal(status: int) -> None:
    assert machine().opened(status, "application/problem+json", None) == Fatal(status)


def test_another_4xx_is_fatal_too_but_429_and_408_are_retried() -> None:
    assert machine().opened(400, None, None) == Fatal(400)
    assert isinstance(machine().opened(429, None, None), Retry)
    assert isinstance(machine().opened(408, None, None), Retry)


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_5xx_is_retried(status: int) -> None:
    assert isinstance(machine().opened(status, None, None), Retry)


def test_retry_after_wins_over_the_backoff_capped_at_a_minute() -> None:
    assert machine().opened(503, None, 1.0) == Retry(1.0)
    assert machine().opened(503, None, 600.0) == Retry(60.0)


def test_an_event_stream_proceeds_and_anything_else_is_retried() -> None:
    assert machine().opened(200, "text/event-stream; charset=utf-8", None) == Proceed()
    assert isinstance(machine().opened(200, "text/html", None), Retry)  # a proxy's page


def test_backoff_doubles_from_one_second_to_five_with_five_attempts() -> None:
    m = machine()
    delays = [m.dropped() for _ in range(5)]
    assert delays == [Retry(1.0), Retry(2.0), Retry(4.0), Retry(5.0), Retry(5.0)]
    assert m.dropped() == Fatal(None)  # the sixth: give up


def test_the_backoff_has_jitter() -> None:
    low = Resumption(jitter=lambda: 0.0).dropped()
    assert low == Retry(0.5)  # half the delay at the low end


def test_progress_earns_a_fresh_set_of_attempts() -> None:
    m = machine()
    for _ in range(5):
        m.dropped()
    m.accept(transient())  # something arrived: the server is back
    assert m.dropped() == Retry(1.0)


def test_reconnects_are_counted() -> None:
    m = machine()
    m.reconnecting()
    m.reconnecting()
    assert m.reconnects == 2

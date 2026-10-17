"""StreamMerger: unit cases plus property-based tests (SC6)."""

import uuid
from datetime import UTC, datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from agent_runtime.streaming.bus import StreamEvent
from agent_runtime.streaming.merger import StreamMerger

RUN = uuid.uuid4()


def ev(seq: int, total: int | None = None) -> StreamEvent:
    terminal = total is not None and seq == total
    return StreamEvent(
        run_id=RUN, seq=seq, ts=datetime.now(UTC), epoch=1,
        type="run.completed" if terminal else "node.completed", payload={},
    )  # fmt: skip


def token(after_seq: int) -> StreamEvent:
    return StreamEvent(
        run_id=RUN, seq=None, after_seq=after_seq, ts=datetime.now(UTC), epoch=1,
        type="token", payload={"delta": "x"},
    )  # fmt: skip


def seqs(events: list[StreamEvent]) -> list[int | None]:
    return [e.seq for e in events]


def test_in_order_live_events_flow_through() -> None:
    m = StreamMerger()
    assert seqs(m.accept([ev(1), ev(2)])) == [1, 2]
    assert m.last == 2 and m.gap is None


def test_duplicates_are_dropped() -> None:
    m = StreamMerger()
    m.accept([ev(1), ev(2)])
    assert m.accept([ev(2), ev(1)]) == []


def test_a_hole_is_reported_and_filled_by_backfill() -> None:
    m = StreamMerger()
    m.accept([ev(1)])
    assert m.accept([ev(4)]) == []  # 2 and 3 missing: hold 4
    assert m.gap == (1, 3)  # back-fill seq > 1 through 3
    assert seqs(m.accept([ev(2), ev(3)])) == [2, 3, 4]
    assert m.gap is None


def test_resume_from_last_event_id() -> None:
    m = StreamMerger(after_seq=5)
    assert m.accept([ev(3), ev(5)]) == []
    assert seqs(m.accept([ev(6)])) == [6]


def test_stops_after_the_terminal_event() -> None:
    m = StreamMerger()
    assert seqs(m.accept([ev(1), ev(2, total=2)])) == [1, 2]
    assert m.done and m.accept([ev(3)]) == []


def test_transient_events_only_after_what_the_client_saw() -> None:
    m = StreamMerger()
    m.accept([ev(1), ev(2)])
    assert m.accept_transient(token(after_seq=2)) is not None
    assert m.accept_transient(token(after_seq=3)) is None  # client hasn't seen seq 3 yet


def test_overflow_signal() -> None:
    m = StreamMerger(max_buffer=3)
    m.accept([ev(i) for i in range(10, 15)])
    assert m.overflowing


@settings(max_examples=600, deadline=None)
@given(data=st.data())
def test_property_any_interleaving_yields_each_event_exactly_once_in_order(
    data: st.DataObject,
) -> None:
    """SC6. Model of the stream endpoint: a client resumes after `start`; the replay
    snapshot was taken at some point (prefix up to `snapshot`); the live feed then
    delivers a random subset of events, duplicated and reordered; whenever the merger
    reports a gap, the shell back-fills it from 'Postgres'; at the end the safety-net
    poll catches whatever live lost. Output must be start+1 … N, exactly once."""
    n = data.draw(st.integers(1, 60), label="events in the run")
    db = {s: ev(s, total=n) for s in range(1, n + 1)}
    start = data.draw(st.integers(0, n), label="client resumes after")
    snapshot = data.draw(st.integers(start, n), label="replay sees up to")
    live = data.draw(
        st.lists(st.integers(1, n), max_size=3 * n).map(lambda xs: [db[x] for x in xs]),
        label="live feed (drops, duplicates, any order)",
    )

    m = StreamMerger(after_seq=start)
    out = m.accept(db[s] for s in range(start + 1, snapshot + 1))  # replay
    for event in live:
        out += m.accept([event])
        if (gap := m.gap) is not None:  # back-fill exactly the hole
            out += m.accept(db[s] for s in range(gap[0] + 1, gap[1] + 1))
        assert seqs(out) == list(range(start + 1, start + 1 + len(out)))  # invariant
    out += m.accept(db[s] for s in range(m.last + 1, n + 1))  # safety-net poll

    assert seqs(out) == list(range(start + 1, n + 1))
    assert m.done or start == n

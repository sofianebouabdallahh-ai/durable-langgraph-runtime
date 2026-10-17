"""StreamMerger: exactly-once, in-order delivery on top of an unreliable feed (R2.5).

Pattern: functional core, imperative shell. This class does no I/O. The
stream endpoint (the shell) feeds it events from three sources (Postgres
replay, live Pub/Sub, Postgres back-fill) in whatever order they arrive,
possibly duplicated, possibly with holes, and the merger:

- emits persisted events strictly as seq last+1, last+2, … (never a gap,
  never a duplicate, never out of order);
- buffers events that arrive ahead of a hole, and reports the hole (`gap`)
  so the shell can back-fill exactly that range from Postgres;
- stops after the terminal event (`done`);
- lets transient events (tokens) through only when they follow what the
  client has already seen.

Because it is pure, it is tested with generated cases (hypothesis): any
interleaving of replay, live, duplicates and drops must yield 1…N exactly once.
"""

from __future__ import annotations

from collections.abc import Iterable

from agent_runtime.streaming.bus import StreamEvent


class StreamMerger:
    def __init__(self, after_seq: int = 0, *, max_buffer: int = 1000) -> None:
        self.last = after_seq  # highest seq emitted (or the client's Last-Event-ID)
        self.done = False
        self._buffer: dict[int, StreamEvent] = {}
        self._max_buffer = max_buffer

    def accept(self, events: Iterable[StreamEvent]) -> list[StreamEvent]:
        """Take persisted events from any source; return those now deliverable, in order."""
        for event in events:
            if self.done or event.seq is None or event.seq <= self.last:
                continue  # transient, finished, or already delivered (duplicate)
            self._buffer.setdefault(event.seq, event)
        out: list[StreamEvent] = []
        while not self.done and (self.last + 1) in self._buffer:
            event = self._buffer.pop(self.last + 1)
            out.append(event)
            self.last += 1
            if event.terminal:
                self.done = True
                self._buffer.clear()
        return out

    def accept_transient(self, event: StreamEvent) -> StreamEvent | None:
        """A token etc. is shown only if it follows what the client has seen."""
        if self.done or event.after_seq is None or event.after_seq > self.last:
            return None
        return event

    @property
    def gap(self) -> tuple[int, int] | None:
        """(after_seq, through_seq) to back-fill from Postgres, if events are waiting on a hole."""
        if not self._buffer:
            return None
        return self.last, min(self._buffer) - 1

    @property
    def overflowing(self) -> bool:
        """Too much buffered ahead of a hole: catch up from Postgres instead."""
        return len(self._buffer) > self._max_buffer

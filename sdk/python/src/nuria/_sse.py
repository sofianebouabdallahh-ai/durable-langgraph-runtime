"""The event-stream parser of the WHATWG HTML standard (§9.2.6), without I/O.

Feed it text as it arrives, in chunks of any size; it returns the events those chunks
completed. Pattern: sans-IO: the same parser serves the async and the sync client, and
its tests need no network.

The two ids are kept apart, because Nuria's stream needs both:
- `Event.id` is the event's own `id:` line, or None. Nuria sends one on persisted events
  only (their `seq`), so None means a transient event (a token, a turn status);
- `Decoder.last_event_id` is the standard's "last event ID buffer", kept across events:
  what to send back as `Last-Event-ID`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_LINE = re.compile(r"\r\n|\r|\n")


@dataclass(frozen=True, slots=True)
class Event:
    event: str  # "message" when the stream gave no `event:` line
    data: str
    id: str | None


class Decoder:
    def __init__(self) -> None:
        self._buffer = ""
        self._after_cr = False
        self._data: list[str] = []
        self._event = ""
        self._id: str | None = None
        self.last_event_id = ""
        self.retry_ms: int | None = None  # the stream's latest `retry:`
        self.comments = 0  # `: ping` keep-alives, among others

    def feed(self, text: str) -> list[Event]:
        if not text:
            return []
        if self._after_cr and text.startswith("\n"):
            text = text[1:]  # the LF of a CRLF the last chunk ended in the middle of
        self._after_cr = False
        self._buffer += text
        out: list[Event] = []
        while (end := _LINE.search(self._buffer)) is not None:
            line, self._buffer = self._buffer[: end.start()], self._buffer[end.end() :]
            # A CR at the very end ends its line now (an event isn't held back waiting), and
            # a LF opening the next chunk is then its second half, not a blank line.
            self._after_cr = end.group() == "\r" and self._buffer == ""
            event = self._line(line)
            if event is not None:
                out.append(event)
        return out

    def _line(self, line: str) -> Event | None:
        if line == "":
            return self._dispatch()
        if line.startswith(":"):
            self.comments += 1
            return None
        field, colon, value = line.partition(":")
        if colon and value.startswith(" "):
            value = value[1:]
        if field == "data":
            self._data.append(value)
        elif field == "event":
            self._event = value
        elif field == "id":
            if "\0" not in value:  # the standard ignores an id with a NUL
                self._id = value
                self.last_event_id = value
        elif field == "retry" and value.isascii() and value.isdigit():
            self.retry_ms = int(value)
        return None

    def _dispatch(self) -> Event | None:
        data, event, own_id = self._data, self._event, self._id
        self._data, self._event, self._id = [], "", None
        if not data:
            return None  # no data: nothing to dispatch (a `retry:` alone, say)
        return Event(event=event or "message", data="\n".join(data), id=own_id)

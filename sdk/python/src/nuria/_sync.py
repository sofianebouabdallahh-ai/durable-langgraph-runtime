"""The sync client: written from `_async.py` by `scripts/unasync.py`. Don't edit it.

Pattern: Facade over the generated client and the sans-IO cores (`_sse`, `_resume`,
`_retry`, `_core`), which decide; this module only does the I/O.

The generated code builds each request (its method, path, typed parameters and body), and
the Facade reads the answer itself: the generated parsers raise on a status value or a
missing field they don't know, so a newer Nuria would break an older client (R19.4).
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from types import ModuleType
from typing import Any
from uuid import UUID

import httpx

from nuria import _core, _sse, errors
from nuria._generated.api.runs import cancel_run, get_run
from nuria._generated.api.sessions import (
    create_session,
    get_session,
    list_messages,
    list_sessions,
    send_message,
)
from nuria._generated.models import CreateSessionRequest, SendMessageRequest
from nuria._resume import Fatal, Resumption, Retry, Verdict
from nuria._retry import RetryPolicy
from nuria.types import (
    ENDED,
    STOPS,
    Message,
    MessageEvent,
    SessionInfo,
    StatusEvent,
    TurnEvent,
    TurnResult,
)

QUIET_S = 30.0  # a stream this long without a turn event: ask the run whether it ended
_sleep = time.sleep  # one name, so tests can make the waits instant
_STREAM_TIMEOUT = httpx.Timeout(_core.DEFAULT_TIMEOUT_S, read=_core.STREAM_READ_TIMEOUT_S)


class Nuria:
    """`with Nuria("http://localhost:3000/api") as nuria: ...`"""

    def __init__(
        self,
        base_url: str = "http://localhost:3000/api",
        *,
        headers: dict[str, str] | None = None,
        timeout_s: float = _core.DEFAULT_TIMEOUT_S,
        retry: RetryPolicy | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        base = base_url.rstrip("/")
        self._http = httpx.Client(
            base_url=base, headers=headers, timeout=timeout_s, transport=transport
        )
        self._retry = retry or RetryPolicy()
        self.sessions = Sessions(self)

    def __enter__(self) -> Nuria:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def turn(self, session_id: str, run_id: str, *, after_seq: int | None = None) -> Turn:
        """A turn's handle, from its ids: in another process, hours later."""
        return Turn(self, str(session_id), str(run_id), after_seq)

    def _call(self, endpoint: ModuleType, *, safe: bool, **kwargs: Any) -> Any:
        """One generated endpoint's request, with the retry policy; the JSON body, or the
        error raised."""
        request = endpoint._get_kwargs(**kwargs)
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._http.request(**request)
            except httpx.TransportError as exc:
                delay = self._retry.delay(attempt, safe=safe)
                if delay is None:
                    raise errors.ConnectionFailed(f"{type(exc).__name__}: {exc}") from exc
                _sleep(delay)
                continue
            body = _json(response.content)
            if response.status_code < 400:
                return body
            headers = {k.lower(): v for k, v in response.headers.items()}
            error = errors.from_response(response.status_code, body, headers)
            delay = self._retry.delay(
                attempt, safe=safe, status=response.status_code,
                problem_kind=error.kind, retry_after_s=error.retry_after_s,
            )  # fmt: skip
            if delay is None:
                raise error
            _sleep(delay)


class Sessions:
    def __init__(self, nuria: Nuria) -> None:
        self._nuria = nuria

    def create(self, agent: str = "chat", *, title: str | None = None) -> Session:
        body = CreateSessionRequest(agent=agent, title=title)
        data = self._nuria._call(create_session, safe=False, body=body)
        return Session(self._nuria, SessionInfo.of(data))

    def get(self, session_id: str) -> Session:
        data = self._nuria._call(get_session, safe=True, session_id=UUID(str(session_id)))
        return Session(self._nuria, SessionInfo.of(data))

    def list(self, *, limit: int = 50) -> list[Session]:
        data = self._nuria._call(list_sessions, safe=True, limit=limit)
        return [Session(self._nuria, SessionInfo.of(s)) for s in data if isinstance(s, dict)]


class Session:
    def __init__(self, nuria: Nuria, info: SessionInfo) -> None:
        self._nuria = nuria
        self.info = info

    @property
    def id(self) -> str:
        return self.info.id

    def send(
        self,
        content: str,
        *,
        options: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        script: list[dict[str, Any]] | None = None,
    ) -> Turn:
        """Start a turn. One `Idempotency-Key` (yours, or a new one) goes with every retry of
        this send, so a retried send never makes a second turn (R19.6). `script` is for
        Nuria's scripted test model only."""
        key = idempotency_key or str(uuid.uuid4())
        fields: dict[str, Any] = {"content": content}
        if options is not None:
            fields["options"] = options
        if script is not None:
            fields["script"] = script
        data = self._nuria._call(
            send_message, safe=True, session_id=UUID(self.id),
            body=SendMessageRequest.from_dict(fields), idempotency_key=key,
        )  # fmt: skip
        # Start just before the user's message: the turn's events, not the whole session's.
        return Turn(self._nuria, self.id, str(data["run_id"]), int(data["seq"]) - 1)

    def turn(self, run_id: str) -> Turn:
        return Turn(self._nuria, self.id, str(run_id), None)


class Turn:
    """A turn's handle: `events()`, `text()`, `wait()`, `cancel()`. Rebuild it anywhere with
    `nuria.turn(session_id, run_id)`."""

    def __init__(self, nuria: Nuria, session_id: str, run_id: str, after_seq: int | None) -> None:
        self._nuria = nuria
        self.session_id, self.run_id, self.after_seq = session_id, run_id, after_seq
        self._machine: Resumption | None = None  # the last `events()`'s

    @property
    def reconnects(self) -> int:
        """Of the last `events()`: connections after the first."""
        return self._machine.reconnects if self._machine else 0

    @property
    def drains(self) -> int:
        """Of the last `events()`: times a draining replica asked it to reconnect."""
        return self._machine.drains if self._machine else 0

    def __repr__(self) -> str:
        return f"Turn(session_id={self.session_id!r}, run_id={self.run_id!r})"

    def status(self) -> str:
        return str((self._run()).get("status"))

    def wait(self, *, timeout_s: float | None = None) -> TurnResult:
        """The turn's result: `Completed`, `Failed`, `Cancelled`, or `AwaitingApproval`.
        Waits through every other status, for as long as it takes (or `timeout_s`, then
        `TimeoutError`)."""
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        delay = _core.WAIT_FIRST_S
        while True:
            run = self._run()
            if run.get("status") in STOPS:
                messages = self.messages() if run.get("status") in ENDED else ()
                found = _core.result(self.session_id, run, messages)
                if found is not None:
                    return found
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(f"turn {self.run_id} is still {run.get('status')}")
            pause = delay if deadline is None else min(delay, max(0.0, deadline - time.monotonic()))
            _sleep(pause)
            delay = min(delay * _core.WAIT_FACTOR, _core.WAIT_CAP_S)

    def messages(self) -> tuple[Message, ...]:
        """The turn's stored messages, in order."""
        out: list[Message] = []
        after: int | None = self.after_seq or 0
        while after is not None:
            page = self._nuria._call(list_messages, safe=True,
                                           session_id=UUID(self.session_id), after_seq=after,
                                           limit=_core.PAGE)  # fmt: skip
            found, after = _core.of_run(page, self.run_id)
            out += found
        return tuple(out)

    def cancel(self) -> None:
        """Ask the turn to stop (this run, never another turn of the session)."""
        self._nuria._call(cancel_run, safe=False, run_id=UUID(self.run_id))

    def text(self) -> Iterator[str]:
        """The reply's text as it's written; whole even if a token was lost on a reconnect
        (what the tokens missed is added when the stored message arrives)."""
        whole = _core.TextStream()
        for event in self.events():
            piece = whole.text(event)
            if piece:
                yield piece

    def events(self) -> Iterator[TurnEvent]:
        """The turn's events, until it ends or waits for an approval. Resumes through drains
        and dropped connections; a stored message is never seen twice (R19.5)."""
        machine = self._machine = Resumption(self.after_seq)
        while True:
            run = self._run()  # before every connection: has it stopped meanwhile?
            if run.get("status") in STOPS:
                for event in self._catch_up(machine, run):
                    yield event
                return
            next_try: Retry | Fatal = Retry(0.0)  # a clean close: ask the run, connect again
            try:
                with self._nuria._http.stream(
                    "GET", f"/sessions/{self.session_id}/stream",
                    headers=machine.headers(), timeout=_STREAM_TIMEOUT,
                ) as response:  # fmt: skip
                    headers = {k.lower(): v for k, v in response.headers.items()}
                    opened = machine.opened(response.status_code, headers.get("content-type"),
                                            errors.retry_after(headers))  # fmt: skip
                    if isinstance(opened, Fatal):
                        body = _json(response.read())
                        raise errors.from_response(response.status_code, body, headers)
                    if isinstance(opened, Retry):
                        next_try = opened
                    else:
                        decoder = _sse.Decoder()
                        quiet_since = time.monotonic()
                        reconnect = False
                        for chunk in response.iter_text():
                            for raw in decoder.feed(chunk):
                                verdict = machine.accept(raw)
                                if verdict is Verdict.RECONNECT:
                                    reconnect = True  # draining: another replica, now
                                    break
                                found = (
                                    _core.turn_event(raw, self.run_id)
                                    if verdict is Verdict.NEW else None
                                )  # fmt: skip
                                if found is None:
                                    continue
                                quiet_since = time.monotonic()
                                yield found
                                if _core.stops(found):
                                    return
                            if reconnect:
                                break
                            if time.monotonic() - quiet_since > QUIET_S:
                                # Only keep-alives for a while. The turn's status is
                                # transient: one sent before we connected would leave us
                                # here forever. Reconnecting asks the run first.
                                quiet_since = time.monotonic()
                                if (self._run()).get("status") in STOPS:
                                    break
            except httpx.TransportError:
                next_try = machine.dropped()
            if isinstance(next_try, Fatal):
                raise errors.ConnectionFailed(
                    f"the stream of turn {self.run_id} kept failing; gave up after its retries"
                )
            if next_try.after_s:
                _sleep(next_try.after_s)
            machine.reconnecting()

    def _catch_up(self, machine: Resumption, run: dict[str, Any]) -> Iterator[TurnEvent]:
        """The turn stopped while we weren't connected: the stored messages we haven't seen,
        then its status, from the run (the stream's own was transient)."""
        for message in self.messages():
            if machine.cursor is None or message.seq > machine.cursor:
                machine.cursor = message.seq
                yield MessageEvent(message)
        reason = run.get("reason")
        yield StatusEvent(str(run.get("status")), reason if isinstance(reason, str) else None)

    def _run(self) -> dict[str, Any]:
        data = self._nuria._call(get_run, safe=True, run_id=UUID(self.run_id))
        return data if isinstance(data, dict) else {}


def _json(content: bytes) -> Any:
    if not content:
        return None
    try:
        return json.loads(content)
    except ValueError:
        return None

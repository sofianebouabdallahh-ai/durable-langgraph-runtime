"""Live tokens (CR-001 R12.3, R12.5, R12.7): model output as it is generated.

`TokenRelay` is a LangChain callback handler on the main graph. LangChain passes
it every streamed token (`on_llm_new_token`) of every model call inside the
graph. It:

- **coalesces** tokens into batches of at least `flush_ms` and publishes them as
  *transient* `token` events (pub/sub only, never persisted, no `seq`) on the
  session's channel (chat turns) or the run's;
- **tracks the unfinished reply**, so a turn cancelled mid-reply can persist the
  partial text as an `assistant` message with `interrupted: true` (R12.7). The
  complete reply is persisted once, by the transcript, with its checkpoint;
- **honours a cancel mid-reply**: about twice a second while streaming it checks
  the run's cancel flag and, if set, stops the call (`CancelRequested`). Otherwise
  a cancel would only be noticed after the whole reply.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler

from agent_runtime.streaming.bus import EventBus, StreamEvent

log = logging.getLogger(__name__)

CANCEL_CHECK_S = 0.5


class TokenRelay(AsyncCallbackHandler):
    raise_error = True  # so a CancelRequested raised here stops the model call

    def __init__(
        self,
        bus: EventBus | None,
        channel: str,
        run_id: uuid.UUID,
        *,
        flush_ms: int,
        cancel_check: Callable[[], Awaitable[None]],
    ) -> None:
        self._bus = bus
        self._channel = channel
        self._run_id = run_id
        self._flush_s = flush_ms / 1000
        self._cancel_check = cancel_check
        self._buffer: list[str] = []
        self._last_flush = 0.0
        self._last_cancel_check = 0.0
        self.partial = ""  # the reply being generated; "" when none is in progress
        self.published = 0  # batches sent (observability and tests)

    async def on_llm_new_token(
        self,
        token: str | list[str | dict[str, Any]],
        *,
        chunk: Any = None,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        text = (
            token
            if isinstance(token, str)
            else "".join(b if isinstance(b, str) else str(b.get("text", "")) for b in token)
        )  # content blocks (some providers) or a plain string
        if not text:
            return
        self._buffer.append(text)
        self.partial += text
        now = time.monotonic()
        if now - self._last_flush >= self._flush_s:
            await self._flush(now)
        if now - self._last_cancel_check >= CANCEL_CHECK_S:
            self._last_cancel_check = now
            await self._cancel_check()  # raises CancelRequested: the call stops here

    async def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        await self._flush(time.monotonic())
        self.partial = ""  # complete: the transcript persists it with the checkpoint

    async def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        await self._flush(time.monotonic())  # keep `partial`: the reply didn't finish

    async def _flush(self, now: float) -> None:
        if not self._buffer:
            return
        text, self._buffer = "".join(self._buffer), []
        self._last_flush = now
        if self._bus is None:
            return
        event = StreamEvent(
            run_id=self._run_id, seq=None, ts=_now(), epoch=0, type="token",
            payload={"text": text}, after_seq=0,  # 0: shown to every client, never held
        )  # fmt: skip
        try:
            await self._bus.publish(self._channel, event)
            self.published += 1
        except Exception:
            log.warning("token publish failed (transient: dropped)", exc_info=True)


def _now() -> Any:
    from datetime import UTC, datetime

    return datetime.now(UTC)

"""A minimal SSE client for tests: reads a stream until the server closes it.

It is also the streams' contract test (CR-007 R19.1, AC49): every event any test reads is
parsed with the published models (`api/stream_schemas.py`), and a field the server sends
that the models don't declare fails the test that read it.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel

from agent_runtime.api import stream_schemas as contract


@dataclass
class Sse:
    events: list[dict[str, Any]] = field(default_factory=list)  # each: fields + "_received_at"
    comments: list[str] = field(default_factory=list)
    headers: httpx.Headers | None = None

    @property
    def seqs(self) -> list[int]:
        return [int(e["id"]) for e in self.events if e.get("id")]


def undeclared(raw: Any, model: BaseModel, where: str = "") -> list[str]:
    """The fields of `raw` its model doesn't declare (models ignore unknown fields, so a
    newer server doesn't break an older client; the server itself must not send them)."""
    if not isinstance(raw, dict):
        return []
    fields = type(model).model_fields
    out = [f"{where}{key}" for key in raw if key not in fields]
    for key, value in raw.items():
        sub = getattr(model, key, None) if key in fields else None
        if isinstance(sub, BaseModel):
            out += undeclared(value, sub, f"{where}{key}.")
    return out


def check_event(path: str, block: dict[str, Any]) -> None:
    """One SSE event against the published stream schemas (AC49)."""
    if "data" not in block:
        return  # `retry:` with a comment: the stream opening
    raw = json.loads(block["data"])
    name = block.get("event")
    model: BaseModel
    if name == contract.RECONNECT_EVENT:
        model = contract.RECONNECT.validate_python(raw)
    else:
        adapter = contract.SESSION_STREAM if path.startswith("/sessions/") else contract.RUN_STREAM
        model = adapter.validate_python(raw)
        assert name == raw["type"], f"SSE event name {name!r} != its type {raw['type']!r}"
        sent_id = block.get("id")
        assert (sent_id is None) == (raw["seq"] is None), f"id {sent_id!r} vs seq {raw['seq']}"
        assert sent_id is None or int(sent_id) == raw["seq"], f"id {sent_id} != seq {raw['seq']}"
    extra = undeclared(raw, model)
    assert not extra, f"{path}: {name} sends fields the spec doesn't declare: {extra}"


async def read_sse(
    client: httpx.AsyncClient,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    stop_after: int | None = None,
    timeout_s: float = 30,
) -> Sse:
    """Read until the server closes the stream (or `stop_after` persisted events).
    Each event records `_received_at` (wall clock) for latency measurements."""
    out = Sse()
    block: dict[str, Any] = {}
    async with asyncio.timeout(timeout_s), client.stream("GET", path, headers=headers) as resp:
        out.headers = resp.headers
        async for line in resp.aiter_lines():
            if line == "":
                if block:
                    check_event(path.split("?")[0], block)
                    block["_received_at"] = time.time()
                    out.events.append(block)
                    block = {}
                    if stop_after is not None and len(out.seqs) >= stop_after:
                        return out
                continue
            if line.startswith(":"):
                out.comments.append(line[1:].strip())
                continue
            key, _, value = line.partition(":")
            block[key] = value.lstrip()
    return out

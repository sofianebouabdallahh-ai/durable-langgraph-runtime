"""A minimal SSE client for tests: reads a stream until the server closes it."""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class Sse:
    events: list[dict[str, Any]] = field(default_factory=list)  # each: fields + "_received_at"
    comments: list[str] = field(default_factory=list)
    headers: httpx.Headers | None = None

    @property
    def seqs(self) -> list[int]:
        return [int(e["id"]) for e in self.events if e.get("id")]


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

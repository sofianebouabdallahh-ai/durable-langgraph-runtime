"""Phase L7a: one id finds everything (SC1), and no secret reaches a log line (SC6).

A chat turn through the API, with a helper and two tools, traced as in production
(FastAPI instrumented, the run continuing the request's trace); every line captured as
the containers write them (JSON).
"""

from __future__ import annotations

import io
import json
import logging
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent_runtime import logs, telemetry
from agent_runtime.api.app import create_app
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.queue import InMemoryWorkQueue
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.streaming.bus import InMemoryEventBus

pytestmark = pytest.mark.integration

SECRET = "sk-" + "Q" * 40  # an OpenAI-style key: what a person might paste by mistake


class Lines:
    """Every log line written while it's installed, parsed."""

    def __init__(self) -> None:
        self._out = io.StringIO()
        self.handler = logging.StreamHandler(self._out)
        self.handler.setFormatter(logs.JsonFormatter("test"))

    @property
    def raw(self) -> str:
        return self._out.getvalue()

    def all(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.raw.splitlines()]


@pytest.fixture
def lines() -> Iterator[Lines]:
    captured = Lines()
    root = logging.getLogger()
    previous = root.level
    root.addHandler(captured.handler)
    root.setLevel(logging.INFO)
    try:
        yield captured
    finally:
        root.removeHandler(captured.handler)
        root.setLevel(previous)


@pytest.fixture
def provider() -> Iterator[TracerProvider]:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))
    telemetry.use_provider(provider)
    try:
        yield provider
    finally:
        telemetry.use_provider(None)
        provider.shutdown()


@pytest.fixture
async def client(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, provider: TracerProvider
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(test_settings, pool=pool, queue=InMemoryWorkQueue(), bus=InMemoryEventBus())
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        c.app = app  # type: ignore[attr-defined]
        yield c


def call(name: str, **args: Any) -> dict[str, Any]:
    return {"name": name, "args": args}


async def test_one_id_finds_every_line_of_a_turn(
    client: httpx.AsyncClient, pool: Pool, test_settings: Settings, lines: Lines
) -> None:
    sid = (await client.post("/sessions", json={"agent": "delegator"})).json()["id"]
    script = [
        {"content": "", "tool_calls": [call("spawn_subagent", agent="mathematician",
                                            task=f"6*7, my key is {SECRET}")]},
        {"content": "", "tool_calls": [call("wait_subagents",
                                            handles=["${spawn_subagent[0].handle}"])]},
        {"content": "6*7 = 42.", "tool_calls": []},
    ]  # fmt: skip
    subs = {"mathematician": [
        {"content": "", "tool_calls": [call("calculator", expression="6*7")]},
        {"content": "", "tool_calls": [call("return_result", summary="42")]},
    ]}  # fmt: skip
    sent = await client.post(
        f"/sessions/{sid}/messages",
        json={"content": f"use {SECRET}", "script": script, "subagent_scripts": subs},
        headers={"X-Request-ID": "req-from-the-ui-1"},
    )
    assert sent.status_code == 202, sent.text
    assert sent.headers["x-request-id"] == "req-from-the-ui-1"
    run_id = str(sent.json()["run_id"])
    graphs = client.app.state.graphs  # type: ignore[attr-defined]
    done = await RunExecutor(pool, test_settings, graphs, owner="w:1").execute(uuid.UUID(run_id))
    assert str(done.status) == "completed"
    trace_id = telemetry.trace_id_of(done.traceparent)
    assert trace_id

    every = lines.all()
    # The API: the request's line names the route (not the ids), the session and the trace.
    (post,) = [ln for ln in every if ln.get("route") == "/sessions/{session_id}/messages"]
    assert (post["status"], post["method"], post["request_id"]) == (
        202,
        "POST",
        "req-from-the-ui-1",
    )
    assert (post["session_id"], post["trace_id"]) == (sid, trace_id)
    assert sid not in post["msg"]

    # The worker, the helper and the tools: every line of the turn carries all three ids.
    turn = [ln for ln in every if ln.get("run_id") == run_id]
    assert turn, "no line names the run"
    for ln in turn:
        assert (ln["session_id"], ln["trace_id"]) == (sid, trace_id), ln
        assert ln["agent"] == "delegator" and ln["worker"] == "w:1"
    msgs = [ln["msg"] for ln in turn]
    assert any(m.endswith("executing delegator") for m in msgs)
    assert any(m.endswith(": completed") for m in msgs)
    tools = {ln["tool"]: ln for ln in turn if ln["msg"].startswith("tool call:")}
    assert {"spawn_subagent", "wait_subagents", "calculator"} <= set(tools)
    assert tools["calculator"]["helper"] == "mathematician"  # inside the helper
    assert "helper" not in tools["spawn_subagent"]
    helper = [ln for ln in turn if ln.get("helper") == "mathematician"]
    assert any(ln["msg"] == "helper mathematician started" for ln in helper)
    assert all(ln.get("tool") != "spawn_subagent" for ln in helper)  # not the spawner's call
    models = [ln for ln in turn if ln["msg"].startswith("model call:")]
    assert len(models) == 5 and all(ln["tokens_in"] >= 0 and "span_id" in ln for ln in models)
    ended = next(ln for ln in turn if ln["msg"].endswith(": completed"))
    assert ended["tokens"] == done.tokens and ended["steps"] == done.steps

    # SC6: the key was in the message and in a tool's arguments; no line has it.
    assert SECRET not in lines.raw


async def test_no_secret_reaches_a_line(lines: Lines) -> None:
    """SC6, the formatter: in the message, in an event's fields, in an exception."""
    log = logging.getLogger("agent_runtime.test")
    with logs.bind(run_id="r-1", note=f"bound {SECRET}"):
        log.warning("connecting with %s", SECRET)
        logs.event(log, "a call", detail=f"Bearer {'t' * 30}", nested={"key": SECRET})
        try:
            raise RuntimeError(f"auth failed for postgresql://agent:hunter2@db/x with {SECRET}")
        except RuntimeError:
            log.exception("it failed")
    assert SECRET not in lines.raw and "hunter2" not in lines.raw and "t" * 30 not in lines.raw
    assert lines.raw.count("[REDACTED]") >= 5
    assert all(ln["run_id"] == "r-1" for ln in lines.all())

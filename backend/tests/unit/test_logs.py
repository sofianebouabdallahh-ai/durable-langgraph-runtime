"""Phase L7a: the log context, the access log and errors from the browser."""

from __future__ import annotations

import asyncio
import io
import json
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from agent_runtime import logs
from agent_runtime.api.access import AccessLog
from agent_runtime.api.client_errors import TokenBucket, client_errors_router

SID = "0b9c2f3e-8a4d-4c1e-9f7a-2d5b6c7e8f90"


@pytest.fixture
def lines() -> Iterator[io.StringIO]:
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    handler.setFormatter(logs.JsonFormatter("api"))
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield out
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)


def parsed(out: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in out.getvalue().splitlines()]


async def test_bind_nests_reaches_tasks_and_leaves_nothing_behind(lines: io.StringIO) -> None:
    log = logging.getLogger("agent_runtime.t")
    with logs.bind(run_id="r-1", session_id=None):
        with logs.bind(tool="calculator", run_id="r-2"):
            await asyncio.create_task(asyncio.to_thread(lambda: None))
            await asyncio.create_task(_log_in_task(log))
        assert logs.fields() == {"run_id": "r-1"}
        assert logs.fields(without=("run_id",)) == {}
    assert logs.fields() == {}
    (line,) = parsed(lines)
    assert (line["run_id"], line["tool"]) == ("r-2", "calculator")
    assert "session_id" not in line  # None is left out


async def _log_in_task(log: logging.Logger) -> None:
    log.info("inside a task")


def test_event_fields_are_keys_but_never_replace_the_fixed_ones(lines: io.StringIO) -> None:
    log = logging.getLogger("agent_runtime.t")
    logs.event(log, "tool call", status="success", duration_ms=12, msg="nope", level=40)
    logs.event(log, "from the browser", component="ui")
    first, second = parsed(lines)
    assert (first["msg"], first["level"], first["status"], first["duration_ms"]) == (
        "tool call", "ERROR", "success", 12,
    )  # fmt: skip
    assert first["component"] == "api" and second["component"] == "ui"


def test_text_lines_show_the_event_and_are_redacted() -> None:
    record = logging.LogRecord(
        "agent_runtime.t", logging.INFO, __file__, 1, "key %s", ("sk-" + "a" * 30,), None
    )
    record._fields = {"status": "success", "tokens": 3, "none": None}
    text = logs.TextFormatter().format(record)
    assert text.endswith("agent_runtime.t: key [REDACTED] status=success tokens=3")


def app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AccessLog)
    log = logging.getLogger("agent_runtime.endpoint")

    @app.get("/sessions/{session_id}")
    async def session(session_id: str) -> dict[str, str]:
        log.info("inside the endpoint")
        return {"id": session_id}

    @app.get("/sessions/{session_id}/stream")
    async def stream(session_id: str) -> StreamingResponse:
        async def events() -> AsyncIterator[bytes]:
            yield b"data: 1\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/boom")
    async def boom() -> None:
        raise HTTPException(503, "down")

    app.include_router(client_errors_router)
    return app


def client(a: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=a), base_url="http://t")


async def test_the_access_log(lines: io.StringIO) -> None:
    async with client(app()) as c:
        mine = await c.get(f"/sessions/{SID}", headers={"X-Request-ID": "ui-req-123"})
        made = await c.get(f"/sessions/{SID}", headers={"X-Request-ID": "bad id!"})
        await c.get("/healthz")
        await c.get("/boom")
    assert mine.headers["x-request-id"] == "ui-req-123"
    assert len(made.headers["x-request-id"]) == 32  # not the caller's: it isn't one
    every = parsed(lines)
    inside = [ln for ln in every if ln["msg"] == "inside the endpoint"]
    assert inside[0]["request_id"] == "ui-req-123" and inside[0]["session_id"] == SID
    access = [ln for ln in every if ln["logger"] == "api.access"]
    assert [ln["route"] for ln in access] == ["/sessions/{session_id}"] * 2 + ["/boom"]
    assert access[0]["msg"] == "GET /sessions/{session_id} 200" and access[0]["session_id"] == SID
    assert isinstance(access[0]["duration_ms"], int)
    assert (access[2]["status"], access[2]["level"]) == (503, "WARNING")


async def test_a_stream_is_logged_when_it_opens_and_when_it_closes(lines: io.StringIO) -> None:
    async with client(app()) as c:
        await c.get(f"/sessions/{SID}/stream")
    access = [ln for ln in parsed(lines) if ln["logger"] == "api.access"]
    assert [ln.get("stream") for ln in access] == ["open", None]
    assert access[0]["msg"] == "GET /sessions/{session_id}/stream 200 (stream open)"
    assert all(ln["session_id"] == SID for ln in access)


async def test_errors_from_the_browser(lines: io.StringIO) -> None:
    a = app()
    a.state.client_errors = TokenBucket(rate=1, burst=2)
    body = {
        "kind": "error", "message": f"TypeError with {'sk-' + 'b' * 30}", "stack": "at x (y:1)",
        "route": "#/activity", "failed_request_id": "ui-req-123", "version": "0.1.0",
    }  # fmt: skip
    async with client(a) as c:
        codes = [(await c.post("/client-errors", json=body)).status_code for _ in range(3)]
        too_big = await c.post("/client-errors", json={**body, "message": "x" * 2001})
    assert codes == [202, 202, 429] and too_big.status_code == 422
    ui = [ln for ln in parsed(lines) if ln["logger"] == "ui"]
    assert len(ui) == 2
    assert (ui[0]["component"], ui[0]["level"], ui[0]["route"]) == ("ui", "WARNING", "#/activity")
    assert "[REDACTED]" in ui[0]["msg"] and "sk-" not in json.dumps(ui)


def test_lines_go_to_the_collector_as_otlp_records_with_their_trace() -> None:
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
    from opentelemetry.sdk.trace import TracerProvider

    exporter = InMemoryLogRecordExporter()  # type: ignore[no-untyped-call]
    provider = LoggerProvider()
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    handler = logs.OtlpHandler(provider, "worker")
    log = logging.getLogger("agent_runtime.otlp")
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    tracer = TracerProvider().get_tracer("t")
    try:
        with tracer.start_as_current_span("run") as span, logs.bind(run_id="r-1"):
            logs.event(log, f"model call with {'sk-' + 'c' * 30}", tokens_in=3,
                       nested={"a": 1}, level=logging.WARNING)  # fmt: skip
    finally:
        log.removeHandler(handler)
    (got,) = [d.log_record for d in exporter.get_finished_logs()]
    assert got.body == "model call with [REDACTED]"
    assert got.severity_text == "WARNING" and got.severity_number is not None
    assert got.trace_id == span.get_span_context().trace_id
    assert got.span_id == span.get_span_context().span_id
    attrs = dict(got.attributes or {})
    assert attrs["run_id"] == "r-1" and attrs["tokens_in"] == 3 and attrs["component"] == "worker"
    assert attrs["nested"] == '{"a": 1}' and "trace_id" not in attrs and "msg" not in attrs

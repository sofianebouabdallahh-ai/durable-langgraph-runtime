"""Observability units (phase L4a): the worker's probes (SC6, R10.5), metrics derived
from events (R7.2), the W3C helpers and JSON logs (R7.1)."""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import pytest
from prometheus_client import REGISTRY

from agent_runtime import metrics, telemetry
from agent_runtime.worker import HealthServer, Worker

# ---------------------------------------------------------------- probes


@dataclass
class FakeWorker:
    last_tick: float | None = None
    draining: bool = False

    def live(self, max_age_s: float) -> bool:
        return Worker.live(self, max_age_s)  # type: ignore[arg-type]


async def get(port: int, path: str) -> tuple[int, str]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    await writer.drain()
    raw = await reader.read()
    writer.close()
    head, _, body = raw.decode().partition("\r\n\r\n")
    return int(head.split()[1]), body


async def test_probes_over_http() -> None:
    worker, stopping = FakeWorker(last_tick=time.monotonic()), asyncio.Event()
    server = HealthServer(worker, stopping, liveness_s=30, port=0)  # type: ignore[arg-type]
    assert await server.start("127.0.0.1")
    try:
        assert await get(server.port, "/healthz") == (200, "ok")
        assert await get(server.port, "/readyz") == (200, "ok")
        status, body = await get(server.port, "/metrics")
        assert status == 200 and "runtime_worker_inflight" in body
        assert (await get(server.port, "/nope"))[0] == 404
    finally:
        await server.stop()


def test_liveness_fails_when_the_loop_stalls() -> None:
    """SC6: the loop last ticked longer ago than worker_liveness_s → restart me."""
    worker = FakeWorker(last_tick=time.monotonic() - 31)
    server = HealthServer(worker, asyncio.Event(), liveness_s=30, port=0)  # type: ignore[arg-type]
    assert server.respond("/healthz")[0] == 503
    worker.last_tick = time.monotonic()
    assert server.respond("/healthz")[0] == 200


def test_not_ready_before_the_first_tick_and_at_once_on_drain() -> None:
    worker, stopping = FakeWorker(), asyncio.Event()
    server = HealthServer(worker, stopping, liveness_s=30, port=0)  # type: ignore[arg-type]
    assert server.respond("/readyz")[0] == 503  # starting
    worker.last_tick = time.monotonic()
    assert server.respond("/readyz")[0] == 200
    stopping.set()  # SIGTERM: not ready at once, still live while it drains
    assert server.respond("/readyz") == (503, "text/plain", b"draining")
    assert server.respond("/healthz")[0] == 200


async def test_a_taken_port_is_not_fatal() -> None:
    first = HealthServer(FakeWorker(), asyncio.Event(), liveness_s=30, port=0)  # type: ignore[arg-type]
    assert await first.start("127.0.0.1")
    try:
        second = HealthServer(FakeWorker(), asyncio.Event(), liveness_s=30, port=first.port)  # type: ignore[arg-type]
        assert not await second.start("127.0.0.1")
    finally:
        await first.stop()


# --------------------------------------------------------------- metrics


@dataclass
class Ev:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


def sample(name: str, labels: dict[str, str] | None = None) -> float:
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


def test_events_become_metrics() -> None:
    expected = [  # (metric, labels, increment)
        ("runtime_budget_breaches_total", {"budget": "tokens"}, 1),
        ("runtime_loop_detections_total", {}, 1),
        ("runtime_releases_total", {"reason": "circuit_open"}, 1),
        ("runtime_policy_decisions_total", {"decision": "deny", "kind": "risk"}, 1),
        ("runtime_tool_calls_total", {"tool": "t", "cached": "true", "status": "done"}, 1),
        ("runtime_subagents_total", {"outcome": "timed_out"}, 1),
        ("runtime_children_spawned_total", {}, 3),
    ]
    before = [sample(name, labels) for name, labels, _ in expected]
    metrics.observe_events([
        Ev("run.failed", {"reason": "budget:tokens"}),
        Ev("run.failed", {"reason": "loop_detected"}),
        Ev("run.released", {"reason": "circuit_open"}),
        Ev("policy.decision", {"decision": "deny", "kind": "risk"}),
        Ev("tool.completed", {"tool": "t", "cached": True, "status": "done", "duration_ms": 3}),
        Ev("subagent.completed", {"status": "timed_out"}),
        Ev("children.spawned", {"children": [{}, {}, {}]}),
        Ev("something.new", {}),  # unknown types are ignored
        Ev("node.completed", {"duration_ms": "not a number"}),  # never raises
    ])  # fmt: skip
    after = [sample(name, labels) for name, labels, _ in expected]
    assert [a - b for a, b in zip(after, before, strict=True)] == [n for *_, n in expected]


def test_llm_usage_and_budget_warnings() -> None:
    tokens = sample("runtime_llm_tokens_total", {"model": "m", "direction": "out"})
    cost = sample("runtime_llm_cost_usd_total", {"model": "m"})
    warnings = sample("runtime_budget_warnings_total", {"budget": "cost"})
    metrics.llm_usage("m", 10, 5, 0.25)
    metrics.budget_warning("budget:cost")
    assert sample("runtime_llm_tokens_total", {"model": "m", "direction": "out"}) == tokens + 5
    assert sample("runtime_llm_cost_usd_total", {"model": "m"}) == pytest.approx(cost + 0.25)
    assert sample("runtime_budget_warnings_total", {"budget": "cost"}) == warnings + 1


# ------------------------------------------------------------ context, logs


def test_trace_id_of_a_traceparent() -> None:
    tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    assert telemetry.trace_id_of(tp) == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert telemetry.trace_id_of(None) is None
    assert telemetry.trace_id_of("garbage") is None
    assert telemetry.trace_id_of("00-" + "0" * 32 + "-00f067aa0ba902b7-01") is None


def test_off_by_default() -> None:
    """SC4: nothing configured → no SDK, no traceparent."""
    assert telemetry.configure("api", "") is False
    assert not telemetry.enabled()
    with telemetry.tracer().start_as_current_span("x"):
        assert telemetry.current_traceparent() is None


def record(msg: str, exc: bool = False) -> logging.LogRecord:
    info = None
    if exc:
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            info = sys.exc_info()
    return logging.LogRecord("agent_runtime.x", logging.WARNING, __file__, 1, msg, (), info)


def test_json_lines_carry_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POD_NAME", "worker-7d9f")
    fmt = telemetry.JsonFormatter("worker")
    plain = json.loads(fmt.format(record("hello")))
    assert plain["msg"] == "hello" and plain["level"] == "WARNING"
    assert plain["component"] == "worker" and plain["pod"] == "worker-7d9f"
    assert "run_id" not in plain
    with telemetry.bind_run("r-1", 3, "abc"):
        line = json.loads(fmt.format(record("inside", exc=True)))
    assert (line["run_id"], line["epoch"], line["trace_id"]) == ("r-1", 3, "abc")
    assert "ValueError: boom" in line["exc"]


def test_setup_logging_switches_format(capsys: pytest.CaptureFixture[str]) -> None:
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    try:
        telemetry.setup_logging("INFO", "json", "api")
        logging.getLogger("agent_runtime.t").info("one")
        assert json.loads(capsys.readouterr().err)["msg"] == "one"
        telemetry.setup_logging("INFO", "text")
        logging.getLogger("agent_runtime.t").info("two")
        assert capsys.readouterr().err.rstrip().endswith("agent_runtime.t: two")
    finally:
        root.handlers[:], _ = saved
        root.setLevel(saved[1])


def test_probe_and_scrape_requests_are_not_logged() -> None:
    probe = telemetry.ProbeFilter()

    def access(path: str) -> logging.LogRecord:
        return logging.LogRecord(
            "uvicorn.access", logging.INFO, __file__, 1, '%s - "GET %s HTTP/1.1" %d',
            ("10.0.0.1:5000", path, 200), None,
        )  # fmt: skip

    assert not probe.filter(access("/readyz"))
    assert not probe.filter(access("/metrics"))
    assert probe.filter(access("/runs/abc"))

"""Observability (phase L4a): one trace across processes and time (AC8, R2.7, R7.1),
metrics that move with real runs (R7.2), and logs that carry the run (R7.1).

Spans go to an in-memory exporter installed with `telemetry.use_provider`, so the
tests see exactly what Jaeger would receive, and nothing global is touched."""

import asyncio
import io
import json
import logging
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client import REGISTRY

from agent_runtime import logs, metrics, telemetry
from agent_runtime.api.app import create_app
from agent_runtime.config import Settings
from agent_runtime.db import Pool
from agent_runtime.graphs import default_registry
from agent_runtime.queue import InMemoryWorkQueue
from agent_runtime.runs.executor import RunExecutor
from agent_runtime.runs.service import RunService
from agent_runtime.runs.state import RunStatus as S
from agent_runtime.runs.store import Run, RunRepository
from agent_runtime.streaming.bus import InMemoryEventBus
from tests.integration.support import node_completed, wait_until

pytestmark = pytest.mark.integration
GRAPHS = default_registry()


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry.use_provider(provider)
    try:
        yield exporter
    finally:
        telemetry.use_provider(None)
        provider.shutdown()


@pytest.fixture
def settings_fast(test_settings: Settings) -> Settings:
    return test_settings.model_copy(update={"lease_ttl_s": 1.5, "heartbeat_s": 0.4})


def request_span(name: str = "POST /runs") -> Any:
    """Stands in for FastAPI's server span around a request."""
    return telemetry.tracer().start_as_current_span(name)


def by_name(spans: list[ReadableSpan], name: str) -> list[ReadableSpan]:
    return [s for s in spans if s.name == name]


def parent_of(span: ReadableSpan, spans: list[ReadableSpan]) -> ReadableSpan | None:
    assert span.parent is not None
    return next((s for s in spans if s.context.span_id == span.parent.span_id), None)


def attr(span: ReadableSpan, key: str) -> Any:
    assert span.attributes is not None
    return span.attributes.get(key)


async def get(pool: Pool, run_id: uuid.UUID) -> Run:
    async with pool.connection() as conn:
        return await RunRepository(conn).get(run_id)


# --------------------------------------------------------------------- AC8


async def test_one_trace_spans_the_request_the_parent_and_its_child_runs(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, spans: InMemorySpanExporter
) -> None:
    """SC1 (workflow half): request → parent `run` → each child's `run`, one trace."""
    with request_span() as request:
        parent = await RunService(pool, test_settings, GRAPHS).create_run(
            "fanout", {"topic": "t", "n": 2}
        )
    trace_id = format(request.get_span_context().trace_id, "032x")
    assert telemetry.trace_id_of(parent.traceparent) == trace_id

    first = await RunExecutor(pool, test_settings, GRAPHS).execute(parent.id)
    assert first.status is S.WAITING_CHILDREN
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT id FROM runs WHERE parent_run_id = %s", (parent.id,))
        children = [r["id"] for r in await cur.fetchall()]
    for child in children:
        assert (await RunExecutor(pool, test_settings, GRAPHS).execute(child)).status is S.COMPLETED
    done = await RunExecutor(pool, test_settings, GRAPHS).execute(parent.id)  # fan-in
    assert done.status is S.COMPLETED

    finished = list(spans.get_finished_spans())
    assert {format(s.context.trace_id, "032x") for s in finished} == {trace_id}
    runs = by_name(finished, "run")
    parent_runs = [s for s in runs if attr(s, "run.id") == str(parent.id)]
    child_runs = [s for s in runs if attr(s, "run.id") != str(parent.id)]
    assert len(parent_runs) == 2 and len(child_runs) == 2  # fan-out, then fan-in
    for s in parent_runs:  # each execution of the parent hangs below the request
        assert s.parent is not None and s.parent.span_id == request.get_span_context().span_id
    spawned_in = min(parent_runs, key=lambda s: s.start_time or 0)  # the fan-out
    for s in child_runs:  # children were created inside the parent's first execution
        assert parent_of(s, finished) is spawned_in
        assert attr(s, "run.depth") == 1 and attr(s, "run.status") == "completed"
    nodes = [s for s in finished if s.name.startswith("node:")]
    assert {s.name for s in nodes} >= {"node:plan", "node:research", "node:synthesize"}
    assert all(parent_of(n, finished) in runs for n in nodes)


async def test_a_turn_with_helpers_is_one_trace_with_model_tool_and_subagent_spans(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, spans: InMemorySpanExporter
) -> None:
    """SC1 (agent half): node → llm.call / tool:*, and sub-agents as spans of the run's
    worker (CR-005) with their own model and tool calls below them."""

    def call(name: str, **args: Any) -> dict[str, Any]:
        return {"name": name, "args": args}

    script = [
        {"content": "", "tool_calls": [call("spawn_subagent", agent="mathematician", task="6*7")]},
        {"content": "", "tool_calls": [call("wait_subagents",
                                            handles=["${spawn_subagent[0].handle}"])]},
        {"content": "6*7 = 42.", "tool_calls": []},
    ]  # fmt: skip
    subs = {"mathematician": [
        {"content": "", "tool_calls": [call("calculator", expression="6*7")]},
        {"content": "", "tool_calls": [call("return_result", summary="42")]},
    ]}  # fmt: skip
    with request_span("POST /sessions/{id}/messages"):
        run = await RunService(pool, test_settings, GRAPHS).create_run(
            "delegator", {"message": "go", "script": script, "subagent_scripts": subs}
        )
    done = await RunExecutor(pool, test_settings, GRAPHS, owner="w:1").execute(run.id)
    assert done.status is S.COMPLETED

    finished = list(spans.get_finished_spans())
    assert len({s.context.trace_id for s in finished}) == 1
    (run_span,) = by_name(finished, "run")
    (sub,) = by_name(finished, "subagent:mathematician")
    spawned_by = parent_of(sub, finished)
    assert spawned_by is not None and spawned_by.name == "node:tools"
    assert parent_of(spawned_by, finished) is run_span
    assert attr(sub, "worker") == "w:1"

    llm = by_name(finished, "llm.call")
    assert len(llm) == 5  # 3 main + 2 sub-agent
    main_llm = [s for s in llm if parent_of(s, finished) is not sub]
    assert all(parent_of(s, finished).name == "node:model" for s in main_llm)  # type: ignore[union-attr]
    assert sum(parent_of(s, finished) is sub for s in llm) == 2
    assert all(attr(s, "llm.model") == "scripted" for s in llm)
    assert all(attr(s, "llm.attempts") == 1 for s in llm)
    assert all(isinstance(attr(s, "llm.tokens_in"), int) for s in llm)

    (calc,) = by_name(finished, "tool:calculator")
    assert parent_of(calc, finished) is sub
    assert (attr(calc, "tool.status"), attr(calc, "tool.cached")) == ("success", False)
    (spawn,) = by_name(finished, "tool:spawn_subagent")
    assert parent_of(spawn, finished).name == "node:tools"  # type: ignore[union-attr]


async def test_the_trace_survives_a_crash(
    pool: Pool, settings_fast: Settings, checkpoint_tables: None, spans: InMemorySpanExporter
) -> None:
    """SC2: the worker dies mid-run; the reclaimed execution continues the same trace,
    as a second `run` span marked reclaimed."""
    with request_span():
        run = await RunService(pool, settings_fast, GRAPHS).create_run(
            "toy", {"question": "q", "delay_s": 0.3}
        )
    worker_a = asyncio.create_task(
        RunExecutor(pool, settings_fast, GRAPHS, owner="a:1").execute(run.id)
    )
    await wait_until(lambda: node_completed(pool, run.id, "plan"))
    worker_a.cancel()
    await asyncio.gather(worker_a, return_exceptions=True)
    await asyncio.sleep(settings_fast.lease_ttl_s + 0.2)
    done = await RunExecutor(pool, settings_fast, GRAPHS, owner="b:2").execute(run.id)
    assert done.status is S.COMPLETED

    finished = list(spans.get_finished_spans())
    runs = sorted(by_name(finished, "run"), key=lambda s: s.start_time or 0)
    assert len(runs) == 2
    assert runs[0].context.trace_id == runs[1].context.trace_id
    assert runs[0].parent is not None and runs[1].parent is not None
    assert runs[0].parent.span_id == runs[1].parent.span_id  # both under the request
    assert [attr(s, "run.reclaimed") for s in runs] == [False, True]
    assert [attr(s, "run.epoch") for s in runs] == [1, 2]
    assert [attr(s, "worker") for s in runs] == ["a:1", "b:2"]
    assert attr(runs[1], "run.status") == "completed"


async def test_with_tracing_off_nothing_is_recorded(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    """SC4: no provider configured → no traceparent stored, no trace id shown."""
    assert not telemetry.enabled()
    with request_span():
        run = await RunService(pool, test_settings, GRAPHS).create_run("toy", {"question": "q"})
    assert run.traceparent is None
    done = await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)
    assert done.traceparent is None and done.status is S.COMPLETED


# ------------------------------------------------------------------- logs


async def test_every_log_line_during_a_run_carries_its_context(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, spans: InMemorySpanExporter
) -> None:
    """SC5: JSON lines with run_id, epoch and trace_id."""
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    handler.setFormatter(logs.JsonFormatter("worker"))
    logger = logging.getLogger("agent_runtime")
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.INFO)
    try:
        with request_span():
            run = await RunService(pool, test_settings, GRAPHS).create_run("toy", {"question": "q"})
        await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    mine = [line for line in lines if str(run.id) in line["msg"]]
    assert len(mine) >= 2  # executing …, completed
    for line in mine:
        assert line["run_id"] == str(run.id)
        assert line["epoch"] == 1
        assert line["trace_id"] == telemetry.trace_id_of(run.traceparent)
        assert line["component"] == "worker"


# ---------------------------------------------------------------- metrics


def sample(name: str, labels: dict[str, str] | None = None) -> float:
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


async def test_counters_move_with_real_runs(
    pool: Pool, settings_fast: Settings, checkpoint_tables: None
) -> None:
    """SC3: completed runs, a reclaim, a failure by reason, node latency."""
    completed = sample("runtime_runs_total", {"status": "completed", "reason": ""})
    failed = sample("runtime_runs_total", {"status": "failed", "reason": "error"})
    reclaims = sample("runtime_reclaims_total")
    nodes = sample("runtime_node_duration_seconds_count", {"node": "plan", "outcome": "ok"})
    turns = sample(
        "runtime_run_duration_seconds_count", {"kind": "workflow", "status": "completed"}
    )
    service = RunService(pool, settings_fast, GRAPHS)

    ok = await service.create_run("toy", {"question": "q"})
    await RunExecutor(pool, settings_fast, GRAPHS).execute(ok.id)
    bad = await service.create_run("toy", {"question": "q", "fail_at": "research"})
    assert (await RunExecutor(pool, settings_fast, GRAPHS).execute(bad.id)).reason == "error"
    slow = await service.create_run("toy", {"question": "q", "delay_s": 0.3})
    task = asyncio.create_task(
        RunExecutor(pool, settings_fast, GRAPHS, owner="a:1").execute(slow.id)
    )
    await wait_until(lambda: node_completed(pool, slow.id, "plan"))
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(settings_fast.lease_ttl_s + 0.2)
    await RunExecutor(pool, settings_fast, GRAPHS, owner="b:2").execute(slow.id)

    assert sample("runtime_runs_total", {"status": "completed", "reason": ""}) == completed + 2
    assert sample("runtime_runs_total", {"status": "failed", "reason": "error"}) == failed + 1
    assert sample("runtime_reclaims_total") == reclaims + 1
    assert sample("runtime_node_duration_seconds_count",
                  {"node": "plan", "outcome": "ok"}) == nodes + 3  # fmt: skip
    assert sample("runtime_run_duration_seconds_count",
                  {"kind": "workflow", "status": "completed"}) == turns + 2  # fmt: skip


async def test_model_usage_and_tool_calls_are_counted(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    calls = sample("runtime_llm_calls_total", {"model": "scripted"})
    tools = sample("runtime_tool_calls_total", {"tool": "calculator", "cached": "false",
                                                "status": "done"})  # fmt: skip
    script = [
        {"content": "", "tool_calls": [{"name": "calculator", "args": {"expression": "2+2"}}]},
        {"content": "4", "tool_calls": []},
    ]
    run = await RunService(pool, test_settings, GRAPHS).create_run(
        "assistant", {"message": "2+2?", "script": script}
    )
    assert (await RunExecutor(pool, test_settings, GRAPHS).execute(run.id)).status is S.COMPLETED
    assert sample("runtime_llm_calls_total", {"model": "scripted"}) == calls + 2
    assert sample("runtime_tool_calls_total", {"tool": "calculator", "cached": "false",
                                               "status": "done"}) == tools + 1  # fmt: skip


async def test_state_gauges_read_postgres_and_redis(
    pool: Pool, test_settings: Settings, checkpoint_tables: None
) -> None:
    queue = InMemoryWorkQueue()
    service = RunService(pool, test_settings, GRAPHS)
    await service.create_run("toy", {"question": "q"})
    await metrics.StatePoller(pool, queue).poll()
    async with pool.connection() as conn:
        depth = await RunRepository(conn).queue_depth()
    assert sample("runtime_queue_depth") == depth >= 1
    assert sample("runtime_kill_switch") == 0
    assert sample("runtime_queue_pending") == await queue.pending_count()
    # One agent switched off counts too (L7): the gauge reads the per-agent switches.
    async with pool.connection() as conn:
        before = (
            await (await conn.execute("SELECT count(*) AS n FROM kill_switches")).fetchone()
            or {"n": 0}
        )["n"]
        await conn.execute("INSERT INTO kill_switches (agent) VALUES ('gauge-test')")
    try:
        await metrics.StatePoller(pool, queue).poll()
        assert sample("runtime_agents_switched_off") == before + 1
    finally:
        async with pool.connection() as conn:
            await conn.execute("DELETE FROM kill_switches WHERE agent = 'gauge-test'")


async def test_api_serves_metrics_about_and_the_runs_trace_id(
    pool: Pool, test_settings: Settings, checkpoint_tables: None, spans: InMemorySpanExporter
) -> None:
    settings = test_settings.model_copy(update={
        "otel_exporter_otlp_endpoint": "http://collector:4318",
        "trace_ui_url": "http://localhost:16686", "dashboard_url": "http://localhost:3001",
    })  # fmt: skip
    app = create_app(settings, pool=pool, queue=InMemoryWorkQueue(), bus=InMemoryEventBus())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client,
    ):
        scraped = await client.get("/metrics")
        assert scraped.status_code == 200
        assert "runtime_runs_total" in scraped.text
        assert "runtime_stream_subscribers" in scraped.text
        about = (await client.get("/about")).json()
        assert about["tracing"] is True
        assert about["trace_ui_url"] == "http://localhost:16686"
        assert about["dashboard_url"] == "http://localhost:3001"
        with request_span():
            created = await client.post("/runs", json={"graph": "toy", "input": {"question": "q"}})
        run_id = created.json()["run_id"]
        view = (await client.get(f"/runs/{run_id}")).json()
    run = await get(pool, uuid.UUID(run_id))
    assert view["trace_id"] == telemetry.trace_id_of(run.traceparent) is not None

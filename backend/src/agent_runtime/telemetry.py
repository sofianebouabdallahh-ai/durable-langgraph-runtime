"""Tracing (R2.7, R7.1); logs are agent_runtime.logs.

    API request ──► traceparent stored on the run (Postgres) ──► any worker, any time:

    run ─┬─ node:{name} ─┬─ llm.call
         │               └─ tool:{name}
         ├─ subagent:{name} ─ llm.call, tool:{name}
         └─ child runs: their own `run` spans, below it

Patterns:
- Facade: the rest of the runtime calls `configure`, `current_traceparent`,
  `run_span` and `child_span`; only this module (and the log formatter) touches
  OpenTelemetry.
- Null Object: with no `OTEL_EXPORTER_OTLP_ENDPOINT`, no SDK is installed. The
  OpenTelemetry API is then a no-op: spans are non-recording, `current_traceparent`
  returns None, and nothing is exported (L4a SC4).

The context travels **in Postgres, on the run** (`runs.traceparent`), never in the
Redis message, so a reclaim after a crash, a resume after an approval and a parent
re-queued by its children all continue the same trace.

Node spans are opened from the executor's LangChain callbacks, which run outside the
node's own context; `RunTrace` keeps them so that the model and tool calls inside a
node (the middleware, the ToolPipeline) can open their spans under it.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
import socket
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from langgraph.errors import GraphBubbleUp
from opentelemetry import context as otel_context
from opentelemetry import propagate, trace
from opentelemetry.trace import Span, Status, StatusCode

from agent_runtime import logs

TRACER = "agent_runtime"
_configured = False
_provider: trace.TracerProvider | None = None  # ours, once configured (or a test's)
_log_provider: Any = None  # the OTLP log pipeline, once configured
log = logging.getLogger(__name__)

# Kubernetes resource attributes, passed in by the Downward API (L4b) when present.
_K8S_ENV = {
    "k8s.pod.name": "POD_NAME",
    "k8s.namespace.name": "POD_NAMESPACE",
    "k8s.node.name": "NODE_NAME",
}


# ------------------------------------------------------------------ setup


def configure(service: str, endpoint: str, instance: str | None = None) -> bool:
    """Install the SDK and an OTLP/HTTP exporter, only when `endpoint` is set.

    Idempotent. Returns whether tracing is on. FastAPI and httpx are
    auto-instrumented by the caller (only those two: our own spans carry the meaning).
    """
    global _configured
    if not endpoint or _configured:
        return _configured
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    attrs: dict[str, str] = {
        "service.name": service,
        "service.instance.id": instance or f"{socket.gethostname()}:{os.getpid()}",
    }
    attrs |= {k: v for k, env in _K8S_ENV.items() if (v := os.environ.get(env))}
    resource = Resource.create(attrs)
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")
    # Export every second (not the default 5 s): a worker killed mid-run loses only
    # the spans of its last second; the run itself is reclaimed in the same trace.
    provider.add_span_processor(BatchSpanProcessor(exporter, schedule_delay_millis=1000))
    trace.set_tracer_provider(provider)
    use_provider(provider)
    _ship_logs(endpoint, resource, service)
    _configured = True
    return True


def _ship_logs(endpoint: str, resource: Any, service: str) -> None:
    """Log lines go to the collector too (phase L7b), with the same resource, so Loki
    files them under the same service as the traces."""
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

    global _log_provider
    _log_provider = LoggerProvider(resource=resource)
    exporter = OTLPLogExporter(endpoint=endpoint.rstrip("/") + "/v1/logs")
    _log_provider.add_log_record_processor(
        BatchLogRecordProcessor(exporter, schedule_delay_millis=1000)
    )
    logs.ship(_log_provider, service)


def use_provider(provider: trace.TracerProvider | None) -> None:
    """The provider our spans go to (tests install one with an in-memory exporter)."""
    global _provider
    _provider = provider


def enabled() -> bool:
    return _configured


def shutdown() -> None:
    """Flush buffered spans and log lines (a worker draining, an API stopping)."""
    for provider in (_provider, _log_provider):
        shutdown_ = getattr(provider, "shutdown", None)
        if _configured and shutdown_ is not None:
            shutdown_()


def tracer() -> trace.Tracer:
    return (_provider or trace.get_tracer_provider()).get_tracer(TRACER)


# ------------------------------------------------------------- W3C context


def current_traceparent() -> str | None:
    """The current span as a W3C `traceparent`, or None (tracing off, or no span)."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier.get("traceparent")


def context_of(traceparent: str | None) -> otel_context.Context:
    """A context whose parent is `traceparent`; an empty one when there is none."""
    if not traceparent:
        return otel_context.Context()
    return propagate.extract({"traceparent": traceparent})


def trace_id_of(traceparent: str | None) -> str | None:
    """`00-<trace id>-<span id>-<flags>` → the 32-hex trace id."""
    parts = (traceparent or "").split("-")
    if len(parts) == 4 and len(parts[1]) == 32 and parts[1] != "0" * 32:
        return parts[1]
    return None


def _hex_trace_id(span: Span) -> str | None:
    ctx = span.get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


# ------------------------------------------------------------------- spans


@dataclass
class RunTrace:
    """One execution's spans: the `run` span and its open `node:*` spans."""

    span: Span
    _nodes: dict[Any, Span] = field(default_factory=dict)

    def start_node(self, key: Any, name: str) -> None:
        parent = trace.set_span_in_context(self.span)
        self._nodes[key] = tracer().start_span(f"node:{name}", context=parent,
                                               attributes={"node": name})  # fmt: skip

    def end_node(self, key: Any, error: BaseException | None = None) -> None:
        span = self._nodes.pop(key, None)
        if span is None:
            return
        if error is not None:
            span.set_status(Status(StatusCode.ERROR, type(error).__name__))
        span.end()

    def parent(self) -> otel_context.Context:
        """The innermost open node (one at a time in an agent graph), else the run."""
        span = next(reversed(self._nodes.values()), None) or self.span
        return trace.set_span_in_context(span)

    def close(self) -> None:
        for key in list(self._nodes):
            self.end_node(key)


_run_trace: contextvars.ContextVar[RunTrace | None] = contextvars.ContextVar(
    "run_trace", default=None
)


@contextlib.contextmanager
def run_span(traceparent: str | None, attributes: Mapping[str, Any]) -> Iterator[RunTrace]:
    """The `run` span of one execution, parented to the context stored on the run.
    Inside it, `current_traceparent()` is this span: child runs hang below it."""
    with tracer().start_as_current_span(
        "run", context=context_of(traceparent), attributes=dict(attributes),
        kind=trace.SpanKind.CONSUMER,
    ) as span:  # fmt: skip
        rt = RunTrace(span)
        token = _run_trace.set(rt)
        try:
            yield rt
        finally:
            rt.close()
            _run_trace.reset(token)


def parent_context() -> otel_context.Context:
    """Where a model or tool call's span belongs: the open node, else the current span."""
    rt = _run_trace.get()
    return rt.parent() if rt is not None else otel_context.get_current()


@contextlib.contextmanager
def child_span(
    name: str,
    attributes: Mapping[str, Any] | None = None,
    *,
    current: bool = False,
    parent: otel_context.Context | None = None,
) -> Iterator[Span]:
    """A span under `parent` (default: `parent_context()`). `current=True` also makes it
    the current span (and hides the run's node spans), so that a sub-agent's own calls,
    in a task of their own, nest below it."""
    ctx = parent if parent is not None else parent_context()
    if not current:
        span = tracer().start_span(name, context=ctx, attributes=dict(attributes or {}))
        try:
            yield span
        except BaseException as exc:
            _record_error(span, exc)
            raise
        finally:
            span.end()
        return
    token = _run_trace.set(None)
    try:
        with tracer().start_as_current_span(
            name, context=ctx, attributes=dict(attributes or {})
        ) as span:
            yield span
    finally:
        _run_trace.reset(token)


def _record_error(span: Span, exc: BaseException) -> None:
    # An interrupt (an approval pause) unwinds through the span but is not an error.
    if isinstance(exc, Exception) and not isinstance(exc, GraphBubbleUp):
        span.set_status(Status(StatusCode.ERROR, type(exc).__name__))


def run_trace_id() -> str | None:
    """The trace id of the current run's execution, for logs and the UI."""
    rt = _run_trace.get()
    if rt is not None:
        return _hex_trace_id(rt.span)
    return _hex_trace_id(trace.get_current_span())

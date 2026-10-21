"""Logs (phase L7a): one id finds everything.

    HTTP request  ─► request_id, session_id (or run_id) from the path
    run           ─► run_id, epoch, session_id, agent, agent_version, kind, worker, trace_id
    helper task   ─► helper, helper_handle
    tool call     ─► tool, tool_call_id
    model call    ─► model

Each boundary `bind`s its ids; every line written inside it (and in tasks it starts)
carries them, plus the current span's `trace_id` and `span_id`. Lines are JSON on stderr
in containers (the source of truth: it works with no collector) and text at a terminal.
Every line goes through `redact()`: a key in a message, an exception or a field never
reaches a log. What gets logged is what happened and the numbers, never message text,
tool arguments or results.

Patterns:
- Facade: the runtime calls `bind`, `fields` and `event`; only this module formats lines.
- Context Object: the ids travel in a context variable (copied into the tasks a boundary
  starts), not through every function's arguments.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import sys
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from opentelemetry import trace

from agent_runtime.redaction import redact

_EMPTY: Mapping[str, Any] = MappingProxyType({})
_fields: contextvars.ContextVar[Mapping[str, Any]] = contextvars.ContextVar(
    "log_fields", default=_EMPTY
)
_EVENT = "_fields"  # the LogRecord attribute an event's own fields travel in
_FIXED = ("ts", "level", "logger", "msg")  # never overwritten by a field


@contextlib.contextmanager
def bind(**fields: Any) -> Iterator[None]:
    """Every line in this context (and tasks it starts) carries these fields. None is
    left out; an inner bind adds to the outer one and wins on a clash."""
    merged = {**_fields.get(), **{k: v for k, v in fields.items() if v is not None}}
    token = _fields.set(MappingProxyType(merged))
    try:
        yield
    finally:
        _fields.reset(token)


def fields(*, without: tuple[str, ...] = ()) -> dict[str, Any]:
    """What's bound now (less `without`): to carry into a task that starts from an empty
    context."""
    return {k: v for k, v in _fields.get().items() if k not in without}


def event(logger: logging.Logger, msg: str, /, level: int = logging.INFO, **fields: Any) -> None:
    """One line for one thing that happened: `msg` names it, `fields` hold its numbers
    and outcome (never content). In JSON they're top-level keys; in text, `k=v`."""
    logger.log(level, msg, extra={_EVENT: fields})


def _current_span() -> dict[str, str]:
    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return {}
    return {"trace_id": format(ctx.trace_id, "032x"), "span_id": format(ctx.span_id, "016x")}


def _clean(value: Any) -> Any:
    plain = isinstance(value, str | int | float | bool | dict | list)
    return redact(value if plain else str(value))


def line_of(record: logging.LogRecord, static: Mapping[str, str]) -> dict[str, Any]:
    """A record as one line's fields: ts, level, logger, msg, `static` (component, pod);
    the bound fields; the event's fields; the span; `exc`. All of it redacted. The same
    dict goes to stdout (JSON) and, with tracing on, to the collector (OTLP)."""
    line: dict[str, Any] = {
        "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
        "level": record.levelname,
        "logger": record.name,
        "msg": redact(record.getMessage()),
        **static,
    }
    span = _current_span()
    if "trace_id" in span and "trace_id" not in _fields.get():
        line["trace_id"] = span["trace_id"]
    for key, value in [*_fields.get().items(), *getattr(record, _EVENT, {}).items()]:
        if key not in _FIXED and value is not None:
            line[key] = _clean(value)
    if "span_id" in span:
        line["span_id"] = span["span_id"]
    if record.exc_info:
        line["exc"] = redact(logging.Formatter().formatException(record.exc_info))
    return line


def _static(component: str | None) -> dict[str, str]:
    static = {"component": component} if component else {}
    if pod := os.environ.get("POD_NAME"):
        static["pod"] = pod
    return static


class JsonFormatter(logging.Formatter):
    """One JSON object per line (`line_of`)."""

    def __init__(self, component: str | None = None) -> None:
        super().__init__()
        self._static = _static(component)

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(line_of(record, self._static), default=str, ensure_ascii=False)


class OtlpHandler(logging.Handler):
    """The same lines, as OTLP log records, to the collector (phase L7b): Loki keeps them
    beside the traces. A copy: stdout stays the source of truth, so a collector that's
    down loses nothing that matters. The Logs API is still `_logs` (unstable) in the
    OpenTelemetry SDK, so it's used here only, in a few lines."""

    def __init__(self, provider: Any, component: str | None = None) -> None:
        super().__init__()
        self._logger = provider.get_logger("agent_runtime")
        self._static = _static(component)

    def emit(self, record: logging.LogRecord) -> None:
        from opentelemetry._logs import LogRecord, SeverityNumber

        try:
            line = line_of(record, self._static)
            body = line.pop("msg")
            for key in ("ts", "level"):
                line.pop(key)
            trace_id, span_id = line.pop("trace_id", None), line.pop("span_id", None)
            attributes = {k: v if isinstance(v, str | int | float | bool) else json.dumps(v)
                          for k, v in line.items()}  # fmt: skip
            self._logger.emit(LogRecord(
                timestamp=int(record.created * 1e9),
                trace_id=int(trace_id, 16) if trace_id else None,
                span_id=int(span_id, 16) if span_id else None,
                severity_text=record.levelname,
                severity_number=_SEVERITY.get(record.levelno, SeverityNumber.INFO),
                body=body, attributes=attributes,
            ))  # fmt: skip
        except Exception:
            self.handleError(record)


def _severities() -> dict[int, Any]:
    from opentelemetry._logs import SeverityNumber

    return {logging.DEBUG: SeverityNumber.DEBUG, logging.INFO: SeverityNumber.INFO,
            logging.WARNING: SeverityNumber.WARN, logging.ERROR: SeverityNumber.ERROR,
            logging.CRITICAL: SeverityNumber.FATAL}  # fmt: skip


_SEVERITY = _severities()


def ship(provider: Any, component: str | None) -> None:
    """Also send every line to the collector (tracing on): see `OtlpHandler`."""
    root = logging.getLogger()
    if not any(isinstance(h, OtlpHandler) for h in root.handlers):
        root.addHandler(OtlpHandler(provider, component))


class TextFormatter(logging.Formatter):
    """For a person at a terminal: the classic line, then the event's fields as `k=v`
    (the bound ids are left to JSON, to keep lines short). Redacted too."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        extra = getattr(record, _EVENT, {})
        if extra:
            text += " " + " ".join(f"{k}={v}" for k, v in extra.items() if v is not None)
        return str(redact(text))


class ProbeFilter(logging.Filter):
    """Drops uvicorn's access lines for probes and scrapes, should its access log be on
    (ours, `api.access`, already leaves them out)."""

    PATHS = (" /healthz ", " /readyz ", " /metrics ")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(p in message for p in self.PATHS)


def setup(level: str, fmt: str, component: str | None = None) -> None:
    """The process's one handler: JSON (containers) or text (a terminal), on stderr."""
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, ProbeFilter) for f in access.filters):
        access.addFilter(ProbeFilter())
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter(component) if fmt == "json" else TextFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler, *(h for h in root.handlers if isinstance(h, OtlpHandler))]
    root.setLevel(level)
    for chatty in ("httpx", "httpcore"):  # a line per outgoing request: our own say more
        logging.getLogger(chatty).setLevel(max(logging.WARNING, logging.getLevelName(level)))

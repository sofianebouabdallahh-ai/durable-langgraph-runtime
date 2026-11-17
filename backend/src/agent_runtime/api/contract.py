"""The spec as a published contract (CR-007 R19.1, phase S1): what Nuria adds to the
OpenAPI document FastAPI builds.

- **Operation ids** are the route functions' names (`send_message`), so a generated client
  reads well; a test keeps them unique.
- **Errors are problem details, as they are on the wire** (`problems.py`). FastAPI's
  default 422 (`HTTPValidationError`, a shape this API never sends) becomes
  `ValidationProblem`; every operation gets `default: Problem` (any other error, including
  the guard's 403 and 421 and a 500); a route declares the statuses a client branches on
  with `responses=problems(404, 409)`.
- **Streams are typed:** a stream route declares `responses=sse("SessionStreamEvent")`,
  and the event models (`stream_schemas.py`) become named components.

The tests hold the server to all of it (`tests/sse.py`, `tests/problem_contract.py`).

Pattern: Decorator, over FastAPI's `openapi()`: same call, same cache, a finished document.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel, TypeAdapter
from pydantic.json_schema import models_json_schema

from agent_runtime.api import stream_schemas
from agent_runtime.api.problems import MEDIA_TYPE, Problem, ValidationProblem

Schema = dict[str, Any]
REF = "#/components/schemas/{model}"

# What each status means here, as the spec says it (a route's own description can say more).
MEANING = {
    400: "The request can't be handled as sent",
    404: "Not found",
    409: "The resource's current state doesn't allow this",
    413: "Too large",
    422: "The request didn't validate",
    429: "Too many requests: retry after `Retry-After` seconds",
    503: "Unavailable for now: retry after `Retry-After` seconds (draining or paused)",
}
_STREAM_MODELS: tuple[type[BaseModel], ...] = (
    stream_schemas.RunStreamEvent,
    stream_schemas.ReconnectData,
)
_UNIONS: dict[str, Any] = {"SessionStreamEvent": stream_schemas.SessionStreamEvent}


def operation_id(route: APIRoute) -> str:
    return route.name


def _problem(description: str, model: str = "Problem") -> Schema:
    return {
        "description": description,
        "content": {MEDIA_TYPE: {"schema": {"$ref": REF.format(model=model)}}},
    }


def problems(*statuses: int) -> dict[Any, Any]:
    """`responses=` for the error statuses a route can answer with (besides 422)."""
    return {status: _problem(MEANING[status]) for status in statuses}


def sse(event: str, *statuses: int) -> dict[Any, Any]:
    """`responses=` for a stream whose events' `data` is the `event` component, in the shape
    FastAPI gives its own SSE routes (OpenAPI 3.2's `itemSchema`, inside a 3.1 document).
    `event: reconnect` carries `ReconnectData` instead."""
    data = {
        "oneOf": [{"$ref": REF.format(model=event)}, {"$ref": REF.format(model="ReconnectData")}]
    }
    item = {
        "type": "object",
        "required": ["data"],
        "properties": {
            "data": {
                "type": "string",
                "contentMediaType": "application/json",
                "contentSchema": data,
            },
            "event": {"type": "string", "description": "The event's `type`, or `reconnect`"},
            "id": {"type": "string", "description": "Persisted events only: their `seq`"},
            "retry": {"type": "integer", "minimum": 0},
        },
    }
    return {
        200: {
            "description": "Server-sent events",
            "content": {"text/event-stream": {"itemSchema": item}},
        }
    } | problems(*statuses)


def _components(schema: Schema) -> Schema:
    components: Schema = schema.setdefault("components", {}).setdefault("schemas", {})
    models: tuple[type[BaseModel], ...] = (Problem, ValidationProblem, *_STREAM_MODELS)
    _, defs = models_json_schema([(m, "serialization") for m in models], ref_template=REF)
    for name, union in _UNIONS.items():
        named = TypeAdapter(union).json_schema(mode="serialization", ref_template=REF)
        defs.setdefault("$defs", {}).update(named.pop("$defs", {}))
        components[name] = named
    for name, model_schema in defs.get("$defs", {}).items():
        components.setdefault(name, model_schema)  # FastAPI's own (MessageView) stay
    return components


def finish(schema: Schema) -> Schema:
    components = _components(schema)
    validation = _problem(MEANING[422], "ValidationProblem")
    for item in schema.get("paths", {}).values():
        for operation in item.values():
            responses: Schema = operation.setdefault("responses", {})
            default_422 = responses.get("422", {}).get("content", {}).get("application/json", {})
            if default_422.get("schema", {}).get("$ref", "").endswith("/HTTPValidationError"):
                responses["422"] = validation
            responses.setdefault("default", _problem("Any other error, as problem details"))
    for unused in ("HTTPValidationError", "ValidationError"):
        components.pop(unused, None)
    return schema


def install(app: FastAPI) -> None:
    build: Callable[[], Schema] = app.openapi

    def openapi() -> Schema:
        if app.openapi_schema is None:
            app.openapi_schema = finish(build())
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
    app.state.contract = True  # the apps the tests hold to it (tests/problem_contract.py)

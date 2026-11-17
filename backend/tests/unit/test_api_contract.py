"""The spec is a contract SDKs are generated from (CR-007 R19.1, phase S1)."""

import json
import re
from typing import Any, get_args

import pytest
from pydantic import SecretStr

from agent_runtime.api import stream_schemas
from agent_runtime.api.app import create_app
from agent_runtime.api.problems import MEDIA_TYPE
from agent_runtime.config import Settings
from agent_runtime.runs.events import EventType
from agent_runtime.streaming.bus import TURN_STATUS_OF
from agent_runtime.subagents.store import ResultStatus, Status

METHODS = {"get", "put", "post", "patch", "delete"}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    app = create_app(Settings.model_construct(postgres_password=SecretStr("unused")))
    return app.openapi()


def operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (m, p, op) for p, item in spec["paths"].items() for m, op in item.items() if m in METHODS
    ]


def test_operation_ids_are_the_function_names_unique_and_snake_case(spec: dict[str, Any]) -> None:
    ids = [op["operationId"] for _, _, op in operations(spec)]
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", i) for i in ids), ids
    send = spec["paths"]["/sessions/{session_id}/messages"]["post"]
    assert send["operationId"] == "send_message"


def test_every_error_is_problem_details(spec: dict[str, Any]) -> None:
    text = json.dumps(spec)
    assert "HTTPValidationError" not in text  # FastAPI's 422 shape: the API never sends it
    for method, path, op in operations(spec):
        responses = op["responses"]
        assert "default" in responses, f"{method} {path}"
        for status, response in responses.items():
            if (path, status) == ("/readyz", "503"):
                continue  # a probe's answer: the same Health body, by design
            if status == "default" or int(status) >= 400:
                assert list(response["content"]) == [MEDIA_TYPE], f"{method} {path} {status}"
        if "422" in responses:
            ref = responses["422"]["content"][MEDIA_TYPE]["schema"]["$ref"]
            assert ref.endswith("/ValidationProblem"), f"{method} {path}"


def test_every_reference_resolves(spec: dict[str, Any]) -> None:
    names = set(spec["components"]["schemas"])
    refs = set(re.findall(r'"#/components/schemas/([^"]+)"', json.dumps(spec)))
    assert refs <= names, refs - names


def test_streams_are_typed(spec: dict[str, Any]) -> None:
    for path, event in (
        ("/runs/{run_id}/stream", "RunStreamEvent"),
        ("/sessions/{session_id}/stream", "SessionStreamEvent"),
    ):
        content = spec["paths"][path]["get"]["responses"]["200"]["content"]["text/event-stream"]
        data = content["itemSchema"]["properties"]["data"]["contentSchema"]
        assert {"$ref": f"#/components/schemas/{event}"} in data["oneOf"], path
    session = spec["components"]["schemas"]["SessionStreamEvent"]
    assert set(session["discriminator"]["mapping"]) == {
        "message.created", "token", "turn.status",
        "subagent.spawned", "subagent.progress", "subagent.completed",
    }  # fmt: skip


def test_the_schemas_enums_match_the_code() -> None:
    """A new run event, turn status or helper status needs its schema (and the reverse)."""
    assert {e.value for e in EventType} | {"token"} == stream_schemas.RUN_EVENT_TYPES
    assert {s.value for s in stream_schemas.TurnStatus} == set(TURN_STATUS_OF.values())
    assert {s.value for s in stream_schemas.HelperStatus} == set(get_args(Status))
    assert {s.value for s in stream_schemas.HelperResultStatus} == set(get_args(ResultStatus))

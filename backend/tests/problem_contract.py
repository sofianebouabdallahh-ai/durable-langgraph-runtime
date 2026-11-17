"""Every error the API sends in the tests is the error its spec declares (CR-007 R19.1).

Installed for the whole session by `conftest.py`: it wraps `httpx.ASGITransport`, which
every API test's client goes through, so no test can skip it. It checks the apps that
publish the contract (`api/contract.py`), not the fakes and small apps tests serve. An
error response must be:

- problem details (`application/problem+json`) that validate as `Problem`, or
  `ValidationProblem` for a 422;
- a status its operation declares, unless only the app's edges send it: the guard's 403
  and 421 and an unexpected 500, which `default: Problem` covers.

A failure names the operation and the status, in the test that caused it.
"""

from __future__ import annotations

import re
import weakref
from typing import Any

import httpx
from fastapi import FastAPI

from agent_runtime.api.problems import MEDIA_TYPE, Problem, ValidationProblem

EDGE_STATUSES = frozenset({403, 421, 500})  # middleware and the catch-all: `default`
_routes: weakref.WeakKeyDictionary[FastAPI, list[tuple[re.Pattern[str], str, dict[str, Any]]]]
_routes = weakref.WeakKeyDictionary()


def _segments(template: str) -> str:
    """`/skills/{skill_id}/files/{path}` → a regex; `{path}` may span slashes."""
    out, at = [], 0
    for m in re.finditer(r"\{([^/}]+)\}", template):
        out += [re.escape(template[at : m.start()]), ".+" if m.group(1) == "path" else "[^/]+"]
        at = m.end()
    return "".join([*out, re.escape(template[at:])])


def _operations(app: FastAPI) -> list[tuple[re.Pattern[str], str, dict[str, Any]]]:
    if app not in _routes:
        table = []
        for template, item in app.openapi().get("paths", {}).items():
            pattern = re.compile("^" + _segments(template) + "$")
            for method, operation in item.items():
                table.append((pattern, method.upper(), operation))
        # A literal segment beats a parameter (`/skills/upload` before `/skills/{skill_id}`).
        table.sort(key=lambda row: row[0].pattern.count("[^/]+") + row[0].pattern.count(".+"))
        _routes[app] = table
    return _routes[app]


def check(app: FastAPI, request: httpx.Request, response: httpx.Response) -> None:
    status = response.status_code
    if status < 400 or status in EDGE_STATUSES:
        return
    where = f"{request.method} {request.url.path} → {status}"
    media = response.headers.get("content-type", "").split(";")[0].strip()
    found = next(
        (op for pattern, method, op in _operations(app)
         if method == request.method and pattern.match(request.url.path)),
        None,
    )  # fmt: skip
    declared = found.get("responses", {}) if found else {}
    if media != MEDIA_TYPE and media in declared.get(str(status), {}).get("content", {}):
        return  # declared with a body of its own (`/readyz`'s 503 is its Health)
    assert media == MEDIA_TYPE, f"{where}: sent {media or 'no content type'}, not problem details"
    body = response.json()
    (ValidationProblem if status == 422 else Problem).model_validate(body)
    assert body["status"] == status, f"{where}: the problem says status {body['status']}"
    if found is None:
        return  # a path outside the spec (an unknown one gets Starlette's 404, as a problem)
    assert str(status) in declared, (
        f"{where}: {found['operationId']} doesn't declare {status} (declares {sorted(declared)})"
    )


def install() -> None:
    """Wrap `httpx.ASGITransport` for the session (idempotent)."""
    if getattr(httpx.ASGITransport, "_problem_contract", False):
        return
    original = httpx.ASGITransport.handle_async_request

    async def handle(self: httpx.ASGITransport, request: httpx.Request) -> httpx.Response:
        response = await original(self, request)
        app = self.app
        published = isinstance(app, FastAPI) and getattr(app.state, "contract", False)
        if published and response.status_code >= 400:  # Nuria's API, not a fake or test app
            assert isinstance(app, FastAPI)
            await response.aread()
            check(app, request, response)
        return response

    httpx.ASGITransport.handle_async_request = handle  # type: ignore[method-assign]
    httpx.ASGITransport._problem_contract = True  # type: ignore[attr-defined]

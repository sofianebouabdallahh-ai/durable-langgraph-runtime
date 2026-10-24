"""Operations commands for people running the stack: `runtime smoke`, `runtime doctor`.

- **smoke** proves the whole system works, the way a user would use it: through the
  API, a session, one chat turn, executed by the workers, with whatever model is
  configured. The scripted model must also use a tool through the tool pipeline: Run
  Python in the sandbox when there is one (so a broken sandbox shows here), else the
  calculator (the hidden `assistant` agent has it); a real model must give a non-empty
  answer. Exit 0 or a reason.
- **doctor** collects what a bug report needs (versions, service health, the
  effective configuration) with every secret redacted. Setup adds the services'
  logs and zips it; nothing is ever sent anywhere by this command.
"""

from __future__ import annotations

import asyncio
import json
import platform
import sys
import time
from dataclasses import dataclass, field
from importlib import metadata
from typing import Any

import httpx

from agent_runtime.config import Settings
from agent_runtime.redaction import redact

# The scripted check: (agent, its turn, what the tool must return).
SANDBOX_CHECK = (
    "chat",
    [{"tool_calls": [{"name": "run_python", "args": {"code": "print(6*7)"}}]},
     {"content": "The answer is 42."}],
    {"stdout": "42\n"},
)  # fmt: skip
CALCULATOR_CHECK = (
    "assistant",  # a hidden built-in: no sandbox needed, nothing saved
    [{"tool_calls": [{"name": "calculator", "args": {"expression": "6*7"}}]},
     {"content": "The answer is 42."}],
    {"value": 42.0},
)  # fmt: skip
REAL_PROMPT = "Reply with one short sentence confirming you are working."


class SmokeFailed(Exception):
    pass


@dataclass
class SmokeResult:
    session_id: str
    seconds: float
    answer: str
    steps: list[str] = field(default_factory=list)


async def wait_ready(
    client: httpx.AsyncClient, *, within_s: float = 30.0, interval_s: float = 1.0
) -> None:
    """`/readyz` answers 200, riding out a few seconds of 502-504 or refused
    connections: right after API replicas are recreated (a config change), the UI's
    proxy needs a moment to resolve their new addresses."""
    deadline = time.monotonic() + within_s
    while True:
        try:
            ready = await client.get("/readyz")
            if ready.status_code == 200:
                return
            problem = f"{ready.status_code}: {ready.text[:200]}"
            transient = ready.status_code in (502, 503, 504)
        except httpx.TransportError as exc:
            problem, transient = repr(exc), True
        if not transient or time.monotonic() >= deadline:
            raise SmokeFailed(f"the API isn't ready ({problem})")
        await asyncio.sleep(interval_s)


async def smoke(
    api: str,
    settings: Settings,
    *,
    timeout_s: float = 180.0,
    ui: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,  # tests
) -> SmokeResult:
    started = time.monotonic()
    scripted = settings.model_provider == "scripted"
    agent, script, expected = SANDBOX_CHECK if settings.sandboxd_url else CALCULATOR_CHECK
    if ui is not None:
        await check_ui(ui)
    async with httpx.AsyncClient(
        base_url=api.rstrip("/"), timeout=30, transport=transport
    ) as client:
        await wait_ready(client)
        # A default model chosen in the app (Settings → Models) answers instead of setup's:
        # then it's a real model's check, whatever setup chose.
        chosen = await client.get("/models/default")
        if chosen.status_code == 200 and (chosen.json() or {}).get("connection"):
            scripted = False
        created = await client.post(
            "/sessions", json={"agent": agent if scripted else "chat", "title": "smoke test"}
        )
        _require(created, 201, "create a session")
        sid = created.json()["id"]
        body: dict[str, Any] = {"content": "What is 6*7?" if scripted else REAL_PROMPT}
        if scripted:
            body["script"] = script
        sent = await client.post(f"/sessions/{sid}/messages", json=body)
        _require(sent, 202, "send a message")
        deadline = time.monotonic() + timeout_s
        while True:  # the turn is done once the session has no active run
            session = (await client.get(f"/sessions/{sid}")).json()
            if session["active_run_id"] is None:
                break
            if time.monotonic() > deadline:
                raise SmokeFailed(
                    f"the turn didn't finish within {timeout_s:.0f}s (status "
                    f"{session['active_run_status']}): are the workers running?"
                )
            await asyncio.sleep(0.5)
        messages = (await client.get(f"/sessions/{sid}/messages")).json()["messages"]
        # Setup's check isn't a conversation of the user's: keep it out of the chat list.
        await client.patch(f"/sessions/{sid}", json={"status": "archived"})
    kinds = [m["type"] for m in messages]
    if "error" in kinds:
        error = next(m["content"] for m in messages if m["type"] == "error")
        raise SmokeFailed(f"the turn failed: {error}")
    answer = next((m["content"]["text"] for m in reversed(messages) if m["type"] == "assistant"),
                  "")  # fmt: skip
    if not answer.strip():
        raise SmokeFailed(f"no answer from the model (messages: {kinds})")
    if scripted:
        results = [m["content"].get("result") or {} for m in messages
                   if m["type"] == "tool_result"]  # fmt: skip
        if len(results) != 1 or any(results[0].get(k) != v for k, v in expected.items()):
            what = "Run Python (the sandbox)" if agent == "chat" else "the calculator"
            raise SmokeFailed(f"{what} didn't run through the tool pipeline: {results}")
    return SmokeResult(sid, time.monotonic() - started, answer, kinds)


async def check_ui(url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
    """The web UI serves its page, with the security headers the chat relies on."""
    async with httpx.AsyncClient(timeout=10, transport=transport) as client:
        try:
            page = await client.get(url.rstrip("/") + "/")
        except httpx.HTTPError as exc:
            raise SmokeFailed(f"the UI isn't reachable at {url} ({type(exc).__name__})") from exc
    if page.status_code != 200 or 'id="root"' not in page.text:
        raise SmokeFailed(f"the UI didn't serve its page (HTTP {page.status_code})")
    csp = page.headers.get("content-security-policy", "")
    if "default-src 'self'" not in csp:
        raise SmokeFailed("the UI's Content-Security-Policy header is missing")


def _require(resp: httpx.Response, status: int, what: str) -> None:
    if resp.status_code != status:
        raise SmokeFailed(f"couldn't {what}: HTTP {resp.status_code} {resp.text[:300]}")


# ------------------------------------------------------------------- doctor

_SECRET_WORDS = ("password", "secret", "key", "token")


def redacted_settings(settings: Settings) -> dict[str, Any]:
    """The effective configuration, with every secret replaced (R14.12): SecretStr
    fields, anything named like a secret, and credentials inside URLs."""
    out: dict[str, Any] = {}
    for name, value in settings.model_dump().items():
        if any(word in name for word in _SECRET_WORDS):
            out[name] = "[REDACTED]" if value else None
        elif isinstance(value, str):
            out[name] = redact(value)
        else:
            out[name] = json.loads(json.dumps(value, default=str))
    return out


async def doctor(settings: Settings, api: str | None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "runtime": _version("durable-agent-runtime"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": {p: _version(p) for p in
                     ("langgraph", "langchain", "langchain-openai", "fastapi", "psycopg")},
        "config": redacted_settings(settings),
        "checks": {},
    }  # fmt: skip
    checks: dict[str, Any] = report["checks"]
    checks["postgres"] = await _check_postgres(settings)
    checks["redis"] = await _check_redis(settings)
    if api:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(api.rstrip("/") + "/readyz")
            checks["api"] = {"ok": r.status_code == 200, "status": r.status_code}
        except httpx.HTTPError as exc:
            checks["api"] = {"ok": False, "error": type(exc).__name__}
    report["ok"] = all(c.get("ok") for c in checks.values())
    return report


async def _check_postgres(settings: Settings) -> dict[str, Any]:
    import psycopg

    try:
        async with await psycopg.AsyncConnection.connect(
            settings.database_url("postgresql"), connect_timeout=5
        ) as conn:
            await conn.execute("SELECT 1")
            schema: str | None = "unknown (this login can't read alembic_version)"
            try:  # least-privilege logins (api, worker) may not read the migration table
                cur = await conn.execute("SELECT version_num FROM alembic_version")
                row = await cur.fetchone()
                schema = row[0] if row else None
            except psycopg.errors.InsufficientPrivilege:
                pass
        return {"ok": True, "user": settings.postgres_user, "schema": schema}
    except Exception as exc:  # report, never raise: this is a diagnostic
        return {"ok": False, "error": redact(f"{type(exc).__name__}: {exc}")[:300]}


async def _check_redis(settings: Settings) -> dict[str, Any]:
    from redis.asyncio import Redis

    client = Redis.from_url(settings.redis_url, socket_connect_timeout=5)
    try:
        await client.ping()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": redact(f"{type(exc).__name__}: {exc}")[:300]}
    finally:
        await client.aclose()


def _version(package: str) -> str | None:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None

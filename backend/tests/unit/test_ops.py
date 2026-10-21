"""`runtime doctor` never reveals a secret (SC9, R14.12)."""

import json

import httpx
import pytest
from pydantic import SecretStr

from agent_runtime.config import Settings
from agent_runtime.ops import redacted_settings

PASSWORD = "pw-" + "Zq8vT1rK9mX2"  # assembled at runtime: no secret scanner hit
API_KEY = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2"
URL_PASS = "hunter" + "2-very-secret"


def test_the_effective_configuration_is_redacted() -> None:
    settings = Settings(
        postgres_password=SecretStr(PASSWORD),
        openai_api_key=SecretStr(API_KEY),
        redis_url=f"redis://default:{URL_PASS}@cache:6379/0",
        ollama_base_url="http://127.0.0.1:11434/v1",
    )
    report = json.dumps(redacted_settings(settings))
    for secret in (PASSWORD, API_KEY, URL_PASS):
        assert secret not in report
    shown = redacted_settings(settings)
    assert shown["postgres_password"] == "[REDACTED]" and shown["openai_api_key"] == "[REDACTED]"
    assert shown["redis_url"] == "redis://[REDACTED]@cache:6379/0"
    assert shown["ollama_base_url"] == "http://127.0.0.1:11434/v1"  # non-secrets stay readable
    assert shown["model_provider"] == "scripted"


async def test_the_ui_check_wants_the_page_and_its_csp() -> None:
    import httpx
    import pytest

    from agent_runtime.ops import SmokeFailed, check_ui

    def serve(body: str, csp: str | None, status: int = 200) -> httpx.MockTransport:
        headers = {"content-security-policy": csp} if csp else {}
        return httpx.MockTransport(lambda _: httpx.Response(status, text=body, headers=headers))

    page = '<div id="root"></div>'
    await check_ui("http://ui", serve(page, "default-src 'self'; img-src 'self'"))
    with pytest.raises(SmokeFailed, match="Content-Security-Policy"):
        await check_ui("http://ui", serve(page, None))
    with pytest.raises(SmokeFailed, match="didn't serve its page"):
        await check_ui("http://ui", serve("<html>nginx default</html>", "default-src 'self'"))
    with pytest.raises(SmokeFailed, match="HTTP 502"):
        await check_ui("http://ui", serve("bad gateway", None, 502))


async def test_smoke_waits_out_a_moment_of_502_then_succeeds() -> None:
    from agent_runtime.ops import wait_ready

    answers = iter([502, 503, 200])
    transport = httpx.MockTransport(lambda _: httpx.Response(next(answers)))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
        await wait_ready(client, within_s=5, interval_s=0)


async def test_smoke_gives_up_on_a_real_failure_or_after_the_deadline() -> None:
    from agent_runtime.ops import SmokeFailed, wait_ready

    def answer(code: int) -> httpx.MockTransport:
        return httpx.MockTransport(lambda _: httpx.Response(code, text="nope"))

    async with httpx.AsyncClient(transport=answer(500), base_url="http://api") as client:
        with pytest.raises(SmokeFailed, match="500"):  # not transient: at once
            await wait_ready(client, within_s=60, interval_s=0)
    async with httpx.AsyncClient(transport=answer(502), base_url="http://api") as client:
        with pytest.raises(SmokeFailed, match="502"):
            await wait_ready(client, within_s=0, interval_s=0)


@pytest.mark.parametrize(
    ("sandbox", "agent", "tool", "returned"),
    [
        ("http://sandboxd:8070", "chat", "run_python", {"stdout": "42\n", "exit_code": 0}),
        ("", "assistant", "calculator", {"value": 42.0}),
    ],
)
async def test_the_scripted_smoke_checks_the_sandbox_when_there_is_one(
    sandbox: str, agent: str, tool: str, returned: dict[str, object]
) -> None:
    """With a sandbox, setup's check runs Python in it (a broken sandbox shows at setup);
    without one (--no-sandbox), the calculator, on a hidden agent: nothing saved."""
    import json

    from agent_runtime.config import Settings
    from agent_runtime.ops import SmokeFailed, smoke

    sent: list[dict[str, object]] = []

    def api(result: dict[str, object]) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if request.method == "POST" and path == "/sessions":
                sent.append(json.loads(request.content))
                return httpx.Response(201, json={"id": "s1"})
            if request.method == "POST" and path.endswith("/messages"):
                sent.append(json.loads(request.content))
                return httpx.Response(202, json={"run_id": "r1"})
            if path == "/sessions/s1":
                return httpx.Response(200, json={"active_run_id": None})
            if path.endswith("/messages"):
                return httpx.Response(200, json={"messages": [
                    {"type": "user", "content": {"text": "What is 6*7?"}},
                    {"type": "tool_call", "content": {"tool": tool}},
                    {"type": "tool_result", "content": {"tool": tool, "result": result}},
                    {"type": "assistant", "content": {"text": "The answer is 42."}},
                ]})  # fmt: skip
            return httpx.Response(200, json={})

        return httpx.MockTransport(handle)

    settings = Settings(postgres_password="pw", model_provider="scripted", sandboxd_url=sandbox)  # type: ignore[arg-type]
    done = await smoke("http://api", settings, transport=api(returned))
    assert done.answer == "The answer is 42."
    assert sent[0]["agent"] == agent
    assert sent[1]["script"][0]["tool_calls"][0]["name"] == tool  # type: ignore[index]
    with pytest.raises(SmokeFailed, match="didn't run through the tool pipeline"):
        await smoke("http://api", settings, transport=api({"error": "no"}))


async def test_a_default_model_chosen_in_the_app_gets_the_real_models_check() -> None:
    """Setup said demo, but Settings → Models has a default: that model answers, so the
    check is a real model's (an answer), not the scripted tool turn."""
    import json

    from agent_runtime.config import Settings
    from agent_runtime.ops import REAL_PROMPT, smoke

    sent: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/models/default":
            return httpx.Response(200, json={"connection": {"id": "c"}, "model": "gpt"})
        if request.method == "POST":
            sent.append(json.loads(request.content))
            return httpx.Response(201 if path == "/sessions" else 202, json={"id": "s1"})
        if path == "/sessions/s1":
            return httpx.Response(200, json={"active_run_id": None})
        if path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [
                {"type": "assistant", "content": {"text": "I'm working."}}]})  # fmt: skip
        return httpx.Response(200, json={})

    settings = Settings(postgres_password="pw", model_provider="scripted")  # type: ignore[arg-type]
    done = await smoke("http://api", settings, transport=httpx.MockTransport(handle))
    assert done.answer == "I'm working."
    assert sent[0]["agent"] == "chat" and sent[1] == {"content": REAL_PROMPT}

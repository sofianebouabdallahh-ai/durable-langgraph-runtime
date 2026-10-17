"""`runtime doctor` never reveals a secret (SC9, R14.12)."""

import json

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

"""A local model gets longer per call than a cloud one: its first call loads it."""

import pytest
from pydantic import SecretStr

from agent_runtime.config import Settings
from agent_runtime.models.connections import any_local
from agent_runtime.models.provider import call_timeout_s, configured_provider, is_local
from agent_runtime.runs.limits import local_model_limits


@pytest.mark.parametrize(
    ("url", "local"),
    [
        ("http://host.docker.internal:11434/v1", True),  # Ollama on the host (macOS, Windows)
        ("http://ollama:11434/v1", True),  # the stack's own Ollama
        ("http://localhost:1234/v1", True),  # LM Studio
        ("http://127.0.0.1:8000/v1", True),
        ("http://192.168.1.20:8000/v1", True),  # a model server at home
        ("http://gpu-box.local:8000/v1", True),
        ("http://my-server:11434/v1", True),  # Ollama's port, wherever it is
        ("https://api.openai.com/v1", False),
        ("https://my-foundry.openai.azure.com/openai/v1", False),
        ("https://8.8.8.8/v1", False),
    ],
)
def test_where_a_model_runs(url: str, local: bool) -> None:
    assert is_local(url) is local


def test_the_call_limit_follows_where_the_model_runs() -> None:
    s = Settings(postgres_password="pw", model_timeout_s=60, local_model_timeout_s=300)  # type: ignore[arg-type]
    assert call_timeout_s("ollama", "http://anywhere/v1", s) == 300
    assert call_timeout_s("compatible", "http://host.docker.internal:11434/v1", s) == 300
    assert call_timeout_s("openai", "https://api.openai.com/v1", s) == 60


def test_setups_own_model_gets_the_local_limit_when_it_is_local() -> None:
    """`./setup.sh --model compatible --base-url http://host.docker.internal:11434/v1`
    is configured as OpenAI-compatible: the address says it's local."""
    local = Settings(postgres_password="pw", model_provider="openai",  # type: ignore[arg-type]
                     openai_api_key=SecretStr("x"),
                     openai_base_url="http://host.docker.internal:11434/v1")  # fmt: skip
    cloud = Settings(postgres_password="pw", model_provider="openai",  # type: ignore[arg-type]
                     openai_api_key=SecretStr("x"))  # fmt: skip
    assert configured_provider(local).timeout_s == local.local_model_timeout_s  # type: ignore[attr-defined]
    assert configured_provider(cloud).timeout_s == cloud.model_timeout_s  # type: ignore[attr-defined]


def test_a_turn_on_a_local_model_gets_longer_never_past_the_run_ceiling() -> None:
    s = Settings(postgres_password="pw", local_turn_timeout_s=900, run_timeout_s=1200)  # type: ignore[arg-type]
    assert local_model_limits({"timeout_s": 120, "max_steps": 8}, s) == {
        "timeout_s": 900, "max_steps": 8}  # fmt: skip
    assert local_model_limits({"timeout_s": 1000}, s)["timeout_s"] == 1000  # already longer
    tight = Settings(postgres_password="pw", local_turn_timeout_s=900, run_timeout_s=600)  # type: ignore[arg-type]
    assert local_model_limits({"timeout_s": 120}, tight)["timeout_s"] == 600


def test_which_bindings_are_local() -> None:
    assert any_local({"default": {"local": False}, "cheap": {"local": True}})
    assert not any_local({"default": {"local": False}})
    assert not any_local({"default": {"connection_id": "c1"}})  # a run from before L8
    assert not any_local(None)

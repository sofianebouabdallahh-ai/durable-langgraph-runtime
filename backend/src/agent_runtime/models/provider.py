"""ModelProvider (R3.1): which chat and embedding models a run uses.

Pattern: Ports & Adapters. Agent definitions name a model *role* (`model: chat`,
`researcher`, …); the provider maps the role to a concrete model:

- `scripted` (default; tests, CI, demos): the ScriptedChatModel, driven by the
  run's script. No network, no key.
- `openai`: the OpenAI API (`OPENAI_API_KEY`).
- `ollama`: a local Ollama server through its OpenAI-compatible API (`/v1`), so
  one adapter serves both. Keyless.

The runtime owns retries (`ModelCaller`, R14.7), so the SDK's own are off, and
it streams (tokens become transient `token` events) with usage reported in the
stream (`stream_usage`), which is what the budget counts. Max output tokens per
call: R14.5 (4 096).
"""

from __future__ import annotations

import hashlib
import ipaddress
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from typing import TYPE_CHECKING, Any, Literal, Protocol
from urllib.parse import urlparse

from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

from agent_runtime.models.scripted import ScriptedChatModel, ScriptTurn

if TYPE_CHECKING:
    from langchain_openai import ChatOpenAI

    from agent_runtime.config import Settings

ProviderName = Literal["scripted", "openai", "ollama"]

DEFAULT_MODELS: dict[str, dict[str, str]] = {
    "openai": {"default": "gpt-4o-mini", "embed": "text-embedding-3-small"},
    "ollama": {"default": "qwen2.5:7b", "embed": "nomic-embed-text"},
}
MAX_OUTPUT_TOKENS = 4096  # R14.5
EMBED_DIM = 768  # matches the chunks table (migration 0001)


class ModelProvider(Protocol):
    name: str

    def chat(
        self, role: str, *, temperature: float, script: list[ScriptTurn], offset: int
    ) -> BaseChatModel:
        """The chat model for one call. `script`/`offset` matter to the scripted one."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class ScriptedProvider:
    name: str = "scripted"
    streaming: bool = False  # SCRIPTED_STREAMING: exercise token streaming in tests
    stream_delay_s: float = 0.0

    def chat(
        self, role: str, *, temperature: float, script: list[ScriptTurn], offset: int
    ) -> BaseChatModel:
        if self.streaming:
            return ScriptedChatModel(script=script, offset=offset, streaming=True,
                                     stream_delay_s=self.stream_delay_s)  # fmt: skip
        return ScriptedChatModel(script=script, offset=offset)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Deterministic pseudo-embeddings (hashed character trigrams), for tests."""
        return [_hashed(t) for t in texts]


_REASONING_KEYS = ("reasoning_content", "reasoning")  # DeepSeek-style; Ollama, vLLM, others


def _reasoning_of(message: Any) -> str | None:
    """A provider's reasoning text, from a choice's message or a streamed delta."""
    found = message if isinstance(message, dict) else getattr(message, "model_extra", None) or {}
    for key in _REASONING_KEYS:
        value = found.get(key) if isinstance(found, dict) else None
        if isinstance(value, str) and value:
            return value
    return None


@cache
def _reasoning_chat_openai() -> type[ChatOpenAI]:
    """ChatOpenAI that keeps a provider's reasoning (`reasoning_content` / `reasoning`):
    langchain-openai leaves these non-standard fields out. It lands in the message's
    `additional_kwargs["reasoning"]`, where the transcript records it (L6: a chat's
    download shows how the agent thought, not only what it did)."""
    from langchain_openai import ChatOpenAI

    class ReasoningChatOpenAI(ChatOpenAI):
        def _create_chat_result(self, response: Any, generation_info: Any = None) -> Any:
            result = super()._create_chat_result(response, generation_info)
            raw = response if isinstance(response, dict) else response.model_dump()
            choices = raw.get("choices") or []
            for generation, choice in zip(result.generations, choices, strict=False):
                text = _reasoning_of(choice.get("message") or {})
                if text:
                    generation.message.additional_kwargs["reasoning"] = text
            return result

        def _convert_chunk_to_generation_chunk(
            self, chunk: dict[str, Any], default_chunk_class: type, base_generation_info: Any
        ) -> Any:
            generation = super()._convert_chunk_to_generation_chunk(
                chunk, default_chunk_class, base_generation_info
            )
            choices = chunk.get("choices") or []
            text = _reasoning_of((choices[0].get("delta") or {}) if choices else {})
            if generation is not None and text:
                generation.message.additional_kwargs["reasoning"] = text  # chunks concatenate
            return generation

    return ReasoningChatOpenAI


@dataclass
class OpenAICompatibleProvider:
    """OpenAI, or anything speaking its API (Ollama's `/v1`)."""

    name: str
    base_url: str
    api_key: SecretStr  # kept wrapped: never printable, never logged
    models: dict[str, str]  # role → model; "default" for unlisted roles; "embed"
    timeout_s: float = 60.0  # R14.5: model call timeout
    _cache: dict[tuple[str, float], BaseChatModel] = field(default_factory=dict)

    def model_for(self, role: str) -> str:
        return self.models.get(role) or self.models["default"]

    def chat(
        self, role: str, *, temperature: float, script: list[ScriptTurn], offset: int
    ) -> BaseChatModel:
        key = (role, temperature)
        if key not in self._cache:  # the client holds a connection pool: reuse it
            self._cache[key] = _reasoning_chat_openai()(
                model=self.model_for(role), base_url=self.base_url, api_key=self.api_key,
                temperature=temperature, max_completion_tokens=MAX_OUTPUT_TOKENS,
                timeout=self.timeout_s, max_retries=0, streaming=True, stream_usage=True,
            )  # fmt: skip
        return self._cache[key]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from langchain_openai import OpenAIEmbeddings

        embedder = OpenAIEmbeddings(
            model=self.models["embed"], base_url=self.base_url, api_key=self.api_key,
            check_embedding_ctx_length=False,  # plain strings: Ollama doesn't take tokens
        )  # fmt: skip
        return await embedder.aembed_documents(texts)


def _hashed(text: str, dim: int = EMBED_DIM) -> list[float]:
    vec = [0.0] * dim
    t = f"  {text.lower()}  "
    for i in range(len(t) - 2):
        h = int.from_bytes(hashlib.blake2b(t[i : i + 3].encode(), digest_size=4).digest())
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


ProviderFactory = Callable[[], ModelProvider]

# Where a model runs on this machine (or the stack's own Ollama), as the containers see it.
LOCAL_HOSTS = frozenset({"localhost", "host.docker.internal", "ollama"})


def is_local(base_url: str) -> bool:
    """A model on this machine or this network (Ollama, LM Studio, vLLM at home), rather
    than a cloud service: by the address it's reached at."""
    url = urlparse(base_url)
    host = (url.hostname or "").lower()
    if host in LOCAL_HOSTS or host.endswith(".local") or url.port == 11434:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def call_timeout_s(kind: str, base_url: str, settings: Settings) -> float:
    """One model call's time limit: longer for a local model (see Settings)."""
    local = kind == "ollama" or is_local(base_url)
    return settings.local_model_timeout_s if local else settings.model_timeout_s


def provider_from(
    name: ProviderName,
    *,
    openai_api_key: SecretStr | None,
    openai_base_url: str,
    ollama_base_url: str,
    role_models: dict[str, str],
    scripted_streaming: bool = False,
    stream_delay_s: float = 0.0,
    timeout_s: float = 60.0,
) -> ModelProvider:
    """Build the configured provider. Role models override the provider's defaults."""
    if name == "scripted":
        return ScriptedProvider(streaming=scripted_streaming, stream_delay_s=stream_delay_s)
    models = DEFAULT_MODELS[name] | {r: m for r, m in role_models.items() if m}
    if name == "openai":
        if not openai_api_key:
            raise ValueError("MODEL_PROVIDER=openai needs OPENAI_API_KEY")
        return OpenAICompatibleProvider("openai", openai_base_url, openai_api_key, models,
                                        timeout_s=timeout_s)  # fmt: skip
    return OpenAICompatibleProvider("ollama", ollama_base_url, SecretStr("ollama"), models,
                                    timeout_s=timeout_s)  # fmt: skip


_PROVIDERS: dict[tuple[object, ...], ModelProvider] = {}


def configured_provider(settings: Settings) -> ModelProvider:
    """The provider these settings select; one per process (clients pool connections)."""
    roles = {"chat": settings.model_chat, "planner": settings.model_planner,
             "researcher": settings.model_researcher, "critic": settings.model_critic,
             "synthesizer": settings.model_synthesizer, "embed": settings.model_embed}  # fmt: skip
    key = (settings.model_provider, settings.openai_base_url, settings.ollama_base_url,
           tuple(sorted(roles.items())), settings.scripted_streaming,
           settings.scripted_stream_delay_s)  # fmt: skip
    if key not in _PROVIDERS:
        base_url = (settings.ollama_base_url if settings.model_provider == "ollama"
                    else settings.openai_base_url)  # fmt: skip
        _PROVIDERS[key] = provider_from(
            settings.model_provider, openai_api_key=settings.openai_api_key,
            openai_base_url=settings.openai_base_url, ollama_base_url=settings.ollama_base_url,
            role_models=roles, scripted_streaming=settings.scripted_streaming,
            stream_delay_s=settings.scripted_stream_delay_s,
            timeout_s=call_timeout_s(settings.model_provider, base_url, settings),
        )  # fmt: skip
    return _PROVIDERS[key]

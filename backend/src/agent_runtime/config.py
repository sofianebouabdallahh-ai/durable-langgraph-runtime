"""Runtime configuration (R9.1).

Settings come from environment variables only. Nothing reads a .env file here:
Compose injects .env through `env_file`, Kubernetes through a ConfigMap and a
Secret (R10.4), and the Makefile exports it for local commands. One model, several
delivery mechanisms.

Settings are added in the phase that first needs them, so each field has a reason
to exist. LLM provider settings arrive with ModelProvider (phase 6).
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_ONLY = SettingsConfigDict(
    env_file=None,  # environment only (R9.1)
    case_sensitive=False,
    extra="ignore",
)


class ModelPrice(BaseModel):
    input_per_mtok: float = Field(ge=0)
    output_per_mtok: float = Field(ge=0)

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok) / 1e6


class AgentSettings(BaseSettings):
    """What loading and validating agent definitions needs, and nothing more.

    Interface segregation: `runtime agents validate` (in CI, on a laptop) must
    not require database credentials just to read Markdown files.
    """

    model_config = _ENV_ONLY

    # Run limits (R1.7, R2.8, R2.9)
    run_timeout_s: int = Field(default=20 * 60, gt=0)
    run_max_steps: int = Field(default=200, gt=0)
    run_max_children: int = Field(default=6, gt=0)  # per fan-out (R2.9); options may lower it
    run_max_depth: int = Field(default=2, ge=0)  # parent → child → grandchild (R14.6)
    run_max_descendants: int = Field(default=20, gt=0)  # per root run (R14.6)
    queue_depth_limit: int = Field(default=100, gt=0)  # at this many queued, POST /runs → 429
    queue_depth_cache_s: float = Field(default=1.0, ge=0)  # per API replica
    overload_retry_after_s: int = Field(default=5, gt=0)  # the 429's Retry-After

    # Server ceilings (R14.3): agent profiles and per-run options may only go below these.
    # Wall-clock and steps ceilings are run_timeout_s and run_max_steps above.
    ceiling_model_calls: int = Field(default=100, gt=0)
    ceiling_tool_calls: int = Field(default=100, gt=0)
    ceiling_tokens: int = Field(default=1_000_000, gt=0)
    ceiling_cost_usd: float = Field(default=2.0, gt=0)
    # A Studio test chat's budget (CR-006 R17.3): the draft's own limits, tightened to these.
    playground_timeout_s: int = Field(default=180, gt=0)
    playground_model_calls: int = Field(default=20, gt=0)
    playground_tool_calls: int = Field(default=20, gt=0)
    playground_cost_usd: float = Field(default=0.25, gt=0)
    # R14.2: at this share of any budget the agent gets one wrap-up turn.
    soft_limit_ratio: float = Field(default=0.8, gt=0, lt=1)

    # Agent definitions (R15.1): one folder per agent, relative to the working directory.
    agents_dir: Path = Path("agents")
    # Built-in skills (CR-006 R17.4): one Agent Skills folder each, reviewed like code.
    skills_dir: Path = Path("skills")
    # The fixture search tool's data (R3.3), relative to the working directory.
    search_fixtures_dir: Path = Path("fixtures/search")


class Settings(AgentSettings):
    """Full runtime configuration: everything in AgentSettings plus services."""

    model_config = _ENV_ONLY

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # JSON lines carry run_id, epoch and trace_id (R7.1); text is for a terminal.
    log_format: Literal["json", "text"] = "text"

    # Observability (R7.1, R7.2). Tracing is on only when an OTLP endpoint is set:
    # with none, OpenTelemetry stays a no-op and the stack pays nothing (L4a SC4).
    otel_exporter_otlp_endpoint: str = ""  # e.g. http://otel-collector:4318
    # Links the UI shows, when observability is on (browser-facing URLs, not secrets).
    trace_ui_url: str = ""  # Grafana: a run's trace (Tempo) and log lines (Loki) open in Explore
    dashboard_url: str = ""  # Grafana
    # The worker's /healthz /readyz /metrics. 0 = off (the default: several workers share
    # a host in development); containers set 8081, one worker process each.
    worker_health_port: int = Field(default=0, ge=0)
    worker_liveness_s: float = Field(default=30.0, gt=0)  # the main loop must tick within this

    # Postgres: the only source of truth. Split into parts rather than one URL so
    # the password can live in a Secret and the rest in a ConfigMap (R10.4).
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "agent_runtime"
    postgres_user: str = "agent"
    postgres_password: SecretStr  # required: no default, so no secret is baked in

    # Redis: work stream and pub/sub. Holds nothing that can't be rebuilt.
    redis_url: str = "redis://localhost:6379/0"
    work_stream: str = "runs:work"  # R2.1
    work_group: str = "workers"

    # Workers (R2.2, R10.7)
    worker_concurrency: int = Field(default=4, gt=0)  # runs in flight per worker process
    worker_block_ms: int = Field(default=2000, gt=0)  # XREADGROUP BLOCK: how long a read waits
    worker_grace_s: float = Field(default=50.0, gt=0)  # drain budget; < k8s terminationGrace (60)
    relay_interval_s: float = Field(default=10.0, gt=0)  # outbox relay sweep period
    session_idle_ttl_s: float = Field(default=24 * 3600, gt=0)  # then archived (R15.6)
    session_sweep_s: float = Field(default=60.0, gt=0)  # how often workers look for idle ones
    relay_stale_s: float = Field(default=30.0, gt=0)  # re-send a queued run's message after this

    # Streaming (R2.5, §5). Pub/Sub is only a wake-up hint; Postgres is the record.
    stream_ping_s: float = Field(default=15.0, gt=0)  # SSE keep-alive comment (§5)
    stream_poll_s: float = Field(default=15.0, gt=0)  # safety-net poll when no live event
    stream_queue_size: int = Field(default=1000, gt=0)  # per stream; overflow → catch up from DB
    stream_live_enabled: bool = True  # False = no Pub/Sub (AC3 demo: the stream stalls)
    api_grace_s: float = Field(default=25.0, gt=0)  # drain open streams on SIGTERM (R10.7)

    # Kill switch / admin endpoints (R14.18): internal only, never routed by the Ingress.
    admin_api_enabled: bool = True

    # The master key for saved model keys (Settings → Models, R18.3). Generated by setup.
    nuria_secret_key: SecretStr | None = None

    # Web tools (L6a). Search: SearXNG in the stack unless Settings → Tools picks a keyed
    # provider. Pages: read by the `fetcher` service (the only one tools reach the web
    # through); empty: read in-process, with the same guard.
    searxng_url: str = "http://searxng:8080"
    fetcher_url: str = ""
    # Code and shell (L6b): sandboxd, the one service that starts containers, and the token
    # workers use to call it (generated by setup). Empty URL: the code tools are off.
    sandboxd_url: str = ""
    sandboxd_token: SecretStr | None = None
    # Host names the page reader lets through although they're private. Tests only (the
    # fake web in the test profile); never set in a real install.
    fetch_allow_hosts: str = ""

    # Models (R3.1, R14.1, R14.7)
    model_provider: Literal["scripted", "openai", "ollama"] = "scripted"  # CI: keyless
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    ollama_base_url: str = "http://127.0.0.1:11434/v1"
    # Model per role (agent files say `model: <role>`); empty: the provider's default.
    model_chat: str = ""
    model_planner: str = ""
    model_researcher: str = ""
    model_critic: str = ""
    model_synthesizer: str = ""
    model_embed: str = ""
    token_flush_ms: int = Field(default=20, gt=0)  # coalesce streamed tokens (R12.3)
    scripted_streaming: bool = False  # the scripted model streams word by word (tests)
    scripted_stream_delay_s: float = Field(default=0.0, ge=0)  # per streamed word (tests)
    # USD per million tokens, by model name; models not listed cost 0.
    model_prices: dict[str, ModelPrice] = Field(
        default_factory=lambda: {"scripted": ModelPrice(input_per_mtok=0, output_per_mtok=0)}
    )
    # One model call's time limit (R14.5). A local model (Ollama, or any model on this
    # machine or network) gets longer: its first call after a while loads it into memory,
    # which on a busy laptop takes minutes, and it generates more slowly.
    model_timeout_s: float = Field(default=60.0, gt=0)
    local_model_timeout_s: float = Field(default=300.0, gt=0)
    mcp_timeout_s: float = Field(default=60.0, gt=0)  # one call to an MCP server (L8)
    model_retry_attempts: int = Field(default=3, ge=1, le=5)  # every attempt is charged
    model_retry_base_s: float = Field(default=1.0, gt=0)
    model_retry_cap_s: float = Field(default=20.0, gt=0)
    breaker_failures: int = Field(default=5, gt=0)  # this many in breaker_window_s → open
    breaker_window_s: float = Field(default=30.0, gt=0)
    breaker_open_s: float = Field(default=30.0, gt=0)

    # Admission control (R14.8)
    session_messages_per_minute: int = Field(default=10, gt=0)
    global_daily_cost_usd: float | None = Field(default=None, gt=0)  # None: no ceiling

    # Sub-agents per run (CR-005 R16.3): configurable down only (R14.3)
    subagent_max_parallel: int = Field(default=4, gt=0, le=4)
    subagent_max_total: int = Field(default=10, gt=0, le=10)
    subagent_timeout_s: int = Field(default=180, gt=0)  # when the sub-agent's file sets none

    # Leases and reclaim (R2.3, R2.4)
    lease_ttl_s: float = Field(default=30.0, gt=0)
    heartbeat_s: float = Field(default=10.0, gt=0)
    # How often a worker checks whether its run was stopped (Stop, the kill switch): the
    # step in progress is cut off within this, not only between steps.
    cancel_poll_s: float = Field(default=1.0, gt=0)
    reaper_interval_s: float = Field(default=5.0, gt=0)
    max_reclaims: int = Field(default=3, ge=0)

    @model_validator(mode="after")
    def _heartbeat_fits_in_lease(self) -> Self:
        # R2.3: heartbeat every ttl/3, so two heartbeats can be missed (a GC pause,
        # a slow network) before the lease expires and another worker reclaims the run.
        if self.heartbeat_s > self.lease_ttl_s / 3:
            raise ValueError(
                f"heartbeat_s ({self.heartbeat_s}) must be <= lease_ttl_s / 3 "
                f"({self.lease_ttl_s / 3:.1f})"
            )
        return self

    def for_component(self, component: str) -> Self:
        """These settings, connecting as `component`'s own least-privilege user.

        Fails fast if that user isn't configured: a long-running service must
        never silently fall back to the migrator's (schema owner's) credentials.
        """
        creds = component_credentials(component)
        if creds is None:
            prefix = component.upper()
            raise ValueError(
                f"{prefix}_POSTGRES_USER and {prefix}_POSTGRES_PASSWORD must be set "
                f"(least-privilege database user for the {component}, R14.13)"
            )
        return self.model_copy(
            update={"postgres_user": creds.user, "postgres_password": creds.password}
        )

    def database_url(self, driver: str = "postgresql+psycopg") -> str:
        """SQLAlchemy URL. Contains the password: never log it."""
        password = self.postgres_password.get_secret_value()
        return (
            f"{driver}://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


class DbCredentials(BaseSettings):
    """One component's own database login (R14.13), read from
    `<COMPONENT>_POSTGRES_USER` / `<COMPONENT>_POSTGRES_PASSWORD`."""

    model_config = _ENV_ONLY

    user: str
    password: SecretStr


def component_credentials(component: str) -> DbCredentials | None:
    """Credentials for `component` (api, worker, …), or None if not configured."""
    prefix = f"{component.upper()}_POSTGRES_"
    try:
        return DbCredentials(_env_prefix=prefix)  # type: ignore[call-arg]
    except ValidationError:
        return None


@lru_cache
def get_agent_settings() -> AgentSettings:
    return AgentSettings()


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings, read once from the environment."""
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment

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

from pydantic import Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_ONLY = SettingsConfigDict(
    env_file=None,  # environment only (R9.1)
    case_sensitive=False,
    extra="ignore",
)


class AgentSettings(BaseSettings):
    """What loading and validating agent definitions needs, and nothing more.

    Interface segregation: `runtime agents validate` (in CI, on a laptop) must
    not require database credentials just to read Markdown files.
    """

    model_config = _ENV_ONLY

    # Run limits (R1.7, R2.8, R2.9)
    run_timeout_s: int = Field(default=20 * 60, gt=0)
    run_max_steps: int = Field(default=200, gt=0)
    run_max_children: int = Field(default=6, gt=0)
    queue_depth_limit: int = Field(default=100, gt=0)  # above this, POST /runs returns 429

    # Server ceilings (R14.3): agent profiles and per-run options may only go below these.
    # Wall-clock and steps ceilings are run_timeout_s and run_max_steps above.
    ceiling_model_calls: int = Field(default=100, gt=0)
    ceiling_tool_calls: int = Field(default=100, gt=0)
    ceiling_tokens: int = Field(default=1_000_000, gt=0)
    ceiling_cost_usd: float = Field(default=2.0, gt=0)

    # Agent definitions (R15.1): one folder per agent, relative to the working directory.
    agents_dir: Path = Path("agents")


class Settings(AgentSettings):
    """Full runtime configuration: everything in AgentSettings plus services."""

    model_config = _ENV_ONLY

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

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
    relay_stale_s: float = Field(default=30.0, gt=0)  # re-send a queued run's message after this

    # Kill switch / admin endpoints (R14.18): internal only, never routed by the Ingress.
    admin_api_enabled: bool = True

    # Leases and reclaim (R2.3, R2.4)
    lease_ttl_s: float = Field(default=30.0, gt=0)
    heartbeat_s: float = Field(default=10.0, gt=0)
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

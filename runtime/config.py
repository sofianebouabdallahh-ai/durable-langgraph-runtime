"""Runtime configuration (R9.1).

Settings come from environment variables only. Nothing reads a .env file here:
Compose injects .env through `env_file`, Kubernetes through a ConfigMap and a
Secret (R10.4), and the Makefile exports it for local commands. One model, several
delivery mechanisms.

Settings are added in the phase that first needs them, so each field has a reason
to exist. LLM provider settings arrive with ModelProvider (phase 6).
"""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,  # environment only (R9.1)
        case_sensitive=False,
        extra="ignore",
    )

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

    # Run limits (R1.7, R2.8, R2.9)
    run_timeout_s: int = Field(default=20 * 60, gt=0)
    run_max_steps: int = Field(default=200, gt=0)
    run_max_children: int = Field(default=6, gt=0)
    queue_depth_limit: int = Field(default=100, gt=0)  # above this, POST /runs returns 429

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

    def database_url(self, driver: str = "postgresql+psycopg") -> str:
        """SQLAlchemy URL. Contains the password: never log it."""
        password = self.postgres_password.get_secret_value()
        return (
            f"{driver}://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings, read once from the environment."""
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment

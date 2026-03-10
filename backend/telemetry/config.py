"""Telemetry configuration utilities."""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TelemetrySettings(BaseSettings):
    """Runtime configuration for telemetry services."""

    model_config = SettingsConfigDict(
        env_prefix="TELEMETRY_",
        case_sensitive=False,
    )

    database_url: str = Field(
        "postgresql+asyncpg://postgres:password@localhost:5432/omniference",
        description="SQLAlchemy async connection URL targeting TimescaleDB.",
    )
    db_echo: bool = Field(
        False,
        description="Enable SQLAlchemy engine echo for debugging.",
    )
    db_schema: str = Field(
        "public",
        description="Database schema for telemetry tables.",
    )
    redis_url: Optional[str] = Field(
        default=None,
        description="Redis connection string for pub/sub. Optional for MVP.",
    )
    metrics_retention_days: int = Field(
        30,
        description="Default retention policy for gpu_metrics hypertable (days).",
        ge=1,
    )
    credential_secret_key: str = Field(
        "CHANGE_ME",
        description="Secret material used to derive encryption key for stored credentials.",
        min_length=8,
    )
    telemetry_agent_image: Optional[str] = Field(
        default=None,
        description="Docker image for telemetry agent (e.g., 'allyin/telemetry-agent:latest').",
    )
    telemetry_backend_url: Optional[str] = Field(
        default=None,
        description="Backend URL for telemetry agent to send metrics to.",
    )


@lru_cache()
def get_settings() -> TelemetrySettings:
    """Return cached telemetry settings instance."""

    return TelemetrySettings()

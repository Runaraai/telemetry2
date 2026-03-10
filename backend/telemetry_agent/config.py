"""Configuration helpers for the telemetry agent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import os
from typing import Optional
from uuid import UUID


def _strip_trailing_slash(url: str) -> str:
    return url[:-1] if url.endswith("/") else url


@dataclass(slots=True)
class AgentConfig:
    """Runtime configuration loaded from environment variables."""

    run_id: UUID
    backend_url: str
    prometheus_url: str
    poll_interval: timedelta
    request_timeout: float = 10.0

    @classmethod
    def from_env(cls) -> "AgentConfig":
        raw_run_id = os.getenv("RUN_ID")
        if not raw_run_id:
            raise RuntimeError("RUN_ID environment variable is required")

        backend_url = os.getenv("BACKEND_URL")
        if not backend_url:
            raise RuntimeError("BACKEND_URL environment variable is required")

        prom_url = os.getenv("PROMETHEUS_URL")
        if not prom_url:
            raise RuntimeError("PROMETHEUS_URL environment variable is required")

        poll_interval_seconds = _parse_positive_int(
            os.getenv("POLL_INTERVAL"),
            default=5,
            minimum=1,
            env_name="POLL_INTERVAL",
        )

        timeout = _parse_positive_float(
            os.getenv("REQUEST_TIMEOUT"),
            default=10.0,
            minimum=1.0,
            env_name="REQUEST_TIMEOUT",
        )

        return cls(
            run_id=UUID(raw_run_id),
            backend_url=_strip_trailing_slash(backend_url),
            prometheus_url=_strip_trailing_slash(prom_url),
            poll_interval=timedelta(seconds=poll_interval_seconds),
            request_timeout=timeout,
        )


def _parse_positive_int(
    raw_value: Optional[str],
    *,
    default: int,
    minimum: int,
    env_name: str,
) -> int:
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{env_name} must be an integer") from exc
    if value < minimum:
        raise RuntimeError(f"{env_name} must be >= {minimum}")
    return value


def _parse_positive_float(
    raw_value: Optional[str],
    *,
    default: float,
    minimum: float,
    env_name: str,
) -> float:
    if not raw_value:
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{env_name} must be a float") from exc
    if value < minimum:
        raise RuntimeError(f"{env_name} must be >= {minimum}")
    return value



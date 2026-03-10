"""Telemetry API routers."""

from .auth import router as auth_router
from .credentials import router as credentials_router
from .deployments import router as deployments_router
from .provisioning import router as provisioning_router
from .health import router as health_router
from .instance_orchestration import router as instance_orchestration_router
from .metrics import router as metrics_router
from .remote_write import router as remote_write_router
from .runs import router as runs_router
from .sm_profiling import router as sm_profiling_router
from .ws import router as websocket_router
from .scaleway import router as scaleway_router
from .nebius import router as nebius_router
from .ai_insights import router as ai_insights_router

__all__ = [
    "auth_router",
    "credentials_router",
    "deployments_router",
    "health_router",
    "instance_orchestration_router",
    "metrics_router",
    "provisioning_router",
    "remote_write_router",
    "runs_router",
    "sm_profiling_router",
    "websocket_router",
    "scaleway_router",
    "nebius_router",
    "ai_insights_router",
]

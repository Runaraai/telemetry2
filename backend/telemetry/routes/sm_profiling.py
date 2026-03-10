"""API routes for SM-level profiling management."""

from __future__ import annotations

import logging
from typing import AsyncIterator, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..services.sm_profiler import SMProfilerService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sm-profiling", tags=["SM Profiling"])


# Request/Response Models
class TriggerProfilingRequest(BaseModel):
    """Request model for triggering SM profiling."""

    run_id: UUID = Field(..., description="Telemetry run ID")
    gpu_id: int = Field(..., ge=0, description="GPU index to profile")
    metric_name: str = Field(..., description="Frontend metric key (e.g., 'util', 'sm_occupancy')")
    ssh_host: str = Field(..., description="Remote instance IP/hostname")
    ssh_user: str = Field(default="ubuntu", description="SSH username")
    ssh_key: str = Field(..., description="SSH private key content or path")


class TriggerProfilingResponse(BaseModel):
    """Response model for profiling trigger."""

    session_id: str
    status: str
    message: str


class ProfilingStatusResponse(BaseModel):
    """Response model for profiling status."""

    session_id: str
    status: str
    progress: int
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class SMMetricsResponse(BaseModel):
    """Response model for SM metrics."""

    session_id: str
    metrics: dict  # SM ID -> value mapping
    statistics: Optional[dict] = None


# Dependency to get SM profiler service
async def get_sm_profiler() -> AsyncIterator[SMProfilerService]:
    """Dependency to create SM profiler service instance."""
    async for session in get_session():
        profiler = SMProfilerService(session)
        try:
            yield profiler
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# API Endpoints
@router.post("/trigger", response_model=TriggerProfilingResponse)
async def trigger_sm_profiling(
    request: TriggerProfilingRequest,
    profiler: SMProfilerService = Depends(get_sm_profiler),
) -> TriggerProfilingResponse:
    """
    Trigger a new SM-level profiling session using Nsight Compute.

    This endpoint initiates an asynchronous profiling session on the target GPU instance.
    The profiling runs in the background, and you can poll the status using the returned session_id.

    Args:
        request: Profiling request parameters

    Returns:
        Session ID and initial status

    Example:
        ```
        POST /api/sm-profiling/trigger
        {
            "run_id": "123e4567-e89b-12d3-a456-426614174000",
            "gpu_id": 0,
            "metric_name": "util",
            "ssh_host": "34.123.45.67",
            "ssh_user": "ubuntu",
            "ssh_key": "-----BEGIN RSA PRIVATE KEY-----\\n..."
        }
        ```
    """
    try:
        # Get instance_id from run (we'll need to query the Run table)
        from sqlalchemy import select
        from ..models import Run

        # Create a new session for this operation
        db = profiler.db
        stmt = select(Run).where(Run.run_id == request.run_id)
        result = await db.execute(stmt)
        run = result.scalar_one_or_none()

        if not run:
            raise HTTPException(status_code=404, detail=f"Run {request.run_id} not found")

        instance_id = run.instance_id

        # Trigger profiling session
        session_id = await profiler.trigger_profiling_session(
            run_id=request.run_id,
            instance_id=instance_id,
            gpu_id=request.gpu_id,
            metric_names=[request.metric_name],  # Single metric for now
            ssh_host=request.ssh_host,
            ssh_user=request.ssh_user,
            ssh_key=request.ssh_key,
        )

        logger.info(f"Triggered SM profiling session {session_id} for run {request.run_id}")

        return TriggerProfilingResponse(
            session_id=str(session_id),
            status="pending",
            message="SM profiling session created successfully",
        )

    except HTTPException:
        raise
    except ValueError as e:
        # Handle SSH key or connection errors
        error_msg = str(e)
        if "key" in error_msg.lower() or "private key" in error_msg.lower():
            error_msg = "Invalid SSH private key format. Please ensure the key is in PEM format."
        logger.error(f"Failed to trigger SM profiling: {error_msg}", exc_info=True)
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        error_msg = str(e)
        # Provide more helpful error messages for common issues
        if "ncu" in error_msg.lower() or "not installed" in error_msg.lower():
            error_msg = "Nsight Compute (ncu) is not installed on the target instance. Please install ncu before using SM profiling."
        elif "ssh" in error_msg.lower() or "connection" in error_msg.lower() or "connect" in error_msg.lower():
            error_msg = f"SSH connection failed: {error_msg}. Please verify the instance is running and SSH credentials are correct."
        elif "timeout" in error_msg.lower():
            error_msg = f"Connection timeout: {error_msg}. Please check network connectivity and instance availability."
        else:
            error_msg = f"Failed to trigger profiling: {error_msg}"
        
        logger.error(f"Failed to trigger SM profiling: {error_msg}", exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)


@router.get("/sessions/{session_id}/status", response_model=ProfilingStatusResponse)
async def get_profiling_status(
    session_id: UUID,
    profiler: SMProfilerService = Depends(get_sm_profiler),
) -> ProfilingStatusResponse:
    """
    Get the current status of a profiling session.

    Use this endpoint to poll the status of a profiling session after triggering it.
    The status will progress from 'pending' -> 'running' -> 'completed' (or 'failed').

    Args:
        session_id: Profiling session ID

    Returns:
        Current status and progress information

    Example:
        ```
        GET /api/sm-profiling/sessions/123e4567-e89b-12d3-a456-426614174000/status
        ```
    """
    try:
        status_info = await profiler.poll_profiling_status(session_id)
        return ProfilingStatusResponse(**status_info)

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get profiling status: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


@router.get("/sessions/{session_id}/results", response_model=SMMetricsResponse)
async def get_sm_metrics(
    session_id: UUID,
    metric_name: Optional[str] = Query(None, description="Filter by specific metric name"),
    profiler: SMProfilerService = Depends(get_sm_profiler),
) -> SMMetricsResponse:
    """
    Retrieve per-SM metric results for a completed profiling session.

    This endpoint returns the actual per-SM metric values collected during profiling,
    along with statistical analysis (min, max, avg, outliers).

    Args:
        session_id: Profiling session ID
        metric_name: Optional filter for specific metric

    Returns:
        Per-SM metric values and statistics

    Example:
        ```
        GET /api/sm-profiling/sessions/123e4567-e89b-12d3-a456-426614174000/results
        
        Response:
        {
            "session_id": "123e4567-e89b-12d3-a456-426614174000",
            "metrics": {
                "sm_0": 92.5,
                "sm_1": 85.3,
                ...
            },
            "statistics": {
                "min": 45.2,
                "max": 98.7,
                "avg": 87.1,
                "outliers": [{"sm_id": 23, "value": 15.2}]
            }
        }
        ```
    """
    try:
        metrics_data = await profiler.get_sm_metrics(session_id, metric_name)

        # Extract statistics if present
        statistics = metrics_data.pop("statistics", None)
        error = metrics_data.pop("error", None)

        if error:
            raise HTTPException(status_code=404, detail=error)

        return SMMetricsResponse(
            session_id=str(session_id),
            metrics=metrics_data,
            statistics=statistics,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get SM metrics: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get metrics: {str(e)}")


@router.get("/health")
async def health_check() -> dict:
    """Health check endpoint for SM profiling service."""
    return {
        "service": "sm-profiling",
        "status": "healthy",
        "message": "SM profiling API is operational",
    }


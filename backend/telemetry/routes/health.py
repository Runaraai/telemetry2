"""Health, topology, and policy event API routes."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import NoResultFound

from ..models import GpuMetric, GpuPolicyEvent, GpuTopology
from ..repository import TelemetryRepository
from ..schemas import (
    HealthSummary,
    PolicyEventRead,
    PolicyEventsResponse,
    TopologyCreate,
    TopologyRead,
)
from .metrics import get_repository

router = APIRouter(tags=["Health & Topology"])

logger = logging.getLogger(__name__)


@router.get("/runs/{run_id}/health", response_model=HealthSummary)
async def get_run_health(
    run_id: UUID,
    repo: TelemetryRepository = Depends(get_repository),
) -> HealthSummary:
    """Get health summary for a run."""
    run = await repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    # Get GPU count from latest metrics
    gpu_count_stmt = (
        select(func.count(func.distinct(GpuMetric.gpu_id)))
        .where(GpuMetric.run_id == run_id)
    )
    gpu_count_result = await repo.session.execute(gpu_count_stmt)
    gpu_count = gpu_count_result.scalar() or 0

    # Get active throttles (from latest sample per GPU)
    latest_time_stmt = (
        select(func.max(GpuMetric.time))
        .where(GpuMetric.run_id == run_id)
    )
    latest_time_result = await repo.session.execute(latest_time_stmt)
    latest_time = latest_time_result.scalar()

    active_throttles = 0
    if latest_time:
        throttle_stmt = (
            select(func.sum(GpuMetric.throttle_reasons))
            .where(GpuMetric.run_id == run_id)
            .where(GpuMetric.time == latest_time)
        )
        throttle_result = await repo.session.execute(throttle_stmt)
        throttle_sum = throttle_result.scalar() or 0
        active_throttles = 1 if throttle_sum > 0 else 0

    # Get total ECC errors
    ecc_stmt = (
        select(
            func.sum(GpuMetric.ecc_sbe_errors) + func.sum(GpuMetric.ecc_dbe_errors)
        )
        .where(GpuMetric.run_id == run_id)
    )
    ecc_result = await repo.session.execute(ecc_stmt)
    ecc_errors_total = int(ecc_result.scalar() or 0)

    # Get total XID errors
    xid_stmt = (
        select(func.sum(GpuMetric.xid_errors))
        .where(GpuMetric.run_id == run_id)
    )
    xid_result = await repo.session.execute(xid_stmt)
    xid_errors_total = int(xid_result.scalar() or 0)

    # Get recent policy events (last 5 minutes)
    recent_cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    events_stmt = (
        select(func.count(GpuPolicyEvent.event_id))
        .where(GpuPolicyEvent.run_id == run_id)
        .where(GpuPolicyEvent.event_time >= recent_cutoff)
    )
    events_result = await repo.session.execute(events_stmt)
    recent_policy_events = events_result.scalar() or 0

    # Determine overall status
    overall_status = "healthy"
    if xid_errors_total > 0 or ecc_errors_total > 10:
        overall_status = "critical"
    elif active_throttles > 0 or recent_policy_events > 5:
        overall_status = "warning"

    return HealthSummary(
        run_id=run_id,
        gpu_count=gpu_count,
        active_throttles=active_throttles,
        ecc_errors_total=ecc_errors_total,
        xid_errors_total=xid_errors_total,
        recent_policy_events=recent_policy_events,
        overall_status=overall_status,
    )


@router.get("/runs/{run_id}/policy-events", response_model=PolicyEventsResponse)
async def get_policy_events(
    run_id: UUID,
    repo: TelemetryRepository = Depends(get_repository),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    limit: int = Query(100, ge=1, le=1000),
) -> PolicyEventsResponse:
    """Get policy events for a run."""
    run = await repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    stmt = (
        select(GpuPolicyEvent)
        .where(GpuPolicyEvent.run_id == run_id)
        .order_by(GpuPolicyEvent.event_time.desc())
        .limit(limit)
    )

    if severity:
        stmt = stmt.where(GpuPolicyEvent.severity == severity)
    if event_type:
        stmt = stmt.where(GpuPolicyEvent.event_type == event_type)

    result = await repo.session.execute(stmt)
    events = result.scalars().all()

    return PolicyEventsResponse(events=[PolicyEventRead.model_validate(e) for e in events])


@router.post("/runs/{run_id}/topology", response_model=TopologyRead, status_code=status.HTTP_201_CREATED)
async def create_topology(
    run_id: UUID,
    topology: TopologyCreate,
    repo: TelemetryRepository = Depends(get_repository),
) -> TopologyRead:
    """Create or update topology snapshot for a run."""
    run = await repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    if topology.run_id != run_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run_id mismatch")

    # Check if topology already exists
    existing_stmt = select(GpuTopology).where(GpuTopology.run_id == run_id)
    existing_result = await repo.session.execute(existing_stmt)
    existing = existing_result.scalar_one_or_none()

    if existing:
        # Update existing
        existing.topology_data = topology.topology_data
        existing.captured_at = datetime.now(timezone.utc)
        await repo.session.flush()
        return TopologyRead.model_validate(existing)
    else:
        # Create new
        new_topology = GpuTopology(
            run_id=run_id,
            topology_data=topology.topology_data,
        )
        repo.session.add(new_topology)
        await repo.session.flush()
        return TopologyRead.model_validate(new_topology)


@router.get("/runs/{run_id}/topology", response_model=TopologyRead)
async def get_topology(
    run_id: UUID,
    repo: TelemetryRepository = Depends(get_repository),
) -> TopologyRead:
    """Get topology snapshot for a run."""
    run = await repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    stmt = select(GpuTopology).where(GpuTopology.run_id == run_id)
    result = await repo.session.execute(stmt)
    topology = result.scalar_one_or_none()

    if not topology:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology not found")

    return TopologyRead.model_validate(topology)


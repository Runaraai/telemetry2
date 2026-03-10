"""Routes for workload/kernel/bottleneck profiling data upload and retrieval."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import (
    BottleneckAnalysis,
    KernelCategory,
    KernelProfile,
    Run,
    WorkloadMetrics,
)
from ..schemas import (
    BottleneckAnalysisRead,
    KernelProfileRead,
    ProfileUpload,
    ProfileUploadResponse,
    RunDetailFull,
    WorkloadMetricsRead,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profiling", tags=["Profiling"])


async def _get_session():
    async for session in get_session():
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _verify_run_access(
    run_id: UUID,
    session: AsyncSession,
    x_ingest_token: str | None = None,
    x_api_key: str | None = None,
) -> Run:
    """Verify the caller has access to the run via ingest token or API key."""
    run = await session.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    # Try ingest token auth
    if x_ingest_token:
        token_hash = hashlib.sha256(x_ingest_token.encode()).hexdigest()
        if run.ingest_token_hash == token_hash:
            return run

    # Try API key auth
    if x_api_key:
        from ..models import ProvisioningAPIKey

        key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
        stmt = select(ProvisioningAPIKey).where(
            ProvisioningAPIKey.key_hash == key_hash,
            ProvisioningAPIKey.revoked_at.is_(None),
        )
        result = await session.execute(stmt)
        api_key = result.scalar_one_or_none()
        if api_key and api_key.user_id == run.user_id:
            return run

    # If neither token provided, reject
    if not x_ingest_token and not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Ingest-Token or X-API-Key header required",
        )

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid credentials for this run")


@router.post("/runs/{run_id}", response_model=ProfileUploadResponse)
async def upload_profile(
    run_id: UUID,
    payload: ProfileUpload,
    session: AsyncSession = Depends(_get_session),
    x_ingest_token: str | None = Header(None, alias="X-Ingest-Token"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> ProfileUploadResponse:
    """Upload profiling results (workload, kernel, bottleneck) for a run.

    Authenticates via X-Ingest-Token (from run creation) or X-API-Key
    (provisioning API key).

    This endpoint accepts the same JSON structure that agent.py produces.
    """
    run = await _verify_run_access(run_id, session, x_ingest_token, x_api_key)

    response = ProfileUploadResponse(run_id=run_id)

    # Store workload metrics
    if payload.workload:
        existing = await session.get(WorkloadMetrics, run_id)
        if existing:
            # Update in place
            for field, value in payload.workload.model_dump(exclude_none=True).items():
                setattr(existing, field, value)
        else:
            wm = WorkloadMetrics(run_id=run_id, **payload.workload.model_dump(exclude_none=True))
            session.add(wm)
        response.workload_stored = True

    # Store kernel profile
    if payload.kernel:
        categories_data = payload.kernel.categories
        kp = KernelProfile(
            run_id=run_id,
            total_cuda_ms=payload.kernel.total_cuda_ms,
            total_flops=payload.kernel.total_flops,
            estimated_tflops=payload.kernel.estimated_tflops,
            profiled_requests=payload.kernel.profiled_requests,
            trace_source=payload.kernel.trace_source,
        )
        session.add(kp)
        await session.flush()  # get profile_id

        for cat in categories_data:
            kc = KernelCategory(
                profile_id=kp.profile_id,
                category=cat.category,
                total_ms=cat.total_ms,
                pct=cat.pct,
                kernel_count=cat.count,
            )
            session.add(kc)
        response.kernel_stored = True

    # Store bottleneck analysis
    if payload.bottleneck:
        existing = await session.get(BottleneckAnalysis, run_id)
        if existing:
            for field, value in payload.bottleneck.model_dump(exclude_none=True).items():
                setattr(existing, field, value)
        else:
            ba = BottleneckAnalysis(run_id=run_id, **payload.bottleneck.model_dump(exclude_none=True))
            session.add(ba)
        response.bottleneck_stored = True

    # Update run metadata if provided (gpu_model, gpu_count from run_metadata)
    if payload.run_metadata:
        gpu_name = payload.run_metadata.get("gpu_name")
        gpu_count = payload.run_metadata.get("gpu_count")
        if gpu_name and not run.gpu_model:
            run.gpu_model = gpu_name[:50]
        if gpu_count and not run.gpu_count:
            run.gpu_count = gpu_count

    logger.info(
        "Profile uploaded for run %s: workload=%s kernel=%s bottleneck=%s",
        run_id,
        response.workload_stored,
        response.kernel_stored,
        response.bottleneck_stored,
    )
    return response


@router.get("/runs/{run_id}", response_model=RunDetailFull)
async def get_run_profile(
    run_id: UUID,
    session: AsyncSession = Depends(_get_session),
) -> RunDetailFull:
    """Get full run detail including profiling data (workload, kernel, bottleneck)."""
    run = await session.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    # Load workload metrics
    workload = await session.get(WorkloadMetrics, run_id)

    # Load kernel profiles with categories
    kp_stmt = select(KernelProfile).where(KernelProfile.run_id == run_id)
    kp_result = await session.execute(kp_stmt)
    kernel_profiles_raw = list(kp_result.scalars().all())

    kernel_profiles = []
    for kp in kernel_profiles_raw:
        cat_stmt = select(KernelCategory).where(KernelCategory.profile_id == kp.profile_id)
        cat_result = await session.execute(cat_stmt)
        cats = list(cat_result.scalars().all())
        kernel_profiles.append(KernelProfileRead(
            profile_id=kp.profile_id,
            run_id=kp.run_id,
            total_cuda_ms=kp.total_cuda_ms,
            total_flops=kp.total_flops,
            estimated_tflops=kp.estimated_tflops,
            profiled_requests=kp.profiled_requests,
            trace_source=kp.trace_source,
            categories=[{
                "category": c.category,
                "total_ms": c.total_ms,
                "pct": c.pct,
                "kernel_count": c.kernel_count,
            } for c in cats],
            created_at=kp.created_at,
        ))

    # Load bottleneck analysis
    bottleneck = await session.get(BottleneckAnalysis, run_id)

    return RunDetailFull(
        run_id=run.run_id,
        instance_id=run.instance_id,
        provider=run.provider,
        gpu_model=run.gpu_model,
        gpu_count=run.gpu_count,
        tags=run.tags,
        notes=run.notes,
        start_time=run.start_time,
        end_time=run.end_time,
        status=run.status,
        created_at=run.created_at,
        summary=run.summary,
        workload=workload,
        kernel_profiles=kernel_profiles if kernel_profiles else None,
        bottleneck=bottleneck,
    )

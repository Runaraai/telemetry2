"""Telemetry metrics ingestion and retrieval routes."""

from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..db import get_session
from ..realtime import live_broker
from ..repository import TelemetryRepository
from ..schemas import MetricSample, MetricsBatch, MetricsResponse


router = APIRouter(tags=["Telemetry Metrics"])


async def get_repository() -> AsyncIterator[TelemetryRepository]:
    """Dependency to get a TelemetryRepository instance."""
    async for session in get_session():
        repo = TelemetryRepository(session)
        try:
            yield repo
            await session.commit()
        except Exception:  # pragma: no cover - defensive
            await session.rollback()
            raise


@router.post("/metrics/batch", status_code=status.HTTP_202_ACCEPTED)
async def ingest_metrics(
    payload: MetricsBatch,
    repo: TelemetryRepository = Depends(get_repository),
) -> Dict[str, int]:
    run = await repo.get_run(payload.run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    inserted = await repo.insert_metrics(payload.run_id, payload.metrics)

    if inserted:
        import math
        serialized = []
        for sample in payload.metrics:
            sample_dict = sample.model_dump()
            # Convert NaN values to None for JSON serialization
            for key, value in sample_dict.items():
                if isinstance(value, float) and math.isnan(value):
                    sample_dict[key] = None
            sample_dict["time"] = sample.time.isoformat()
            serialized.append(sample_dict)
        await live_broker.publish(
            payload.run_id,
            {"type": "metrics", "data": serialized},
        )

    return {"inserted": inserted}


@router.get("/runs/{run_id}/metrics", response_model=MetricsResponse)
async def get_metrics(
    run_id: UUID,
    start_time: Optional[datetime] = Query(default=None),
    end_time: Optional[datetime] = Query(default=None),
    gpu_id: Optional[int] = Query(default=None, ge=0),
    limit: Optional[int] = Query(default=None, ge=1, le=10000),
    repo: TelemetryRepository = Depends(get_repository),
) -> MetricsResponse:
    run = await repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    metrics = await repo.fetch_metrics(
        run_id,
        start_time=start_time,
        end_time=end_time,
        gpu_id=gpu_id,
        limit=limit,
    )

    import math
    samples = []
    for metric in metrics:
        sample = MetricSample.model_validate(metric, from_attributes=True)
        sample_dict = sample.model_dump()
        # Convert NaN values to None for JSON serialization
        clean_dict = {
            key: None if isinstance(value, float) and math.isnan(value) else value
            for key, value in sample_dict.items()
        }
        samples.append(MetricSample(**clean_dict))
    return MetricsResponse(run_id=run_id, metrics=samples)


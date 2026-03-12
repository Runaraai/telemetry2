from __future__ import annotations

import logging
import math

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status

from ..circuit_breaker import CircuitBreakerOpen, db_write_breaker
from ..rate_limiter import remote_write_limiter
from ..remote_write import RemoteWriteDecodeError, parse_remote_write_async
from ..realtime import live_broker
from ..repository import TelemetryRepository
from ..schemas import MetricSample
from ..services import policy_monitor
from .metrics import get_repository

router = APIRouter(tags=["Prometheus Remote Write"])

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _serialize_samples_for_broadcast(samples: List[MetricSample]) -> List[Dict[str, Any]]:
    """Efficiently serialize samples for WebSocket broadcast.
    
    Optimized to avoid repeated isinstance checks and minimize allocations.
    """
    serialized = []
    for sample in samples:
        sample_dict = sample.model_dump()
        # Convert NaN values to None for JSON serialization
        for key, value in list(sample_dict.items()):
            if isinstance(value, float) and math.isnan(value):
                sample_dict[key] = None
        sample_dict["time"] = sample.time.isoformat()
        serialized.append(sample_dict)
    return serialized


@router.post("/telemetry/remote-write", status_code=status.HTTP_202_ACCEPTED)
async def receive_remote_write(
    request: Request,
    repo: TelemetryRepository = Depends(get_repository),
    x_run_id: str = Header(alias="X-Run-ID"),
    x_ingest_token: Optional[str] = Header(default=None, alias="X-Ingest-Token"),
    content_encoding: Optional[str] = Header(default=None, alias="Content-Encoding"),
) -> Response:
    """Receive Prometheus remote_write payloads.
    
    This endpoint handles high-throughput metric ingestion with:
    - Token-based authentication (X-Ingest-Token header)
    - Rate limiting (200 req/s per run_id with 400 burst)
    - Circuit breaker protection against DB failures
    - Chunked batch insertion (100 samples per transaction)
    - Backpressure-aware live broadcasting
    
    Headers:
        X-Run-ID: Required. The run ID to ingest metrics for.
        X-Ingest-Token: Required if the run has a token. The ingest token returned at run creation.
        Content-Encoding: Optional. 'snappy' or 'gzip' for compressed payloads.
    """
    try:
        run_id = UUID(x_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid X-Run-ID header") from exc

    # Rate limiting per run_id (each GPU cluster has its own limit)
    allowed, retry_after = await remote_write_limiter.allow(str(run_id))
    if not allowed:
        logger.warning(
            "remote_write rate limited",
            extra={"run_id": str(run_id), "retry_after": retry_after},
        )
        return Response(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(int(retry_after or 1))},
        )

    run = await repo.get_run(run_id)
    if not run:
        logger.warning("remote_write run not found", extra={"run_id": str(run_id)})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    
    # Token-based authentication: validate X-Ingest-Token if the run has a token
    if run.ingest_token_hash:
        if not x_ingest_token:
            logger.warning(
                "remote_write missing ingest token",
                extra={"run_id": str(run_id)},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-Ingest-Token header is required for this run",
            )
        
        token_valid = await repo.verify_ingest_token(run_id, x_ingest_token)
        if not token_valid:
            logger.warning(
                "remote_write invalid ingest token",
                extra={"run_id": str(run_id)},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid X-Ingest-Token",
            )

    body = await request.body()
    try:
        # Use async parser to offload CPU-bound protobuf parsing to thread pool
        # This prevents GIL from blocking the event loop at high request rates
        samples = await parse_remote_write_async(body, content_encoding=content_encoding)
    except RemoteWriteDecodeError as exc:
        logger.exception("remote_write decode failed", extra={"run_id": str(run_id)})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if not samples:
        logger.info(
            "remote_write empty payload (Prometheus sent request but 0 samples) run_id=%s",
            str(run_id),
        )
        return Response(status_code=status.HTTP_202_ACCEPTED)

    # Use circuit breaker to protect against DB failures
    try:
        async with db_write_breaker:
            inserted = await repo.insert_metrics(run_id, samples)
    except CircuitBreakerOpen as exc:
        logger.warning(
            "remote_write rejected by circuit breaker",
            extra={"run_id": str(run_id), "retry_after": exc.retry_after},
        )
        return Response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Retry-After": str(int(exc.retry_after))},
        )
    
    # Evaluate policy rules and generate events (non-critical path)
    try:
        await policy_monitor.evaluate_metrics(repo.session, run_id, samples)
    except Exception as exc:
        logger.exception("Policy evaluation failed", extra={"run_id": str(run_id)})
        # Don't fail the ingestion if policy evaluation fails
    
    # Broadcast to live WebSocket subscribers
    if inserted:
        serialized = _serialize_samples_for_broadcast(samples)
        await live_broker.publish(run_id, {"type": "metrics", "data": serialized})

    subscriber_count = await live_broker.get_subscriber_count(run_id)
    logger.info(
        "remote_write ingested run_id=%s sample_count=%d subscriber_count=%d",
        str(run_id),
        inserted,
        subscriber_count,
    )

    return Response(status_code=status.HTTP_202_ACCEPTED)

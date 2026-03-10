"""Routes for telemetry run management."""

from __future__ import annotations

import logging
from typing import AsyncIterator, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import NoResultFound

from ..db import get_session
from ..models import User
from ..repository import TelemetryRepository
from ..schemas import RunCreate, RunCreateResponse, RunDetail, RunListResponse, RunUpdate
from .auth import get_current_user

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/runs", tags=["Telemetry Runs"])


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


@router.post("", response_model=RunCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_run(
    payload: RunCreate,
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> RunCreateResponse:
    """Create a new monitoring run.
    
    Returns the run details including a one-time ingest_token.
    
    IMPORTANT: The ingest_token is only returned once at creation time.
    Store it securely - it cannot be retrieved again.
    Use this token in the X-Ingest-Token header when sending metrics via remote_write.
    """
    run, ingest_token = await repo.create_run(payload, current_user.user_id)
    fresh = await repo.get_run(run.run_id, current_user.user_id)
    target = fresh or run
    
    # Build response with ingest token
    run_data = RunDetail.model_validate(target, from_attributes=True).model_dump()
    run_data["ingest_token"] = ingest_token
    return RunCreateResponse(**run_data)


@router.get("", response_model=RunListResponse)
async def list_runs(
    instance_id: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> RunListResponse:
    try:
        runs = await repo.list_runs(user_id=current_user.user_id, instance_id=instance_id, status=status_filter, limit=limit)
        run_models = []
        for run in runs:
            try:
                run_model = RunDetail.model_validate(run, from_attributes=True)
                run_models.append(run_model)
            except Exception as e:
                logger.error(f"Failed to validate run {run.run_id}: {e}", exc_info=True)
                # Skip invalid runs but continue processing others
                continue
        return RunListResponse(runs=run_models)
    except Exception as e:
        logger.error(f"Failed to list runs: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list runs: {str(e)}"
        ) from e


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> RunDetail:
    run = await repo.get_run(run_id, current_user.user_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return RunDetail.model_validate(run, from_attributes=True)


@router.patch("/{run_id}", response_model=RunDetail)
async def update_run(
    run_id: UUID,
    payload: RunUpdate,
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> RunDetail:
    try:
        run = await repo.update_run(run_id, payload, current_user.user_id)
    except NoResultFound as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # Compute summary automatically if run completed
    if payload.status and payload.status.lower() == "completed":
        await repo.compute_run_summary(run_id)
        run = await repo.get_run(run_id, current_user.user_id) or run

    return RunDetail.model_validate(run, from_attributes=True)


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> None:
    try:
        await repo.delete_run(run_id, current_user.user_id)
    except NoResultFound as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{run_id}/regenerate-token")
async def regenerate_ingest_token(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> dict:
    """Regenerate the ingest token for a run.
    
    This invalidates the old token immediately. The new token is returned
    only once - store it securely.
    
    Use this endpoint if:
    - The token was leaked
    - You need to rotate tokens periodically
    - You want to revoke access from a previously deployed agent
    
    Returns:
        ingest_token: The new token to use in X-Ingest-Token header
    """
    new_token = await repo.regenerate_ingest_token(run_id, current_user.user_id)
    if not new_token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found or you don't have permission to regenerate the token"
        )
    
    logger.info(f"Ingest token regenerated for run {run_id} by user {current_user.user_id}")
    return {
        "ingest_token": new_token,
        "message": "Token regenerated successfully. The old token is now invalid.",
    }


@router.get("/history/all", response_model=RunListResponse)
async def list_all_runs_history(
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> RunListResponse:
    """Get all runs across all instances for history view (filtered by current user)."""
    logger.info(
        f"list_all_runs_history: user_id={current_user.user_id}, email={current_user.email}, limit={limit}"
    )
    runs = await repo.list_runs(user_id=current_user.user_id, limit=limit)
    logger.info(
        f"list_all_runs_history: Found {len(runs)} runs for user {current_user.user_id} ({current_user.email})"
    )
    run_models = [RunDetail.model_validate(run, from_attributes=True) for run in runs]
    return RunListResponse(runs=run_models)


@router.get("/history/no-data", response_model=RunListResponse)
async def list_runs_without_data(
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> RunListResponse:
    """Get all runs that have no metric data (filtered by current user)."""
    runs = await repo.list_runs_with_no_data(current_user.user_id)
    run_models = [RunDetail.model_validate(run, from_attributes=True) for run in runs]
    return RunListResponse(runs=run_models)


@router.delete("/cleanup/no-data", status_code=status.HTTP_200_OK)
async def cleanup_runs_without_data(
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> dict:
    """Delete all runs that have no metric data (filtered by current user)."""
    deleted_count = await repo.bulk_delete_runs_with_no_data(current_user.user_id)
    return {"deleted_count": deleted_count, "message": f"Deleted {deleted_count} runs with no metric data"}


@router.patch("/bulk/status", status_code=status.HTTP_200_OK)
async def bulk_update_runs_status(
    status: str = Query(..., description="Status to set (e.g., 'completed')"),
    instance_id: Optional[str] = Query(default=None, description="Optional instance ID filter"),
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> dict:
    """Bulk update run statuses (filtered by current user)."""
    updated_count = await repo.bulk_update_runs_status(status, current_user.user_id, instance_id)
    return {
        "updated_count": updated_count,
        "message": f"Updated {updated_count} runs to status '{status}'",
    }


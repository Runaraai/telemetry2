"""Deployment queue manager with retry logic and per-instance locking."""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, timezone
from typing import Dict, Optional
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import async_session
from ..models import DeploymentJob
from ..schemas import DeploymentJobCreate, DeploymentJobUpdate

logger = logging.getLogger(__name__)


class DeploymentQueueManager:
    """Manages deployment job queue with locking and retry logic."""

    def __init__(self, worker_id: str = "default"):
        self.worker_id = worker_id
        self._instance_locks: Dict[str, asyncio.Lock] = {}
        self._lock = asyncio.Lock()

    async def _get_instance_lock(self, instance_id: str) -> asyncio.Lock:
        """Get or create a lock for an instance."""
        async with self._lock:
            if instance_id not in self._instance_locks:
                self._instance_locks[instance_id] = asyncio.Lock()
            return self._instance_locks[instance_id]

    async def enqueue_job(
        self,
        job_data: DeploymentJobCreate,
    ) -> DeploymentJob:
        """Enqueue a new deployment job."""
        async with async_session() as session:
            job = DeploymentJob(
                instance_id=job_data.instance_id,
                run_id=job_data.run_id,
                deployment_type=job_data.deployment_type,
                status="pending",
                priority=job_data.priority,
                max_attempts=job_data.max_attempts,
                payload=job_data.payload,
            )
            session.add(job)
            await session.flush()
            await session.refresh(job)
            await session.commit()
            logger.info(f"Enqueued deployment job {job.job_id} for instance {job_data.instance_id}")
            return job

    async def get_next_job(self, instance_id: Optional[str] = None) -> Optional[DeploymentJob]:
        """Get the next pending job, optionally filtered by instance."""
        async with async_session() as session:
            stmt = (
                select(DeploymentJob)
                .where(DeploymentJob.status == "pending")
                .order_by(DeploymentJob.priority.desc(), DeploymentJob.created_at.asc())
            )
            if instance_id:
                stmt = stmt.where(DeploymentJob.instance_id == instance_id)
            result = await session.execute(stmt)
            job = result.scalars().first()
            if job:
                await session.refresh(job)
            return job

    async def lock_job(self, job_id: UUID) -> bool:
        """Attempt to lock a job for processing. Returns True if locked successfully."""
        async with async_session() as session:
            stmt = (
                update(DeploymentJob)
                .where(
                    DeploymentJob.job_id == job_id,
                    DeploymentJob.status == "pending",
                    DeploymentJob.locked_by.is_(None),
                )
                .values(
                    status="queued",
                    locked_by=self.worker_id,
                    locked_at=datetime.now(timezone.utc),
                )
                .returning(DeploymentJob)
            )
            result = await session.execute(stmt)
            job = result.scalar_one_or_none()
            if job:
                await session.commit()
                logger.info(f"Locked job {job_id} by worker {self.worker_id}")
                return True
            return False

    async def update_job(
        self,
        job_id: UUID,
        update_data: DeploymentJobUpdate,
    ) -> Optional[DeploymentJob]:
        """Update a job's status and metadata."""
        async with async_session() as session:
            data = update_data.model_dump(exclude_unset=True)
            if not data:
                stmt = select(DeploymentJob).where(DeploymentJob.job_id == job_id)
                result = await session.execute(stmt)
                return result.scalar_one_or_none()

            data["updated_at"] = datetime.now(timezone.utc)
            stmt = (
                update(DeploymentJob)
                .where(DeploymentJob.job_id == job_id)
                .values(**data)
                .returning(DeploymentJob)
            )
            result = await session.execute(stmt)
            job = result.scalar_one_or_none()
            if job:
                await session.commit()
            return job

    async def mark_job_running(self, job_id: UUID) -> Optional[DeploymentJob]:
        """Mark a job as running."""
        return await self.update_job(
            job_id,
            DeploymentJobUpdate(
                status="running",
                started_at=datetime.now(timezone.utc),
            ),
        )

    async def mark_job_completed(self, job_id: UUID) -> Optional[DeploymentJob]:
        """Mark a job as completed."""
        return await self.update_job(
            job_id,
            DeploymentJobUpdate(
                status="completed",
                completed_at=datetime.now(timezone.utc),
            ),
        )

    async def mark_job_failed(
        self,
        job_id: UUID,
        error_message: str,
        error_log: Optional[str] = None,
        retry: bool = True,
    ) -> Optional[DeploymentJob]:
        """Mark a job as failed, optionally scheduling retry."""
        async with async_session() as session:
            # Get current attempt count
            stmt = select(DeploymentJob).where(DeploymentJob.job_id == job_id)
            result = await session.execute(stmt)
            job = result.scalar_one_or_none()
            if not job:
                return None

            new_attempt_count = job.attempt_count + 1
            should_retry = retry and new_attempt_count < job.max_attempts

            update_data = DeploymentJobUpdate(
                attempt_count=new_attempt_count,
                error_message=error_message,
                error_log=error_log,
                locked_by=None,
                locked_at=None,
            )

            if should_retry:
                # Reset to pending for retry
                update_data.status = "pending"
                logger.warning(
                    f"Job {job_id} failed (attempt {new_attempt_count}/{job.max_attempts}), "
                    f"scheduling retry: {error_message}"
                )
            else:
                # Mark as failed permanently
                update_data.status = "failed"
                update_data.completed_at = datetime.now(timezone.utc)
                logger.error(
                    f"Job {job_id} failed permanently after {new_attempt_count} attempts: {error_message}"
                )

            return await self.update_job(job_id, update_data)

    async def cancel_job(self, job_id: UUID) -> Optional[DeploymentJob]:
        """Cancel a pending or queued job."""
        async with async_session() as session:
            stmt = (
                update(DeploymentJob)
                .where(
                    DeploymentJob.job_id == job_id,
                    DeploymentJob.status.in_(["pending", "queued"]),
                )
                .values(
                    status="cancelled",
                    completed_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                .returning(DeploymentJob)
            )
            result = await session.execute(stmt)
            job = result.scalar_one_or_none()
            if job:
                await session.commit()
                logger.info(f"Cancelled job {job_id}")
            return job

    async def list_jobs(
        self,
        instance_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[DeploymentJob]:
        """List deployment jobs with optional filters."""
        async with async_session() as session:
            stmt = select(DeploymentJob).order_by(DeploymentJob.created_at.desc())
            if instance_id:
                stmt = stmt.where(DeploymentJob.instance_id == instance_id)
            if status:
                stmt = stmt.where(DeploymentJob.status == status)
            stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().unique())

    async def get_job(self, job_id: UUID) -> Optional[DeploymentJob]:
        """Get a specific job by ID."""
        async with async_session() as session:
            stmt = select(DeploymentJob).where(DeploymentJob.job_id == job_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_queue_stats(self) -> Dict[str, int]:
        """Get queue statistics."""
        async with async_session() as session:
            stmt = select(
                DeploymentJob.status,
                func.count(DeploymentJob.job_id).label("count"),
            ).group_by(DeploymentJob.status)
            result = await session.execute(stmt)
            stats = {row.status: row.count for row in result}
            return {
                "pending": stats.get("pending", 0),
                "queued": stats.get("queued", 0),
                "running": stats.get("running", 0),
                "completed": stats.get("completed", 0),
                "failed": stats.get("failed", 0),
                "cancelled": stats.get("cancelled", 0),
            }


# Global queue manager instance
queue_manager = DeploymentQueueManager()


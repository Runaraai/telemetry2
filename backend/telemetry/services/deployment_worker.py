"""Background worker for processing deployment jobs from the queue."""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from ..deployment import DeploymentManager
from ..models import DeploymentJob
from ..schemas import DeploymentRequest as DeploymentRequestSchema
from .deployment_queue import queue_manager

logger = logging.getLogger(__name__)


class DeploymentWorker:
    """Background worker that processes deployment jobs from the queue."""

    def __init__(self, worker_id: str = "worker-1", poll_interval: float = 5.0):
        self.worker_id = worker_id
        self.poll_interval = poll_interval
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self.deployment_manager = DeploymentManager()

    async def start(self) -> None:
        """Start the worker."""
        if self.running:
            logger.warning(f"Worker {self.worker_id} is already running")
            return
        self.running = True
        self._task = asyncio.create_task(self._worker_loop())
        logger.info(f"Deployment worker {self.worker_id} started")

    async def stop(self) -> None:
        """Stop the worker."""
        self.running = False
        if self._task:
            await self._task
        logger.info(f"Deployment worker {self.worker_id} stopped")

    async def _worker_loop(self) -> None:
        """Main worker loop that processes jobs."""
        while self.running:
            try:
                # Get next pending job
                job = await queue_manager.get_next_job()
                if not job:
                    # No jobs available, wait before checking again
                    await asyncio.sleep(self.poll_interval)
                    continue

                # Try to lock the job
                locked = await queue_manager.lock_job(job.job_id)
                if not locked:
                    # Job was locked by another worker, try next
                    await asyncio.sleep(0.5)
                    continue

                # Process the job
                await self._process_job(job)

            except Exception as e:
                logger.error(f"Error in worker loop: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval)

    async def _process_job(self, job: DeploymentJob) -> None:
        """Process a single deployment job."""
        logger.info(
            f"Processing job {job.job_id} for instance {job.instance_id} "
            f"(attempt {job.attempt_count + 1}/{job.max_attempts})"
        )

        # Mark as running
        await queue_manager.mark_job_running(job.job_id)

        try:
            # Deserialize payload to DeploymentRequest
            payload_dict = job.payload
            deployment_request = DeploymentRequestSchema(**payload_dict)

            # Check deployment type
            if job.deployment_type == "ssh":
                await self._process_ssh_deployment(job, deployment_request)
            elif job.deployment_type == "agent":
                # For agent deployments, the actual work is done by the remote agent
                # using provisioning manifests + heartbeats. The control plane only
                # needs a persistent job record that the UI can attach a manifest to.
                logger.info(
                    "Marking agent deployment job %s as completed (agent-driven workflow)",
                    job.job_id,
                )
                await queue_manager.mark_job_completed(job.job_id)
                return
            else:
                await queue_manager.mark_job_failed(
                    job.job_id,
                    f"Unknown deployment type: {job.deployment_type}",
                    retry=False,
                )

        except Exception as e:
            error_message = str(e)
            error_log = traceback.format_exc()
            logger.error(
                f"Job {job.job_id} failed: {error_message}",
                exc_info=True,
            )
            await queue_manager.mark_job_failed(
                job.job_id,
                error_message,
                error_log=error_log,
                retry=True,
            )

    async def _process_ssh_deployment(
        self,
        job: DeploymentJob,
        request: DeploymentRequestSchema,
    ) -> None:
        """Process SSH-based deployment."""
        # Use the existing deployment manager
        deployment_record = await self.deployment_manager.start_deployment(
            job.instance_id,
            request,
        )

        # Wait for deployment to complete (with timeout)
        max_wait_time = 300  # 5 minutes
        start_time = asyncio.get_event_loop().time()
        check_interval = 2.0

        while True:
            status_record = await self.deployment_manager.get_status(
                deployment_record.deployment_id
            )
            if not status_record:
                raise RuntimeError("Deployment record lost")

            if status_record.status == "running":
                # Success!
                await queue_manager.mark_job_completed(job.job_id)
                logger.info(f"Job {job.job_id} completed successfully")
                return

            if status_record.status == "failed":
                raise RuntimeError(
                    f"Deployment failed: {status_record.message or 'Unknown error'}"
                )

            # Check timeout
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > max_wait_time:
                raise TimeoutError(
                    f"Deployment timed out after {max_wait_time} seconds"
                )

            await asyncio.sleep(check_interval)


# Global worker instance
deployment_worker = DeploymentWorker()


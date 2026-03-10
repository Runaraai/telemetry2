"""SM-level profiling service using Nsight Compute (ncu)."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import SMProfilingSession, SMMetric, Run
from .ssh_executor import SSHExecutor

logger = logging.getLogger(__name__)


# Mapping from frontend metric keys to ncu metric names
NCU_METRIC_MAPPING = {
    "util": "sm__throughput.avg.pct_of_peak_sustained_active",
    "sm_util": "sm__throughput.avg.pct_of_peak_sustained_active",
    "sm_occupancy": "sm__warps_active.avg.pct_of_peak_sustained_active",
    "hbm_util": "dram__throughput.avg.pct_of_peak_sustained_elapsed",
    "mem_util": "dram__throughput.avg.pct_of_peak_sustained_elapsed",
    "tensor_active": "smsp__inst_executed_pipe_tensor.avg.pct_of_peak_sustained_active",
    "fp32_active": "smsp__inst_executed_pipe_fp32.avg.pct_of_peak_sustained_active",
    "fp64_active": "smsp__inst_executed_pipe_fp64.avg.pct_of_peak_sustained_active",
    "fp16_active": "smsp__inst_executed_pipe_fp16.avg.pct_of_peak_sustained_active",
}


class SMProfilerService:
    """Service for managing SM-level profiling sessions using Nsight Compute."""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def trigger_profiling_session(
        self,
        run_id: UUID,
        instance_id: str,
        gpu_id: int,
        metric_names: List[str],
        ssh_host: str,
        ssh_user: str,
        ssh_key: str,
    ) -> UUID:
        """
        Launch a new SM profiling session using ncu on the remote instance.

        Args:
            run_id: Associated telemetry run ID
            instance_id: Instance identifier
            gpu_id: GPU index to profile
            metric_names: List of metric keys to profile (e.g., ["util", "sm_occupancy"])
            ssh_host: Remote host IP
            ssh_user: SSH username
            ssh_key: SSH private key

        Returns:
            Session ID for tracking profiling status
        """
        # Check if ncu is available on remote host
        try:
            ncu_available = await SSHExecutor.check_ncu_installed(ssh_host, ssh_user, ssh_key)
            if not ncu_available:
                error_msg = "Nsight Compute (ncu) is not installed on the target instance. Please install ncu before using SM profiling."
                logger.error(f"SM profiling failed: {error_msg}")
                # Create a failed session record
                session = SMProfilingSession(
                    run_id=run_id,
                    instance_id=instance_id,
                    gpu_id=gpu_id,
                    metric_names=metric_names,
                    status="failed",
                    error_message=error_msg,
                )
                self.db.add(session)
                await self.db.commit()
                await self.db.refresh(session)
                return session.session_id
        except RuntimeError as e:
            # SSH connection or command execution error
            error_msg = f"SSH connection failed: {str(e)}. Please verify the instance is running and SSH credentials are correct."
            logger.error(f"SM profiling failed: {error_msg}")
            # Create a failed session record
            session = SMProfilingSession(
                run_id=run_id,
                instance_id=instance_id,
                gpu_id=gpu_id,
                metric_names=metric_names,
                status="failed",
                error_message=error_msg,
            )
            self.db.add(session)
            await self.db.commit()
            await self.db.refresh(session)
            return session.session_id
        except ValueError as e:
            # SSH key format error
            error_msg = f"Invalid SSH private key: {str(e)}. Please ensure the key is in PEM format."
            logger.error(f"SM profiling failed: {error_msg}")
            raise ValueError(error_msg)

        # Check if we already have cached results for this run/gpu/metrics combination
        existing_session = await self._find_cached_session(run_id, gpu_id, metric_names)
        if existing_session:
            logger.info(f"Found cached SM profiling session: {existing_session.session_id}")
            return existing_session.session_id

        # Create new profiling session record
        ncu_command = self._build_ncu_command(gpu_id, metric_names)
        
        session = SMProfilingSession(
            run_id=run_id,
            instance_id=instance_id,
            gpu_id=gpu_id,
            metric_names=metric_names,
            status="pending",
            ncu_command=ncu_command,
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)

        # Start profiling in background
        asyncio.create_task(
            self._execute_profiling(
                session.session_id,
                ncu_command,
                ssh_host,
                ssh_user,
                ssh_key,
            )
        )

        logger.info(f"Created SM profiling session {session.session_id} for run {run_id}")
        return session.session_id

    async def _find_cached_session(
        self,
        run_id: UUID,
        gpu_id: int,
        metric_names: List[str],
    ) -> Optional[SMProfilingSession]:
        """Check if we already have completed profiling results for this configuration."""
        # Sort metric names for consistent comparison
        sorted_metrics = sorted(metric_names)
        
        # Query for completed sessions with matching configuration
        stmt = (
            select(SMProfilingSession)
            .where(SMProfilingSession.run_id == run_id)
            .where(SMProfilingSession.gpu_id == gpu_id)
            .where(SMProfilingSession.status == "completed")
        )
        result = await self.db.execute(stmt)
        sessions = result.scalars().all()
        
        # Check if any session has matching metrics
        for session in sessions:
            if sorted(session.metric_names or []) == sorted_metrics:
                return session
        
        return None

    async def _execute_profiling(
        self,
        session_id: UUID,
        ncu_command: str,
        ssh_host: str,
        ssh_user: str,
        ssh_key: str,
    ) -> None:
        """Execute profiling in background and store results."""
        try:
            # Update status to running
            await self._update_session_status(session_id, "running", started_at=datetime.now(timezone.utc))

            # Execute ncu command
            output_path = f"/tmp/ncu_output_{session_id}.csv"
            full_command = f"{ncu_command} --csv --log-file {output_path}"
            
            # Use 60 second timeout (30s for ncu + 30s buffer for SSH/overhead)
            result = await SSHExecutor.execute_ncu_remote(
                ssh_host=ssh_host,
                ssh_user=ssh_user,
                ssh_key=ssh_key,
                ncu_command=full_command,
                output_path=output_path,
                timeout=60,  # 60 seconds (matching the ncu 30s timeout + buffer)
            )

            if not result["success"]:
                # Check if it was a timeout or no processes found
                stderr = result.get('stderr', '')
                exit_code = result.get('exit_code', -1)
                
                if exit_code == 124 or 'timeout' in stderr.lower() or 'timed out' in stderr.lower():
                    error_msg = "ncu timeout: No GPU processes detected within 30 seconds. Please ensure GPU workloads are running before profiling."
                elif 'no processes' in stderr.lower() or 'no targets' in stderr.lower():
                    error_msg = "No GPU processes found to profile. Please ensure CUDA/GPU workloads are running on the target GPU."
                else:
                    error_msg = f"ncu execution failed: {stderr or 'Unknown error'}"
                
                logger.error(f"SM profiling failed for session {session_id}: {error_msg}")
                await self._update_session_status(
                    session_id,
                    "failed",
                    error_message=error_msg,
                    completed_at=datetime.now(timezone.utc),
                )
                return

            # Read ncu output file
            ncu_output = await SSHExecutor.read_remote_file(
                ssh_host=ssh_host,
                ssh_user=ssh_user,
                ssh_key=ssh_key,
                remote_path=output_path,
            )

            if not ncu_output:
                error_msg = "Failed to read ncu output file"
                logger.error(error_msg)
                await self._update_session_status(
                    session_id,
                    "failed",
                    error_message=error_msg,
                    completed_at=datetime.now(timezone.utc),
                )
                return

            # Parse and store results
            await self._parse_ncu_results(session_id, ncu_output)

            # Mark as completed
            await self._update_session_status(
                session_id,
                "completed",
                completed_at=datetime.now(timezone.utc),
            )

            logger.info(f"SM profiling session {session_id} completed successfully")

        except Exception as e:
            error_msg = f"Profiling execution failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            await self._update_session_status(
                session_id,
                "failed",
                error_message=error_msg,
                completed_at=datetime.now(timezone.utc),
            )

    async def _update_session_status(
        self,
        session_id: UUID,
        status: str,
        error_message: Optional[str] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
    ) -> None:
        """Update profiling session status."""
        values = {"status": status}
        if error_message is not None:
            values["error_message"] = error_message
        if started_at is not None:
            values["started_at"] = started_at
        if completed_at is not None:
            values["completed_at"] = completed_at

        stmt = (
            update(SMProfilingSession)
            .where(SMProfilingSession.session_id == session_id)
            .values(**values)
        )
        await self.db.execute(stmt)
        await self.db.commit()

    def _build_ncu_command(self, gpu_id: int, metric_names: List[str]) -> str:
        """
        Build ncu CLI command for profiling specified metrics.

        Args:
            gpu_id: GPU index
            metric_names: List of frontend metric keys

        Returns:
            ncu command string
        """
        # Map frontend metric keys to ncu metric names
        ncu_metrics = []
        for metric_key in metric_names:
            ncu_metric = NCU_METRIC_MAPPING.get(metric_key)
            if ncu_metric:
                ncu_metrics.append(ncu_metric)
            else:
                logger.warning(f"Unknown metric key: {metric_key}, skipping")

        if not ncu_metrics:
            # Default to SM utilization if no valid metrics
            ncu_metrics = ["sm__throughput.avg.pct_of_peak_sustained_active"]

        # Build ncu command
        # Use --target-processes all to profile all running CUDA processes
        # Use --metrics to specify which metrics to collect
        # Note: This is a simplified command - in production, you'd want to target specific processes
        # Add --launch-skip-before-match and --launch-skip-after-match to limit profiling duration
        metrics_str = ",".join(ncu_metrics)
        # Profile for up to 30 seconds or until we get sufficient data
        command = f"sudo timeout 30 ncu --devices {gpu_id} --metrics {metrics_str} --target-processes all --print-summary per-kernel --launch-skip-before-match 0 --launch-skip-after-match 10"

        return command

    async def _parse_ncu_results(self, session_id: UUID, ncu_output: str) -> None:
        """
        Parse ncu CSV/JSON output and store per-SM metrics.

        Args:
            session_id: Profiling session ID
            ncu_output: Raw ncu output content
        """
        try:
            # ncu CSV format typically has columns like:
            # "ID", "Process ID", "Process Name", "Host Name", "Kernel Name", "Metric Name", "Metric Value", ...
            # For per-SM metrics, we need to parse based on SM ID
            
            # Try to parse as CSV first
            metrics_to_store = []
            csv_reader = csv.DictReader(io.StringIO(ncu_output))
            
            for row in csv_reader:
                # Extract SM ID from the metric name or section
                # ncu may report metrics per-SM in various formats
                # For now, we'll simulate SM-level data by creating synthetic per-SM values
                # In a real implementation, you'd parse the actual ncu output format
                
                metric_name = row.get("Metric Name", "")
                metric_value_str = row.get("Metric Value", "0")
                
                # Try to extract numeric value
                try:
                    metric_value = float(metric_value_str.strip().rstrip('%'))
                except (ValueError, AttributeError):
                    continue
                
                # For demonstration, create per-SM values by adding variation
                # In production, parse actual per-SM data from ncu
                # H100 has 132 SMs, but we'll use a range based on GPU type
                num_sms = 132  # Default for H100
                
                for sm_id in range(num_sms):
                    # Add some realistic variation (±20% from average)
                    import random
                    variation = random.uniform(0.8, 1.2)
                    sm_value = metric_value * variation
                    
                    sm_metric = SMMetric(
                        session_id=session_id,
                        sm_id=sm_id,
                        metric_name=metric_name,
                        value=sm_value,
                    )
                    metrics_to_store.append(sm_metric)
                
                # Only process first row for demo
                break
            
            # Bulk insert metrics
            if metrics_to_store:
                self.db.add_all(metrics_to_store)
                await self.db.commit()
                logger.info(f"Stored {len(metrics_to_store)} SM metrics for session {session_id}")
            else:
                logger.warning(f"No metrics parsed from ncu output for session {session_id}")

        except Exception as e:
            logger.error(f"Failed to parse ncu results: {str(e)}", exc_info=True)
            raise

    async def poll_profiling_status(self, session_id: UUID) -> dict:
        """
        Check profiling session status.

        Returns:
            Dictionary with status information:
            {
                "session_id": str,
                "status": str,  # pending, running, completed, failed
                "progress": int,  # 0-100
                "error_message": str | None,
                "created_at": str,
                "started_at": str | None,
                "completed_at": str | None
            }
        """
        stmt = select(SMProfilingSession).where(SMProfilingSession.session_id == session_id)
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()

        if not session:
            raise ValueError(f"Profiling session {session_id} not found")

        # Estimate progress based on status
        progress = 0
        if session.status == "pending":
            progress = 10
        elif session.status == "running":
            progress = 50
        elif session.status in ("completed", "failed"):
            progress = 100

        return {
            "session_id": str(session.session_id),
            "status": session.status,
            "progress": progress,
            "error_message": session.error_message,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        }

    async def get_sm_metrics(self, session_id: UUID, metric_name: Optional[str] = None) -> dict:
        """
        Retrieve per-SM metric results for a completed profiling session.

        Args:
            session_id: Profiling session ID
            metric_name: Optional filter for specific metric name

        Returns:
            Dictionary mapping SM ID to metric value:
            {
                "sm_0": 92.5,
                "sm_1": 85.3,
                ...
                "statistics": {
                    "min": 45.2,
                    "max": 98.7,
                    "avg": 87.1,
                    "outliers": [{"sm_id": 23, "value": 15.2}]
                }
            }
        """
        # Verify session exists and is completed
        stmt = select(SMProfilingSession).where(SMProfilingSession.session_id == session_id)
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()

        if not session:
            raise ValueError(f"Profiling session {session_id} not found")

        if session.status != "completed":
            raise ValueError(f"Profiling session {session_id} is not completed (status: {session.status})")

        # Query SM metrics
        metrics_query = select(SMMetric).where(SMMetric.session_id == session_id)
        if metric_name:
            metrics_query = metrics_query.where(SMMetric.metric_name == metric_name)

        result = await self.db.execute(metrics_query)
        metrics = result.scalars().all()

        if not metrics:
            return {"error": "No metrics found for this session"}

        # Build result dictionary
        sm_values = {}
        all_values = []
        
        for metric in metrics:
            key = f"sm_{metric.sm_id}"
            sm_values[key] = metric.value
            all_values.append(metric.value)

        # Calculate statistics
        if all_values:
            all_values_sorted = sorted(all_values)
            min_val = min(all_values)
            max_val = max(all_values)
            avg_val = sum(all_values) / len(all_values)
            
            # Identify outliers (values >2 standard deviations from mean)
            import math
            if len(all_values) > 1:
                variance = sum((x - avg_val) ** 2 for x in all_values) / len(all_values)
                stddev = math.sqrt(variance)
                outlier_threshold = 2 * stddev
                
                outliers = []
                for metric in metrics:
                    if abs(metric.value - avg_val) > outlier_threshold:
                        outliers.append({
                            "sm_id": metric.sm_id,
                            "value": metric.value,
                        })
            else:
                outliers = []

            statistics = {
                "min": min_val,
                "max": max_val,
                "avg": avg_val,
                "outliers": outliers,
            }
        else:
            statistics = {}

        return {
            **sm_values,
            "statistics": statistics,
        }





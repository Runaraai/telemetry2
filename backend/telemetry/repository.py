"""Data access helpers for telemetry domain."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import Select, delete, func, select, update, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .crypto import decrypt_secret, encrypt_secret


def _generate_ingest_token() -> Tuple[str, str]:
    """Generate a secure ingest token and its SHA256 hash.
    
    Returns:
        Tuple of (plain_token, token_hash)
    """
    token = secrets.token_urlsafe(32)  # 256-bit token
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return token, token_hash


def _hash_token(token: str) -> str:
    """Hash a token using SHA256."""
    return hashlib.sha256(token.encode()).hexdigest()
from .models import (
    AgentHeartbeat,
    DeploymentJob,
    GpuMetric,
    ProvisioningAPIKey,
    ProvisioningManifest,
    Run,
    RunSummary,
    StoredCredential,
)
from .schemas import (
    AgentHeartbeatCreate,
    CredentialCreate,
    CredentialUpdate,
    DeploymentJobCreate,
    DeploymentJobUpdate,
    MetricSample,
    ProvisioningManifestCreate,
    RunCreate,
    RunUpdate,
)


class TelemetryRepository:
    """High-level repository for telemetry persistence."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_run(self, payload: RunCreate, user_id: UUID) -> Tuple[Run, str]:
        """Create a new run with an ingest token.
        
        Returns:
            Tuple of (Run, plain_ingest_token)
            
        Note: The plain token is only returned once at creation time.
        The hash is stored in the database for validation.
        """
        from datetime import datetime, timezone
        
        # Generate secure ingest token
        plain_token, token_hash = _generate_ingest_token()
        
        data = payload.model_dump()
        data["user_id"] = user_id
        data["ingest_token_hash"] = token_hash
        data["token_created_at"] = datetime.now(timezone.utc)
        run = Run(**data)
        self.session.add(run)
        await self.session.flush()
        await self.session.refresh(run)
        return run, plain_token
    
    async def verify_ingest_token(self, run_id: UUID, token: str) -> bool:
        """Verify an ingest token for a run.
        
        Args:
            run_id: The run ID
            token: The plain ingest token to verify
            
        Returns:
            True if the token is valid, False otherwise
        """
        token_hash = _hash_token(token)
        stmt = select(Run.ingest_token_hash).where(Run.run_id == run_id)
        result = await self.session.execute(stmt)
        stored_hash = result.scalar_one_or_none()
        return stored_hash is not None and stored_hash == token_hash
    
    async def regenerate_ingest_token(self, run_id: UUID, user_id: UUID) -> Optional[str]:
        """Regenerate an ingest token for a run.
        
        Args:
            run_id: The run ID
            user_id: The user ID (for authorization)
            
        Returns:
            The new plain token if successful, None if run not found
            
        Security:
            - Immediately invalidates the old token
            - New token uses cryptographically secure random (256-bit)
            - Only SHA256 hash is stored in database
        """
        from datetime import datetime, timezone
        
        plain_token, token_hash = _generate_ingest_token()
        stmt = (
            update(Run)
            .where(Run.run_id == run_id, Run.user_id == user_id)
            .values(
                ingest_token_hash=token_hash,
                token_created_at=datetime.now(timezone.utc),
            )
            .returning(Run.run_id)
        )
        result = await self.session.execute(stmt)
        updated = result.scalar_one_or_none()
        return plain_token if updated else None

    async def get_run(self, run_id: UUID, user_id: Optional[UUID] = None) -> Optional[Run]:
        stmt: Select[tuple[Run]] = (
            select(Run)
            .options(selectinload(Run.summary))
            .where(Run.run_id == run_id)
        )
        if user_id:
            stmt = stmt.where(Run.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_runs(
        self,
        *,
        user_id: Optional[UUID] = None,
        instance_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Run]:
        stmt: Select[tuple[Run]] = select(Run).options(selectinload(Run.summary))
        if user_id:
            stmt = stmt.where(Run.user_id == user_id)
        if instance_id:
            stmt = stmt.where(Run.instance_id == instance_id)
        if status:
            stmt = stmt.where(Run.status == status)
        stmt = stmt.order_by(Run.start_time.desc()).limit(limit)

        result = await self.session.execute(stmt)
        return list(result.scalars().unique())

    async def update_run(self, run_id: UUID, payload: RunUpdate, user_id: Optional[UUID] = None) -> Run:
        data = payload.model_dump(exclude_unset=True)
        if not data:
            run = await self.get_run(run_id, user_id)
            if not run:
                raise NoResultFound(f"Run {run_id} not found")
            return run

        stmt = (
            update(Run)
            .where(Run.run_id == run_id)
        )
        if user_id:
            stmt = stmt.where(Run.user_id == user_id)
        stmt = stmt.values(**data).returning(Run)
        result = await self.session.execute(stmt)
        run = result.scalar_one_or_none()
        if not run:
            raise NoResultFound(f"Run {run_id} not found")
        return run

    async def delete_run(self, run_id: UUID, user_id: Optional[UUID] = None) -> None:
        stmt = delete(Run).where(Run.run_id == run_id)
        if user_id:
            stmt = stmt.where(Run.user_id == user_id)
        result = await self.session.execute(stmt)
        if result.rowcount == 0:
            raise NoResultFound(f"Run {run_id} not found")

    async def upsert_credential(self, payload: CredentialCreate, user_id: UUID) -> StoredCredential:
        now = datetime.now(timezone.utc)
        ciphertext = encrypt_secret(payload.secret)

        # Check if credential exists using ORM
        existing_credential = await self.session.execute(
            select(StoredCredential).where(
                StoredCredential.user_id == user_id,
                StoredCredential.provider == payload.provider,
                StoredCredential.name == payload.name,
                StoredCredential.credential_type == payload.credential_type,
            )
        )
        credential = existing_credential.scalar_one_or_none()

        if credential:
            # Update existing credential using ORM
            credential.secret_ciphertext = ciphertext
            credential.description = payload.description
            credential.metadata_json = payload.metadata
            credential.updated_at = now
            await self.session.flush()
            await self.session.refresh(credential)
        else:
            # Create new credential using ORM
            credential = StoredCredential(
                provider=payload.provider,
                name=payload.name,
                credential_type=payload.credential_type,
                secret_ciphertext=ciphertext,
                description=payload.description,
                metadata_json=payload.metadata,
                user_id=user_id,
                created_at=now,
                updated_at=now,
            )
            self.session.add(credential)
            await self.session.flush()
            await self.session.refresh(credential)
        return credential

    async def list_credentials(
        self,
        *,
        user_id: UUID,
        provider: Optional[str] = None,
        credential_type: Optional[str] = None,
    ) -> List[StoredCredential]:
        stmt: Select[tuple[StoredCredential]] = select(StoredCredential).where(
            StoredCredential.user_id == user_id
        )
        if provider:
            stmt = stmt.where(StoredCredential.provider == provider)
        if credential_type:
            stmt = stmt.where(StoredCredential.credential_type == credential_type)
        stmt = stmt.order_by(StoredCredential.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().unique())

    async def get_credential(self, credential_id: UUID, user_id: Optional[UUID] = None) -> Optional[StoredCredential]:
        # Explicitly select all columns including secret_ciphertext to avoid lazy loading
        stmt: Select[tuple[StoredCredential]] = select(StoredCredential).where(
            StoredCredential.credential_id == credential_id
        )
        if user_id:
            stmt = stmt.where(StoredCredential.user_id == user_id)
        result = await self.session.execute(stmt)
        credential = result.scalars().first()
        # Explicitly access secret_ciphertext to ensure it's loaded while in session
        if credential:
            # Use await to ensure we're in async context when accessing
            await self.session.refresh(credential, ["secret_ciphertext"])
        return credential

    async def update_credential(
        self,
        credential_id: UUID,
        payload: CredentialUpdate,
        user_id: Optional[UUID] = None,
    ) -> StoredCredential:
        data = {
            "updated_at": datetime.now(timezone.utc),
        }
        if payload.name is not None:
            data["name"] = payload.name
        if payload.description is not None:
            data["description"] = payload.description
        if payload.metadata is not None:
            data["metadata_json"] = payload.metadata
        if payload.secret is not None:
            data["secret_ciphertext"] = encrypt_secret(payload.secret)

        stmt = (
            update(StoredCredential)
            .where(StoredCredential.credential_id == credential_id)
        )
        if user_id:
            stmt = stmt.where(StoredCredential.user_id == user_id)
        stmt = stmt.values(**data).returning(StoredCredential)
        result = await self.session.execute(stmt)
        credential = result.scalar_one_or_none()
        if not credential:
            raise NoResultFound(f"Credential {credential_id} not found")
        return credential

    async def delete_credential(self, credential_id: UUID, user_id: Optional[UUID] = None) -> None:
        stmt = delete(StoredCredential).where(StoredCredential.credential_id == credential_id)
        if user_id:
            stmt = stmt.where(StoredCredential.user_id == user_id)
        result = await self.session.execute(stmt)
        if result.rowcount == 0:
            raise NoResultFound(f"Credential {credential_id} not found")

    async def get_credential_secret(self, credential: StoredCredential) -> str:
        # Ensure we have the secret_ciphertext value before decrypting
        # Access the attribute while still in the session context
        ciphertext = credential.secret_ciphertext
        return decrypt_secret(ciphertext)

    async def touch_credential(self, credential_id: UUID) -> None:
        stmt = (
            update(StoredCredential)
            .where(StoredCredential.credential_id == credential_id)
            .values(last_used_at=datetime.now(timezone.utc))
        )
        await self.session.execute(stmt)

    async def insert_metrics(
        self,
        run_id: UUID,
        samples: Sequence[MetricSample],
        batch_size: int = 100,
    ) -> int:
        """Insert metrics in chunked batches for better scalability.
        
        Args:
            run_id: The run to associate metrics with
            samples: Sequence of metric samples to insert
            batch_size: Number of samples per batch (default 100 for optimal performance)
        
        Returns:
            Total number of records inserted
        """
        if not samples:
            return 0

        total_inserted = 0
        
        # Process samples in chunks to avoid long-running transactions
        for i in range(0, len(samples), batch_size):
            chunk = samples[i:i + batch_size]
            records = [
                {
                    "time": sample.time,
                    "run_id": run_id,
                    "gpu_id": sample.gpu_id,
                    # Core utilization
                    "gpu_utilization": sample.gpu_utilization,
                    "sm_utilization": sample.sm_utilization,
                    "hbm_utilization": sample.hbm_utilization,
                    "sm_occupancy": sample.sm_occupancy,
                    "tensor_active": sample.tensor_active,
                    "fp64_active": sample.fp64_active,
                    "fp32_active": sample.fp32_active,
                    "fp16_active": sample.fp16_active,
                    "gr_engine_active": sample.gr_engine_active,
                    # Memory
                    "memory_used_mb": sample.memory_used_mb,
                    "memory_total_mb": sample.memory_total_mb,
                    "memory_utilization": sample.memory_utilization,
                    # Clocks
                    "sm_clock_mhz": sample.sm_clock_mhz,
                    "memory_clock_mhz": sample.memory_clock_mhz,
                    # Power
                    "power_draw_watts": sample.power_draw_watts,
                    "power_limit_watts": sample.power_limit_watts,
                    # Temperature
                    "temperature_celsius": sample.temperature_celsius,
                    "memory_temperature_celsius": sample.memory_temperature_celsius,
                    # PCIe
                    "pcie_rx_mb_per_sec": sample.pcie_rx_mb_per_sec,
                    "pcie_tx_mb_per_sec": sample.pcie_tx_mb_per_sec,
                    "pcie_replay_errors": sample.pcie_replay_errors or 0,
                    # NVLink
                    "nvlink_rx_mb_per_sec": sample.nvlink_rx_mb_per_sec,
                    "nvlink_tx_mb_per_sec": sample.nvlink_tx_mb_per_sec,
                    "nvlink_bandwidth_total": sample.nvlink_bandwidth_total,
                    "nvlink_replay_errors": sample.nvlink_replay_errors or 0,
                    "nvlink_recovery_errors": sample.nvlink_recovery_errors or 0,
                    "nvlink_crc_errors": sample.nvlink_crc_errors or 0,
                    # ECC errors
                    "ecc_sbe_errors": sample.ecc_sbe_errors or 0,
                    "ecc_dbe_errors": sample.ecc_dbe_errors or 0,
                    "ecc_sbe_aggregate": sample.ecc_sbe_aggregate or 0,
                    "ecc_dbe_aggregate": sample.ecc_dbe_aggregate or 0,
                    # Throttle and health
                    "throttle_reasons": sample.throttle_reasons or 0,
                    "throttle_thermal": sample.throttle_thermal or 0,
                    "throttle_power": sample.throttle_power or 0,
                    "throttle_sw_power": sample.throttle_sw_power or 0,
                    "xid_errors": sample.xid_errors or 0,
                    # Configuration
                    "compute_mode": sample.compute_mode,
                    "persistence_mode": sample.persistence_mode,
                    "ecc_mode": sample.ecc_mode,
                    "power_min_limit": sample.power_min_limit,
                    "power_max_limit": sample.power_max_limit,
                    "slowdown_temp": sample.slowdown_temp,
                    "shutdown_temp": sample.shutdown_temp,
                    "total_energy_joules": sample.total_energy_joules,
                    # Retired pages
                    "retired_pages_sbe": sample.retired_pages_sbe or 0,
                    "retired_pages_dbe": sample.retired_pages_dbe or 0,
                    "retired_pages_pending": sample.retired_pages_pending or 0,
                    # Application-level token metrics (token exporter + vLLM /metrics)
                    "tokens_per_second": sample.tokens_per_second,
                    "requests_per_second": sample.requests_per_second,
                    "ttft_p50_ms": sample.ttft_p50_ms,
                    "ttft_p95_ms": sample.ttft_p95_ms,
                    "cost_per_watt": sample.cost_per_watt,
                    # vLLM live inference metrics
                    "prompt_tokens_per_second": sample.prompt_tokens_per_second,
                    "vllm_requests_running": sample.vllm_requests_running,
                    "vllm_requests_waiting": sample.vllm_requests_waiting,
                    "vllm_gpu_cache_usage": sample.vllm_gpu_cache_usage,
                    "vllm_cpu_cache_usage": sample.vllm_cpu_cache_usage,
                }
                for sample in chunk
            ]

            stmt = insert(GpuMetric).values(records)
            # Build comprehensive update dict for all fields
            update_fields = {col: getattr(stmt.excluded, col) for col in records[0].keys() if col not in ("time", "run_id", "gpu_id")}
            stmt = stmt.on_conflict_do_update(
                index_elements=[GpuMetric.time, GpuMetric.run_id, GpuMetric.gpu_id],
                set_=update_fields,
            )

            await self.session.execute(stmt)
            total_inserted += len(records)
        
        return total_inserted

    async def compute_run_summary(self, run_id: UUID) -> Optional[RunSummary]:
        run = await self.get_run(run_id)
        if not run:
            raise NoResultFound(f"Run {run_id} not found")

        metrics_stmt = (
            select(
                func.count().label("total_samples"),
                func.avg(GpuMetric.gpu_utilization).label("avg_gpu_utilization"),
                func.max(GpuMetric.gpu_utilization).label("max_gpu_utilization"),
                func.avg(GpuMetric.memory_utilization).label("avg_memory_utilization"),
                func.avg(GpuMetric.power_draw_watts).label("avg_power_draw_watts"),
                func.max(GpuMetric.power_draw_watts).label("max_power_draw_watts"),
                func.avg(GpuMetric.temperature_celsius).label("avg_temperature"),
                func.max(GpuMetric.temperature_celsius).label("max_temperature"),
            )
            .where(GpuMetric.run_id == run_id)
            .group_by(GpuMetric.run_id)
        )

        result = await self.session.execute(metrics_stmt)
        row = result.one_or_none()
        if not row:
            return None

        duration_seconds: Optional[float] = None
        if run.start_time and run.end_time:
            duration_seconds = (
                run.end_time - run.start_time
            ).total_seconds()

        total_energy_wh: Optional[float] = None
        avg_power = row.avg_power_draw_watts
        if avg_power is not None and duration_seconds:
            total_energy_wh = avg_power * duration_seconds / 3600.0

        summary_data = {
            "run_id": run_id,
            "duration_seconds": duration_seconds,
            "total_samples": row.total_samples,
            "avg_gpu_utilization": row.avg_gpu_utilization,
            "max_gpu_utilization": row.max_gpu_utilization,
            "avg_memory_utilization": row.avg_memory_utilization,
            "avg_power_draw_watts": row.avg_power_draw_watts,
            "max_power_draw_watts": row.max_power_draw_watts,
            "total_energy_wh": total_energy_wh,
            "avg_temperature": row.avg_temperature,
            "max_temperature": row.max_temperature,
        }

        stmt = (
            insert(RunSummary)
            .values(**summary_data)
            .on_conflict_do_update(
                index_elements=[RunSummary.run_id],
                set_={key: summary_data[key] for key in summary_data if key != "run_id"},
            )
            .returning(RunSummary)
        )

        summary_result = await self.session.execute(stmt)
        return summary_result.scalar_one()

    async def fetch_metrics(
        self,
        run_id: UUID,
        *,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        gpu_id: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[GpuMetric]:
        stmt: Select[tuple[GpuMetric]] = select(GpuMetric).where(GpuMetric.run_id == run_id)
        if start_time:
            stmt = stmt.where(GpuMetric.time >= start_time)
        if end_time:
            stmt = stmt.where(GpuMetric.time <= end_time)
        if gpu_id is not None:
            stmt = stmt.where(GpuMetric.gpu_id == gpu_id)
        stmt = stmt.order_by(GpuMetric.time.asc())
        if limit:
            stmt = stmt.limit(limit)

        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def get_run_metric_count(self, run_id: UUID) -> int:
        """Get the count of metric samples for a run."""
        stmt = select(func.count()).where(GpuMetric.run_id == run_id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def list_runs_with_no_data(self, user_id: Optional[UUID] = None) -> List[Run]:
        """Get all runs that have no metric data."""
        # Subquery to get run_ids that have metrics
        runs_with_metrics = select(GpuMetric.run_id).distinct()
        
        # Select runs that are NOT in the runs_with_metrics set
        stmt = (
            select(Run)
            .options(selectinload(Run.summary))
            .where(Run.run_id.not_in(runs_with_metrics))
        )
        if user_id:
            stmt = stmt.where(Run.user_id == user_id)
        stmt = stmt.order_by(Run.start_time.desc())
        
        result = await self.session.execute(stmt)
        return list(result.scalars().unique())

    async def bulk_delete_runs_with_no_data(self, user_id: Optional[UUID] = None) -> int:
        """Delete all runs that have no metric data. Returns count of deleted runs."""
        # Subquery to get run_ids that have metrics
        runs_with_metrics = select(GpuMetric.run_id).distinct()
        
        # Delete runs that are NOT in the runs_with_metrics set
        stmt = delete(Run).where(Run.run_id.not_in(runs_with_metrics))
        if user_id:
            stmt = stmt.where(Run.user_id == user_id)
        
        result = await self.session.execute(stmt)
        return result.rowcount

    async def bulk_update_runs_status(self, status: str, user_id: Optional[UUID] = None, instance_id: Optional[str] = None) -> int:
        """Bulk update run statuses. Returns count of updated runs."""
        stmt = update(Run).values(status=status)
        if user_id:
            stmt = stmt.where(Run.user_id == user_id)
        if instance_id:
            stmt = stmt.where(Run.instance_id == instance_id)
        result = await self.session.execute(stmt)
        return result.rowcount

    # Deployment job methods
    async def create_deployment_job(self, payload: DeploymentJobCreate) -> DeploymentJob:
        """Create a new deployment job."""
        job = DeploymentJob(
            instance_id=payload.instance_id,
            run_id=payload.run_id,
            deployment_type=payload.deployment_type,
            status="pending",
            priority=payload.priority,
            max_attempts=payload.max_attempts,
            payload=payload.payload,
        )
        self.session.add(job)
        await self.session.flush()
        await self.session.refresh(job)
        return job

    async def get_deployment_job(self, job_id: UUID) -> Optional[DeploymentJob]:
        """Get a deployment job by ID."""
        stmt = select(DeploymentJob).where(DeploymentJob.job_id == job_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_deployment_jobs(
        self,
        instance_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[DeploymentJob]:
        """List deployment jobs with optional filters."""
        stmt = select(DeploymentJob).order_by(DeploymentJob.created_at.desc())
        if instance_id:
            stmt = stmt.where(DeploymentJob.instance_id == instance_id)
        if status:
            stmt = stmt.where(DeploymentJob.status == status)
        stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().unique())

    async def update_deployment_job(
        self,
        job_id: UUID,
        payload: DeploymentJobUpdate,
    ) -> Optional[DeploymentJob]:
        """Update a deployment job."""
        data = payload.model_dump(exclude_unset=True)
        if not data:
            return await self.get_deployment_job(job_id)

        data["updated_at"] = datetime.now(timezone.utc)
        stmt = (
            update(DeploymentJob)
            .where(DeploymentJob.job_id == job_id)
            .values(**data)
            .returning(DeploymentJob)
        )
        result = await self.session.execute(stmt)
        job = result.scalar_one_or_none()
        if job:
            await self.session.flush()
        return job

    # Provisioning manifest methods
    async def create_provisioning_manifest(
        self,
        payload: ProvisioningManifestCreate,
    ) -> ProvisioningManifest:
        """Create a provisioning manifest."""
        manifest = ProvisioningManifest(
            deployment_job_id=payload.deployment_job_id,
            instance_id=payload.instance_id,
            token_hash="",  # Will be set by caller after hashing
            manifest_data=payload.manifest_data,
            expires_at=payload.expires_at,
        )
        self.session.add(manifest)
        await self.session.flush()
        await self.session.refresh(manifest)
        return manifest

    async def get_provisioning_manifest(
        self,
        manifest_id: UUID,
    ) -> Optional[ProvisioningManifest]:
        """Get a provisioning manifest by ID."""
        stmt = select(ProvisioningManifest).where(
            ProvisioningManifest.manifest_id == manifest_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_provisioning_manifest_by_token_hash(
        self,
        token_hash: str,
    ) -> Optional[ProvisioningManifest]:
        """Get a provisioning manifest by token hash."""
        stmt = select(ProvisioningManifest).where(
            ProvisioningManifest.token_hash == token_hash,
            ProvisioningManifest.expires_at > datetime.now(timezone.utc),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    # Agent heartbeat methods
    async def create_agent_heartbeat(
        self,
        payload: AgentHeartbeatCreate,
    ) -> AgentHeartbeat:
        """Create an agent heartbeat."""
        heartbeat = AgentHeartbeat(
            manifest_id=payload.manifest_id,  # Can be None for API key-based heartbeats
            instance_id=payload.instance_id,
            agent_version=payload.agent_version,
            phase=payload.phase,
            status=payload.status,
            message=payload.message,
            heartbeat_metadata=payload.metadata,
        )
        self.session.add(heartbeat)
        await self.session.flush()
        await self.session.refresh(heartbeat)
        return heartbeat

    async def get_latest_heartbeat(
        self,
        manifest_id: UUID,
    ) -> Optional[AgentHeartbeat]:
        """Get the latest heartbeat for a manifest."""
        stmt = (
            select(AgentHeartbeat)
            .where(AgentHeartbeat.manifest_id == manifest_id)
            .order_by(AgentHeartbeat.timestamp.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_heartbeat_by_instance(
        self,
        instance_id: str,
    ) -> Optional[AgentHeartbeat]:
        """Get the latest heartbeat for an instance."""
        stmt = (
            select(AgentHeartbeat)
            .where(AgentHeartbeat.instance_id == instance_id)
            .order_by(AgentHeartbeat.timestamp.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    # API Key methods
    async def create_provisioning_api_key(
        self,
        key_hash: str,
        name: str,
        user_id: UUID,
        description: Optional[str] = None,
    ) -> ProvisioningAPIKey:
        """Create a new provisioning API key."""
        api_key = ProvisioningAPIKey(
            key_hash=key_hash,
            name=name,
            user_id=user_id,
            description=description,
        )
        self.session.add(api_key)
        await self.session.flush()
        await self.session.refresh(api_key)
        return api_key

    async def get_provisioning_api_key_by_hash(
        self,
        key_hash: str,
    ) -> Optional[ProvisioningAPIKey]:
        """Get an API key by its hash."""
        stmt = select(ProvisioningAPIKey).where(
            ProvisioningAPIKey.key_hash == key_hash,
            ProvisioningAPIKey.revoked_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_provisioning_api_key(
        self,
        key_id: UUID,
    ) -> Optional[ProvisioningAPIKey]:
        """Get an API key by ID."""
        stmt = select(ProvisioningAPIKey).where(ProvisioningAPIKey.key_id == key_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_provisioning_api_keys(
        self,
        include_revoked: bool = False,
    ) -> List[ProvisioningAPIKey]:
        """List all API keys."""
        stmt = select(ProvisioningAPIKey).order_by(ProvisioningAPIKey.created_at.desc())
        if not include_revoked:
            stmt = stmt.where(ProvisioningAPIKey.revoked_at.is_(None))
        result = await self.session.execute(stmt)
        return list(result.scalars().unique())

    async def revoke_provisioning_api_key(
        self,
        key_id: UUID,
    ) -> Optional[ProvisioningAPIKey]:
        """Revoke an API key."""
        stmt = (
            update(ProvisioningAPIKey)
            .where(ProvisioningAPIKey.key_id == key_id)
            .values(revoked_at=datetime.now(timezone.utc))
            .returning(ProvisioningAPIKey)
        )
        result = await self.session.execute(stmt)
        key = result.scalar_one_or_none()
        if key:
            await self.session.flush()
        return key

    async def update_api_key_last_used(
        self,
        key_hash: str,
    ) -> None:
        """Update the last_used_at timestamp for an API key."""
        stmt = (
            update(ProvisioningAPIKey)
            .where(ProvisioningAPIKey.key_hash == key_hash)
            .values(last_used_at=datetime.now(timezone.utc))
        )
        await self.session.execute(stmt)


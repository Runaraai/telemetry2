"""SQLAlchemy models for telemetry domain."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, MetaData, String, Text, DateTime, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func, text

from .config import get_settings


settings = get_settings()


class Base(DeclarativeBase):
    """Declarative base with shared metadata."""

    metadata = MetaData(schema=settings.db_schema)


class Run(Base):
    """Monitored GPU run metadata."""

    __tablename__ = "runs"
    __table_args__ = (
        Index("idx_runs_instance", "instance_id"),
        Index("idx_runs_provider", "provider"),
        Index("idx_runs_start_time", text("start_time DESC")),
        Index("idx_runs_status", "status"),
        Index("idx_runs_instance_status", "instance_id", "status"),  # Composite index for common query pattern
    )

    run_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[Optional[str]] = mapped_column(String(50))
    gpu_model: Mapped[Optional[str]] = mapped_column(String(50))
    gpu_count: Mapped[Optional[int]]
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    run_type: Mapped[Optional[str]] = mapped_column(String(20), default="monitoring")
    tags: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    notes: Mapped[Optional[str]] = mapped_column(Text())
    gpu_summary: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    # Token hash for remote_write authentication (SHA256 of the token)
    # Token is generated on run creation and returned once to the user
    ingest_token_hash: Mapped[Optional[str]] = mapped_column(String(64))
    # Timestamp when the current token was created/regenerated
    token_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    metrics: Mapped[List["GpuMetric"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    summary: Mapped[Optional["RunSummary"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    workload: Mapped[Optional["WorkloadMetrics"]] = relationship(
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    kernel_profiles: Mapped[List["KernelProfile"]] = relationship(
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    bottleneck: Mapped[Optional["BottleneckAnalysis"]] = relationship(
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class GpuMetric(Base):
    """Individual GPU metric sample with comprehensive DCGM metrics."""

    __tablename__ = "gpu_metrics"
    __table_args__ = (
        Index("idx_gpu_metrics_run_id", "run_id", text("time DESC")),
        Index("idx_gpu_metrics_gpu_id", "run_id", "gpu_id", text("time DESC")),
    )

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    )
    gpu_id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Core utilization
    gpu_utilization: Mapped[Optional[float]] = mapped_column(Float)
    sm_utilization: Mapped[Optional[float]] = mapped_column(Float)
    hbm_utilization: Mapped[Optional[float]] = mapped_column(Float)
    sm_occupancy: Mapped[Optional[float]] = mapped_column(Float)
    tensor_active: Mapped[Optional[float]] = mapped_column(Float)
    fp64_active: Mapped[Optional[float]] = mapped_column(Float)
    fp32_active: Mapped[Optional[float]] = mapped_column(Float)
    fp16_active: Mapped[Optional[float]] = mapped_column(Float)
    gr_engine_active: Mapped[Optional[float]] = mapped_column(Float)
    # Memory
    memory_used_mb: Mapped[Optional[float]] = mapped_column(Float)
    memory_total_mb: Mapped[Optional[float]] = mapped_column(Float)
    memory_utilization: Mapped[Optional[float]] = mapped_column(Float)
    # Clocks
    sm_clock_mhz: Mapped[Optional[float]] = mapped_column(Float)
    memory_clock_mhz: Mapped[Optional[float]] = mapped_column(Float)
    # Power
    power_draw_watts: Mapped[Optional[float]] = mapped_column(Float)
    power_limit_watts: Mapped[Optional[float]] = mapped_column(Float)
    # Temperature
    temperature_celsius: Mapped[Optional[float]] = mapped_column(Float)
    memory_temperature_celsius: Mapped[Optional[float]] = mapped_column(Float)
    # PCIe
    pcie_rx_mb_per_sec: Mapped[Optional[float]] = mapped_column(Float)
    pcie_tx_mb_per_sec: Mapped[Optional[float]] = mapped_column(Float)
    pcie_replay_errors: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # NVLink
    nvlink_rx_mb_per_sec: Mapped[Optional[float]] = mapped_column(Float)
    nvlink_tx_mb_per_sec: Mapped[Optional[float]] = mapped_column(Float)
    nvlink_bandwidth_total: Mapped[Optional[float]] = mapped_column(Float)
    nvlink_replay_errors: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    nvlink_recovery_errors: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    nvlink_crc_errors: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # ECC errors
    ecc_sbe_errors: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    ecc_dbe_errors: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    ecc_sbe_aggregate: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    ecc_dbe_aggregate: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Throttle and health
    throttle_reasons: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    throttle_thermal: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    throttle_power: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    throttle_sw_power: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    xid_errors: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Configuration
    compute_mode: Mapped[Optional[int]] = mapped_column(Integer)
    persistence_mode: Mapped[Optional[int]] = mapped_column(Integer)
    ecc_mode: Mapped[Optional[int]] = mapped_column(Integer)
    power_min_limit: Mapped[Optional[float]] = mapped_column(Float)
    power_max_limit: Mapped[Optional[float]] = mapped_column(Float)
    slowdown_temp: Mapped[Optional[float]] = mapped_column(Float)
    shutdown_temp: Mapped[Optional[float]] = mapped_column(Float)
    total_energy_joules: Mapped[Optional[float]] = mapped_column(Float)
    # Retired pages
    retired_pages_sbe: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    retired_pages_dbe: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    retired_pages_pending: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    run: Mapped[Run] = relationship(back_populates="metrics")


class RunSummary(Base):
    """Aggregated statistics for a completed run."""

    __tablename__ = "run_summaries"

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)
    total_samples: Mapped[Optional[int]] = mapped_column(Integer)
    avg_gpu_utilization: Mapped[Optional[float]] = mapped_column(Float)
    max_gpu_utilization: Mapped[Optional[float]] = mapped_column(Float)
    avg_memory_utilization: Mapped[Optional[float]] = mapped_column(Float)
    avg_power_draw_watts: Mapped[Optional[float]] = mapped_column(Float)
    max_power_draw_watts: Mapped[Optional[float]] = mapped_column(Float)
    total_energy_wh: Mapped[Optional[float]] = mapped_column(Float)
    avg_temperature: Mapped[Optional[float]] = mapped_column(Float)
    max_temperature: Mapped[Optional[float]] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    run: Mapped[Run] = relationship(back_populates="summary")


class GpuPolicyEvent(Base):
    """Policy violation and alert events."""

    __tablename__ = "gpu_policy_events"
    __table_args__ = (
        Index("idx_policy_events_run_id", "run_id", text("event_time DESC")),
        Index("idx_policy_events_severity", "run_id", "severity", text("event_time DESC")),
    )

    event_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    gpu_id: Mapped[int] = mapped_column(Integer, nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'thermal', 'power', 'ecc', 'throttle', 'xid'
    severity: Mapped[str] = mapped_column(String(20), nullable=False)  # 'info', 'warning', 'critical'
    message: Mapped[str] = mapped_column(Text(), nullable=False)
    metric_value: Mapped[Optional[float]] = mapped_column(Float)
    threshold_value: Mapped[Optional[float]] = mapped_column(Float)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class GpuTopology(Base):
    """GPU topology and connectivity information."""

    __tablename__ = "gpu_topology"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_topology_run"),
    )

    topology_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    topology_data: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class StoredCredential(Base):
    """Encrypted credential storage for provider/API/SSH secrets."""

    __tablename__ = "credential_store"
    __table_args__ = (
        UniqueConstraint("provider", "name", "credential_type", "user_id", name="uq_credential_provider_name_type_user"),
    )

    credential_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    credential_type: Mapped[str] = mapped_column(String(50), nullable=False)
    secret_ciphertext: Mapped[str] = mapped_column(Text(), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text())
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        server_onupdate=func.now(),
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class SMProfilingSession(Base):
    """Nsight Compute profiling session metadata."""

    __tablename__ = "sm_profiling_sessions"
    __table_args__ = (
        Index("idx_sm_profiling_run_id", "run_id"),
        Index("idx_sm_profiling_status", "status"),
    )

    session_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False)
    gpu_id: Mapped[int] = mapped_column(Integer, nullable=False)
    metric_names: Mapped[List[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # pending, running, completed, failed
    ncu_command: Mapped[Optional[str]] = mapped_column(Text())
    error_message: Mapped[Optional[str]] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class SMMetric(Base):
    """Per-SM metric values from profiling."""

    __tablename__ = "sm_metrics"
    __table_args__ = (
        Index("idx_sm_metrics_session", "session_id"),
        Index("idx_sm_metrics_sm_id", "sm_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("sm_profiling_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    sm_id: Mapped[int] = mapped_column(Integer, nullable=False)  # SM index (0-107 for H100)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class InstanceOrchestration(Base):
    """Instance launch and setup orchestration tracking."""

    __tablename__ = "instance_orchestrations"
    __table_args__ = (
        Index("idx_orchestration_instance", "instance_id"),
        Index("idx_orchestration_status", "status"),
        Index("idx_orchestration_instance_status", "instance_id", "status"),
    )

    orchestration_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # launching, waiting_ip, setting_up, deploying_model, ready, failed
    current_phase: Mapped[str] = mapped_column(String(50), nullable=False)  # launch, setup, model_deploy
    progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))  # 0-100
    ip_address: Mapped[Optional[str]] = mapped_column(String(50))
    ssh_user: Mapped[str] = mapped_column(String(50), nullable=False, server_default="ubuntu")
    ssh_key_name: Mapped[str] = mapped_column(String(100), nullable=False)  # Required for instance orchestration
    model_deployed: Mapped[Optional[str]] = mapped_column(String(100))
    vllm_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    error_message: Mapped[Optional[str]] = mapped_column(Text())
    logs: Mapped[Optional[str]] = mapped_column(Text())
    config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class DeploymentJob(Base):
    """Deployment job queue for SSH-based deployments with retry logic."""

    __tablename__ = "deployment_jobs"
    __table_args__ = (
        Index("idx_deployment_jobs_instance", "instance_id"),
        Index("idx_deployment_jobs_status", "status"),
        Index("idx_deployment_jobs_created", text("created_at DESC")),
        Index("idx_deployment_jobs_instance_status", "instance_id", "status"),
        Index("idx_deployment_jobs_run_status", "run_id", "status"),
    )

    job_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    deployment_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ssh")  # ssh, agent
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # pending, queued, running, completed, failed, cancelled
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))  # Higher = more priority
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)  # DeploymentRequest serialized
    error_message: Mapped[Optional[str]] = mapped_column(Text())
    error_log: Mapped[Optional[str]] = mapped_column(Text())  # Full error traceback
    locked_by: Mapped[Optional[str]] = mapped_column(String(255))  # Worker identifier
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProvisioningManifest(Base):
    """Manifest-driven provisioning configuration for agent-based deployments."""

    __tablename__ = "provisioning_manifests"
    __table_args__ = (
        Index("idx_provisioning_manifests_deployment", "deployment_job_id"),
        Index("idx_provisioning_manifests_token", "token_hash"),
        Index("idx_provisioning_manifests_expires", "expires_at"),
    )

    manifest_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    deployment_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("deployment_jobs.job_id", ondelete="CASCADE"),
        nullable=False,
    )
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)  # SHA256 of token
    manifest_data: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)  # Full manifest JSON
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AgentHeartbeat(Base):
    """Agent heartbeat and status updates from provisioning agents."""

    __tablename__ = "agent_heartbeats"
    __table_args__ = (
        Index("idx_agent_heartbeats_instance", "instance_id"),
        Index("idx_agent_heartbeats_manifest", "manifest_id"),
        Index("idx_agent_heartbeats_timestamp", text("timestamp DESC")),
    )

    heartbeat_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    manifest_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("provisioning_manifests.manifest_id", ondelete="CASCADE"),
        nullable=True,  # Nullable for API key-based heartbeats
    )
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(50), nullable=False)
    phase: Mapped[str] = mapped_column(String(50), nullable=False)  # installing, deploying, running, failed
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # healthy, error, warning
    message: Mapped[Optional[str]] = mapped_column(Text())
    heartbeat_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column("metadata", JSON)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ProvisioningAPIKey(Base):
    """API keys for agent-based provisioning (long-lived, revocable)."""

    __tablename__ = "provisioning_api_keys"
    __table_args__ = (
        Index("idx_provisioning_api_keys_key_hash", "key_hash"),
        Index("idx_provisioning_api_keys_revoked", "revoked_at"),
    )

    key_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)  # SHA256 of API key
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # User-friendly name
    description: Mapped[Optional[str]] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class WorkloadMetrics(Base):
    """Workload-level inference profiling metrics for a run."""

    __tablename__ = "workload_metrics"

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    model_name: Mapped[Optional[str]] = mapped_column(String(255))
    server_url: Mapped[Optional[str]] = mapped_column(String(500))
    concurrency: Mapped[Optional[int]] = mapped_column(Integer)
    num_requests: Mapped[Optional[int]] = mapped_column(Integer)
    successful_requests: Mapped[Optional[int]] = mapped_column(Integer)
    failed_requests: Mapped[Optional[int]] = mapped_column(Integer)
    duration_s: Mapped[Optional[float]] = mapped_column(Float)
    # TTFT (time-to-first-token) in milliseconds
    ttft_mean_ms: Mapped[Optional[float]] = mapped_column(Float)
    ttft_p50_ms: Mapped[Optional[float]] = mapped_column(Float)
    ttft_p95_ms: Mapped[Optional[float]] = mapped_column(Float)
    ttft_p99_ms: Mapped[Optional[float]] = mapped_column(Float)
    # TPOT (time-per-output-token) in milliseconds
    tpot_mean_ms: Mapped[Optional[float]] = mapped_column(Float)
    tpot_p50_ms: Mapped[Optional[float]] = mapped_column(Float)
    tpot_p95_ms: Mapped[Optional[float]] = mapped_column(Float)
    tpot_p99_ms: Mapped[Optional[float]] = mapped_column(Float)
    # E2E latency in milliseconds
    e2e_latency_mean_ms: Mapped[Optional[float]] = mapped_column(Float)
    e2e_latency_p99_ms: Mapped[Optional[float]] = mapped_column(Float)
    # Throughput
    throughput_req_sec: Mapped[Optional[float]] = mapped_column(Float)
    throughput_tok_sec: Mapped[Optional[float]] = mapped_column(Float)
    total_input_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    total_output_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class KernelProfile(Base):
    """CUDA kernel profiling breakdown for a run."""

    __tablename__ = "kernel_profiles"

    profile_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    total_cuda_ms: Mapped[Optional[float]] = mapped_column(Float)
    total_flops: Mapped[Optional[float]] = mapped_column(Float)
    estimated_tflops: Mapped[Optional[float]] = mapped_column(Float)
    profiled_requests: Mapped[Optional[str]] = mapped_column(String(50))
    trace_source: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    categories: Mapped[List["KernelCategory"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class KernelCategory(Base):
    """Individual CUDA kernel category timing within a profile."""

    __tablename__ = "kernel_categories"
    __table_args__ = (
        Index("idx_kernel_categories_profile", "profile_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("kernel_profiles.profile_id", ondelete="CASCADE"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    total_ms: Mapped[float] = mapped_column(Float, nullable=False)
    pct: Mapped[float] = mapped_column(Float, nullable=False)
    kernel_count: Mapped[int] = mapped_column(Integer, nullable=False)

    profile: Mapped[KernelProfile] = relationship(back_populates="categories")


class BottleneckAnalysis(Base):
    """Bottleneck classification and efficiency analysis for a run."""

    __tablename__ = "bottleneck_analyses"

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    primary_bottleneck: Mapped[str] = mapped_column(String(20), nullable=False)
    compute_util_pct: Mapped[Optional[float]] = mapped_column(Float)
    sm_active_mean_pct: Mapped[Optional[float]] = mapped_column(Float)
    memory_bw_util_pct: Mapped[Optional[float]] = mapped_column(Float)
    hbm_bw_mean_gbps: Mapped[Optional[float]] = mapped_column(Float)
    cpu_overhead_estimated_pct: Mapped[Optional[float]] = mapped_column(Float)
    nvlink_util_pct: Mapped[Optional[float]] = mapped_column(Float)
    arithmetic_intensity: Mapped[Optional[float]] = mapped_column(Float)
    roofline_bound: Mapped[Optional[str]] = mapped_column(String(20))
    mfu_pct: Mapped[Optional[float]] = mapped_column(Float)
    actual_tflops: Mapped[Optional[float]] = mapped_column(Float)
    peak_tflops_bf16: Mapped[Optional[float]] = mapped_column(Float)
    recommendations: Mapped[Optional[List[str]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class User(Base):
    """User accounts for API authentication."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_user_email"),
    )

    user_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

"""Pydantic schemas for telemetry APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator
from pydantic.config import ConfigDict


class RunBase(BaseModel):
    """Shared fields between run create/update schemas."""

    instance_id: str = Field(..., max_length=255)
    provider: Optional[str] = Field(None, max_length=50)
    gpu_model: Optional[str] = Field(None, max_length=50)
    gpu_count: Optional[int] = Field(None, ge=0)
    tags: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class RunCreate(RunBase):
    """Schema for creating a new run."""

    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = Field(default="active", max_length=20)


class RunUpdate(BaseModel):
    """Schema for updating an existing run."""

    status: Optional[str] = Field(None, max_length=20)
    provider: Optional[str] = Field(None, max_length=50)
    end_time: Optional[datetime] = None
    tags: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None

    @field_validator("end_time", mode="before")
    def validate_end_time(cls, value: Optional[datetime]) -> Optional[datetime]:  # noqa: D417,E0213
        if value is None:
            return None
        if isinstance(value, str):
            try:
                # Handle 'Z' suffix which represents UTC
                if value.endswith('Z'):
                    value = value[:-1] + '+00:00'
                value = datetime.fromisoformat(value)
            except ValueError as exc:  # pragma: no cover - defensive path
                raise ValueError("end_time must be a valid ISO-8601 datetime string") from exc
        if value.tzinfo is None:
            raise ValueError("end_time must be timezone-aware (TIMESTAMPTZ)")
        return value


class RunRead(RunBase):
    """Schema returned for run detail."""

    run_id: UUID
    start_time: datetime
    end_time: Optional[datetime]
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RunSummaryRead(BaseModel):
    """Summary statistics for a run."""

    duration_seconds: Optional[float]
    total_samples: Optional[int]
    avg_gpu_utilization: Optional[float]
    max_gpu_utilization: Optional[float]
    avg_memory_utilization: Optional[float]
    avg_power_draw_watts: Optional[float]
    max_power_draw_watts: Optional[float]
    total_energy_wh: Optional[float]
    avg_temperature: Optional[float]
    max_temperature: Optional[float]
    computed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RunDetail(RunRead):
    """Run detail including optional summary."""

    summary: Optional[RunSummaryRead]


class RunCreateResponse(RunDetail):
    """Response for run creation, includes one-time ingest token.
    
    IMPORTANT: The ingest_token is only returned once at creation time.
    Store it securely - it cannot be retrieved again.
    """

    ingest_token: str = Field(
        ...,
        description="One-time token for authenticating remote_write requests. "
                    "Include this in the X-Ingest-Token header. "
                    "This token is only shown once - store it securely."
    )


class RunListResponse(BaseModel):
    """Paginated run list response."""

    runs: List[RunDetail]


class MetricSample(BaseModel):
    """Single GPU metric sample with comprehensive DCGM metrics."""

    time: datetime
    gpu_id: int = Field(..., ge=0)
    # Core utilization
    gpu_utilization: Optional[float] = None
    sm_utilization: Optional[float] = None
    hbm_utilization: Optional[float] = None
    sm_occupancy: Optional[float] = None
    tensor_active: Optional[float] = None
    fp64_active: Optional[float] = None
    fp32_active: Optional[float] = None
    fp16_active: Optional[float] = None
    gr_engine_active: Optional[float] = None
    encoder_utilization: Optional[float] = None
    decoder_utilization: Optional[float] = None
    # Memory
    memory_used_mb: Optional[float] = None
    memory_total_mb: Optional[float] = None
    memory_utilization: Optional[float] = None
    # Clocks
    sm_clock_mhz: Optional[float] = None
    memory_clock_mhz: Optional[float] = None
    # Power
    power_draw_watts: Optional[float] = None
    power_limit_watts: Optional[float] = None
    # Temperature
    temperature_celsius: Optional[float] = None
    memory_temperature_celsius: Optional[float] = None
    slowdown_temperature_celsius: Optional[float] = None
    # PCIe
    pcie_rx_mb_per_sec: Optional[float] = None
    pcie_tx_mb_per_sec: Optional[float] = None
    pcie_replay_errors: Optional[int] = Field(default=0, ge=0)
    # NVLink
    nvlink_rx_mb_per_sec: Optional[float] = None
    nvlink_tx_mb_per_sec: Optional[float] = None
    nvlink_bandwidth_total: Optional[float] = None
    nvlink_replay_errors: Optional[int] = Field(default=0, ge=0)
    nvlink_recovery_errors: Optional[int] = Field(default=0, ge=0)
    nvlink_crc_errors: Optional[int] = Field(default=0, ge=0)
    # ECC errors
    ecc_sbe_errors: Optional[int] = Field(default=0, ge=0)
    ecc_dbe_errors: Optional[int] = Field(default=0, ge=0)
    ecc_sbe_aggregate: Optional[int] = Field(default=0, ge=0)
    ecc_dbe_aggregate: Optional[int] = Field(default=0, ge=0)
    # Throttle and health
    throttle_reasons: Optional[int] = Field(default=0, ge=0)
    throttle_thermal: Optional[int] = Field(default=0, ge=0)
    throttle_power: Optional[int] = Field(default=0, ge=0)
    throttle_sw_power: Optional[int] = Field(default=0, ge=0)
    xid_errors: Optional[int] = Field(default=0, ge=0)
    # Configuration
    compute_mode: Optional[int] = None
    persistence_mode: Optional[int] = None
    ecc_mode: Optional[int] = None
    power_min_limit: Optional[float] = None
    power_max_limit: Optional[float] = None
    slowdown_temp: Optional[float] = None
    shutdown_temp: Optional[float] = None
    total_energy_joules: Optional[float] = None
    # Additional metrics
    fan_speed_percent: Optional[float] = None
    pstate: Optional[int] = None
    # Retired pages
    retired_pages_sbe: Optional[int] = Field(default=0, ge=0)
    retired_pages_dbe: Optional[int] = Field(default=0, ge=0)
    retired_pages_pending: Optional[int] = Field(default=0, ge=0)
    # Application-level token metrics (not GPU-specific, but stored per GPU for consistency)
    tokens_per_second: Optional[float] = None
    requests_per_second: Optional[float] = None
    ttft_p50_ms: Optional[float] = None
    ttft_p95_ms: Optional[float] = None
    cost_per_watt: Optional[float] = None

    @field_validator("time", mode="before")
    def validate_time(cls, value: datetime) -> datetime:  # noqa: D417,E0213
        if value.tzinfo is None:
            raise ValueError("time must be timezone-aware (TIMESTAMPTZ)")
        return value


class MetricsBatch(BaseModel):
    """Batch of GPU metrics for ingestion."""

    run_id: UUID
    metrics: List[MetricSample]


class MetricsQuery(BaseModel):
    """Query parameters for metrics retrieval."""

    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    gpu_id: Optional[int] = Field(default=None, ge=0)
    downsample: Optional[str] = Field(default=None)


class MetricsResponse(BaseModel):
    """Response payload for metrics queries."""

    run_id: UUID
    metrics: List[MetricSample]


class PrerequisiteItem(BaseModel):
    """Represents a single infrastructure prerequisite."""

    id: str
    title: str
    description: str
    verify_command: Optional[str] = None
    install_hint: Optional[str] = None
    docs_link: Optional[str] = None


class PrerequisitesResponse(BaseModel):
    """List of prerequisites the host should satisfy before deployment."""

    prerequisites: List[PrerequisiteItem]


class CredentialBase(BaseModel):
    provider: str = Field(..., max_length=50)
    name: str = Field(..., max_length=100)
    credential_type: str = Field(..., max_length=50)
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class CredentialCreate(CredentialBase):
    secret: str = Field(..., min_length=1)


class CredentialUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    secret: Optional[str] = Field(default=None, min_length=1)


class CredentialDetail(CredentialBase):
    credential_id: UUID
    created_at: datetime
    updated_at: datetime
    last_used_at: Optional[datetime] = None
    secret_available: bool = True
    secret_preview: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CredentialWithSecret(CredentialDetail):
    secret: str


class DeploymentRequest(BaseModel):
    """Request payload for starting monitoring deployment."""

    run_id: UUID
    ssh_host: Optional[str] = Field(None, description="SSH host (required for SSH deployment, not needed for agent)")
    ssh_user: Optional[str] = Field(None, description="SSH user (required for SSH deployment, not needed for agent)")
    ssh_key: Optional[str] = Field(None, description="SSH private key (required for SSH deployment, not needed for agent)")
    backend_url: str
    ssh_port: int = Field(default=22, ge=1, le=65535)
    poll_interval: int = Field(default=5, ge=1)
    enable_profiling: bool = Field(
        default=False,
        description="Enable DCGM profiling mode for detailed SM/Tensor/DRAM metrics. "
                    "Requires user consent due to performance overhead and elevated privileges."
    )

    @field_validator("backend_url", mode="after")
    def validate_backend_url(cls, value: str) -> str:  # noqa: D417,E0213
        cleaned = value.strip()
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("backend_url must be a valid HTTP or HTTPS URL")

        host = parsed.hostname.lower()
        if host in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("backend_url must be reachable from the remote host; use a routable address instead of localhost")

        return cleaned.rstrip("/")


class DeploymentResponse(BaseModel):
    """Response payload after initiating deployment."""

    deployment_id: UUID
    run_id: UUID  # Include run_id so frontend knows which run to use
    status: str
    message: Optional[str] = None


class DeploymentStatusResponse(BaseModel):
    """Deployment status lookup response."""

    deployment_id: UUID
    status: str
    message: Optional[str] = None
    services: Optional[Dict[str, str]] = None
    updated_at: datetime


class TeardownRequest(BaseModel):
    """Request payload for tearing down monitoring stack."""

    run_id: UUID
    preserve_data: bool = False


class PolicyEventRead(BaseModel):
    """Policy event response schema."""

    event_id: UUID
    run_id: UUID
    gpu_id: int
    event_time: datetime
    event_type: str
    severity: str
    message: str
    metric_value: Optional[float]
    threshold_value: Optional[float]
    metadata_json: Optional[Dict[str, Any]] = Field(alias="metadata")
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PolicyEventsResponse(BaseModel):
    """Response for policy events query."""

    events: List[PolicyEventRead]


class TopologyRead(BaseModel):
    """GPU topology response schema."""

    topology_id: UUID
    run_id: UUID
    topology_data: Dict[str, Any]
    captured_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TopologyCreate(BaseModel):
    """Create topology snapshot."""

    run_id: UUID
    topology_data: Dict[str, Any]


class HealthSummary(BaseModel):
    """Health summary for a run."""

    run_id: UUID
    gpu_count: int
    active_throttles: int
    ecc_errors_total: int
    xid_errors_total: int
    recent_policy_events: int
    overall_status: str  # 'healthy', 'warning', 'critical'


class InstanceOrchestrationRequest(BaseModel):
    """Request schema for launching and orchestrating instance setup."""

    instance_type: str
    region: str
    ssh_key_name: str
    ssh_key: str  # SSH private key content
    model_name: Optional[str] = None  # Optional: pre-select model for deployment
    vllm_config: Optional[Dict[str, Any]] = None


class InstanceOrchestrationStatus(BaseModel):
    """Response schema for instance orchestration status."""

    orchestration_id: UUID
    instance_id: str
    status: str
    current_phase: str
    progress: int
    ip_address: Optional[str] = None
    ssh_user: str
    ssh_key_name: str  # Add missing field
    model_deployed: Optional[str] = None
    vllm_config: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    logs: Optional[str] = None
    config: Dict[str, Any]  # Add missing field
    started_at: datetime
    completed_at: Optional[datetime] = None
    last_updated: datetime

    model_config = ConfigDict(from_attributes=True)


class ModelDeployRequest(BaseModel):
    """Request schema for deploying a model."""

    model_name: str
    vllm_config: Dict[str, Any] = Field(default_factory=dict)


class DeploymentJobCreate(BaseModel):
    """Schema for creating a deployment job."""

    instance_id: str
    run_id: UUID
    deployment_type: str = Field(default="ssh", pattern="^(ssh|agent)$")
    priority: int = Field(default=0, ge=-100, le=100)
    max_attempts: int = Field(default=3, ge=1, le=10)
    payload: Dict[str, Any]  # DeploymentRequest serialized


class DeploymentJobUpdate(BaseModel):
    """Schema for updating a deployment job."""

    status: Optional[str] = Field(None, pattern="^(pending|queued|running|completed|failed|cancelled)$")
    error_message: Optional[str] = None
    error_log: Optional[str] = None
    locked_by: Optional[str] = None
    locked_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class DeploymentJobRead(BaseModel):
    """Schema for reading a deployment job."""

    job_id: UUID
    instance_id: str
    run_id: UUID
    deployment_type: str
    status: str
    priority: int
    attempt_count: int
    max_attempts: int
    payload: Dict[str, Any]
    error_message: Optional[str]
    error_log: Optional[str]
    locked_by: Optional[str]
    locked_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeploymentJobListResponse(BaseModel):
    """Paginated deployment job list response."""

    jobs: List[DeploymentJobRead]
    total: int
    pending: int
    running: int


class ProvisioningManifestCreate(BaseModel):
    """Schema for creating a provisioning manifest."""

    deployment_job_id: UUID
    instance_id: str
    manifest_data: Dict[str, Any]
    expires_at: datetime


class ProvisioningManifestRead(BaseModel):
    """Schema for reading a provisioning manifest."""

    manifest_id: UUID
    deployment_job_id: UUID
    instance_id: str
    token_hash: str
    manifest_data: Dict[str, Any]
    expires_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProvisioningTokenResponse(BaseModel):
    """Response with provisioning token and manifest URL."""

    token: str
    manifest_url: str
    expires_at: datetime


class AgentHeartbeatCreate(BaseModel):
    """Schema for agent heartbeat submission."""

    manifest_id: Optional[UUID] = None  # Optional for API key-based heartbeats
    instance_id: str
    api_key: Optional[str] = None  # For API key-based authentication
    agent_version: str
    phase: str
    status: str = Field(pattern="^(healthy|error|warning)$")
    message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class AgentHeartbeatRead(BaseModel):
    """Schema for reading agent heartbeat."""

    heartbeat_id: UUID
    manifest_id: Optional[UUID]  # Can be None for API key-based heartbeats
    instance_id: str
    agent_version: str
    phase: str
    status: str
    message: Optional[str]
    metadata: Optional[Dict[str, Any]] = Field(alias="heartbeat_metadata")
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# API Key Management Schemas
class ProvisioningAPIKeyCreate(BaseModel):
    """Schema for creating a provisioning API key."""

    name: str = Field(..., max_length=100)
    description: Optional[str] = None


class ProvisioningAPIKeyRead(BaseModel):
    """Schema for reading a provisioning API key (without the actual key)."""

    key_id: UUID
    name: str
    description: Optional[str]
    created_at: datetime
    revoked_at: Optional[datetime]
    last_used_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class ProvisioningAPIKeyResponse(BaseModel):
    """Response with API key (only shown once on creation)."""

    key_id: UUID
    api_key: str  # Only shown once
    name: str
    description: Optional[str]
    created_at: datetime


class AgentRegistrationRequest(BaseModel):
    """Schema for agent self-registration."""

    instance_id: str
    api_key: str
    hostname: Optional[str] = None
    os_info: Optional[Dict[str, Any]] = None
    gpu_info: Optional[Dict[str, Any]] = None


class AgentRegistrationResponse(BaseModel):
    """Response after agent registration."""

    instance_id: str
    registered: bool
    message: str


class DeploymentConfigRequest(BaseModel):
    """Schema for requesting deployment config."""

    instance_id: str
    api_key: str
    poll_interval: Optional[int] = Field(default=5, ge=1, le=60)
    enable_profiling: Optional[bool] = Field(default=False)
    metadata: Optional[Dict[str, Any]] = None


class DeploymentConfigResponse(BaseModel):
    """Response with deployment configuration."""

    instance_id: str
    run_id: UUID
    docker_compose: str  # Full docker-compose.yml content
    prometheus_config: str  # Prometheus configuration
    backend_url: str
    poll_interval: int
    enable_profiling: bool
    dcgm_collectors_csv: str
    nvidia_smi_exporter: str
    dcgm_health_exporter: str
    token_exporter: str
    deployment_instructions: Optional[Dict[str, Any]] = None  # Optional deployment instructions for agent


# ── Workload / Kernel / Bottleneck profiling schemas ─────────────────────────


class WorkloadMetricsCreate(BaseModel):
    """Workload profiling data submitted by the agent."""

    model_name: Optional[str] = None
    server_url: Optional[str] = None
    concurrency: Optional[int] = None
    num_requests: Optional[int] = None
    successful_requests: Optional[int] = None
    failed_requests: Optional[int] = None
    duration_s: Optional[float] = None
    ttft_mean_ms: Optional[float] = None
    ttft_p50_ms: Optional[float] = None
    ttft_p95_ms: Optional[float] = None
    ttft_p99_ms: Optional[float] = None
    tpot_mean_ms: Optional[float] = None
    tpot_p50_ms: Optional[float] = None
    tpot_p95_ms: Optional[float] = None
    tpot_p99_ms: Optional[float] = None
    e2e_latency_mean_ms: Optional[float] = None
    e2e_latency_p99_ms: Optional[float] = None
    throughput_req_sec: Optional[float] = None
    throughput_tok_sec: Optional[float] = None
    total_input_tokens: Optional[int] = None
    total_output_tokens: Optional[int] = None


class WorkloadMetricsRead(WorkloadMetricsCreate):
    """Workload metrics returned from the API."""

    run_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KernelCategoryData(BaseModel):
    """Single kernel category timing."""

    category: str
    total_ms: float
    pct: float
    count: int = Field(alias="kernel_count", default=0)

    model_config = ConfigDict(populate_by_name=True)


class KernelProfileCreate(BaseModel):
    """Kernel profiling data submitted by the agent."""

    total_cuda_ms: Optional[float] = None
    total_flops: Optional[float] = None
    estimated_tflops: Optional[float] = None
    profiled_requests: Optional[str] = None
    trace_source: Optional[str] = None
    categories: List[KernelCategoryData] = Field(default_factory=list)


class KernelProfileRead(BaseModel):
    """Kernel profile returned from the API."""

    profile_id: UUID
    run_id: UUID
    total_cuda_ms: Optional[float]
    total_flops: Optional[float]
    estimated_tflops: Optional[float]
    profiled_requests: Optional[str]
    trace_source: Optional[str]
    categories: List[KernelCategoryData]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BottleneckAnalysisCreate(BaseModel):
    """Bottleneck analysis data submitted by the agent."""

    primary_bottleneck: str = Field(..., max_length=20)
    compute_util_pct: Optional[float] = None
    sm_active_mean_pct: Optional[float] = None
    memory_bw_util_pct: Optional[float] = None
    hbm_bw_mean_gbps: Optional[float] = None
    cpu_overhead_estimated_pct: Optional[float] = None
    nvlink_util_pct: Optional[float] = None
    arithmetic_intensity: Optional[float] = None
    roofline_bound: Optional[str] = None
    mfu_pct: Optional[float] = None
    actual_tflops: Optional[float] = None
    peak_tflops_bf16: Optional[float] = None
    recommendations: Optional[List[str]] = None


class BottleneckAnalysisRead(BottleneckAnalysisCreate):
    """Bottleneck analysis returned from the API."""

    run_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProfileUpload(BaseModel):
    """Complete profiling payload uploaded by the agent after a run.

    Matches the JSON output structure of agent.py / report.py.
    """

    workload: Optional[WorkloadMetricsCreate] = None
    kernel: Optional[KernelProfileCreate] = None
    bottleneck: Optional[BottleneckAnalysisCreate] = None
    run_metadata: Optional[Dict[str, Any]] = None
    gpu: Optional[Dict[str, Any]] = None


class ProfileUploadResponse(BaseModel):
    """Response after successful profile upload."""

    run_id: UUID
    workload_stored: bool = False
    kernel_stored: bool = False
    bottleneck_stored: bool = False


class RunDetailFull(RunDetail):
    """Extended run detail including profiling data."""

    workload: Optional[WorkloadMetricsRead] = None
    kernel_profiles: Optional[List[KernelProfileRead]] = None
    bottleneck: Optional[BottleneckAnalysisRead] = None


# Authentication schemas
class UserCreate(BaseModel):
    """Schema for creating a new user."""

    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=6)


class UserLogin(BaseModel):
    """Schema for user login."""

    email: str = Field(..., max_length=255)
    password: str


class Token(BaseModel):
    """Schema for JWT token response."""

    access_token: str
    token_type: str = "bearer"


class UserRead(BaseModel):
    """Schema for reading user information."""

    user_id: UUID
    email: str
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


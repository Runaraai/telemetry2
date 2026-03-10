"""Routes for manifest-driven provisioning (agent-based deployments)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
import os
from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..deployment import DeploymentManager
from ..models import User
from ..repository import TelemetryRepository
from .auth import get_current_user
from ..schemas import (
    AgentHeartbeatCreate,
    AgentHeartbeatRead,
    AgentRegistrationRequest,
    AgentRegistrationResponse,
    DeploymentConfigRequest,
    DeploymentConfigResponse,
    DeploymentRequest,
    ProvisioningAPIKeyCreate,
    ProvisioningAPIKeyRead,
    ProvisioningAPIKeyResponse,
    ProvisioningManifestCreate,
    ProvisioningManifestRead,
    ProvisioningTokenResponse,
    RunCreate,
    RunUpdate,
)
from .runs import get_repository

router = APIRouter(prefix="/provision", tags=["Provisioning"])


@router.post("/manifests/{deployment_job_id}", response_model=ProvisioningTokenResponse)
async def create_provisioning_manifest(
    deployment_job_id: UUID,
    repo: TelemetryRepository = Depends(get_repository),
) -> ProvisioningTokenResponse:
    """Create a provisioning manifest and token for agent-based deployment."""
    # Get the deployment job
    job = await repo.get_deployment_job(deployment_job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment job not found",
        )
    if job.deployment_type != "agent":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job is not an agent-based deployment",
        )

    # Generate a secure token
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    # Build manifest data
    manifest_data = {
        "deployment_job_id": str(job.job_id),
        "instance_id": job.instance_id,
        "run_id": str(job.run_id),
        "payload": job.payload,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Create manifest with 1 hour expiration
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    manifest_payload = ProvisioningManifestCreate(
        deployment_job_id=deployment_job_id,
        instance_id=job.instance_id,
        manifest_data=manifest_data,
        expires_at=expires_at,
    )
    manifest = await repo.create_provisioning_manifest(manifest_payload)

    # Update manifest with token hash
    from sqlalchemy import update
    from ..models import ProvisioningManifest
    stmt = (
        update(ProvisioningManifest)
        .where(ProvisioningManifest.manifest_id == manifest.manifest_id)
        .values(token_hash=token_hash)
    )
    await repo.session.execute(stmt)
    await repo.session.commit()
    await repo.session.refresh(manifest)

    # Build manifest URL (will be used by agent to fetch manifest)
    import os
    api_base_url = os.getenv("API_BASE_URL", "https://voertx.cloud")
    manifest_url = f"{api_base_url}/api/telemetry/provision/manifests/{manifest.manifest_id}?token={token}"

    return ProvisioningTokenResponse(
        token=token,
        manifest_url=manifest_url,
        expires_at=expires_at,
    )


@router.get("/manifests/{manifest_id}", response_model=ProvisioningManifestRead)
async def get_provisioning_manifest(
    manifest_id: UUID,
    token: str,
    repo: TelemetryRepository = Depends(get_repository),
) -> ProvisioningManifestRead:
    """Get a provisioning manifest by ID and token (for agent to fetch)."""
    # Hash the token
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    # Find manifest by token hash
    manifest = await repo.get_provisioning_manifest_by_token_hash(token_hash)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Manifest not found or token invalid",
        )

    # Check expiration
    if manifest.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Manifest has expired",
        )

    # Verify manifest_id matches
    if manifest.manifest_id != manifest_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Manifest not found",
        )

    return ProvisioningManifestRead.model_validate(manifest)


@router.post("/callbacks", response_model=AgentHeartbeatRead)
async def agent_heartbeat(
    payload: AgentHeartbeatCreate,
    repo: TelemetryRepository = Depends(get_repository),
) -> AgentHeartbeatRead:
    """Receive agent heartbeat and status updates."""
    # Import queue_manager at the top level
    from ..services.deployment_queue import queue_manager
    
    # Support both manifest-based (legacy) and API key-based (new) heartbeats
    if payload.manifest_id:
        # Legacy manifest-based heartbeat
        manifest = await repo.get_provisioning_manifest(payload.manifest_id)
        if not manifest:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Manifest not found",
            )
        # Create heartbeat
        heartbeat = await repo.create_agent_heartbeat(payload)

        # Update deployment job status based on heartbeat
        if payload.status == "error" and payload.phase == "deploying":
            job = await repo.get_deployment_job(manifest.deployment_job_id)
            if job:
                await queue_manager.mark_job_failed(
                    job.job_id,
                    f"Agent deployment failed: {payload.message or 'Unknown error'}",
                    retry=True,
                )
        elif payload.status == "healthy" and payload.phase == "running":
            job = await repo.get_deployment_job(manifest.deployment_job_id)
            if job:
                await queue_manager.mark_job_completed(job.job_id)
    else:
        # New API key-based heartbeat
        if not payload.api_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either manifest_id or api_key must be provided",
            )
        # Verify API key
        key_hash = hashlib.sha256(payload.api_key.encode()).hexdigest()
        api_key = await repo.get_provisioning_api_key_by_hash(key_hash)
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )
        # Update last used timestamp
        await repo.update_api_key_last_used(key_hash)
        # Create heartbeat (manifest_id will be None)
        heartbeat = await repo.create_agent_heartbeat(payload)

    await repo.session.commit()
    return AgentHeartbeatRead.model_validate(heartbeat)


@router.get("/callbacks/{manifest_id}/heartbeats", response_model=Dict[str, Any])
async def get_agent_heartbeats(
    manifest_id: UUID,
    limit: int = 50,
    repo: TelemetryRepository = Depends(get_repository),
) -> Dict[str, Any]:
    """Get recent heartbeats for a manifest."""
    manifest = await repo.get_provisioning_manifest(manifest_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Manifest not found",
        )

    from sqlalchemy import select
    from ..models import AgentHeartbeat
    stmt = (
        select(AgentHeartbeat)
        .where(AgentHeartbeat.manifest_id == manifest_id)
        .order_by(AgentHeartbeat.timestamp.desc())
        .limit(limit)
    )
    result = await repo.session.execute(stmt)
    heartbeats = list(result.scalars().unique())

    latest = await repo.get_latest_heartbeat(manifest_id)

    return {
        "manifest_id": str(manifest_id),
        "total_heartbeats": len(heartbeats),
        "latest": AgentHeartbeatRead.model_validate(latest) if latest else None,
        "heartbeats": [AgentHeartbeatRead.model_validate(h) for h in heartbeats],
    }


@router.get("/instances/{instance_id}/status", response_model=Dict[str, Any])
async def get_agent_status_by_instance(
    instance_id: str,
    repo: TelemetryRepository = Depends(get_repository),
) -> Dict[str, Any]:
    """Get the latest agent status for an instance."""
    import logging
    logger = logging.getLogger(__name__)
    
    logger.debug(f"Looking up heartbeat for instance_id: {instance_id}")
    heartbeat = await repo.get_latest_heartbeat_by_instance(instance_id)
    if not heartbeat:
        logger.warning(f"No heartbeat found for instance_id: {instance_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No agent heartbeat found for this instance",
        )
    
    logger.debug(f"Found heartbeat: phase={heartbeat.phase}, status={heartbeat.status}, timestamp={heartbeat.timestamp}")
    
    # Get the run_id from the most recent run for this instance
    runs = await repo.list_runs(instance_id=instance_id, limit=1)
    run_id = runs[0].run_id if runs else None
    
    # Return heartbeat with run_id
    result = AgentHeartbeatRead.model_validate(heartbeat).model_dump()
    if run_id:
        result['run_id'] = str(run_id)
    return result


@router.post("/instances/{instance_id}/stop")
async def stop_agent(
    instance_id: str,
    run_id: UUID = Query(..., description="Run ID to stop"),
    repo: TelemetryRepository = Depends(get_repository),
) -> Dict[str, Any]:
    """
    Stop agent monitoring for an instance.
    
    Note: This marks the run as completed in the database. To actually stop the agent service
    and containers on the GPU instance, you need to SSH into the instance and run:
    - sudo systemctl stop omniference-agent
    - sudo docker compose -f /tmp/gpu-telemetry-{instance_id}/docker-compose.yml down
    """
    # Update run status to completed
    try:
        await repo.update_run(
            run_id,
            RunUpdate(
                status="completed",
                end_time=datetime.now(timezone.utc),
            ),
        )
        await repo.session.commit()
        return {
            "success": True,
            "message": f"Run marked as stopped. To actually stop the agent service and containers on the GPU instance, SSH into it and run:\n\nsudo systemctl stop omniference-agent\nsudo docker compose -f /tmp/gpu-telemetry-{instance_id}/docker-compose.yml down",
            "instructions": {
                "stop_agent": f"sudo systemctl stop omniference-agent",
                "stop_containers": f"sudo docker compose -f /tmp/gpu-telemetry-{instance_id}/docker-compose.yml down",
            }
        }
    except Exception as e:
        await repo.session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop agent: {str(e)}",
        )


# API Key Management Endpoints
@router.post("/api-keys", response_model=ProvisioningAPIKeyResponse)
async def create_api_key(
    payload: ProvisioningAPIKeyCreate,
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> ProvisioningAPIKeyResponse:
    """Create a new provisioning API key."""
    # Generate a secure API key
    api_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    # Create the API key record
    key_record = await repo.create_provisioning_api_key(
        key_hash=key_hash,
        name=payload.name,
        user_id=current_user.user_id,
        description=payload.description,
    )
    await repo.session.commit()

    return ProvisioningAPIKeyResponse(
        key_id=key_record.key_id,
        api_key=api_key,  # Only shown once
        name=key_record.name,
        description=key_record.description,
        created_at=key_record.created_at,
    )


@router.get("/api-keys", response_model=list[ProvisioningAPIKeyRead])
async def list_api_keys(
    include_revoked: bool = False,
    repo: TelemetryRepository = Depends(get_repository),
) -> list[ProvisioningAPIKeyRead]:
    """List all API keys."""
    keys = await repo.list_provisioning_api_keys(include_revoked=include_revoked)
    return [ProvisioningAPIKeyRead.model_validate(k) for k in keys]


@router.post("/api-keys/{key_id}/revoke", response_model=ProvisioningAPIKeyRead)
async def revoke_api_key(
    key_id: UUID,
    repo: TelemetryRepository = Depends(get_repository),
) -> ProvisioningAPIKeyRead:
    """Revoke an API key."""
    key = await repo.revoke_provisioning_api_key(key_id)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )
    await repo.session.commit()
    return ProvisioningAPIKeyRead.model_validate(key)


# Agent Registration Endpoint
@router.post("/register", response_model=AgentRegistrationResponse)
async def register_agent(
    payload: AgentRegistrationRequest,
    repo: TelemetryRepository = Depends(get_repository),
) -> AgentRegistrationResponse:
    """Register an agent instance with the backend using API key authentication."""
    # Verify API key
    key_hash = hashlib.sha256(payload.api_key.encode()).hexdigest()
    api_key = await repo.get_provisioning_api_key_by_hash(key_hash)
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    # Update last used timestamp
    await repo.update_api_key_last_used(key_hash)
    await repo.session.commit()

    # For now, just return success - instance registration can be enhanced later
    return AgentRegistrationResponse(
        instance_id=payload.instance_id,
        registered=True,
        message="Instance registered successfully",
    )


# Deployment Config Endpoint
@router.post("/config", response_model=DeploymentConfigResponse)
async def get_deployment_config(
    payload: DeploymentConfigRequest,
    repo: TelemetryRepository = Depends(get_repository),
) -> DeploymentConfigResponse:
    """Get deployment configuration (docker-compose.yml and prometheus.yml) for an instance."""
    # Verify API key
    key_hash = hashlib.sha256(payload.api_key.encode()).hexdigest()
    api_key = await repo.get_provisioning_api_key_by_hash(key_hash)
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    # Update last used timestamp for auditing
    await repo.update_api_key_last_used(key_hash)

    # Create a fresh run so remote_write has a destination
    # Associate run with the user who owns the API key
    # Note: create_run returns (Run, ingest_token) tuple
    run, ingest_token = await repo.create_run(
        RunCreate(
            instance_id=payload.instance_id,
            gpu_model=None,
            gpu_count=None,
        ),
        user_id=api_key.user_id
    )

    # Resolve backend URL (used for Prometheus remote_write)
    api_base_url = os.getenv("API_BASE_URL", "https://omniference.com").rstrip("/")

    poll_interval = payload.poll_interval or 5
    enable_profiling = bool(payload.enable_profiling)
    metadata = payload.metadata or {}

    # Map agent metadata to DeploymentManager system_info structure
    system_info: Dict[str, Any] = {
        "gpu_count": int(metadata.get("gpu_count", 1)),
    }
    dcgm_image = metadata.get("dcgm_image")
    if dcgm_image:
        system_info["dcgm_image"] = dcgm_image

    deployment_request = DeploymentRequest(
        run_id=run.run_id,
        backend_url=api_base_url,
        poll_interval=poll_interval,
        enable_profiling=enable_profiling,
    )

    manager = DeploymentManager()
    docker_compose = manager._compose_content(deployment_request, system_info)
    # Pass ingest_token to Prometheus config for remote_write authentication
    prometheus_config = manager._prometheus_config(deployment_request, system_info, ingest_token=ingest_token)
    dcgm_collectors = manager._dcgm_collectors_csv(enable_profiling)
    nvidia_smi_script = manager._nvidia_smi_exporter_script()
    dcgm_health_script = manager._dcgm_health_exporter_script()
    token_exporter_script = manager._token_exporter_script()

    await repo.session.commit()

    # Add deployment instructions for profiling mode
    deployment_instructions = None
    if enable_profiling:
        deployment_instructions = {
            "profiling_enabled": True,
            "prerequisites": [
                "Stop any existing GPU workloads before deploying",
                "Stop existing DCGM exporter container: docker compose stop dcgm-exporter",
                "Remove DCGM exporter container: docker compose rm -f dcgm-exporter",
                "Deploy with: docker compose up -d",
                "Verify profiling metrics: curl -s http://localhost:9400/metrics | grep DCGM_FI_PROF_SM_ACTIVE"
            ],
            "note": "DCGM profiling requires the DCGM daemon to start BEFORE GPU workloads. If workloads are already running, profiling metrics will not be available."
        }

    return DeploymentConfigResponse(
        instance_id=payload.instance_id,
        run_id=run.run_id,
        docker_compose=docker_compose,
        prometheus_config=prometheus_config,
        backend_url=api_base_url,
        poll_interval=poll_interval,
        enable_profiling=enable_profiling,
        dcgm_collectors_csv=dcgm_collectors,
        nvidia_smi_exporter=nvidia_smi_script,
        dcgm_health_exporter=dcgm_health_script,
        token_exporter=token_exporter_script,
        deployment_instructions=deployment_instructions,
    )


"""API routes for instance orchestration."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Dict, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Header, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import async_session, get_session
from ..models import InstanceOrchestration
from ..schemas import (
    InstanceOrchestrationRequest,
    InstanceOrchestrationStatus,
    ModelDeployRequest,
)
from ..services.instance_orchestrator import InstanceOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telemetry/instances/orchestrate", tags=["instance-orchestration"])


@router.post("", response_model=InstanceOrchestrationStatus)
async def start_orchestration(
    request: InstanceOrchestrationRequest,
    x_lambda_api_key: str = Header(None, alias="X-Lambda-API-Key"),
) -> InstanceOrchestrationStatus:
    """
    Launch instance and start automated setup orchestration.
    
    This endpoint:
    1. Launches a Lambda Cloud instance
    2. Waits for IP address
    3. Triggers automated setup
    4. Optionally deploys a model
    
    Returns orchestration_id for status polling.
    """
    try:
        logger.info(f"Starting orchestration request: instance_type={request.instance_type}, region={request.region}")
        
        if not x_lambda_api_key:
            raise HTTPException(status_code=400, detail="X-Lambda-API-Key header is required")
        
        # Validate required fields
        if not request.instance_type:
            raise HTTPException(status_code=400, detail="instance_type is required")
        if not request.region:
            raise HTTPException(status_code=400, detail="region is required")
        if not request.ssh_key_name:
            raise HTTPException(status_code=400, detail="ssh_key_name is required")
        if not request.ssh_key:
            raise HTTPException(status_code=400, detail="ssh_key is required")
        
        logger.info("Request validation passed, creating orchestration record...")
        
        async with async_session() as session:
            # Create orchestration record
            # Ensure config is always a dict (required by schema)
            orchestration_config = {
                "instance_type": request.instance_type,
                "region": request.region,
                "ssh_key_name": request.ssh_key_name,
                "ssh_key": request.ssh_key,  # Store SSH key in config for later retrieval
            }
            if request.model_name:
                orchestration_config["model_name"] = request.model_name
            if request.vllm_config:
                orchestration_config["vllm_config"] = request.vllm_config
            
            orchestration = InstanceOrchestration(
                instance_id="",  # Will be set after launch
                status="launching",
                current_phase="launch",
                progress=0,
                ssh_user="ubuntu",
                ssh_key_name=request.ssh_key_name,  # Required field
                config=orchestration_config,
            )
            session.add(orchestration)
            await session.flush()  # Flush to get the orchestration_id
            orchestration_id = orchestration.orchestration_id
            logger.info(f"Flushed orchestration {orchestration_id}, committing to database...")
            
            # Commit the orchestration record to database so it can be queried immediately
            await session.commit()
            logger.info(f"Successfully created and committed orchestration {orchestration_id} with status 'launching'")
            
            # Start background orchestration task (after commit to ensure record exists)
            asyncio.create_task(
                InstanceOrchestrator.launch_and_setup(
                    orchestration_id=orchestration_id,
                    instance_type=request.instance_type,
                    region=request.region,
                    ssh_key_name=request.ssh_key_name,
                    api_key=x_lambda_api_key,
                    ssh_key_data=request.ssh_key,
                    model_name=request.model_name,
                    vllm_config=request.vllm_config or {},
                )
            )

            # Query the orchestration fresh from database to ensure all fields are loaded
            # This avoids issues with detached objects after commit
            async with async_session() as response_session:
                response_stmt = select(InstanceOrchestration).where(
                    InstanceOrchestration.orchestration_id == orchestration_id
                )
                response_result = await response_session.execute(response_stmt)
                response_orchestration = response_result.scalar_one_or_none()
                
                if not response_orchestration:
                    logger.error(f"Orchestration {orchestration_id} not found after commit!")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Orchestration {orchestration_id} was created but could not be retrieved"
                    )
                
                logger.info(f"Retrieved orchestration {orchestration_id} for response")
                
                # Ensure config is not None (required by schema)
                if response_orchestration.config is None:
                    logger.warning(f"Orchestration {orchestration_id} has None config, setting to empty dict")
                    response_orchestration.config = {}
                
                # Log key fields for debugging
                logger.debug(f"Orchestration fields - id: {response_orchestration.orchestration_id}, "
                           f"status: {response_orchestration.status}, "
                           f"config: {response_orchestration.config is not None}, "
                           f"ssh_key_name: {response_orchestration.ssh_key_name}")
                
                try:
                    return InstanceOrchestrationStatus.model_validate(response_orchestration)
                except Exception as validation_error:
                    logger.error(
                        f"Failed to validate orchestration response: {type(validation_error).__name__}: {validation_error}",
                        exc_info=True
                    )
                    # Log the orchestration object for debugging
                    logger.error(f"Orchestration object type: {type(response_orchestration)}")
                    if hasattr(response_orchestration, '__dict__'):
                        logger.error(f"Orchestration dict keys: {list(response_orchestration.__dict__.keys())}")
                    # Try to get field values
                    try:
                        logger.error(f"orchestration_id: {response_orchestration.orchestration_id}")
                        logger.error(f"instance_id: {response_orchestration.instance_id}")
                        logger.error(f"status: {response_orchestration.status}")
                        logger.error(f"config: {response_orchestration.config}")
                        logger.error(f"ssh_key_name: {response_orchestration.ssh_key_name}")
                        logger.error(f"ssh_user: {response_orchestration.ssh_user}")
                    except Exception as log_error:
                        logger.error(f"Error logging orchestration fields: {log_error}")
                    
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to serialize orchestration response: {type(validation_error).__name__}: {str(validation_error)}"
                    )

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        logger.error(
            f"Failed to start orchestration: {error_type}: {error_msg}",
            exc_info=True
        )
        # Include error type in detail for better debugging
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start orchestration: {error_type}: {error_msg}"
        )


@router.get("/{orchestration_id}/status", response_model=InstanceOrchestrationStatus)
async def get_orchestration_status(orchestration_id: UUID) -> InstanceOrchestrationStatus:
    """Get current status of an orchestration."""
    logger.info(f"Fetching orchestration status for {orchestration_id}")
    orchestration = await InstanceOrchestrator.get_orchestration_status(orchestration_id)
    if not orchestration:
        logger.warning(f"Orchestration {orchestration_id} not found in database")
        raise HTTPException(status_code=404, detail=f"Orchestration {orchestration_id} not found")
    logger.info(f"Found orchestration {orchestration_id} with status {orchestration.status}")
    return InstanceOrchestrationStatus.model_validate(orchestration)


@router.get("/by-instance/{instance_id}", response_model=Optional[InstanceOrchestrationStatus])
async def get_orchestration_by_instance(instance_id: str) -> Optional[InstanceOrchestrationStatus]:
    """Get orchestration status by Lambda Labs instance ID."""
    try:
        async with async_session() as session:
            stmt = select(InstanceOrchestration).where(
                InstanceOrchestration.instance_id == instance_id
            ).order_by(InstanceOrchestration.started_at.desc())
            result = await session.execute(stmt)
            orchestration = result.scalar_one_or_none()
            if orchestration:
                return InstanceOrchestrationStatus.model_validate(orchestration)
            return None
    except Exception as e:
        logger.error(f"Failed to fetch orchestration for instance {instance_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch orchestration for instance {instance_id}: {type(e).__name__}: {str(e)}"
        )


@router.post("/{orchestration_id}/deploy-model", response_model=InstanceOrchestrationStatus)
async def deploy_model(
    orchestration_id: UUID,
    request: ModelDeployRequest,
) -> InstanceOrchestrationStatus:
    """
    Deploy a model to an orchestrated instance.
    
    This starts the deployment in the background and returns immediately.
    Poll the status endpoint to check deployment progress.
    """
    orchestration = await InstanceOrchestrator.get_orchestration_status(orchestration_id)
    if not orchestration:
        raise HTTPException(status_code=404, detail="Orchestration not found")
    
    # Allow re-deployment if status is "deploying_model" but no model is actually deployed
    # This handles cases where a previous deployment failed or got stuck
    if orchestration.status == "deploying_model":
        if orchestration.model_deployed and orchestration.model_deployed.strip():
            # A model is actually deployed, so a deployment is truly in progress
            raise HTTPException(
                status_code=400,
                detail="A model deployment is already in progress. Please wait for it to complete before deploying another model."
            )
        else:
            # Status is "deploying_model" but no model is deployed - likely a stuck/failed deployment
            # Allow re-deployment by resetting status to "ready"
            logger.warning(f"Orchestration {orchestration_id} has status 'deploying_model' but no model deployed. Allowing re-deployment.")
            async with async_session() as reset_session:
                await InstanceOrchestrator._update_status(
                    reset_session,
                    orchestration_id,
                    "ready",
                    "ready",
                    orchestration.progress,
                    "Previous deployment appears to have failed. Ready for new deployment.",
                )
            # Refresh orchestration status
            orchestration = await InstanceOrchestrator.get_orchestration_status(orchestration_id)
    elif orchestration.status == "failed":
        # Allow re-deployment from failed status by resetting to ready
        logger.info(f"Orchestration {orchestration_id} has status 'failed'. Resetting to 'ready' for re-deployment.")
        async with async_session() as reset_session:
            await InstanceOrchestrator._update_status(
                reset_session,
                orchestration_id,
                "ready",
                "ready",
                orchestration.progress,
                "Resetting from failed state. Ready for new deployment.",
            )
        # Refresh orchestration status
        orchestration = await InstanceOrchestrator.get_orchestration_status(orchestration_id)
    elif orchestration.status != "ready" and orchestration.status != "setting_up":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot deploy model: instance status is '{orchestration.status}'. Instance must be 'ready' or 'setting_up' to deploy a model."
        )
    
    if not orchestration.ip_address:
        raise HTTPException(status_code=400, detail="Instance IP address not available")
    
    # Get SSH key from orchestration config
    ssh_key = orchestration.config.get("ssh_key", "") if orchestration.config else ""
    if not ssh_key:
        logger.error(f"SSH key not found in orchestration config for {orchestration_id}. Config keys: {list(orchestration.config.keys()) if orchestration.config else 'None'}")
        raise HTTPException(status_code=400, detail="SSH key not found in orchestration config. Please ensure the SSH key was provided during instance launch.")
    
    logger.info(f"Retrieved SSH key from config for {orchestration_id}. Key length: {len(ssh_key)} chars, starts with: {ssh_key[:50]}...")
    
    # Update status to deploying_model immediately with initial log message
    async with get_session() as session:
        await InstanceOrchestrator._update_status(
            session,
            orchestration_id,
            "deploying_model",
            "model_deploy",
            90,
            f"Starting model deployment: {request.model_name}...",
        )
        logger.info(f"Updated orchestration {orchestration_id} to deploying_model status with initial log message")
            
    # Start deployment in background task (similar to instance launch)
    async def deploy_model_background():
        try:
            async with async_session() as session:
                await InstanceOrchestrator._deploy_model(
                    session,
                    orchestration_id,
                    orchestration.ip_address,
                    ssh_key,
                    request.model_name,
                    request.vllm_config or {},
                )
                await InstanceOrchestrator._update_status(
                    session,
                    orchestration_id,
                    "ready",
                    "ready",
                    100,
                    f"Model {request.model_name} deployed successfully!",
                    model_deployed=request.model_name,
                )
        except Exception as e:
            logger.error(f"Background model deployment failed for {orchestration_id}: {str(e)}", exc_info=True)
            async with async_session() as error_session:
                await InstanceOrchestrator._update_status(
                    error_session,
                    orchestration_id,
                    "failed",
                    "error",
                    0,
                    f"Model deployment failed: {str(e)}",
                    error_message=str(e),
                )
    
    # Start background task
    asyncio.create_task(deploy_model_background())
    
    # Return current status immediately (will show deploying_model)
    orchestration = await InstanceOrchestrator.get_orchestration_status(orchestration_id)
    return InstanceOrchestrationStatus.model_validate(orchestration)


@router.get("/{orchestration_id}/model-progress")
async def get_model_progress(orchestration_id: UUID):
    """
    Check model loading progress by inspecting vLLM container logs.
    Returns recent logs and status information.
    """
    orchestration = await InstanceOrchestrator.get_orchestration_status(orchestration_id)
    if not orchestration:
        raise HTTPException(status_code=404, detail="Orchestration not found")
    
    if not orchestration.ip_address:
        raise HTTPException(status_code=400, detail="Instance IP address not available")
    
    # Get SSH key from orchestration config
    ssh_key = orchestration.config.get("ssh_key", "") if orchestration.config else ""
    if not ssh_key:
        raise HTTPException(status_code=400, detail="SSH key not available")
    
    from ..services.ssh_executor import SSHExecutor
    
    results = {}
    
    # Check container status
    try:
        stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
            ssh_host=orchestration.ip_address,
            ssh_user="ubuntu",
            ssh_key=ssh_key,
            command="sudo docker ps --filter name=vllm --format '{{.Status}}'",
            timeout=30,
            check_status=False
        )
        results["container_status"] = stdout.strip() if stdout else "Not running"
    except Exception as e:
        results["container_status"] = f"Error: {str(e)}"
    
    # Get recent logs
    try:
        stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
            ssh_host=orchestration.ip_address,
            ssh_user="ubuntu",
            ssh_key=ssh_key,
            command="sudo docker logs --tail 30 vllm 2>&1",
            timeout=30,
            check_status=False
        )
        results["recent_logs"] = stdout.split('\n')[-30:] if stdout else []
    except Exception as e:
        results["recent_logs"] = [f"Error getting logs: {str(e)}"]
    
    # Check model cache size
    try:
        stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
            ssh_host=orchestration.ip_address,
            ssh_user="ubuntu",
            ssh_key=ssh_key,
            command="du -sh ~/.cache/huggingface/hub 2>/dev/null || echo 'Cache not found'",
            timeout=30,
            check_status=False
        )
        results["cache_size"] = stdout.strip() if stdout else "Unknown"
    except Exception as e:
        results["cache_size"] = f"Error: {str(e)}"
    
    # Check health endpoint
    try:
        stdout, stderr, exit_code = await SSHExecutor.execute_remote_command(
            ssh_host=orchestration.ip_address,
            ssh_user="ubuntu",
            ssh_key=ssh_key,
            command="curl -s http://localhost:8000/health 2>&1 | head -3",
            timeout=10,
            check_status=False
        )
        results["health_status"] = stdout.strip() if stdout else "Not responding"
    except Exception as e:
        results["health_status"] = f"Not ready: {str(e)}"
    
    return results


@router.post("/proxy-inference")
async def proxy_inference(
    ip_address: str = Body(..., embed=True),
    request_body: Dict[str, Any] = Body(...)
) -> Dict[str, Any]:
    """
    Proxy inference requests to deployed instances.
    This endpoint allows the frontend to make HTTPS requests that are proxied
    to HTTP instances, avoiding Mixed Content errors.
    """
    try:
        # Validate IP address format
        if not ip_address or ':' in ip_address:
            raise HTTPException(status_code=400, detail="Invalid IP address")
        
        # Construct the instance URL
        instance_url = f"http://{ip_address}:8000/v1/chat/completions"
        
        # Forward the request to the instance
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                instance_url,
                json=request_body,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code >= 400:
                error_text = response.text
                try:
                    error_json = response.json()
                    error_text = error_json.get("error", {}).get("message", error_text)
                except:
                    pass
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Inference failed: {error_text}"
                )
            
            return response.json()
            
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Request to instance timed out")
    except httpx.RequestError as e:
        logger.error(f"Proxy inference error: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail=f"Failed to connect to instance: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in proxy inference: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )

"""Routes for deploying telemetry monitoring stack."""

from __future__ import annotations

import asyncio
import shlex
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..deployment import deployment_manager
from typing import Optional
from ..models import User
from ..repository import TelemetryRepository
from .auth import get_current_user
from ..schemas import (
    DeploymentJobCreate,
    DeploymentJobListResponse,
    DeploymentJobRead,
    DeploymentJobUpdate,
    DeploymentRequest,
    DeploymentResponse,
    DeploymentStatusResponse,
    PrerequisiteItem,
    PrerequisitesResponse,
    RunCreate,
    RunUpdate,
    TeardownRequest,
)
from ..services.deployment_queue import queue_manager
from .runs import get_repository


router = APIRouter(prefix="/instances", tags=["Telemetry Deployment"])

SYSTEM_PREREQUISITES: List[PrerequisiteItem] = [
    PrerequisiteItem(
        id="nvidia_driver",
        title="NVIDIA datacenter driver installed and active",
        description="The GPU host must have the NVIDIA datacenter driver (535+) installed and working. This is the ONLY prerequisite that must be installed manually before using 'Start Monitoring'. After installation, if nvidia-smi fails, you may need to install kernel headers and rebuild DKMS modules (see component status for specific fix command).",
        verify_command="nvidia-smi",
        install_hint="sudo apt update && sudo apt --fix-broken install -y && sudo apt install -y linux-headers-$(uname -r) nvidia-driver-535-server && sudo reboot",
        docs_link="https://docs.nvidia.com/datacenter/tesla/tesla-installation-notes/index.html",
    ),
    PrerequisiteItem(
        id="driver_reboot",
        title="System rebooted after driver installation",
        description="After installing or upgrading the NVIDIA driver, the host must be rebooted before the driver becomes active. The driver will not work until after reboot.",
        verify_command="nvidia-smi",
    ),
    PrerequisiteItem(
        id="ssh_access",
        title="SSH access with passwordless sudo",
        description="The SSH user configured in Omniference must have passwordless sudo privileges. This is required to install Docker, NVIDIA Container Toolkit, DCGM, and Fabric Manager automatically.",
        verify_command="sudo -n true",
    ),
    PrerequisiteItem(
        id="internet_access",
        title="Outbound internet connectivity",
        description="The host must be able to reach: apt repositories (Ubuntu packages), Docker Hub, NVIDIA Container Registry. Required for automatic installation of Docker, NVIDIA Container Toolkit, DCGM, and Fabric Manager.",
        verify_command="curl -s https://registry-1.docker.io/v2/ > /dev/null",
    ),
    PrerequisiteItem(
        id="profiling_dcgm_service",
        title="[Profiling Only] DCGM daemon running with profiling enabled at boot",
        description="To enable profiling metrics even after workloads start, install DCGM as a system service that starts BEFORE any GPU workloads at boot time. This reserves the profiling hardware counters early. Run the install script: 'curl -fsSL https://github.com/NVIDIA/dcgm-exporter/raw/main/etc/dcgm-exporter/install-dcgm.sh | sudo bash && sudo systemctl enable nv-hostengine && sudo systemctl start nv-hostengine'. After reboot, profiling will work even with active workloads. Without this, you must start monitoring before workloads (see alternative below).",
        verify_command="systemctl is-active nv-hostengine && dcgmi discovery -l | grep -q GPU",
        install_hint="curl -fsSL https://raw.githubusercontent.com/NVIDIA/dcgm-exporter/main/etc/dcgm-exporter/install-dcgm.sh | sudo bash && sudo systemctl enable nv-hostengine && sudo reboot",
        docs_link="https://docs.nvidia.com/datacenter/dcgm/latest/dcgm-user-guide/getting-started.html",
    ),
    PrerequisiteItem(
        id="profiling_idle_gpu",
        title="[Profiling Only - Alternative] GPUs must be idle when monitoring starts",
        description="Alternative to installing DCGM service: Ensure NO GPU workloads are running when you start monitoring, then start your workload AFTER monitoring is deployed. This is simpler but requires careful timing. For always-on profiling that works with any workload timing, use the DCGM service prerequisite above instead.",
        verify_command="nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l | grep '^0$'",
        install_hint="Stop all GPU workloads, start monitoring, then start workloads",
        docs_link="https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/feature-overview.html#profiling-metrics",
    ),
    PrerequisiteItem(
        id="token_metrics_workload_integration",
        title="[Token Metrics] Workload must POST to token exporter",
        description="To see token per second metrics, your inference workload must POST metrics to the token exporter endpoint at http://localhost:9402/update. The token exporter container runs automatically, but your workload needs to send JSON updates: {\"tokens_per_second\": 123.4, \"total_tokens\": 5000, \"requests_per_second\": 2.5, \"total_requests\": 100}",
        verify_command="curl -s http://localhost:9402/health 2>/dev/null | grep -q 'OK' || echo 'token-exporter not responding'",
        install_hint="Integrate POST requests to http://localhost:9402/update in your inference workload. See telemetry documentation for examples.",
        docs_link="https://docs.omniference.com/telemetry/token-metrics",
    ),
]


@router.get("/prerequisites", response_model=PrerequisitesResponse)
async def get_prerequisites() -> PrerequisitesResponse:
    """Return the static list of system prerequisites for GPU hosts."""
    return PrerequisitesResponse(prerequisites=SYSTEM_PREREQUISITES)


@router.post("/{instance_id}/deploy", response_model=DeploymentResponse, status_code=status.HTTP_202_ACCEPTED)
async def deploy_instance(
    instance_id: str,
    payload: DeploymentRequest,
    deployment_type: str = Query("ssh", description="Deployment type: 'ssh' or 'agent'"),
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> DeploymentResponse:
    """
    Deploy telemetry stack via queue. Uses the supplied run_id if it already exists;
    otherwise creates a new run locally so remote_write has a target.
    
    Args:
        instance_id: The instance identifier
        payload: Deployment request (SSH fields optional for agent deployment)
        deployment_type: "ssh" for SSH push, "agent" for agent pull (default: "ssh")
    """
    if deployment_type not in ["ssh", "agent"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="deployment_type must be 'ssh' or 'agent'"
        )
    
    ingest_token = ""
    created_run_in_request = False
    token_updated_in_request = False
    run = await repo.get_run(payload.run_id, current_user.user_id)
    if run:
        run_id = run.run_id
        # Existing runs store only token hash; regenerate a token so this deployment
        # can include X-Ingest-Token in Prometheus remote_write.
        ingest_token = await repo.regenerate_ingest_token(run_id, current_user.user_id)
        if not ingest_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot generate ingest token for this run",
            )
        token_updated_in_request = True
    else:
        run_payload = RunCreate(
            instance_id=instance_id,
            gpu_model=None,  # Will be detected from metrics later
            gpu_count=None,
        )
        run, ingest_token = await repo.create_run(run_payload, current_user.user_id)
        run_id = run.run_id
        payload.run_id = run_id
        created_run_in_request = True
        token_updated_in_request = True

    # Ensure deployment payload carries ingest token for SSH flow.
    payload.ingest_token = ingest_token
    
    # For agent deployment, SSH fields are not required
    if deployment_type == "agent":
        # Agent deployment payload only needs: run_id, backend_url, poll_interval, enable_profiling
        agent_payload = {
            "run_id": str(run_id),
            "ingest_token": ingest_token,
            "backend_url": payload.backend_url,
            "poll_interval": payload.poll_interval,
            "enable_profiling": payload.enable_profiling,
        }
        job_payload = agent_payload
    else:
        # SSH deployment needs all fields
        # Use mode='json' to serialize UUIDs and other non-JSON types to strings
        job_payload = payload.model_dump(mode='json')
    
    # If we created a fallback run in this request, commit it before enqueueing.
    # The queue manager uses a separate DB session; without this commit, FK checks
    # against deployment_jobs.run_id can fail.
    if created_run_in_request or token_updated_in_request:
        await repo.session.commit()

    # Enqueue deployment job instead of starting directly
    job_data = DeploymentJobCreate(
        instance_id=instance_id,
        run_id=run_id,
        deployment_type=deployment_type,
        priority=0,
        max_attempts=3,
        payload=job_payload,
    )
    job = await queue_manager.enqueue_job(job_data)
    
    # Return response with job_id as deployment_id for backward compatibility
    return DeploymentResponse(
        deployment_id=job.job_id,
        run_id=run_id,
        status="queued",
        message=f"Deployment job queued (job_id: {job.job_id}). Processing...",
    )


@router.get("/{instance_id}/deployments/{deployment_id}", response_model=DeploymentStatusResponse)
async def get_deployment_status(
    instance_id: str, 
    deployment_id: UUID,
    repo: TelemetryRepository = Depends(get_repository),
) -> DeploymentStatusResponse:
    # First check if this is a job ID (new queue-based deployment)
    job = await queue_manager.get_job(deployment_id)
    if job:
        if job.instance_id != instance_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deployment job not found for this instance",
            )
        # Map job status to deployment status
        status_map = {
            "pending": "deploying",
            "queued": "deploying",
            "running": "deploying",
            "completed": "running",
            "failed": "failed",
            "cancelled": "failed",
        }
        deployment_status = status_map.get(job.status, "deploying")
        message = job.error_message or f"Job status: {job.status}"
        if job.status == "running":
            message = "Deployment in progress..."
        elif job.status == "completed":
            message = "Deployment completed successfully"
        elif job.status == "failed":
            message = f"Deployment failed: {job.error_message or 'Unknown error'}"
        
        return DeploymentStatusResponse(
            deployment_id=job.job_id,
            status=deployment_status,
            message=message,
            services=None,
            updated_at=job.updated_at,
        )
    
    # Fallback to old deployment manager for backward compatibility
    record = await deployment_manager.get_status(deployment_id)
    if not record or record.instance_id != instance_id:
        # Deployment record not found (e.g., backend restarted)
        # Check if there's an active run - if so, monitoring might still be running
        runs = await repo.list_runs(instance_id=instance_id, status="active", limit=1)
        if runs:
            # There's an active run - deployment record was lost but monitoring may still be active
            # Return a synthetic "running" status so frontend doesn't get stuck
            return DeploymentStatusResponse(
                deployment_id=deployment_id,
                status="running",
                message="Deployment record was lost after backend restart, but an active run exists. Monitoring may still be active - check component status to verify. If containers are not running, please redeploy.",
                services=None,
                updated_at=datetime.now(timezone.utc),
            )
        
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Deployment record not found. This may happen after a backend restart. Please redeploy monitoring."
        )

    return DeploymentStatusResponse(
        deployment_id=record.deployment_id,
        status=record.status,
        message=record.message,
        services=record.services or None,
        updated_at=record.updated_at,
    )


@router.post("/{instance_id}/teardown", status_code=status.HTTP_200_OK)
async def teardown_instance(
    instance_id: str,
    payload: TeardownRequest,
    repo: TelemetryRepository = Depends(get_repository),
) -> Dict[str, Any]:
    """
    Stop monitoring for a run and clean up telemetry stack.
    
    This works even if the deployment record is not found (e.g., after backend restart).
    Always updates run status to completed, even if teardown fails.
    """
    # First, try using the deployment manager (works if deployment record exists)
    teardown_status = "not_found"
    try:
        await deployment_manager.teardown(instance_id, payload)
        teardown_status = "completed"
    except ValueError as e:
        # Deployment record not found (e.g., backend restarted)
        # This is OK - we'll still update the run status
        teardown_status = f"deployment_not_found: {str(e)}"
    except Exception as e:
        teardown_status = f"error: {str(e)}"

    # ALWAYS update the run status to completed (main purpose of "stop monitoring")
    run_update_status = "failed"
    try:
        await repo.update_run(
            payload.run_id,
            RunUpdate(
                status="completed",
                end_time=datetime.now(timezone.utc),
            ),
        )
        run_update_status = "success"
    except Exception as e:
        run_update_status = f"error: {str(e)}"

    return {
        "success": True,
        "teardown_status": teardown_status,
        "run_update_status": run_update_status,
    }


@router.post("/{instance_id}/cleanup", status_code=status.HTTP_200_OK)
async def cleanup_instance(
    instance_id: str,
    repo: TelemetryRepository = Depends(get_repository),
) -> Dict[str, str]:
    """Clean up all telemetry containers on the instance (for orphaned deployments)."""
    # Get any active run for this instance to get credentials
    runs = await repo.list_runs(instance_id=instance_id, limit=1)
    if not runs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No runs found for instance. Cannot determine credentials.",
        )
    
    # Use the deployment manager to connect and clean up
    from ..schemas import DeploymentRequest
    import paramiko
    
    # Get credentials (we need to get from somewhere - for now use stored credentials)
    # This is a simplified version - in production you'd get stored credentials
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Cleanup endpoint not yet implemented. Use teardown for specific runs.",
    )


@router.get("/{instance_id}/component-status", response_model=Dict[str, Any])
async def get_component_status(
    instance_id: str,
    run_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> Dict[str, Any]:
    """
    Check status of all telemetry components (containers, services, prerequisites).
    Returns status for each component: 'healthy' (green), 'error' (red), or 'not_found' (white).
    """
    # Get the most recent active run if run_id not provided
    if not run_id:
        runs = await repo.list_runs(instance_id=instance_id, status="active", limit=1)
        if not runs:
            # Return empty status if no active run
            return {
                "components": {},
                "message": "No active telemetry run found",
            }
        run_id = runs[0].run_id
    
    # Get run to access credentials
    run = await repo.get_run(run_id, current_user.user_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )
    
    components = {}
    
    try:
        # Find deployment record for this run
        deployment_record = None
        async with deployment_manager._lock:
            for record in deployment_manager._records.values():
                if record.run_id == run_id and record.instance_id == instance_id:
                    deployment_record = record
                    break
        
        if not deployment_record:
            return {
                "components": {
                    "deployment": {"status": "not_found", "message": "No deployment record found"},
                },
                "message": "Deployment not found",
            }
        
        # Connect via SSH to check components
        request = deployment_record.request
        ssh = deployment_manager._connect(request)
        
        try:
            def exec_safe(cmd: str) -> str:
                """Helper to safely execute SSH commands."""
                try:
                    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=10)
                    exit_status = stdout.channel.recv_exit_status()
                    if exit_status == 0:
                        return stdout.read().decode().strip()
                except Exception:
                    pass
                return ""
            
            # Check Docker containers
            containers = [
                "dcgm-exporter",
                "nvidia-smi-exporter", 
                "token-exporter",
                "dcgm-health-exporter",
                "prometheus"
            ]
            
            for container in containers:
                try:
                    # Check if container is running
                    result = exec_safe(f"sudo docker ps --filter 'name={container}' --format '{{{{.Status}}}}'")
                    if result and "Up" in result:
                        components[container] = {
                            "status": "healthy",
                            "message": "Running",
                        }
                    else:
                        # Check if container exists but is stopped
                        exists = exec_safe(f"sudo docker ps -a --filter 'name={container}' --format '{{{{.ID}}}}'")
                        if exists:
                            components[container] = {
                                "status": "error",
                                "message": "Container exists but not running",
                            }
                        else:
                            components[container] = {
                                "status": "not_found",
                                "message": "Container not found",
                            }
                except Exception as e:
                    components[container] = {
                        "status": "error",
                        "message": f"Error checking: {str(e)}",
                    }
            
            # Check DCGM service
            try:
                dcgm_status = exec_safe("systemctl is-active nv-hostengine 2>/dev/null || echo 'inactive'")
                if dcgm_status.strip() == "active":
                    components["dcgm_service"] = {
                        "status": "healthy",
                        "message": "DCGM service is active",
                    }
                else:
                    # Check if DCGM is installed
                    dcgm_installed = exec_safe("command -v dcgmi >/dev/null 2>&1 && echo 'installed' || echo 'not_installed'")
                    if dcgm_installed.strip() == "installed":
                        components["dcgm_service"] = {
                            "status": "error",
                            "message": "DCGM installed but service not active",
                        }
                    else:
                        components["dcgm_service"] = {
                            "status": "not_found",
                            "message": "DCGM not installed",
                        }
            except Exception as e:
                components["dcgm_service"] = {
                    "status": "error",
                    "message": f"Error checking DCGM: {str(e)}",
                }
            
            # Check nvidia-smi
            try:
                nvidia_smi = exec_safe("nvidia-smi --version 2>/dev/null | head -n1 || echo 'not_found'")
                if nvidia_smi and "not_found" not in nvidia_smi:
                    components["nvidia_smi"] = {
                        "status": "healthy",
                        "message": f"Available ({nvidia_smi[:50]})",
                    }
                else:
                    components["nvidia_smi"] = {
                        "status": "error",
                        "message": "nvidia-smi not available",
                    }
            except Exception as e:
                components["nvidia_smi"] = {
                    "status": "error",
                    "message": f"Error checking nvidia-smi: {str(e)}",
                }
            
            # Check Docker
            try:
                docker_version = exec_safe("docker --version 2>/dev/null || echo 'not_found'")
                if docker_version and "not_found" not in docker_version:
                    components["docker"] = {
                        "status": "healthy",
                        "message": "Docker is available",
                    }
                else:
                    components["docker"] = {
                        "status": "error",
                        "message": "Docker not available",
                    }
            except Exception as e:
                components["docker"] = {
                    "status": "error",
                    "message": f"Error checking Docker: {str(e)}",
                }
            
            # Check Prometheus metrics endpoint
            try:
                prom_metrics = exec_safe("curl -s http://localhost:9090/api/v1/status/config 2>/dev/null | head -c 100 || echo 'not_available'")
                if prom_metrics and "not_available" not in prom_metrics:
                    components["prometheus_api"] = {
                        "status": "healthy",
                        "message": "Prometheus API responding",
                    }
                else:
                    components["prometheus_api"] = {
                        "status": "error",
                        "message": "Prometheus API not responding",
                    }
            except Exception as e:
                components["prometheus_api"] = {
                    "status": "error",
                    "message": f"Error checking Prometheus: {str(e)}",
                }
            
            # Check prerequisites status
            for prereq in SYSTEM_PREREQUISITES:
                try:
                    # Special handling for nvidia_driver - check both nvidia-smi and kernel modules
                    if prereq.id == "nvidia_driver":
                        # Check nvidia-smi first
                        nvidia_smi_result = exec_safe("nvidia-smi --version 2>&1 || echo 'nvidia-smi-failed'")
                        # Check if nvidia kernel modules are loaded
                        nvidia_modules = exec_safe("lsmod | grep -E '^nvidia' || echo 'no-modules'")
                        # Check current kernel vs DKMS modules (check both nvidia and nvidia-srv)
                        current_kernel = exec_safe("uname -r").strip()
                        dkms_status_all = exec_safe("sudo dkms status 2>/dev/null || echo 'dkms-not-found'")
                        # Extract driver version from installed packages
                        driver_version = exec_safe("dpkg -l | grep '^ii.*nvidia-driver' | awk '{print $2}' | head -n1 | cut -d- -f3 || echo ''").strip()
                        
                        if "nvidia-smi-failed" in nvidia_smi_result or "no-modules" in nvidia_modules:
                            # Driver not working - check if it's a kernel mismatch
                            # Check if DKMS has modules for current kernel
                            has_current_kernel = current_kernel in dkms_status_all if dkms_status_all and current_kernel else False
                            
                            if not has_current_kernel and driver_version:
                                # Kernel mismatch detected
                                # Try to find the actual module name (nvidia-srv or nvidia)
                                module_name = "nvidia-srv" if "nvidia-srv" in dkms_status_all else "nvidia"
                                # Check if kernel headers are installed
                                headers_check = exec_safe(f"test -d /lib/modules/{current_kernel}/build && echo 'headers-found' || echo 'headers-missing'")
                                if "headers-missing" in headers_check:
                                    components[f"prereq_{prereq.id}"] = {
                                        "status": "error",
                                        "message": f"{prereq.title} - Kernel mismatch (running {current_kernel}, driver built for different kernel). Install headers: sudo apt install -y linux-headers-{current_kernel} && sudo dkms install {module_name}/{driver_version} -k {current_kernel} && sudo reboot",
                                    }
                                else:
                                    components[f"prereq_{prereq.id}"] = {
                                        "status": "error",
                                        "message": f"{prereq.title} - Kernel mismatch (running {current_kernel}, driver built for different kernel). Run: sudo dkms install {module_name}/{driver_version} -k {current_kernel} && sudo reboot",
                                    }
                            else:
                                components[f"prereq_{prereq.id}"] = {
                                    "status": "error",
                                    "message": f"{prereq.title} - Driver installed but not working. Check: lsmod | grep nvidia",
                                }
                        elif nvidia_smi_result and "nvidia-smi-failed" not in nvidia_smi_result:
                            components[f"prereq_{prereq.id}"] = {
                                "status": "healthy",
                                "message": f"{prereq.title} - Working ({nvidia_smi_result.split()[2] if len(nvidia_smi_result.split()) > 2 else 'verified'})",
                            }
                        else:
                            components[f"prereq_{prereq.id}"] = {
                                "status": "not_found",
                                "message": f"{prereq.title} - Not installed",
                            }
                    else:
                        # Run the verify command to check if prerequisite is met
                        verify_result = exec_safe(prereq.verify_command)
                        if verify_result and "not_found" not in verify_result.lower() and "not_available" not in verify_result.lower() and "not_installed" not in verify_result.lower():
                            # Check if command succeeded (exit code 0 means success)
                            # If verify_result is empty but command succeeded, it's healthy
                            # If verify_result has content and doesn't contain error keywords, it's healthy
                            if not verify_result or any(keyword in verify_result.lower() for keyword in ["ok", "active", "installed", "running"]):
                                components[f"prereq_{prereq.id}"] = {
                                    "status": "healthy",
                                    "message": f"{prereq.title} - Verified",
                                }
                            else:
                                components[f"prereq_{prereq.id}"] = {
                                    "status": "error",
                                    "message": f"{prereq.title} - Not met",
                                }
                        else:
                            components[f"prereq_{prereq.id}"] = {
                                "status": "not_found",
                                "message": f"{prereq.title} - Not found",
                            }
                except Exception as e:
                    components[f"prereq_{prereq.id}"] = {
                        "status": "error",
                        "message": f"{prereq.title} - Check failed: {str(e)[:50]}",
                    }
            
            # Check token exporter endpoint specifically for token metrics
            try:
                token_health = exec_safe("curl -s http://localhost:9402/health 2>/dev/null || echo 'not_available'")
                if token_health and "OK" in token_health:
                    components["token_exporter_endpoint"] = {
                        "status": "healthy",
                        "message": "Token exporter endpoint responding",
                    }
                else:
                    components["token_exporter_endpoint"] = {
                        "status": "error",
                        "message": "Token exporter endpoint not responding",
                    }
            except Exception as e:
                components["token_exporter_endpoint"] = {
                    "status": "error",
                    "message": f"Error checking token exporter: {str(e)}",
                }
            
        finally:
            ssh.close()
            
    except Exception as e:
        return {
            "components": {},
            "message": f"Error checking components: {str(e)}",
            "error": str(e),
        }
    
    return {
        "components": components,
        "message": "Component status retrieved",
    }


@router.post("/{instance_id}/run-profiling", status_code=status.HTTP_202_ACCEPTED)
async def run_profiling(
    instance_id: str,
    run_id: Optional[UUID] = None,
    mode: str = Query("standard", description="Profiling mode: standard, kernel, or full"),
    num_requests: int = Query(50, ge=1, le=500, description="Number of requests"),
    concurrency: int = Query(4, ge=1, le=32, description="Max concurrent requests"),
    max_tokens: int = Query(256, ge=1, le=4096, description="Max tokens per request"),
    vllm_server: Optional[str] = Query(None, description="vLLM server URL (e.g. http://localhost:8000)"),
    model_name: Optional[str] = Query(None, description="Model name to benchmark"),
    create_new_run: bool = Query(False, description="Create a new run record (used for kernel mode)"),
    current_user: User = Depends(get_current_user),
    repo: TelemetryRepository = Depends(get_repository),
) -> Dict[str, Any]:
    """Trigger a workload/kernel profiling run on a deployed instance via SSH.

    Uploads agent.py and the telemetry package to the instance, then runs
    agent.py with --backend-url, --run-id, and --ingest-token to upload
    profiling results directly to the backend.

    - mode=standard: Runs workload benchmark collecting TTFT/ITL/throughput via vLLM's streaming API.
      Attaches results to an existing run (pass run_id) or creates a new 'workload' run.
    - mode=kernel: Always creates a NEW separate run with run_type='kernel'. Returns the new run_id.
      Requires vLLM was started with --profiler-config.
    - mode=full: Runs standard then kernel sequentially on the same run.

    Requires an active SSH deployment for the instance (SSH credentials come from deployment record).
    """
    if mode not in ("standard", "kernel", "full"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="mode must be 'standard', 'kernel', or 'full'",
        )

    # Find deployment record for this instance (provides SSH credentials)
    deployment_record = None
    async with deployment_manager._lock:
        for record in deployment_manager._records.values():
            if record.instance_id == instance_id and record.status == "running":
                deployment_record = record
                break

    if not deployment_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active deployment found for this instance. Start GPU monitoring first (it provides the SSH connection).",
        )

    request = deployment_record.request
    backend_url = request.backend_url

    # -----------------------------------------------------------------------
    # Kernel mode: always create a NEW separate run with run_type='kernel'
    # -----------------------------------------------------------------------
    if mode == "kernel" or create_new_run:
        run_type_value = "kernel" if mode == "kernel" else "workload"
        new_run, ingest_token = await repo.create_run(
            RunCreate(
                instance_id=instance_id,
                status="active",
                run_type=run_type_value,
            ),
            current_user.user_id,
        )
        await repo.session.commit()
        effective_run_id = new_run.run_id
    # -----------------------------------------------------------------------
    # Standard/full mode: use existing run_id or create a workload run
    # -----------------------------------------------------------------------
    else:
        if run_id:
            run = await repo.get_run(run_id, current_user.user_id)
            if not run:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Run not found",
                )
            ingest_token = await repo.regenerate_ingest_token(run_id, current_user.user_id)
            if not ingest_token:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot generate ingest token for this run",
                )
            effective_run_id = run_id
        else:
            # No run_id provided — create a standalone workload run
            new_run, ingest_token = await repo.create_run(
                RunCreate(
                    instance_id=instance_id,
                    status="active",
                    run_type="workload",
                ),
                current_user.user_id,
            )
            await repo.session.commit()
            effective_run_id = new_run.run_id

    def _run_profiling_sync():
        import os as _os
        from pathlib import Path as _Path

        ssh = deployment_manager._connect(request)
        try:
            remote_dir = f"/tmp/omni-profiling-{effective_run_id}"
            ssh.exec_command(
                f"mkdir -p {remote_dir}/telemetry/gpu"
                f" {remote_dir}/telemetry/kernel"
                f" {remote_dir}/telemetry/workload"
            )
            import time
            time.sleep(0.5)

            # Upload agent files via SFTP
            sftp = ssh.open_sftp()
            try:
                scripts_dir = _Path(__file__).resolve().parent.parent.parent / "scripts" / "scripts"

                for fname in ["agent.py", "upload.py"]:
                    local = scripts_dir / fname
                    if local.exists():
                        sftp.put(str(local), f"{remote_dir}/{fname}")

                # Upload telemetry package
                tel_dir = scripts_dir / "telemetry"
                if tel_dir.exists():
                    for root, dirs, files in _os.walk(tel_dir):
                        rel = _os.path.relpath(root, scripts_dir)
                        remote_sub = f"{remote_dir}/{rel}".replace("\\", "/")
                        try:
                            sftp.mkdir(remote_sub)
                        except IOError:
                            pass
                        for f in files:
                            if f.endswith(".py"):
                                sftp.put(
                                    _os.path.join(root, f),
                                    f"{remote_sub}/{f}",
                                )
            finally:
                sftp.close()

            # Build agent.py command
            cmd_parts = [
                f"cd {shlex.quote(remote_dir)} && python3 agent.py",
                f"--mode {shlex.quote(mode)}",
                f"--num-requests {num_requests}",
                f"--concurrency {concurrency}",
                f"--max-tokens {max_tokens}",
                f"--backend-url {shlex.quote(str(backend_url))}",
                f"--run-id {shlex.quote(str(effective_run_id))}",
                f"--ingest-token {shlex.quote(str(ingest_token))}",
                "--skip-runara",
                "--no-start-vllm",
                "--skip-dcgm",
            ]
            if vllm_server:
                cmd_parts.append(f"--server {shlex.quote(vllm_server)}")
            if model_name:
                cmd_parts.append(f"--model {shlex.quote(model_name)}")
            cmd_parts.append("2>&1")

            cmd = " ".join(cmd_parts)
            stdin, stdout, stderr = ssh.exec_command(cmd, timeout=600)
            exit_code = stdout.channel.recv_exit_status()
            output = (stdout.read() + stderr.read()).decode("utf-8", errors="replace")[-2000:]

            return {
                "success": exit_code == 0,
                "exit_code": exit_code,
                "output_tail": output,
            }
        finally:
            ssh.close()

    result = await asyncio.get_running_loop().run_in_executor(
        None, _run_profiling_sync
    )

    # Mark kernel/standalone workload runs as completed after agent finishes
    if mode == "kernel" or create_new_run or not run_id:
        from datetime import datetime as _dt, timezone as _tz
        await repo.update_run(
            effective_run_id,
            RunUpdate(
                status="completed" if result["success"] else "failed",
                end_time=_dt.now(_tz.utc),
            ),
        )
        await repo.session.commit()

    return {
        "status": "completed" if result["success"] else "failed",
        "run_id": str(effective_run_id),
        "mode": mode,
        "run_type": "kernel" if mode == "kernel" else "workload" if (create_new_run or not run_id) else "monitoring",
        "exit_code": result["exit_code"],
        "output_tail": result["output_tail"],
    }


@router.get("/jobs", response_model=DeploymentJobListResponse)
async def list_deployment_jobs(
    instance_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    repo: TelemetryRepository = Depends(get_repository),
) -> DeploymentJobListResponse:
    """List deployment jobs with optional filters."""
    jobs = await queue_manager.list_jobs(instance_id=instance_id, status=status, limit=limit)
    stats = await queue_manager.get_queue_stats()
    return DeploymentJobListResponse(
        jobs=[DeploymentJobRead.model_validate(job) for job in jobs],
        total=len(jobs),
        pending=stats["pending"],
        running=stats["running"],
    )


@router.get("/jobs/{job_id}", response_model=DeploymentJobRead)
async def get_deployment_job(
    job_id: UUID,
    repo: TelemetryRepository = Depends(get_repository),
) -> DeploymentJobRead:
    """Get a specific deployment job."""
    job = await queue_manager.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment job not found",
        )
    return DeploymentJobRead.model_validate(job)


@router.post("/jobs/{job_id}/retry", response_model=DeploymentJobRead)
async def retry_deployment_job(
    job_id: UUID,
    repo: TelemetryRepository = Depends(get_repository),
) -> DeploymentJobRead:
    """Retry a failed deployment job."""
    job = await queue_manager.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment job not found",
        )
    if job.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot retry job with status: {job.status}",
        )
    
    # Reset job to pending
    updated = await queue_manager.update_job(
        job_id,
        DeploymentJobUpdate(
            status="pending",
            error_message=None,
            error_log=None,
            locked_by=None,
            locked_at=None,
        ),
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retry job",
        )
    return DeploymentJobRead.model_validate(updated)


@router.post("/jobs/{job_id}/cancel", response_model=DeploymentJobRead)
async def cancel_deployment_job(
    job_id: UUID,
    repo: TelemetryRepository = Depends(get_repository),
) -> DeploymentJobRead:
    """Cancel a pending or queued deployment job."""
    job = await queue_manager.cancel_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment job not found or cannot be cancelled",
        )
    return DeploymentJobRead.model_validate(job)


@router.get("/queue/stats", response_model=Dict[str, Any])
async def get_queue_stats() -> Dict[str, Any]:
    """Get deployment queue statistics."""
    stats = await queue_manager.get_queue_stats()
    return stats

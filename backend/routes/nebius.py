"""
Nebius AI Cloud API Routes - Direct API pattern for instance management.

FastAPI routes for managing Nebius Cloud instances:
- List instances
- Get available presets (GPU types)
- Launch new instances
"""

import logging
import os
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Body, status
from pydantic import BaseModel, Field

from managers.nebius_manager import NebiusManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/nebius", tags=["Nebius"])


# Request/Response Models
class NebiusCredentials(BaseModel):
    """Nebius credentials from frontend."""
    service_account_id: str = Field(..., description="Nebius service account ID")
    key_id: str = Field(..., description="Authorized key ID")
    private_key: str = Field(..., description="PEM private key (can be base64 encoded)")
    project_id: Optional[str] = Field(None, description="Optional project ID override")


class ListInstancesRequest(BaseModel):
    """Request to list instances."""
    credentials: Dict[str, Any] = Field(..., description="Nebius credentials")
    project_id: str = Field(..., description="Nebius project ID")


class GetPresetsRequest(BaseModel):
    """Request to get available presets."""
    credentials: Dict[str, Any] = Field(..., description="Nebius credentials")
    project_id: str = Field(..., description="Nebius project ID")
    region: Optional[str] = Field(None, description="Nebius region identifier")
    quota_name: Optional[str] = Field(
        None,
        description="Quota name to query via QuotaAllowanceService",
    )


class LaunchInstanceRequest(BaseModel):
    """Request to launch a new instance."""
    credentials: Dict[str, Any] = Field(..., description="Nebius credentials")
    project_id: str = Field(..., description="Nebius project ID")
    preset_id: str = Field(..., description="Preset ID (e.g., 'gpu-h100-1x80gb')")
    ssh_public_key: str = Field(..., description="SSH public key to inject")
    zone_id: Optional[str] = Field(None, description="Optional zone ID (auto-detected if not provided)")
    subnet_id: Optional[str] = Field(
        None,
        description="Optional subnet ID. If omitted, server will auto-discover (requires VPC protobufs).",
    )
    ssh_key_name: Optional[str] = Field(
        None,
        description="Optional friendly name for the SSH key being pushed to the VM.",
    )


class DeleteInstanceRequest(BaseModel):
    """Request to delete an instance."""
    credentials: Dict[str, Any] = Field(..., description="Nebius credentials")
    project_id: str = Field(..., description="Nebius project ID")
    instance_id: str = Field(..., description="Nebius instance ID")


class InstanceResponse(BaseModel):
    """Instance information in unified format."""
    id: str
    name: Optional[str] = None
    status: str
    public_ip: Optional[str] = None
    private_ip: Optional[str] = None
    instance_type: str
    zone: Optional[str] = None
    created_at: Optional[int] = None


class PresetResponse(BaseModel):
    """GPU preset information."""
    id: str
    name: str
    platform_id: Optional[str] = None
    platform_name: Optional[str] = None
    gpus: int
    vcpus: int
    memory_gb: int
    gpu_memory_gb: Optional[int] = None
    platform_regions: List[str] = Field(default_factory=list)
    platform_zones: List[str] = Field(default_factory=list)
    hourly_cost_usd: Optional[float] = None
    monthly_cost_usd: Optional[float] = None
    cost_breakdown: Dict[str, Dict[str, Optional[float]]] = Field(default_factory=dict)
 

class NebiusQuotaResponse(BaseModel):
    limit: Optional[int] = None
    usage: Optional[int] = None
    usage_percentage: Optional[float] = None
    state: Optional[str] = None
    usage_state: Optional[str] = None
    unit: Optional[str] = None
    is_near_limit: bool = False
    is_at_limit: bool = False


class PresetListResponse(BaseModel):
    presets: List[PresetResponse]
    quota: Optional[NebiusQuotaResponse] = None
    project_id: Optional[str] = None  # The resolved project_id that was actually used


class DeleteInstanceResponse(BaseModel):
    id: str
    status: str


def _build_project_region_map() -> Dict[str, str]:
    raw = os.getenv("NEBIUS_REGION_PROJECT_MAP", "")
    region_to_project: Dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        region, project = entry.split(":", 1)
        region_to_project[region.strip()] = project.strip()

    default_project = os.getenv("NEBIUS_DEFAULT_PROJECT_ID")
    default_region = os.getenv("NEBIUS_DEFAULT_REGION")
    if default_project and default_region and default_region not in region_to_project:
        region_to_project[default_region] = default_project

    project_to_region: Dict[str, str] = {}
    for region, project in region_to_project.items():
        project_to_region.setdefault(project, region)
    return project_to_region


_PROJECT_TO_REGION = _build_project_region_map()


@router.post("/instances", response_model=List[InstanceResponse])
async def list_instances(request: ListInstancesRequest = Body(...)):
    """
    List all instances in the specified Nebius project.
    
    Credentials are sent from frontend and not stored server-side.
    """
    try:
        manager = NebiusManager(request.credentials)
        instances = await manager.list_instances(request.project_id)
        
        return [InstanceResponse(**instance) for instance in instances]
        
    except ValueError as e:
        logger.error(f"Nebius list instances error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error listing Nebius instances: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list instances: {str(e)}"
        )


@router.post("/presets", response_model=PresetListResponse)
async def get_presets(request: GetPresetsRequest = Body(...)):
    """
    Get available GPU presets (instance types) for the specified project.
    
    Credentials are sent from frontend and not stored server-side.
    If region is provided and NEBIUS_REGION_PROJECT_MAP is configured,
    the project_id will be automatically resolved from the region.
    """
    try:
        # Resolve project_id from region if provided and mapping exists
        effective_project_id = request.project_id
        logger.info("get_presets called with project_id=%s, region=%s", request.project_id, request.region)
        if request.region:
            raw = os.getenv("NEBIUS_REGION_PROJECT_MAP", "")
            logger.debug("NEBIUS_REGION_PROJECT_MAP: %s", raw)
            for entry in raw.split(","):
                entry = entry.strip()
                if not entry or ":" not in entry:
                    continue
                region, project = entry.split(":", 1)
                if region.strip() == request.region.strip():
                    effective_project_id = project.strip()
                    logger.info("Resolved project_id %s for region %s (was %s)", effective_project_id, request.region, request.project_id)
                    break
            else:
                logger.debug("No project mapping found for region %s, using provided project_id %s", request.region, request.project_id)
        else:
            logger.debug("No region provided, using project_id %s", request.project_id)
        
        manager = NebiusManager(request.credentials)
        presets = await manager.get_presets(effective_project_id)
        preset_payload = [PresetResponse(**preset) for preset in presets]

        quota_payload: NebiusQuotaResponse = NebiusQuotaResponse()
        quota_region = request.region or _PROJECT_TO_REGION.get(request.project_id)
        quota_name = request.quota_name or os.getenv("NEBIUS_DEFAULT_QUOTA_NAME")

        if quota_region and quota_name:
            try:
                quota_data = await manager.get_quota_status(
                    project_id=effective_project_id,  # Use effective_project_id for quota lookup
                    region=quota_region,
                    quota_name=quota_name,
                )
                quota_payload = NebiusQuotaResponse(**quota_data)
            except ValueError as quota_err:
                logger.warning(
                    "Nebius quota fetch error for %s/%s: %s",
                    quota_region,
                    quota_name,
                    quota_err,
                )
        else:
            logger.debug(
                "Skipping Nebius quota lookup (region=%s, quota_name=%s)",
                quota_region,
                quota_name,
            )

        return PresetListResponse(presets=preset_payload, quota=quota_payload, project_id=effective_project_id)
        
    except ValueError as e:
        logger.error(f"Nebius get presets error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error getting Nebius presets: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get presets: {str(e)}"
        )


@router.post("/launch", response_model=InstanceResponse)
async def launch_instance(request: LaunchInstanceRequest = Body(...)):
    """
    Launch a new Nebius instance with the specified preset and SSH key.
    
    Automatically discovers the first available subnet in the project.
    Uses hardcoded ubuntu22.04-cuda12 image family.
    
    Credentials are sent from frontend and not stored server-side.
    If zone_id is provided, project_id will be resolved from the region in the zone.
    """
    try:
        # Resolve project_id from zone region if mapping exists
        effective_project_id = request.project_id
        if request.zone_id:
            # Extract region from zone (e.g., "eu-west1-a" -> "eu-west1")
            zone_region = "-".join(request.zone_id.split("-")[:-1]) if "-" in request.zone_id else request.zone_id.split("-")[0]
            raw = os.getenv("NEBIUS_REGION_PROJECT_MAP", "")
            for entry in raw.split(","):
                entry = entry.strip()
                if not entry or ":" not in entry:
                    continue
                region, project = entry.split(":", 1)
                if region.strip() == zone_region.strip():
                    effective_project_id = project.strip()
                    logger.info("Resolved project_id %s for zone %s (region %s)", effective_project_id, request.zone_id, zone_region)
                    break
        
        manager = NebiusManager(request.credentials)
        instance = await manager.launch_instance(
            project_id=effective_project_id,
            preset_id=request.preset_id,
            ssh_public_key=request.ssh_public_key,
            zone_id=request.zone_id,
            subnet_id=request.subnet_id,
            ssh_key_name=request.ssh_key_name,
        )
        
        return InstanceResponse(**instance)
        
    except ValueError as e:
        logger.error(f"Nebius launch instance error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error launching Nebius instance: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to launch instance: {str(e)}"
        )


@router.post("/delete", response_model=DeleteInstanceResponse)
async def delete_instance(request: DeleteInstanceRequest = Body(...)):
    """
    Delete an existing Nebius instance.
    """
    try:
        manager = NebiusManager(request.credentials)
        result = await manager.delete_instance(
            project_id=request.project_id,
            instance_id=request.instance_id,
        )
        return DeleteInstanceResponse(**result)
    except ValueError as e:
        logger.error(f"Nebius delete instance error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Unexpected error deleting Nebius instance: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete instance: {str(e)}",
        )

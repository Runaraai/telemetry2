"""Nebius API proxy endpoints."""

from __future__ import annotations

from typing import List, Optional

import grpc
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from telemetry.services.nebius_client import NebiusComputeClient

router = APIRouter(prefix="/nebius", tags=["Nebius"])
_compute_client = NebiusComputeClient()


class NebiusCredentialPayload(BaseModel):
    service_account_id: Optional[str] = Field(None, description="Override service account id")
    key_id: Optional[str] = Field(None, description="Override authorized key id")
    private_key: Optional[str] = Field(
        None,
        description="PEM private key contents (\n separated or base64).",
    )


class NebiusPlatformsRequest(BaseModel):
    region: str = Field(..., description="Nebius region, e.g., eu-north1")
    project_id: Optional[str] = Field(
        None,
        description="Optional Nebius project/parent id to override the configured map.",
    )
    include_non_gpu: bool = Field(False, description="Include CPU-only presets")
    min_gpu_count: int = Field(
        1,
        ge=0,
        description="Filter out presets with fewer GPUs than this value.",
    )
    credentials: Optional[NebiusCredentialPayload] = Field(
        None,
        description="Optional credential overrides per request.",
    )


class NebiusPresetModel(BaseModel):
    preset_name: str
    gpu_count: int
    vcpu_count: int
    memory_gibibytes: int
    gpu_memory_gibibytes: Optional[int]
    allow_gpu_clustering: bool


class NebiusPlatformModel(BaseModel):
    platform_id: str
    platform_name: str
    human_name: Optional[str]
    region: str
    gpu_memory_gibibytes: Optional[int]
    allow_preset_change: bool
    allowed_for_preemptibles: Optional[bool]
    presets: List[NebiusPresetModel]


class NebiusPlatformsResponse(BaseModel):
    region: str
    project_id: str
    platforms: List[NebiusPlatformModel]


_NEBS_REGIONS = [
    "eu-north1",
    "eu-north2",
    "eu-west1",
    "me-west1",
    "uk-south1",
    "us-central1",
]


@router.get("/regions", response_model=List[str])
async def list_nebius_regions() -> List[str]:
    """Return known public Nebius regions."""
    return _NEBS_REGIONS


@router.post("/platforms", response_model=NebiusPlatformsResponse)
async def list_nebius_platforms(payload: NebiusPlatformsRequest) -> NebiusPlatformsResponse:
    try:
        data = await _compute_client.list_platform_presets(
            region=payload.region,
            project_id=payload.project_id,
            include_non_gpu=payload.include_non_gpu,
            min_gpu_count=payload.min_gpu_count,
            credential_override=payload.credentials.dict(exclude_none=True) if payload.credentials else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except grpc.RpcError as exc:  # pragma: no cover - network failures
        status_code = status.HTTP_502_BAD_GATEWAY
        if exc.code() == grpc.StatusCode.UNAUTHENTICATED:
            status_code = status.HTTP_401_UNAUTHORIZED
        elif exc.code() == grpc.StatusCode.PERMISSION_DENIED:
            status_code = status.HTTP_403_FORBIDDEN
        raise HTTPException(
            status_code=status_code,
            detail=f"Nebius API error: {exc.details()}",
        ) from exc
    return NebiusPlatformsResponse(**data)

"""Routes for Tune Instance (GPU clock & power limit controls)."""

from __future__ import annotations

import base64

from fastapi import APIRouter, HTTPException, status

from ..schemas import (
    TuneInstanceBase,
    TuneSupportedClocksResponse,
    TunePowerLimitsResponse,
    TuneCurrentClockResponse,
    TuneSetClockRequest,
    TuneSetPowerLimitRequest,
)
from ..services.ssh_executor import SSHExecutor
from ..utils.nvidia_smi_parsers import (
    parse_supported_clocks,
    parse_power_limits,
    parse_current_graphics_clock,
)


router = APIRouter(prefix="/instances/tune", tags=["Tune Instance"])


def _resolve_ssh_key(req: TuneInstanceBase) -> str:
    """Resolve ssh_key from request (plain text or base64 PEM)."""
    if req.ssh_key:
        return req.ssh_key
    if req.pem_base64:
        try:
            return base64.b64decode(req.pem_base64).decode("utf-8")
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid pem_base64: {e}",
            ) from e
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Either ssh_key or pem_base64 must be provided",
    )


@router.post("/supported-clocks", response_model=TuneSupportedClocksResponse)
async def fetch_supported_clocks(req: TuneInstanceBase) -> TuneSupportedClocksResponse:
    """
    Fetch supported graphics clock frequencies from the GPU instance.
    Runs nvidia-smi -q -d SUPPORTED_CLOCKS and returns sorted list of frequencies (MHz).
    """
    key = _resolve_ssh_key(req)
    command = "nvidia-smi -q -d SUPPORTED_CLOCKS"
    try:
        stdout, _, _ = await SSHExecutor.execute_remote_command(
            ssh_host=req.ssh_host,
            ssh_user=req.ssh_user,
            ssh_key=key,
            command=command,
            timeout=30,
            check_status=True,
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from e

    supported = parse_supported_clocks(stdout)
    if not supported:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not parse supported clocks from nvidia-smi output",
        )
    return TuneSupportedClocksResponse(supported_clocks_mhz=supported)


@router.post("/power-limits", response_model=TunePowerLimitsResponse)
async def fetch_power_limits(req: TuneInstanceBase) -> TunePowerLimitsResponse:
    """
    Fetch power limit info from the GPU instance.
    Runs nvidia-smi -q -d POWER and returns current, max, and min power limits (W).
    """
    key = _resolve_ssh_key(req)
    command = "nvidia-smi -q -d POWER"
    try:
        stdout, _, _ = await SSHExecutor.execute_remote_command(
            ssh_host=req.ssh_host,
            ssh_user=req.ssh_user,
            ssh_key=key,
            command=command,
            timeout=30,
            check_status=True,
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from e

    current, max_limit, min_limit = parse_power_limits(stdout)
    return TunePowerLimitsResponse(
        current_power_limit_w=current,
        max_power_limit_w=max_limit,
        min_power_limit_w=min_limit,
    )


@router.post("/current-clock", response_model=TuneCurrentClockResponse)
async def fetch_current_clock(req: TuneInstanceBase) -> TuneCurrentClockResponse:
    """
    Fetch current graphics clock from the GPU instance (for progress bar).
    Runs nvidia-smi -q -d CLOCK.
    """
    key = _resolve_ssh_key(req)
    command = "nvidia-smi -q -d CLOCK"
    try:
        stdout, _, _ = await SSHExecutor.execute_remote_command(
            ssh_host=req.ssh_host,
            ssh_user=req.ssh_user,
            ssh_key=key,
            command=command,
            timeout=30,
            check_status=True,
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from e

    current = parse_current_graphics_clock(stdout)
    return TuneCurrentClockResponse(current_graphics_mhz=current)


@router.post("/set-clock", status_code=status.HTTP_200_OK)
async def set_gpu_clock(req: TuneSetClockRequest) -> dict:
    """
    Set GPU graphics clock to the specified frequency (MHz).
    Requires sudo. Command: sudo nvidia-smi -lgc <frequency>
    """
    key = _resolve_ssh_key(req)
    command = f"sudo nvidia-smi -lgc {req.frequency_mhz}"
    try:
        await SSHExecutor.execute_remote_command(
            ssh_host=req.ssh_host,
            ssh_user=req.ssh_user,
            ssh_key=key,
            command=command,
            timeout=30,
            check_status=True,
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from e

    return {"status": "ok", "frequency_mhz": req.frequency_mhz}


@router.post("/reset-clock", status_code=status.HTTP_200_OK)
async def reset_gpu_clock(req: TuneInstanceBase) -> dict:
    """
    Reset GPU clock to default.
    Requires sudo. Command: sudo nvidia-smi -rgc
    """
    key = _resolve_ssh_key(req)
    command = "sudo nvidia-smi -rgc"
    try:
        await SSHExecutor.execute_remote_command(
            ssh_host=req.ssh_host,
            ssh_user=req.ssh_user,
            ssh_key=key,
            command=command,
            timeout=30,
            check_status=True,
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from e

    return {"status": "ok", "message": "GPU clock reset to default"}


@router.post("/set-power-limit", status_code=status.HTTP_200_OK)
async def set_power_limit(req: TuneSetPowerLimitRequest) -> dict:
    """
    Set GPU power limit to the specified value (watts).
    Requires sudo. Command: sudo nvidia-smi -pl <watts>
    """
    key = _resolve_ssh_key(req)
    command = f"sudo nvidia-smi -pl {req.watts}"
    try:
        await SSHExecutor.execute_remote_command(
            ssh_host=req.ssh_host,
            ssh_user=req.ssh_user,
            ssh_key=key,
            command=command,
            timeout=30,
            check_status=True,
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from e

    return {"status": "ok", "watts": req.watts}

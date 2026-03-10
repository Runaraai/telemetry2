"""WebSocket routes for live telemetry."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import decode_access_token
from ..db import get_session
from ..models import Run, User
from ..realtime import live_broker

logger = logging.getLogger(__name__)
router = APIRouter()


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively convert NaN and Infinity values to None for JSON serialization."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {key: _sanitize_for_json(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_for_json(item) for item in obj]
    return obj


async def _verify_websocket_auth(
    run_id: UUID,
    ingest_token: Optional[str] = None,
    jwt_token: Optional[str] = None,
) -> bool:
    """Verify WebSocket authentication via JWT or ingest token.
    
    Args:
        run_id: The run ID
        ingest_token: Optional ingest token for unauthenticated access
        jwt_token: Optional JWT token for authenticated user access
        
    Returns:
        True if authentication is valid
    """
    async for session in get_session():
        # First, check if run exists
        stmt = select(Run).where(Run.run_id == run_id)
        result = await session.execute(stmt)
        run = result.scalar_one_or_none()
        
        if not run:
            return False
        
        # If JWT token is provided, verify user owns the run
        if jwt_token:
            payload = decode_access_token(jwt_token)
            if payload and payload.get("sub"):
                try:
                    user_id = UUID(payload["sub"])
                    if run.user_id == user_id:
                        return True  # User owns the run, allow access
                except (ValueError, TypeError):
                    pass
        
        # If no JWT or JWT doesn't match, check ingest token
        if run.ingest_token_hash:
            # Run has a token - require ingest token
            if not ingest_token:
                return False
            provided_hash = hashlib.sha256(ingest_token.encode()).hexdigest()
            return provided_hash == run.ingest_token_hash
        else:
            # Run has no token - allow access (backwards compatibility)
            return True


@router.websocket("/ws/runs/{run_id}/live")
async def websocket_live_metrics(
    websocket: WebSocket,
    run_id: UUID,
    token: Optional[str] = Query(default=None, description="Ingest token for authentication (optional if JWT provided)"),
    authorization: Optional[str] = Query(default=None, alias="authorization", description="JWT Bearer token (optional)"),
) -> None:
    """Live metrics WebSocket endpoint.
    
    Connect to receive real-time GPU metrics for a run.
    
    Authentication:
    - JWT token: If provided via ?authorization=Bearer%20{token}, user must own the run
    - Ingest token: If provided via ?token={token}, must match run's ingest token
    - No token: Only allowed if run has no ingest token (backwards compatibility)
    
    Args:
        run_id: The run ID to stream metrics for
        token: Optional ingest token for unauthenticated access
        authorization: Optional JWT Bearer token (format: "Bearer {token}")
        
    Examples:
        # With JWT (authenticated user)
        ws://localhost:8000/ws/runs/{run_id}/live?authorization=Bearer%20{jwt_token}
        
        # With ingest token (unauthenticated)
        ws://localhost:8000/ws/runs/{run_id}/live?token={ingest_token}
    
    Close Codes:
        1008: Policy Violation (Unauthorized - invalid or missing token)
        1011: Unexpected Condition (Run not found)
    """
    # Extract JWT from authorization header if provided
    jwt_token = None
    if authorization:
        # Support both "Bearer {token}" and just "{token}" formats
        if authorization.startswith("Bearer "):
            jwt_token = authorization[7:]
        else:
            jwt_token = authorization
    
    # Validate authentication before accepting connection
    is_valid = await _verify_websocket_auth(run_id, ingest_token=token, jwt_token=jwt_token)
    if not is_valid:
        logger.warning(
            f"WebSocket connection rejected for run {run_id}: authentication failed"
        )
        await websocket.close(code=1008, reason="Unauthorized: Invalid or missing authentication")
        return
    
    await websocket.accept()
    logger.info(f"WebSocket connection established for run {run_id}")
    queue = await live_broker.register(run_id)

    # Send periodic ping to keep connection alive (every 30 seconds)
    async def send_ping():
        try:
            while True:
                await asyncio.sleep(30)
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    ping_task = asyncio.create_task(send_ping())

    try:
        while True:
            # Wait for messages with a timeout to allow ping to work
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=60.0)
            except asyncio.TimeoutError:
                # Send keepalive ping if no data received
                try:
                    await websocket.send_json({"type": "keepalive"})
                except Exception:
                    break
                continue

            # Sanitize NaN/Infinity values before JSON serialization
            sanitized_payload = _sanitize_for_json(payload)
            try:
                await websocket.send_json(sanitized_payload)
            except Exception as e:
                logger.error(f"Error sending WebSocket message for run {run_id}: {e}", exc_info=True)
                break
    except WebSocketDisconnect:  # pragma: no cover - network path
        logger.info(f"WebSocket disconnected normally for run {run_id}")
    except Exception as e:
        logger.error(f"WebSocket error for run {run_id}: {e}", exc_info=True)
    finally:
        ping_task.cancel()
        try:
            await ping_task
        except asyncio.CancelledError:
            pass
        await live_broker.unregister(run_id, queue)
        logger.info(f"WebSocket connection closed for run {run_id}")

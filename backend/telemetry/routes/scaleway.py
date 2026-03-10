"""Scaleway products proxy (avoids exposing secrets to browser)."""

from __future__ import annotations

from typing import List, Optional, Dict
import json
import logging
import asyncio


import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
import uuid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scaleway", tags=["Scaleway"])


async def _get_scaleway_credentials_from_user(request: Optional["Request"] = None) -> Optional[Dict]:
    """Get the user's Scaleway credentials from stored credentials."""
    try:
        if not request:
            logger.warning("No request object provided to _get_scaleway_credentials_from_user")
            return None
        
        authorization = request.headers.get("Authorization")
        if not authorization or not authorization.startswith("Bearer "):
            logger.warning("No valid Authorization header found for Scaleway credentials")
            return None
        
        token = authorization.split(" ")[1]
        from telemetry.auth import decode_access_token
        from telemetry.db import async_session
        from telemetry.models import User
        from telemetry.repository import TelemetryRepository
        from sqlalchemy import select
        from uuid import UUID
        
        payload = decode_access_token(token)
        if not payload:
            logger.warning("Token decode failed for Scaleway credentials")
            return None
        
        user_id_str = payload.get("sub")
        if not user_id_str:
            logger.warning("No user_id in token payload for Scaleway credentials")
            return None
        
        try:
            user_id = UUID(user_id_str)
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid user_id in token: {e}")
            return None
        
        async with async_session() as session:
            stmt = select(User).where(User.user_id == user_id)
            result = await session.execute(stmt)
            current_user = result.scalar_one_or_none()
            if not current_user:
                logger.warning(f"User not found for user_id: {user_id}")
                return None
            
            repo = TelemetryRepository(session)
            credentials = await repo.list_credentials(
                user_id=current_user.user_id,
                provider="scaleway",
                credential_type="access_key"
            )
            logger.info(f"Found {len(credentials)} Scaleway credential(s) for user {user_id} (email: {current_user.email})")
            
            if not credentials:
                logger.warning(f"No Scaleway credentials found for user {user_id} (email: {current_user.email})")
                return None
                
            default_cred = next((c for c in credentials if c.name == "default"), credentials[0])
            logger.info(f"Using Scaleway credential: credential_id={default_cred.credential_id}, name={default_cred.name}, created_at={default_cred.created_at}")
            
            secret = await repo.get_credential_secret(default_cred)
            logger.info(f"Retrieved Scaleway secret for user {user_id}: type={type(secret).__name__}, length={len(secret) if secret else 0}, preview={secret[:50] + '...' if secret and len(secret) > 50 else secret}")
            
            if not secret:
                logger.error(f"Scaleway secret is empty for credential {default_cred.credential_id}")
                return None
            
            # Try to parse as JSON, but handle plain strings too
            try:
                secret_data = json.loads(secret) if isinstance(secret, str) else secret
                logger.info(f"Parsed Scaleway secret as JSON: has_secretKey={bool(secret_data.get('secretKey') or secret_data.get('secret_key'))}, has_accessKeyId={bool(secret_data.get('accessKeyId') or secret_data.get('access_key_id'))}, has_projectId={bool(secret_data.get('projectId') or secret_data.get('project_id'))}")
            except json.JSONDecodeError as e:
                # If it's not JSON, treat it as a plain secret_key string
                logger.warning(f"Scaleway secret is not valid JSON for user {user_id}, treating as plain string: {e}, secret_preview={secret[:100] if secret else 'None'}")
                secret_data = {"secret_key": secret}
            
            # Also check metadata for project_id if not in secret_data
            project_id = secret_data.get("projectId") or secret_data.get("project_id")
            if not project_id and default_cred.metadata_json:
                project_id = default_cred.metadata_json.get("project_id")
                logger.info(f"Found project_id in metadata: {project_id}")
            
            result = {
                "secret_key": secret_data.get("secretKey") or secret_data.get("secret_key") or secret,
                "access_key": secret_data.get("accessKeyId") or secret_data.get("access_key_id"),
                "project_id": project_id
            }
            logger.info(f"Returning Scaleway credentials for user {user_id}: has_secret_key={bool(result['secret_key'])}, has_access_key={bool(result['access_key'])}, has_project_id={bool(result['project_id'])}")
            return result
    except Exception as e:
        logger.error(f"Failed to get user Scaleway credentials: {e}", exc_info=True)
    return None

class ScalewayProductsRequest(BaseModel):
    zone: str = Field(..., description="Scaleway zone, e.g., fr-par-1")
    secret_key: Optional[str] = Field(None, description="Scaleway secret key (X-Auth-Token)")
    access_key: Optional[str] = Field(None, description="Scaleway access key (not required for products)")
    project_id: Optional[str] = Field(None, description="Scaleway project id")
    gpu_only: bool = Field(default=True, description="Return only GPU-capable offerings")
    availability: bool = Field(default=True, description="Fetch per-zone availability")


class ScalewayServer(BaseModel):
    id: str
    commercial_type: str
    stock: Optional[str] = None
    availability: Optional[str] = None
    hourly_price: Optional[float] = None
    monthly_price: Optional[float] = None
    gpu: Optional[int] = None
    vcpus: Optional[int] = None
    ram_bytes: Optional[int] = None
    raw: dict


class ScalewayProductsResponse(BaseModel):
    zone: str
    servers: List[ScalewayServer]

class ScalewayLaunchRequest(BaseModel):
    zone: str = Field(..., description="Scaleway zone, e.g., fr-par-1")
    secret_key: Optional[str] = Field(None, description="Scaleway secret key (X-Auth-Token)")
    project_id: Optional[str] = Field(None, description="Scaleway project id")
    commercial_type: str = Field(..., description="Instance commercial type, e.g., L4-1-24G")
    public_key: str = Field(..., description="SSH public key content")
    ssh_key_name: Optional[str] = Field(None, description="Optional SSH key name; autogenerated if omitted")
    image: str = Field("ubuntu_jammy", description="Image ID or slug/label to use when creating the server")
    name: Optional[str] = Field(None, description="Optional server name; autogenerated if omitted")
    root_volume_size: Optional[int] = Field(None, description="Root volume size in bytes (default: let Scaleway decide)")
    root_volume_type: Optional[str] = Field(None, description="Root volume type (l_ssd or sbs_volume, default: auto)")

class ScalewayLaunchResponse(BaseModel):
    id: str
    commercial_type: str
    zone: str
    status: Optional[str] = None
    ip: Optional[str] = None


class ScalewayServerStatusRequest(BaseModel):
    zone: str = Field(..., description="Scaleway zone, e.g., fr-par-1")
    server_id: str = Field(..., description="Scaleway server id")
    secret_key: str = Field(..., description="Scaleway secret key (X-Auth-Token)")
    project_id: Optional[str] = Field(None, description="Scaleway project id")


class ScalewayServerStatusResponse(BaseModel):
    id: str
    commercial_type: Optional[str] = None
    zone: str
    status: Optional[str] = None
    ip: Optional[str] = None
    state_detail: Optional[str] = None


class ScalewayInstancesRequest(BaseModel):
    zone: str = Field(..., description="Scaleway zone, e.g., fr-par-1")
    secret_key: str = Field(..., description="Scaleway secret key (X-Auth-Token)")
    project_id: Optional[str] = Field(None, description="Scaleway project id")
    page: int = Field(1, description="Page of results to fetch")
    per_page: int = Field(50, description="Max number of instances per page (Scaleway max 100)")


class ScalewayInstance(BaseModel):
    id: str
    name: Optional[str] = None
    commercial_type: Optional[str] = None
    zone: Optional[str] = None
    status: Optional[str] = None
    state: Optional[str] = None
    state_detail: Optional[str] = None
    public_ip: Optional[str] = None
    private_ip: Optional[str] = None
    created_at: Optional[str] = None
    modification_date: Optional[str] = None
    project_id: Optional[str] = None
    tags: Optional[List[str]] = None
    raw: dict


class ScalewayInstancesResponse(BaseModel):
    zone: str
    servers: List[ScalewayInstance]


class ScalewayDeleteRequest(BaseModel):
    zone: str = Field(..., description="Scaleway zone, e.g., fr-par-1")
    server_id: str = Field(..., description="Scaleway server id")
    secret_key: str = Field(..., description="Scaleway secret key (X-Auth-Token)")
    project_id: Optional[str] = Field(None, description="Scaleway project id")


class ScalewayDeleteResponse(BaseModel):
    id: str
    zone: str
    status: str


async def _resolve_image_id(client: httpx.AsyncClient, headers: dict, zone: str, image_label: Optional[str]) -> str:
    """Resolve an image id. Accepts an id directly or tries to find by name/label, falling back to Ubuntu."""
    if image_label and image_label.count("-") == 4:
        # Looks like a UUID id, use directly
        return image_label

    params = {"per_page": 50, "arch": "x86_64"}
    if image_label:
        params["name"] = image_label
    url = f"https://api.scaleway.com/instance/v1/zones/{zone}/images"
    resp = await client.get(url, headers=headers, params=params)
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to list images (status {resp.status_code}): {resp.text}",
        )
    images = resp.json().get("images", []) or []
    # Filter to x86_64 images only (GPU instances are always x86_64)
    images = [img for img in images if img.get("arch", "") == "x86_64"]

    def match_label(img):
        name = (img.get("name") or "").lower()
        return image_label and image_label.lower() in name

    # Try to find by provided label
    for img in images:
        if match_label(img):
            return img["id"]

    # Fallback to an Ubuntu image
    for img in images:
        if "ubuntu" in (img.get("name") or "").lower():
            return img["id"]

    if images:
        return images[0]["id"]

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not resolve a valid image for this zone")


@router.get("/regions", response_model=List[str])
async def list_scaleway_regions() -> List[str]:
    """Static list of common GPU regions. Scaleway API lacks a simple region listing."""
    return [
        "fr-par-1",
        "fr-par-2",
        "fr-par-3",
        "nl-ams-1",
        "nl-ams-2",
        "nl-ams-3",
        "pl-waw-1",
        "pl-waw-2",
        "pl-waw-3",
    ]


@router.post("/products", response_model=ScalewayProductsResponse)
async def get_scaleway_products(payload: ScalewayProductsRequest, request: Request) -> ScalewayProductsResponse:
    # Get credentials from user storage if not provided
    if not payload.secret_key:
        user_creds = await _get_scaleway_credentials_from_user(request)
        if user_creds:
            payload.secret_key = payload.secret_key or user_creds.get("secret_key")
            payload.access_key = payload.access_key or user_creds.get("access_key")
            payload.project_id = payload.project_id or user_creds.get("project_id")
        else:
            # Log when credentials are not found for debugging
            logger.warning("Scaleway credentials not found in user storage - user may need to integrate")
    
    if not payload.secret_key:
        raise HTTPException(status_code=400, detail="Scaleway credentials not found. Please integrate first.")
    
    url = f"https://api.scaleway.com/instance/v1/zones/{payload.zone}/products/servers"
    headers = {"X-Auth-Token": payload.secret_key}
    if payload.project_id:
        # Project scoping helps Scaleway return zone-specific availability
        headers["X-Project-ID"] = payload.project_id
    params = {}
    if payload.availability:
        params["availability"] = "true"

    availability_lookup: dict[str, str] = {}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
            # If availability param triggers 400, retry without it
            if resp.status_code == 400 and params.get("availability"):
                resp = await client.get(url, headers=headers)

            if payload.availability:
                avail_url = f"https://api.scaleway.com/instance/v1/zones/{payload.zone}/products/servers/availability"
                try:
                    avail_resp = await client.get(avail_url, headers=headers)
                    if avail_resp.status_code == 200:
                        avail_data = avail_resp.json()
                        raw_avail = avail_data.get("servers") or {}
                        for key, info in raw_avail.items():
                            if isinstance(info, dict):
                                availability_lookup[key] = (
                                    info.get("availability")
                                    or info.get("stock")
                                    or info.get("status")
                                )
                            elif isinstance(info, (str, bool)):
                                availability_lookup[key] = info
                except httpx.RequestError:
                    pass  # ignore availability lookup failures
    except httpx.RequestError as exc:  # pragma: no cover - network failure
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Scaleway API request failed: {exc}",
        ) from exc

    if resp.status_code == 401:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Scaleway credentials")
    if resp.status_code == 403:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied for Scaleway credentials")
    if resp.status_code >= 500:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Scaleway service unavailable (status {resp.status_code}, body: {resp.text})",
        )
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Scaleway API error (status {resp.status_code}): {resp.text}",
        )

    data = resp.json()
    servers_raw = data.get("servers") or {}
    servers: List[ScalewayServer] = []
    for key, val in servers_raw.items():
        hourly_price = None
        monthly_price = None
        stock = val.get("stock")
        availability = val.get("availability")
        commercial_type = val.get("commercial_type") or key

        price_info = val.get("hourly_price") or val.get("hourly_price_with_tax") or {}
        if isinstance(price_info, dict):
            price_val = price_info.get("price") or price_info.get("value")
            if price_val is not None:
                try:
                    hourly_price = float(price_val)
                except Exception:  # pragma: no cover - parse error
                    hourly_price = None
        elif isinstance(price_info, (int, float, str)):
            try:
                hourly_price = float(price_info)
            except Exception:  # pragma: no cover
                hourly_price = None

        monthly_info = val.get("monthly_price") or val.get("monthly_price_with_tax") or {}
        if isinstance(monthly_info, dict):
            price_val = monthly_info.get("price") or monthly_info.get("value")
            if price_val is not None:
                try:
                    monthly_price = float(price_val)
                except Exception:  # pragma: no cover
                    monthly_price = None

        gpu_count = val.get("gpu_count") or val.get("gpu") or None

        def is_gpu_product() -> bool:
            """Identify GPU-capable offerings using count, category, or name hints."""
            if gpu_count and gpu_count > 0:
                return True
            categories = val.get("categories") or []
            if isinstance(categories, list) and any("gpu" in str(c).lower() for c in categories):
                return True
            name_hint = (commercial_type or "").lower()
            # Common GPU product hints
            gpu_markers = ["h100", "a100", "l4", "l40", "h200", "v100", "p100", "gpu"]
            return any(marker in name_hint for marker in gpu_markers)

        # Skip non-GPU types if gpu_only is requested
        if payload.gpu_only and not is_gpu_product():
            continue

        # Explicitly skip known non-target GPU families (as per reported extras)
        name_hint = (commercial_type or "").lower()
        banned_markers = ["3070", "b300", "h100-1-m", "h100-2-m"]
        if any(bad in name_hint for bad in banned_markers):
            continue

        # Optionally skip out-of-stock entries to match UI expectations
        if stock and str(stock).lower() == "out_of_stock":
            continue

        # Derive zone-specific availability if provided
        stock_status = stock or availability
        if not stock_status and availability_lookup:
            stock_status = availability_lookup.get(commercial_type) or availability_lookup.get(key)
        if payload.zone and isinstance(val.get("stocks"), dict):
            zone_entry = val["stocks"].get(payload.zone) or val["stocks"].get(payload.zone.lower()) or val["stocks"].get(payload.zone.upper())
            if isinstance(zone_entry, str):
                stock_status = zone_entry
            elif isinstance(zone_entry, dict):
                stock_status = zone_entry.get("availability") or zone_entry.get("stock") or zone_entry.get("status") or stock_status
        # Normalize booleans to strings
        if isinstance(stock_status, bool):
            stock_status = "available" if stock_status else "no_capacity"

        servers.append(
            ScalewayServer(
                id=key,
                commercial_type=commercial_type,
                stock=stock_status,
                availability=stock_status,
                hourly_price=hourly_price,
                monthly_price=monthly_price,
                gpu=gpu_count,
                vcpus=val.get("ncpus") or val.get("vcpu_count") or None,
                ram_bytes=val.get("ram") or None,
                raw=val,
            )
        )

    return ScalewayProductsResponse(zone=payload.zone, servers=servers)


async def _ensure_ssh_key(client: httpx.AsyncClient, headers: dict, project_id: str, public_key: str, name: Optional[str]) -> str:
    """Create or reuse an SSH key and return its id."""
    key_name = name or f"omniference-{uuid.uuid4().hex[:8]}"

    # First check if the key already exists (by public_key match)
    list_resp = await client.get(
        "https://api.scaleway.com/iam/v1alpha1/ssh-keys",
        headers=headers,
        params={"project_id": project_id},
    )
    if list_resp.status_code == 200:
        for item in list_resp.json().get("ssh_keys", []):
            if item.get("public_key", "").strip() == public_key.strip():
                return item.get("id")

    # Key doesn't exist yet — create it
    create_payload = {
        "name": key_name,
        "public_key": public_key,
        "project_id": project_id,
    }
    resp = await client.post("https://api.scaleway.com/iam/v1alpha1/ssh-keys", headers=headers, json=create_payload)
    if resp.status_code < 400:
        data = resp.json()
        return data.get("id")

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to create SSH key: {resp.text}")


@router.post("/launch", response_model=ScalewayLaunchResponse)
async def launch_scaleway_server(payload: ScalewayLaunchRequest, request: Request) -> ScalewayLaunchResponse:
    """Launch a Scaleway server in the specified zone."""
    import asyncio
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Get credentials from user storage if not provided
        if not payload.secret_key or not payload.project_id:
            user_creds = await _get_scaleway_credentials_from_user(request)
            if user_creds:
                payload.secret_key = payload.secret_key or user_creds.get("secret_key")
                payload.project_id = payload.project_id or user_creds.get("project_id")
        
        if not payload.secret_key or not payload.project_id:
            raise HTTPException(status_code=400, detail="Scaleway credentials not found. Please integrate first.")
        
        headers = {"X-Auth-Token": payload.secret_key, "X-Project-ID": payload.project_id}
        # Generate a name similar to Scaleway's console naming convention
        # If no name provided, use a simpler pattern
        if payload.name:
            server_name = payload.name
        else:
            # Use shorter, cleaner names: scw-{type}-{short-id}
            type_short = payload.commercial_type.lower().replace("-", "").replace("_", "")
            short_id = uuid.uuid4().hex[:6]
            server_name = f"scw-{type_short}-{short_id}"

        async with httpx.AsyncClient(timeout=60) as client:
            # Ensure SSH key exists (Scaleway injects project keys automatically; we just ensure it exists)
            await _ensure_ssh_key(client, headers, payload.project_id, payload.public_key, payload.ssh_key_name)

            # Resolve image label to ID (Scaleway API accepts both labels and IDs)
            image_id = await _resolve_image_id(client, headers, payload.zone, payload.image)

            # Step 1: Create a flexible IP first to ensure we have an IP available
            logger.info(f"Creating flexible IP for Scaleway instance in zone {payload.zone}")
            flexible_ip_id = None
            flexible_ip_address = None
            try:
                create_ip_url = f"https://api.scaleway.com/instance/v1/zones/{payload.zone}/ips"
                create_ip_body = {
                    "project": payload.project_id,
                    "tags": ["omniference-auto"],
                }
                create_ip_resp = await client.post(create_ip_url, headers=headers, json=create_ip_body, timeout=30)
                
                if create_ip_resp.status_code in (200, 201):
                    ip_data = create_ip_resp.json()
                    flexible_ip = ip_data.get("ip") or ip_data
                    flexible_ip_id = flexible_ip.get("id")
                    flexible_ip_address = flexible_ip.get("address")
                    logger.info(f"Created flexible IP {flexible_ip_id} ({flexible_ip_address}) for instance {server_name}")
                else:
                    logger.warning(
                        f"Failed to create flexible IP (status {create_ip_resp.status_code}): {create_ip_resp.text}. "
                        f"Will try to create server without pre-allocated IP."
                    )
            except Exception as e:
                logger.warning(f"Error creating flexible IP: {e}. Will proceed with server creation and attach IP later if needed.")

            # Step 2: Create the server (following Scaleway API documentation structure)
            create_body = {
                "name": server_name,
                "commercial_type": payload.commercial_type,
                "project": payload.project_id,
                "image": image_id,
                "enable_ipv6": False,
            }
            
            # Configure volumes based on Scaleway API behavior:
            # - If l_ssd is specified, Scaleway selects instance_local image
            # - If sbs_volume or no volume specified, Scaleway selects instance_sbs image
            # - H100 instances don't support l_ssd, so we must use sbs_volume
            commercial_type_lower = (payload.commercial_type or "").lower()
            is_h100 = "h100" in commercial_type_lower
            user_provided_volume = payload.root_volume_type is not None or payload.root_volume_size is not None
            
            if is_h100:
                # H100 instances don't support local volumes (l_ssd), must use sbs_volume
                # Try without volumes first to let Scaleway select compatible image/volume
                # If user specified size, we'll add volumes after first attempt if needed
                if payload.root_volume_size is not None:
                    # User wants specific size, use sbs_volume
                    volume_size = payload.root_volume_size
                    create_body["volumes"] = {
                        "0": {
                            "volume_type": "sbs_volume",
                            "size": volume_size,
                        }
                    }
                    logger.info(f"H100 instance detected ({payload.commercial_type}), using sbs_volume ({volume_size / 1_000_000_000:.1f}GB)")
                else:
                    # Let Scaleway handle defaults (will use sbs_volume compatible image)
                    logger.info(f"H100 instance detected ({payload.commercial_type}), letting Scaleway use default volume configuration")
            elif user_provided_volume:
                # User provided volume settings for non-H100 instance
                volume_type = payload.root_volume_type or "l_ssd"
                volume_size = payload.root_volume_size or 20_000_000_000
                create_body["volumes"] = {
                    "0": {
                        "volume_type": volume_type,
                        "size": volume_size,
                    }
                }
                logger.info(f"User specified volume settings: type={volume_type}, size={volume_size / 1_000_000_000:.1f}GB")
            else:
                # Let Scaleway use defaults based on image type
                logger.info("Using Scaleway default volume configuration based on image")
            
            # Try to attach flexible IP during creation (some API versions may support this)
            # If not supported, we'll attach it immediately after creation
            if flexible_ip_id:
                create_body["public_ip"] = flexible_ip_id
                logger.info(f"Attempting to attach flexible IP {flexible_ip_id} during server creation")

            create_url = f"https://api.scaleway.com/instance/v1/zones/{payload.zone}/servers"
            resp = await client.post(create_url, headers=headers, json=create_body)
            
            # If creation failed with public_ip field, try without it (attach after creation)
            if resp.status_code >= 400 and flexible_ip_id and "public_ip" in resp.text.lower():
                logger.info(f"Server creation with public_ip field failed, will attach IP after creation")
                create_body.pop("public_ip", None)
                resp = await client.post(create_url, headers=headers, json=create_body)
            
            # For H100 instances, if creation fails due to image/volume mismatch, try without volumes
            # This lets Scaleway select the appropriate image and volume configuration
            if resp.status_code >= 400 and is_h100 and "volumes" in create_body:
                error_text = resp.text.lower()
                if "image" in error_text or "volume" in error_text or "constraint" in error_text:
                    logger.info(f"H100 instance creation failed with volumes, retrying without explicit volume configuration")
                    create_body.pop("volumes", None)
                    resp = await client.post(create_url, headers=headers, json=create_body)
            
            if resp.status_code >= 400:
                # If server creation failed and we created a flexible IP, try to clean it up
                if flexible_ip_id:
                    try:
                        delete_ip_url = f"https://api.scaleway.com/instance/v1/zones/{payload.zone}/ips/{flexible_ip_id}"
                        await client.delete(delete_ip_url, headers=headers, timeout=10)
                        logger.info(f"Cleaned up flexible IP {flexible_ip_id} after server creation failed")
                    except Exception:
                        pass
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Scaleway create server failed (status {resp.status_code}): {resp.text}",
                )
            data = resp.json()
            server = data.get("server") or {}
            server_id = server.get("id") or server.get("name") or server_name

            # Step 3: Extract IP from server response
            pub_ip = None
            if server.get("public_ip"):
                pub_ip_obj = server.get("public_ip")
                if isinstance(pub_ip_obj, dict):
                    pub_ip = pub_ip_obj.get("address")
                elif isinstance(pub_ip_obj, str):
                    pub_ip = pub_ip_obj
            elif server.get("public_ips"):
                for ip_obj in server.get("public_ips", []):
                    if ip_obj.get("address"):
                        pub_ip = ip_obj["address"]
                        break
            
            # Step 4: If we created a flexible IP, attach it immediately after server creation
            # This ensures the IP is available right away, even if it wasn't attached during creation
            if flexible_ip_id:
                if pub_ip:
                    # Verify the attached IP matches our flexible IP
                    if pub_ip != flexible_ip_address:
                        logger.info(f"Server has IP {pub_ip} but we created flexible IP {flexible_ip_address}. Will attach flexible IP.")
                        pub_ip = None  # Reset to trigger attachment
                else:
                    logger.info(f"Attaching flexible IP {flexible_ip_id} to server {server_id} immediately after creation")
            
            # Attach flexible IP if we have one and it's not already attached
            if flexible_ip_id and not pub_ip:
                try:
                    # Ensure server is running before attaching IP (some zones require this)
                    server_state = server.get("state")
                    if server_state in {"stopped", "stopped_in_place"}:
                        logger.info(f"Powering on instance {server_id} before attaching flexible IP (current state: {server_state})")
                        action_url = f"https://api.scaleway.com/instance/v1/zones/{payload.zone}/servers/{server_id}/action"
                        try:
                            await client.post(action_url, headers=headers, json={"action": "poweron"}, timeout=30)
                            await asyncio.sleep(3)  # Wait for power-on to initiate
                        except Exception as e:
                            logger.warning(f"Could not power on instance {server_id} before IP attachment: {e}")
                    
                    # Attach the flexible IP using PATCH (Scaleway API standard method)
                    logger.info(f"Attaching flexible IP {flexible_ip_id} ({flexible_ip_address}) to server {server_id}")
                    attach_url = f"https://api.scaleway.com/instance/v1/zones/{payload.zone}/servers/{server_id}"
                    attach_body = {
                        "public_ip": flexible_ip_id
                    }
                    attach_resp = await client.patch(attach_url, headers=headers, json=attach_body, timeout=30)
                    
                    if attach_resp.status_code in (200, 202, 204):
                        logger.info(f"Attached flexible IP {flexible_ip_id} to instance {server_id}")
                        pub_ip = flexible_ip_address
                        await asyncio.sleep(2)  # Wait for attachment to complete
                        
                        # Verify IP is attached
                        verify_url = f"https://api.scaleway.com/instance/v1/zones/{payload.zone}/servers/{server_id}"
                        verify_resp = await client.get(verify_url, headers=headers, timeout=10)
                        if verify_resp.status_code == 200:
                            verify_data = verify_resp.json().get("server", {})
                            if verify_data.get("public_ip"):
                                pub_ip = verify_data["public_ip"].get("address") or pub_ip
                            elif verify_data.get("public_ips"):
                                for ip_obj in verify_data.get("public_ips", []):
                                    if ip_obj.get("address"):
                                        pub_ip = ip_obj["address"]
                                        break
                    else:
                        logger.warning(
                            f"Failed to attach flexible IP {flexible_ip_id} to instance {server_id}: "
                            f"status {attach_resp.status_code}, {attach_resp.text}"
                        )
                except Exception as e:
                    logger.error(f"Error attaching flexible IP {flexible_ip_id} to instance {server_id}: {e}", exc_info=True)

            # Step 4: If still no IP, poll briefly (reduced from 2 minutes to 30 seconds)
            if not pub_ip:
                max_attempts = 6  # 6 attempts * 5 seconds = 30 seconds max
                logger.info(f"Polling for IP address on Scaleway instance {server_id} in zone {payload.zone}")
                for attempt in range(max_attempts):
                    await asyncio.sleep(5)
                    try:
                        get_url = f"https://api.scaleway.com/instance/v1/zones/{payload.zone}/servers/{server_id}"
                        get_resp = await client.get(get_url, headers=headers)
                        if get_resp.status_code == 200:
                            server_data = get_resp.json().get("server", {})
                            server_state = server_data.get("state", "unknown")
                            
                            if server_data.get("public_ip"):
                                pub_ip_obj = server_data.get("public_ip")
                                if isinstance(pub_ip_obj, dict):
                                    pub_ip = pub_ip_obj.get("address")
                                elif isinstance(pub_ip_obj, str):
                                    pub_ip = pub_ip_obj
                            elif server_data.get("public_ips"):
                                for ip_obj in server_data.get("public_ips", []):
                                    if ip_obj.get("address"):
                                        pub_ip = ip_obj["address"]
                                        break
                            
                            if pub_ip:
                                logger.info(f"Scaleway instance {server_id} got IP {pub_ip} after {attempt + 1} polling attempts")
                                break
                    except Exception as e:
                        logger.warning(f"Error polling Scaleway instance {server_id} for IP: {e}")
                
                # If still no IP and we have a flexible IP, try one more attachment attempt
                if not pub_ip and flexible_ip_id:
                    logger.info(f"Final attempt to attach flexible IP {flexible_ip_id} to instance {server_id}")
                    try:
                        attach_url = f"https://api.scaleway.com/instance/v1/zones/{payload.zone}/servers/{server_id}"
                        attach_body = {"public_ip": flexible_ip_id}
                        attach_resp = await client.patch(attach_url, headers=headers, json=attach_body, timeout=30)
                        if attach_resp.status_code in (200, 202, 204):
                            pub_ip = flexible_ip_address
                            await asyncio.sleep(2)
                    except Exception as e:
                        logger.warning(f"Final IP attachment attempt failed: {e}")

            # Final step: Ensure server is powered on (if not already)
            if server.get("state") in {"stopped", "stopped_in_place"}:
                action_url = f"https://api.scaleway.com/instance/v1/zones/{payload.zone}/servers/{server_id}/action"
                try:
                    await client.post(action_url, headers=headers, json={"action": "poweron"}, timeout=30)
                    await asyncio.sleep(3)
                    logger.info(f"Powered on Scaleway instance {server_id}")
                except httpx.RequestError as e:
                    logger.warning(f"Could not power on instance {server_id}: {e}")

        return ScalewayLaunchResponse(
            id=server_id,
            commercial_type=server.get("commercial_type") or payload.commercial_type,
            zone=payload.zone,
            status=server.get("state"),
            ip=pub_ip,
        )
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        # Catch any other exceptions and return 500 with details
        logger.error(f"Unexpected error launching Scaleway instance: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to launch Scaleway instance: {str(e)}"
        )


@router.post("/server-status", response_model=ScalewayServerStatusResponse)
async def scaleway_server_status(payload: ScalewayServerStatusRequest, request: Request) -> ScalewayServerStatusResponse:
    # Get credentials from user storage if not provided
    if not payload.secret_key:
        user_creds = await _get_scaleway_credentials_from_user(request)
        if user_creds:
            payload.secret_key = payload.secret_key or user_creds.get("secret_key")
            payload.project_id = payload.project_id or user_creds.get("project_id")
    
    if not payload.secret_key:
        raise HTTPException(status_code=400, detail="Scaleway credentials not found. Please integrate first.")
    
    headers = {"X-Auth-Token": payload.secret_key}
    if payload.project_id:
        headers["X-Project-ID"] = payload.project_id
    url = f"https://api.scaleway.com/instance/v1/zones/{payload.zone}/servers/{payload.server_id}"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code == 404:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    if resp.status_code == 401:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Scaleway credentials")
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch server status (status {resp.status_code}): {resp.text}",
        )
    data = resp.json().get("server", {})
    pub_ip = None
    if data.get("public_ip"):
        pub_ip = data["public_ip"].get("address")
    if not pub_ip and data.get("public_ips"):
        for ipobj in data.get("public_ips") or []:
            if ipobj.get("address"):
                pub_ip = ipobj["address"]
                break

    # If stopped, try to power on
    if data.get("state") in {"stopped", "stopped_in_place"}:
        action_url = f"https://api.scaleway.com/instance/v1/zones/{payload.zone}/servers/{payload.server_id}/action"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(action_url, headers=headers, json={"action": "poweron"})
        except httpx.RequestError:
            pass

    return ScalewayServerStatusResponse(
        id=data.get("id") or payload.server_id,
        commercial_type=data.get("commercial_type"),
        zone=payload.zone,
        status=data.get("state"),
        ip=pub_ip,
        state_detail=data.get("state_detail"),
    )


@router.post("/instances", response_model=ScalewayInstancesResponse)
async def list_scaleway_instances(payload: ScalewayInstancesRequest) -> ScalewayInstancesResponse:
    """List Scaleway servers for a given zone."""

    headers = {"X-Auth-Token": payload.secret_key}
    if payload.project_id:
        headers["X-Project-ID"] = payload.project_id
    zone = payload.zone
    per_page = max(1, min(payload.per_page or 50, 100))
    page = max(payload.page or 1, 1)

    url = f"https://api.scaleway.com/instance/v1/zones/{zone}/servers"
    instances: List[ScalewayInstance] = []

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            current_page = page
            while True:
                params = {"page": current_page, "per_page": per_page}
                resp = await client.get(url, headers=headers, params=params)

                if resp.status_code == 401:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Scaleway credentials")
                if resp.status_code == 403:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied for Scaleway credentials")
                if resp.status_code >= 500:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Scaleway service unavailable (status {resp.status_code}, body: {resp.text})",
                    )
                if resp.status_code >= 400:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Scaleway API error (status {resp.status_code}): {resp.text}",
                    )

                payload_json = resp.json()
                servers = payload_json.get("servers") or []
                for server in servers:
                    server_id = server.get("id", "unknown")
                    server_name = server.get("name", "unknown")
                    
                    # Extract public IP - try multiple methods
                    public_ip = None
                    private_ip = server.get("private_ip")
                    
                    # Method 1: Check public_ip object (most common)
                    public_ip_obj = server.get("public_ip")
                    if public_ip_obj:
                        if isinstance(public_ip_obj, dict):
                            public_ip = public_ip_obj.get("address") or public_ip_obj.get("id")
                        elif isinstance(public_ip_obj, str):
                            public_ip = public_ip_obj
                    
                    # Method 2: Check direct ip field
                    if not public_ip:
                        public_ip = server.get("ip")
                    
                    # Method 3: Check public_ips array
                    if not public_ip and server.get("public_ips"):
                        public_ips_array = server.get("public_ips") or []
                        for entry in public_ips_array:
                            if isinstance(entry, dict):
                                public_ip = entry.get("address") or entry.get("id")
                                if public_ip:
                                    break
                            elif isinstance(entry, str):
                                public_ip = entry
                                break
                    
                    # Method 4: Check for IP in raw network interfaces
                    if not public_ip and server.get("public_ip_address"):
                        addr = server.get("public_ip_address")
                        if isinstance(addr, dict):
                            public_ip = addr.get("address")
                        elif isinstance(addr, str):
                            public_ip = addr
                    
                    # Method 5: If no IP found in list response, fetch server details (more complete data)
                    if not public_ip:
                        try:
                            detail_url = f"https://api.scaleway.com/instance/v1/zones/{zone}/servers/{server_id}"
                            detail_resp = await client.get(detail_url, headers=headers, timeout=10)
                            if detail_resp.status_code == 200:
                                detail_data = detail_resp.json()
                                detail_server = detail_data.get("server") or detail_data
                                
                                # Try all methods again on detailed server data
                                detail_public_ip_obj = detail_server.get("public_ip")
                                if detail_public_ip_obj:
                                    if isinstance(detail_public_ip_obj, dict):
                                        public_ip = detail_public_ip_obj.get("address") or detail_public_ip_obj.get("id")
                                    elif isinstance(detail_public_ip_obj, str):
                                        public_ip = detail_public_ip_obj
                                
                                if not public_ip:
                                    public_ip = detail_server.get("ip")
                                
                                if not public_ip and detail_server.get("public_ips"):
                                    for entry in detail_server.get("public_ips", []):
                                        if isinstance(entry, dict):
                                            public_ip = entry.get("address") or entry.get("id")
                                            if public_ip:
                                                break
                                        elif isinstance(entry, str):
                                            public_ip = entry
                                            break
                                
                                # Update private_ip from detail if not already set
                                if not private_ip:
                                    private_ip = detail_server.get("private_ip")
                                
                                # Update server data with more complete information
                                if detail_server:
                                    server.update(detail_server)
                        except Exception as e:
                            # If detail fetch fails, continue with list data
                            logger.debug(f"Failed to fetch details for server {server_id}: {e}")
                    
                    # Log if instance has no IP (use info level for visibility)
                    if not public_ip:
                        logger.info(
                            f"Scaleway instance {server_id} ({server_name}) in zone {zone} has no public IP. "
                            f"State: {server.get('state')}, Status: {server.get('status')}, "
                            f"public_ip field: {server.get('public_ip')}, "
                            f"ip field: {server.get('ip')}, "
                            f"public_ips array: {server.get('public_ips')}, "
                            f"private_ip: {private_ip}"
                        )
                    
                    instance = ScalewayInstance(
                        id=server_id,
                        name=server.get("name") or server.get("hostname"),
                        commercial_type=server.get("commercial_type"),
                        zone=server.get("zone") or zone,
                        status=server.get("status") or server.get("state"),
                        state=server.get("state"),
                        state_detail=server.get("state_detail"),
                        public_ip=public_ip,
                        private_ip=private_ip,
                        created_at=server.get("creation_date") or server.get("created_at"),
                        modification_date=server.get("modification_date"),
                        project_id=server.get("project") or server.get("project_id"),
                        tags=server.get("tags"),
                        raw=server,
                    )
                    instances.append(instance)

                next_page = payload_json.get("next_page")
                if not next_page or len(servers) < per_page:
                    break
                current_page = next_page
    except httpx.RequestError as exc:  # pragma: no cover - network failure
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Scaleway API request failed: {exc}",
        ) from exc

    return ScalewayInstancesResponse(zone=zone, servers=instances)


@router.post("/delete", response_model=ScalewayDeleteResponse)
async def delete_scaleway_server(payload: ScalewayDeleteRequest) -> ScalewayDeleteResponse:
    """Delete a Scaleway server in the specified zone."""

    headers = {"X-Auth-Token": payload.secret_key}
    if payload.project_id:
        headers["X-Project-ID"] = payload.project_id
    url = f"https://api.scaleway.com/instance/v1/zones/{payload.zone}/servers/{payload.server_id}"
    async def power_off(client: httpx.AsyncClient) -> None:
        action_url = f"https://api.scaleway.com/instance/v1/zones/{payload.zone}/servers/{payload.server_id}/action"
        try:
            await client.post(action_url, headers=headers, json={"action": "poweroff"})
        except httpx.RequestError:
            pass

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for attempt in range(3):
                resp = await client.delete(url, headers=headers)

                if resp.status_code < 400:
                    return ScalewayDeleteResponse(id=payload.server_id, zone=payload.zone, status="deleted")

                if resp.status_code == 404:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
                if resp.status_code == 401:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Scaleway credentials")
                if resp.status_code == 403:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied for Scaleway credentials")
                if resp.status_code >= 500:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Scaleway service unavailable (status {resp.status_code}, body: {resp.text})",
                    )

                # Handle resource still in use error by powering off then retrying
                if resp.status_code == 400:
                    try:
                        payload_json = resp.json()
                    except ValueError:
                        payload_json = {}
                    error_text = resp.text
                    precondition = payload_json.get("precondition")
                    message = payload_json.get("message") or ""
                    if precondition == "resource_still_in_use" or "resource_still_in_use" in error_text:
                        await power_off(client)
                        await asyncio.sleep(5)
                        continue

                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to delete server (status {resp.status_code}): {resp.text}",
                )
    except httpx.RequestError as exc:  # pragma: no cover - network failure
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Scaleway API request failed: {exc}",
        ) from exc

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Failed to delete server after attempting to power it off. Please try again in a few moments.",
    )

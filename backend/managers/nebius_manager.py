"""
Nebius AI Cloud Manager - Direct API pattern for instance management.

This manager handles gRPC communication with Nebius Cloud API for:
- Listing instances
- Getting available GPU presets
- Launching new instances with automatic subnet discovery
"""

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import time

import grpc
import jwt
from grpc import aio

# Nebius protobuf imports (using existing protobuf files in backend/nebius/)
from nebius.common.v1 import (
    metadata_pb2,
    operation_pb2,
    operation_service_pb2,
    operation_service_pb2_grpc,
)

try:
    from nebius.billing.v1alpha1 import (
        calculator_pb2,
        calculator_service_pb2,
        calculator_service_pb2_grpc,
    )
    _HAS_BILLING_SERVICE = True
except ImportError:
    calculator_pb2 = None  # type: ignore
    calculator_service_pb2 = None  # type: ignore
    calculator_service_pb2_grpc = None  # type: ignore
    _HAS_BILLING_SERVICE = False

from nebius.compute.v1 import (
    disk_pb2,
    disk_service_pb2,
    disk_service_pb2_grpc,
    network_interface_pb2,
    platform_service_pb2,
    platform_service_pb2_grpc,
)
from nebius.iam.v1 import token_exchange_service_pb2_grpc, token_service_pb2
from nebius.quotas.v1 import (
    quota_allowance_service_pb2,
    quota_allowance_service_pb2_grpc,
    quota_allowance_pb2,
)

logger = logging.getLogger(__name__)

# Instance/VPC proto availability flags
try:
    from nebius.compute.v1 import (
        instance_pb2,
        instance_service_pb2,
        instance_service_pb2_grpc,
    )
    _HAS_INSTANCE_SERVICE = True
except ImportError:
    instance_pb2 = None  # type: ignore
    instance_service_pb2 = None  # type: ignore
    instance_service_pb2_grpc = None  # type: ignore
    _HAS_INSTANCE_SERVICE = False
    logger.warning(
        "Nebius instance_service protobuf files not found. Instance management will be limited."
    )

try:
    from nebius.vpc.v1 import (
        subnet_pb2,
        subnet_service_pb2,
        subnet_service_pb2_grpc,
    )
    _HAS_VPC_SERVICE = True
except ImportError:
    _HAS_VPC_SERVICE = False
    logger.warning(
        "Nebius VPC subnet_service protobuf files not found. Launch workflow may be limited."
    )

# Nebius API endpoints
_TOKEN_ENDPOINT = "tokens.iam.api.nebius.cloud:443"  # Updated endpoint
_TOKEN_AUDIENCE = "https://iam.api.nebius.cloud/iam/v1/tokens"  # JWT audience
_COMPUTE_ENDPOINT = "compute.api.nebius.cloud:443"
_BILLING_ENDPOINT = "calculator.billing-data-plane.api.nebius.cloud:443"
_VPC_ENDPOINT = "vpc.api.nebius.cloud:443"
_QUOTA_ENDPOINT = "quota-dispatcher.billing-cpl.api.nebius.cloud:443"

# Token exchange constants
_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:token-exchange"
_SUBJECT_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:jwt"
_REQUESTED_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"

# Hardcoded image family as per requirements
_IMAGE_FAMILY = "ubuntu22.04-cuda12"
# Nebius standard images folder - leave empty to use project_id
_IMAGE_FAMILY_FOLDER_ID = os.getenv("NEBIUS_IMAGE_FOLDER_ID", "")
_DEFAULT_SUBNET_ID = os.getenv("NEBIUS_DEFAULT_SUBNET_ID")
_DEFAULT_BOOT_DISK_GB = int(os.getenv("NEBIUS_DEFAULT_BOOT_DISK_GB", "100"))

# Region/platform metadata for UI parity. Nebius PlatformService does not currently
# expose region placement fields in the available proto set, so we enrich presets
# with static knowledge from the public documentation.
_PLATFORM_REGION_MAP: Dict[str, List[str]] = {
    # Hopper / Ada
    "gpu-h100-sxm": ["eu-north1"],
    "gpu-h200-sxm": ["eu-north1", "eu-north2", "eu-west1", "us-central1"],
    "gpu-l40s-a": ["eu-north1"],
    "gpu-l40s-d": ["eu-north1"],
    # Blackwell
    "gpu-b200-sxm": ["us-central1"],
    "gpu-b200-sxm-a": ["me-west1"],
    "gpu-b300-sxm": ["uk-south1"],
    # CPU-only (still allow listing alongside GPU)
    "cpu-d3": ["eu-north1", "eu-west1", "us-central1", "eu-north2", "me-west1", "uk-south1"],
    "cpu-e2": ["eu-north1"],
}

_REGION_ZONE_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    "eu-north1": ("a", "b", "c"),
    "eu-north2": ("a", "b", "c"),
    "eu-west1": ("a", "b", "c"),
    "us-central1": ("a", "b", "c"),
    "me-west1": ("a", "b", "c"),
    "uk-south1": ("a", "b", "c"),
}


def _zones_for_region(region: str) -> List[str]:
    suffixes = _REGION_ZONE_SUFFIXES.get(region, ("a", "b", "c"))
    return [f"{region}-{suffix}" for suffix in suffixes]


class NebiusManager:
    """
    Manager for Nebius Cloud instance operations using gRPC.
    
    Handles authentication via JWT token exchange and provides methods
    for instance management operations.
    """
    
    def __init__(self, credentials: Dict[str, Any]):
        """
        Initialize NebiusManager with credentials.
        
        Args:
            credentials: Dictionary containing:
                - service_account_id: Service account ID
                - key_id: Authorized key ID
                - private_key: PEM private key (can be base64 encoded)
                - project_id: Optional project ID (can be passed per-operation)
        """
        self.credentials = credentials
        self._service_account_id = credentials.get("service_account_id")
        self._key_id = credentials.get("key_id")
        self._private_key = self._normalize_private_key(credentials.get("private_key", ""))
        self._ssl_credentials = grpc.ssl_channel_credentials()
        
        if not self._service_account_id:
            raise ValueError("service_account_id is required in credentials")
        if not self._key_id:
            raise ValueError("key_id is required in credentials")
        if not self._private_key:
            raise ValueError("private_key is required in credentials")
        
        # Log credential info (without sensitive data)
        logger.info(
            "NebiusManager initialized: service_account=%s, key_id=%s, private_key_length=%d",
            self._service_account_id,
            self._key_id,
            len(self._private_key),
        )
    
    @staticmethod
    def _normalize_private_key(raw: str) -> str:
        """Normalize private key - handle base64 encoding and newline issues."""
        if not raw:
            return ""
        text = raw.replace("\\n", "\n").strip()
        
        # If it doesn't look like a PEM, try base64 decode
        if "BEGIN" not in text and len(text) > 0:
            try:
                import base64
                decoded = base64.b64decode(text).decode("utf-8")
                if "BEGIN" in decoded:
                    text = decoded
            except Exception:
                pass
        
        return text
    
    async def _get_access_token(self) -> str:
        """
        Exchange JWT for access token using Nebius Token Exchange Service.
        
        Returns:
            Access token string
        """
        # Build JWT with all required claims including audience
        now = int(time.time())
        payload = {
            "iss": self._service_account_id,
            "sub": self._service_account_id,
            "aud": _TOKEN_AUDIENCE,  # REQUIRED: audience claim for Nebius IAM
            "exp": now + 3600,  # 1 hour expiry
            "iat": now,
        }
        
        logger.debug(
            "Generating JWT: iss=%s, sub=%s, aud=%s, kid=%s",
            self._service_account_id,
            self._service_account_id,
            _TOKEN_AUDIENCE,
            self._key_id,
        )
        
        try:
            jwt_token = jwt.encode(
                payload,
                self._private_key,
                algorithm="RS256",
                headers={"kid": self._key_id},
            )
        except Exception as e:
            logger.error("Failed to encode JWT: %s", e)
            raise ValueError(f"Failed to generate JWT - check your private key: {e}")

        if isinstance(jwt_token, bytes):
            jwt_token = jwt_token.decode("utf-8")
        
        logger.debug("JWT generated successfully, length=%d", len(jwt_token))

        request = token_service_pb2.ExchangeTokenRequest(
            grant_type=_GRANT_TYPE,
            requested_token_type=_REQUESTED_TOKEN_TYPE,
            subject_token=jwt_token,
            subject_token_type=_SUBJECT_TOKEN_TYPE,
        )

        try:
            async with aio.secure_channel(_TOKEN_ENDPOINT, self._ssl_credentials) as channel:
                stub = token_exchange_service_pb2_grpc.TokenExchangeServiceStub(channel)
                response = await stub.Exchange(request)
                logger.debug("Token exchange successful, access_token_length=%d", len(response.access_token))
                return response.access_token
        except grpc.RpcError as e:
            error_code = e.code() if hasattr(e, 'code') else None
            error_details = e.details() if hasattr(e, 'details') else str(e)
            
            logger.error(
                "Token exchange failed: code=%s, details=%s",
                error_code,
                error_details,
            )
            
            if error_code:
                if error_code == grpc.StatusCode.INVALID_ARGUMENT:
                    # Check if it's a key-related error
                    if "Public Key not exists" in error_details or "expired or deactivated" in error_details:
                        raise ValueError(
                            f"Nebius authentication failed: The public key associated with your credentials has expired or been deactivated. "
                            f"Please check your Nebius account and ensure the key_id '{self._key_id}' exists and is active. "
                            f"You may need to create a new key pair in your Nebius service account settings."
                        )
                    else:
                        raise ValueError(
                            f"Nebius authentication failed (invalid argument): {error_details}. "
                            f"Please check your service_account_id, key_id, and private_key."
                        )
                elif error_code == grpc.StatusCode.UNAUTHENTICATED:
                    raise ValueError(
                        "IAM token exchange failed - check your service_account_id, key_id, and private_key"
                    )
                elif error_code == grpc.StatusCode.PERMISSION_DENIED:
                    raise ValueError(
                        "IAM token exchange denied - service account may not have proper permissions"
                    )
            
            raise ValueError(f"IAM token exchange failed: {error_details}")
    
    async def _find_first_subnet(self, project_id: str, token: str) -> str:
        """
        Automatically find the first available subnet in the project.
        """
        if _DEFAULT_SUBNET_ID:
            logger.info("Using default subnet from env: %s", _DEFAULT_SUBNET_ID)
            return _DEFAULT_SUBNET_ID
            
        if not _HAS_VPC_SERVICE:
            raise NotImplementedError(
                "VPC service protobuf files not available. "
                "Please generate subnet_service_pb2.py and subnet_service_pb2_grpc.py "
                "from Nebius API proto definitions and add them to backend/nebius/vpc/v1/, "
                "or set NEBIUS_DEFAULT_SUBNET_ID environment variable."
            )
        
        rpc_metadata = (("authorization", f"Bearer {token}"),)
        
        async with aio.secure_channel(_VPC_ENDPOINT, self._ssl_credentials) as channel:
            stub = subnet_service_pb2_grpc.SubnetServiceStub(channel)
            
            # List subnets in the project
            request = subnet_service_pb2.ListSubnetsRequest(
                parent_id=project_id,
                page_size=100,
            )
            
            try:
                response = await stub.List(request, metadata=rpc_metadata)
                
                fallback_id = None
                # Find first ready subnet
                for subnet in response.items:
                    subnet_id = subnet.metadata.id if subnet.HasField("metadata") else getattr(subnet, "id", None)
                    if subnet_id and not fallback_id:
                        fallback_id = subnet_id
                    if subnet.HasField("status") and subnet.status.state == subnet_pb2.SubnetStatus.State.READY and subnet_id:
                        logger.info("Found READY subnet %s in project %s", subnet_id, project_id)
                        return subnet_id
                
                if fallback_id:
                    logger.warning("No READY subnet found in project %s. Falling back to first subnet %s", project_id, fallback_id)
                    return fallback_id
                raise ValueError(f"No subnet found in project {project_id}")
            except grpc.RpcError as e:
                if e.code() == grpc.StatusCode.PERMISSION_DENIED:
                    raise ValueError(f"Permission denied accessing subnets in project {project_id}")
                elif e.code() == grpc.StatusCode.NOT_FOUND:
                    raise ValueError(f"Project {project_id} not found")
                raise ValueError(f"Failed to list subnets: {e.details()}")

    @staticmethod
    def _parse_cost_value(cost_message: Optional["calculator_pb2.ResourceGroupCost"]) -> Optional[float]:
        """Extract a numeric value from a calculator cost response."""
        if not cost_message or not cost_message.HasField("general"):
            return None
        general = cost_message.general
        raw = general.total.cost or general.total.cost_rounded
        if not raw:
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str):
            try:
                return float(raw)
            except (TypeError, ValueError):
                # Some environments may return currency-wrapped strings; extract first number.
                import re

                m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", raw)
                if not m:
                    return None
                try:
                    return float(m.group(0))
                except (TypeError, ValueError):
                    return None
        return None

    async def _estimate_preset_cost(
        self,
        *,
        project_id: str,
        platform: str,
        preset_id: str,
        subnet_id: Optional[str],
        token: str,
        disk_size_gb: int = _DEFAULT_BOOT_DISK_GB,
    ) -> Optional[Dict[str, Any]]:
        """Call the Nebius billing calculator to estimate compute + storage cost."""
        if not _HAS_BILLING_SERVICE or not calculator_service_pb2 or not calculator_pb2:
            return None
        if not instance_service_pb2 or not instance_pb2:
            return None
        if not platform:
            return None

        metadata = (("authorization", f"Bearer {token}"),)
        boot_disk_placeholder = f"pricing-boot-disk-{preset_id}"

        # For pricing we can omit image folder (parent_id) entirely; image_family is the only required field.
        image_folder = _IMAGE_FAMILY_FOLDER_ID or None

        network_interfaces = []
        if subnet_id:
            network_interfaces = [
                network_interface_pb2.NetworkInterfaceSpec(
                    subnet_id=subnet_id,
                    name="eth0",
                    ip_address=network_interface_pb2.IPAddress(),
                    public_ip_address=network_interface_pb2.PublicIPAddress(),
                )
            ]

        instance_spec = instance_pb2.InstanceSpec(
            service_account_id=self._service_account_id or "",
            # ResourcesSpec.platform expects the platform name (e.g. "gpu-l40s-d"), not the resource ID.
            resources=instance_pb2.ResourcesSpec(platform=platform, preset=preset_id),
            network_interfaces=network_interfaces,
            boot_disk=instance_pb2.AttachedDiskSpec(
                attach_mode=instance_pb2.AttachedDiskSpec.AttachMode.READ_WRITE,
                existing_disk=instance_pb2.ExistingDisk(id=boot_disk_placeholder),
                device_id="boot-disk",
            ),
        )

        instance_request = instance_service_pb2.CreateInstanceRequest(
            metadata=metadata_pb2.ResourceMetadata(parent_id=project_id, name=f"pricing-{preset_id}"),
            spec=instance_spec,
        )

        disk_request = disk_service_pb2.CreateDiskRequest(
            metadata=metadata_pb2.ResourceMetadata(parent_id=project_id, name=boot_disk_placeholder),
            spec=disk_pb2.DiskSpec(
                size_bytes=disk_size_gb * 1024 ** 3,
                block_size_bytes=4096,
                type=disk_pb2.DiskSpec.DiskType.NETWORK_SSD,
                source_image_family=disk_pb2.SourceImageFamily(
                    image_family=_IMAGE_FAMILY,
                    **({"parent_id": image_folder} if image_folder else {}),
                ),
            ),
        )

        resource_specs = {
            "compute": calculator_pb2.ResourceSpec(compute_instance_spec=instance_request),
            "storage": calculator_pb2.ResourceSpec(compute_disk_spec=disk_request),
        }

        component_costs: Dict[str, Dict[str, Optional[float]]] = {}
        total_hourly = 0.0
        total_monthly = 0.0
        have_hourly = False
        have_monthly = False

        async with aio.secure_channel(_BILLING_ENDPOINT, self._ssl_credentials) as channel:
            stub = calculator_service_pb2_grpc.CalculatorServiceStub(channel)
            for label, spec in resource_specs.items():
                try:
                    response = await stub.Estimate(
                        calculator_service_pb2.EstimateRequest(resource_spec=spec),
                        metadata=metadata,
                    )
                except grpc.RpcError as exc:
                    logger.warning(
                        "Nebius pricing estimate failed for preset %s (%s): %s",
                        preset_id,
                        label,
                        exc,
                    )
                    continue

                hourly_value = self._parse_cost_value(response.hourly_cost)
                monthly_value = self._parse_cost_value(response.monthly_cost)

                component_costs[label] = {
                    "hourly": hourly_value,
                    "monthly": monthly_value,
                }

                if hourly_value is not None:
                    total_hourly += hourly_value
                    have_hourly = True
                if monthly_value is not None:
                    total_monthly += monthly_value
                    have_monthly = True

        return {
            "hourly": total_hourly if have_hourly else None,
            "monthly": total_monthly if have_monthly else None,
            "components": component_costs,
        }
    
    async def list_instances(self, project_id: str) -> List[Dict[str, Any]]:
        """
        List all running instances in the project.
        """
        if not _HAS_INSTANCE_SERVICE:
            raise NotImplementedError(
                "Instance service protobuf files not available. "
                "Please generate instance_service_pb2.py and instance_service_pb2_grpc.py "
                "from Nebius API proto definitions and add them to backend/nebius/compute/v1/"
            )
        
        token = await self._get_access_token()
        rpc_metadata = (("authorization", f"Bearer {token}"),)
        
        instances = []
        
        async with aio.secure_channel(_COMPUTE_ENDPOINT, self._ssl_credentials) as channel:
            stub = instance_service_pb2_grpc.InstanceServiceStub(channel)
            
            request = instance_service_pb2.ListInstancesRequest(
                parent_id=project_id,
                page_size=100,
            )
            
            page_token = ""
            while True:
                if page_token:
                    request.page_token = page_token
                
                try:
                    response = await stub.List(request, metadata=rpc_metadata)
                    
                    for instance in response.items:
                        status_state = instance.status.state if instance.HasField("status") else instance_pb2.InstanceStatus.InstanceState.UNSPECIFIED
                        
                        status_map = {
                            instance_pb2.InstanceStatus.InstanceState.RUNNING: "running",
                            instance_pb2.InstanceStatus.InstanceState.STOPPED: "stopped",
                            instance_pb2.InstanceStatus.InstanceState.STARTING: "starting",
                            instance_pb2.InstanceStatus.InstanceState.STOPPING: "stopping",
                            instance_pb2.InstanceStatus.InstanceState.CREATING: "pending",
                            instance_pb2.InstanceStatus.InstanceState.DELETING: "terminating",
                            instance_pb2.InstanceStatus.InstanceState.UPDATING: "updating",
                            instance_pb2.InstanceStatus.InstanceState.ERROR: "error",
                        }
                        status = status_map.get(status_state, "unknown")
                        
                        public_ip = None
                        private_ip = None
                        if instance.HasField("status"):
                            for interface in instance.status.network_interfaces:
                                if interface.ip_address.address:
                                    private_ip = interface.ip_address.address
                                if interface.public_ip_address.address:
                                    public_ip = interface.public_ip_address.address
                        
                        instance_type = "unknown"
                        if instance.HasField("spec") and instance.spec.HasField("resources"):
                            resources = instance.spec.resources
                            if resources.preset:
                                instance_type = resources.preset
                            elif resources.platform:
                                instance_type = resources.platform
                        
                        resource_meta = instance.metadata if instance.HasField("metadata") else None
                        created_at = None
                        if resource_meta and resource_meta.HasField("created_at"):
                            created_at = resource_meta.created_at.seconds
                        
                        zone = None
                        if resource_meta and resource_meta.labels:
                            labels = dict(resource_meta.labels)
                            zone = labels.get("zone_id") or labels.get("zone") or labels.get("nebius.net/zone")
                        
                        instances.append({
                            "id": resource_meta.id if resource_meta and resource_meta.id else "",
                            "name": resource_meta.name if resource_meta and resource_meta.name else None,
                            "status": status,
                            "public_ip": public_ip,
                            "private_ip": private_ip,
                            "instance_type": instance_type,
                            "zone": zone,
                            "created_at": created_at,
                        })
                    
                    if not response.next_page_token:
                        break
                    page_token = response.next_page_token
                    
                except grpc.RpcError as e:
                    if e.code() == grpc.StatusCode.UNAUTHENTICATED:
                        raise ValueError("Authentication failed - check your credentials")
                    elif e.code() == grpc.StatusCode.PERMISSION_DENIED:
                        raise ValueError(f"Permission denied accessing project {project_id}")
                    elif e.code() == grpc.StatusCode.NOT_FOUND:
                        raise ValueError(f"Project {project_id} not found")
                    raise ValueError(f"Failed to list instances: {e.details()}")
        
        logger.info("Nebius InstanceService.List returned %d item(s) for project %s", len(instances), project_id)
        return instances
    
    async def get_presets(self, project_id: str) -> List[Dict[str, Any]]:
        """
        Get available GPU presets (instance types) for the project.
        """
        token = await self._get_access_token()
        metadata = (("authorization", f"Bearer {token}"),)
        
        presets = []
        
        async with aio.secure_channel(_COMPUTE_ENDPOINT, self._ssl_credentials) as channel:
            # Use PlatformService to get available platforms/presets
            platform_stub = platform_service_pb2_grpc.PlatformServiceStub(channel)
            
            request = platform_service_pb2.ListPlatformsRequest(
                parent_id=project_id,
                page_size=100,
            )
            
            page_token = ""
            # Track preset IDs across all platforms to avoid duplicates
            seen_preset_ids = set()
            
            while True:
                if page_token:
                    request.page_token = page_token
                
                try:
                    response = await platform_stub.List(request, metadata=metadata)
                    
                    logger.info("Received %d platforms from Nebius API for project %s", len(response.items), project_id)
                    
                    for platform in response.items:
                        platform_id = platform.metadata.id
                        platform_name = platform.metadata.name or ""
                        preset_count = len(platform.spec.presets)
                        gpu_preset_count = sum(1 for p in platform.spec.presets if p.resources.gpu_count > 0)
                        logger.info("Platform: %s (id: %s) - Total presets: %d, GPU presets: %d", 
                                  platform_name, platform_id, preset_count, gpu_preset_count)
                        
                        declared_regions = _PLATFORM_REGION_MAP.get(platform_name, [])
                        platform_zones: List[str] = []
                        for region in declared_regions:
                            platform_zones.extend(_zones_for_region(region))
                        
                        for preset in platform.spec.presets:
                            # Only include GPU presets (Nebius UI pattern)
                            if preset.resources.gpu_count > 0:
                                # Create unique preset identifier (platform_id:preset_name)
                                preset_id = f"{platform_id}:{preset.name}"
                                
                                # Skip if we've already seen this exact preset
                                if preset_id in seen_preset_ids:
                                    logger.debug("Skipping duplicate preset: %s (platform: %s)", preset.name, platform_name)
                                    continue
                                seen_preset_ids.add(preset_id)
                                
                                presets.append({
                                    "id": preset.name,
                                    "name": preset.name,
                                    "platform_id": platform_id,
                                    "platform_name": platform_name,
                                    "gpus": preset.resources.gpu_count,
                                    "vcpus": preset.resources.vcpu_count,
                                    "memory_gb": preset.resources.memory_gibibytes,
                                    "gpu_memory_gb": platform.spec.gpu_memory_gibibytes,
                                    "platform_regions": declared_regions,
                                    "platform_zones": platform_zones,
                                })
                    
                    if not response.next_page_token:
                        break
                    page_token = response.next_page_token
                    
                except grpc.RpcError as e:
                    if e.code() == grpc.StatusCode.UNAUTHENTICATED:
                        raise ValueError("Authentication failed - check your credentials")
                    elif e.code() == grpc.StatusCode.PERMISSION_DENIED:
                        raise ValueError(f"Permission denied accessing project {project_id}")
                    elif e.code() == grpc.StatusCode.NOT_FOUND:
                        raise ValueError(f"Project {project_id} not found")
                    raise ValueError(f"Failed to list presets: {e.details()}")
        
        pricing_subnet_id: Optional[str] = None
        if presets and _HAS_BILLING_SERVICE:
            pricing_subnet_id = _DEFAULT_SUBNET_ID
            if pricing_subnet_id:
                logger.info("Nebius pricing: using NEBIUS_DEFAULT_SUBNET_ID=%s", pricing_subnet_id)
            else:
                try:
                    pricing_subnet_id = await self._find_first_subnet(project_id, token)
                except Exception as pricing_err:
                    logger.warning(
                        "Nebius pricing disabled (subnet lookup failed). "
                        "Set NEBIUS_DEFAULT_SUBNET_ID to enable estimates without subnet discovery: %s",
                        pricing_err,
                    )

        if presets and _HAS_BILLING_SERVICE:
            for preset in presets:
                platform_name = preset.get("platform_name")
                preset_identifier = preset.get("id") or preset.get("name")
                if not platform_name or not preset_identifier:
                    continue
                try:
                    pricing = await self._estimate_preset_cost(
                        project_id=project_id,
                        platform=platform_name,
                        preset_id=preset_identifier,
                        subnet_id=pricing_subnet_id,
                        token=token,
                    )
                except Exception as exc:
                    logger.warning("Nebius pricing failed for %s: %s", preset_identifier, exc)
                    continue

                if pricing:
                    preset["hourly_cost_usd"] = pricing.get("hourly")
                    preset["monthly_cost_usd"] = pricing.get("monthly")
                    preset["cost_breakdown"] = pricing.get("components", {})
        
        logger.info("Returning %d total presets for project %s", len(presets), project_id)
        # Log unique platforms found
        unique_platforms = set(p.get("platform_name") for p in presets)
        logger.info("Unique platforms found: %s", ", ".join(unique_platforms) if unique_platforms else "none")
        
        return presets
    
    async def get_quota_status(
        self,
        project_id: str,
        region: str,
        quota_name: str,
    ) -> Dict[str, Any]:
        """
        Retrieve quota usage information for a given project/region/quota name.
        """
        token = await self._get_access_token()
        metadata = (("authorization", f"Bearer {token}"),)

        request = quota_allowance_service_pb2.GetByNameRequest(
            parent_id=project_id,
            name=quota_name,
            region=region,
        )

        async with aio.secure_channel(_QUOTA_ENDPOINT, self._ssl_credentials) as channel:
            stub = quota_allowance_service_pb2_grpc.QuotaAllowanceServiceStub(channel)
            try:
                allowance = await stub.GetByName(request, metadata=metadata)
            except grpc.RpcError as e:
                if e.code() == grpc.StatusCode.PERMISSION_DENIED:
                    raise ValueError(f"Permission denied accessing quota {quota_name}")
                elif e.code() == grpc.StatusCode.NOT_FOUND:
                    raise ValueError(f"Quota '{quota_name}' not found for region {region}")
                raise ValueError(f"Failed to fetch quota '{quota_name}': {e.details()}")

        spec = allowance.spec if allowance.HasField("spec") else None
        status = allowance.status if allowance.HasField("status") else None

        limit: Optional[int] = None
        if spec and spec.HasField("limit"):
            limit = spec.limit

        usage = status.usage if status else None

        usage_percentage: Optional[float] = None
        if status and status.usage_percentage:
            try:
                usage_percentage = float(status.usage_percentage)
            except ValueError:
                usage_percentage = None

        ratio: Optional[float] = None
        if limit and limit > 0 and usage is not None:
            ratio = usage / limit

        is_at_limit = ratio is not None and ratio >= 1.0
        is_near_limit = ratio is not None and not is_at_limit and ratio >= 0.8

        state = None
        usage_state = None
        unit = status.unit if status and status.unit else None

        if status:
            try:
                state = quota_allowance_pb2.QuotaAllowanceStatus.State.Name(status.state)
            except ValueError:
                state = str(status.state)
            try:
                usage_state = quota_allowance_pb2.QuotaAllowanceStatus.UsageState.Name(
                    status.usage_state
                )
            except ValueError:
                usage_state = str(status.usage_state)

        return {
            "limit": limit,
            "usage": usage,
            "usage_percentage": usage_percentage,
            "state": state,
            "usage_state": usage_state,
            "unit": unit,
            "is_near_limit": is_near_limit,
            "is_at_limit": is_at_limit,
        }

    async def delete_instance(self, project_id: str, instance_id: str) -> Dict[str, Any]:
        """
        Delete a Nebius instance by ID.
        """
        if not _HAS_INSTANCE_SERVICE:
            raise NotImplementedError(
                "Instance service protobuf files not available. "
                "Please generate instance_service_pb2.py and instance_service_pb2_grpc.py "
                "from Nebius API proto definitions and add them to backend/nebius/compute/v1/"
            )

        token = await self._get_access_token()
        metadata = (("authorization", f"Bearer {token}"),)

        async with aio.secure_channel(_COMPUTE_ENDPOINT, self._ssl_credentials) as channel:
            instance_stub = instance_service_pb2_grpc.InstanceServiceStub(channel)
            operation_stub = operation_service_pb2_grpc.OperationServiceStub(channel)

            request = instance_service_pb2.DeleteInstanceRequest(id=instance_id)

            try:
                operation = await instance_stub.Delete(request, metadata=metadata)
            except grpc.RpcError as e:
                if e.code() == grpc.StatusCode.UNAUTHENTICATED:
                    raise ValueError("Authentication failed - check your credentials")
                elif e.code() == grpc.StatusCode.PERMISSION_DENIED:
                    raise ValueError(f"Permission denied deleting instance {instance_id}")
                elif e.code() == grpc.StatusCode.NOT_FOUND:
                    raise ValueError(f"Instance {instance_id} not found")
                raise ValueError(f"Failed to delete instance: {e.details()}")

            if hasattr(operation, "id") and operation.id:
                delete_operation = await poll_operation_until_done(
                    operation_service=operation_stub,
                    operation_id=operation.id,
                    metadata=metadata,
                )
                if delete_operation.status.code != 0:
                    message = delete_operation.status.message or "instance deletion failed"
                    raise ValueError(message)

            return {
                "id": instance_id,
                "status": "deleted",
            }
    
    async def launch_instance(
        self,
        project_id: str,
        preset_id: str,
        ssh_public_key: str,
        zone_id: Optional[str] = None,
        subnet_id: Optional[str] = None,
        ssh_key_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Launch a new instance with the specified preset and SSH key.
        """
        if not _HAS_INSTANCE_SERVICE:
            raise NotImplementedError(
                "Instance service protobuf files not available. "
                "Please generate instance_service_pb2.py and instance_service_pb2_grpc.py "
                "from Nebius API proto definitions and add them to backend/nebius/compute/v1/"
            )
        
        token = await self._get_access_token()
        metadata = (("authorization", f"Bearer {token}"),)
        
        # Resolve subnet: provided -> env -> discovery
        effective_subnet_id = subnet_id or _DEFAULT_SUBNET_ID
        if effective_subnet_id:
            logger.info("Using provided/default subnet %s for project %s", effective_subnet_id, project_id)
        elif _HAS_VPC_SERVICE:
            effective_subnet_id = await self._find_first_subnet(project_id, token)
            logger.info("Discovered subnet %s for project %s", effective_subnet_id, project_id)
        else:
            raise ValueError(
                "Nebius VPC subnet service protobuf files not available and no subnet_id provided. "
                "Set NEBIUS_DEFAULT_SUBNET_ID or pass subnet_id in the launch request."
            )
        
        # If zone not provided, use the zone from subnet or default
        if not zone_id:
            zone_id = "eu-north1-a"  # Default zone
        
        # Build instance creation request
        instance_name = f"omniference-{int(time.time())}"
        boot_disk_name = f"{instance_name}-boot"
        
        # Determine image folder - try not specifying it first (use API default)
        # If that fails, we can try explicit formats: project-{region}-public-images or project-{region}public-images
        if _IMAGE_FAMILY_FOLDER_ID:
            image_folder = _IMAGE_FAMILY_FOLDER_ID
        else:
            # Don't specify image_folder - let API use its default (project-{region}public-images)
            # This avoids permission issues with explicit folder specification
            image_folder = None
        
        logger.info(
            "Launching instance: name=%s, project=%s, preset=%s, zone=%s, subnet=%s, image_folder=%s",
            instance_name, project_id, preset_id, zone_id, effective_subnet_id, image_folder,
        )
        
        # Create network interface with the discovered subnet
        network_interface = network_interface_pb2.NetworkInterfaceSpec(
            subnet_id=effective_subnet_id,
            name="eth0",
            ip_address=network_interface_pb2.IPAddress(),
            public_ip_address=network_interface_pb2.PublicIPAddress(),
        )
        
        async with aio.secure_channel(_COMPUTE_ENDPOINT, self._ssl_credentials) as channel:
            disk_stub = disk_service_pb2_grpc.DiskServiceStub(channel)
            instance_stub = instance_service_pb2_grpc.InstanceServiceStub(channel)
            operation_stub = operation_service_pb2_grpc.OperationServiceStub(channel)
            
            # Step 1: create boot disk from the Ubuntu image family and wait for completion.
            logger.info("Creating boot disk: name=%s, image_family=%s, folder=%s", boot_disk_name, _IMAGE_FAMILY, image_folder)
            
            try:
                disk_operation = await create_boot_disk(
                    disk_service=disk_stub,
                    project_id=project_id,
                    image_family=_IMAGE_FAMILY,
                    image_folder=image_folder,
                    disk_size_gb=_DEFAULT_BOOT_DISK_GB,
                    disk_name=boot_disk_name,
                    metadata=metadata,
                )
            except grpc.RpcError as e:
                logger.error(
                    "Disk creation RPC failed: code=%s, details=%s",
                    e.code() if hasattr(e, 'code') else 'unknown',
                    e.details() if hasattr(e, 'details') else str(e),
                )
                if hasattr(e, 'code'):
                    if e.code() == grpc.StatusCode.PERMISSION_DENIED:
                        error_msg = (
                            f"Permission denied creating disk in project {project_id}. "
                            f"Ensure the service account has 'compute.disks.create' permission. "
                        )
                        if image_folder:
                            error_msg += f"Also ensure access to image folder '{image_folder}'. "
                        else:
                            error_msg += f"Also ensure access to the default public images folder for region. "
                        error_msg += (
                            f"If the error persists, you may need to set NEBIUS_IMAGE_FOLDER_ID environment variable "
                            f"to the correct image folder ID, or grant the service account access to public images."
                        )
                        raise ValueError(error_msg)
                    elif e.code() == grpc.StatusCode.NOT_FOUND:
                        error_msg = f"Image family '{_IMAGE_FAMILY}' not found"
                        if image_folder:
                            error_msg += f" in folder '{image_folder}'"
                        error_msg += ". Check NEBIUS_IMAGE_FOLDER_ID environment variable or verify the image family exists."
                        raise ValueError(error_msg)
                raise ValueError(f"Failed to create boot disk: {e}")
            
            logger.info("Waiting for disk operation %s to complete...", disk_operation.id)
            
            disk_operation = await poll_operation_until_done(
                operation_service=operation_stub,
                operation_id=disk_operation.id,
                metadata=metadata,
            )
            
            if disk_operation.status.code != 0:
                message = disk_operation.status.message or "boot disk creation failed"
                logger.error("Disk operation failed: %s", message)
                raise ValueError(f"Boot disk operation failed: {message}")
            
            boot_disk_id = disk_operation.resource_id
            if not boot_disk_id:
                raise ValueError("Boot disk creation returned no resource_id")
            
            logger.info("Boot disk created: %s", boot_disk_id)
            
            boot_disk = instance_pb2.AttachedDiskSpec(
                attach_mode=instance_pb2.AttachedDiskSpec.AttachMode.READ_WRITE,
                existing_disk=instance_pb2.ExistingDisk(id=boot_disk_id),
                device_id="boot-disk",
            )
            
            # Look up platform_id and platform_name from presets
            presets = await self.get_presets(project_id)
            
            platform_id = None
            platform_name = None
            for preset in presets:
                preset_identifier = preset.get("id") or preset.get("name")
                if preset_identifier == preset_id:
                    platform_id = preset.get("platform_id")  # Resource ID
                    platform_name = preset.get("platform_name")  # Platform name like "gpu-l40s-d"
                    break
            
            if not platform_id or not platform_name:
                raise ValueError(
                    f"Could not find platform information for preset '{preset_id}'. "
                    f"Please verify the preset exists and try again."
                )
            
            logger.info("Found platform_name %s (id: %s) for preset %s", platform_name, platform_id, preset_id)
            
            # Create cloud-init user data with SSH key
            cloud_init = f"""#cloud-config
users:
  - name: omniference
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - {ssh_public_key.strip()}
"""
            
            # Create instance spec with cloud-init
            # ResourcesSpec.platform expects the platform name (e.g., "gpu-l40s-d"), not the resource ID
            instance_spec = instance_pb2.InstanceSpec(
                resources=instance_pb2.ResourcesSpec(
                    platform=platform_name,
                    preset=preset_id,
                ),
                boot_disk=boot_disk,
                network_interfaces=[network_interface],
                cloud_init_user_data=cloud_init,
            )
            
            # Create instance request
            create_request = instance_service_pb2.CreateInstanceRequest(
                metadata=metadata_pb2.ResourceMetadata(
                    parent_id=project_id,
                    name=instance_name,
                ),
                spec=instance_spec,
            )
            
            logger.info("Creating instance %s with preset %s...", instance_name, preset_id)
            
            try:
                operation = await instance_stub.Create(create_request, metadata=metadata)
                
                instance_id = operation.resource_id if hasattr(operation, 'resource_id') else None
                operation_id = operation.id if hasattr(operation, 'id') else None
                
                logger.info("Instance creation started: operation_id=%s, resource_id=%s", operation_id, instance_id)
                
                return {
                    "id": instance_id or operation_id or "pending",
                    "status": "creating",
                    "name": instance_name,
                    "public_ip": None,
                    "private_ip": None,
                    "instance_type": preset_id,
                    "zone": zone_id,
                    "operation_id": operation_id,
                }
                
            except grpc.RpcError as e:
                logger.error(
                    "Instance creation RPC failed: code=%s, details=%s",
                    e.code() if hasattr(e, 'code') else 'unknown',
                    e.details() if hasattr(e, 'details') else str(e),
                )
                if hasattr(e, 'code'):
                    if e.code() == grpc.StatusCode.UNAUTHENTICATED:
                        raise ValueError("Authentication failed - check your credentials")
                    elif e.code() == grpc.StatusCode.PERMISSION_DENIED:
                        raise ValueError(f"Permission denied creating instance in project {project_id}")
                    elif e.code() == grpc.StatusCode.INVALID_ARGUMENT:
                        raise ValueError(f"Invalid arguments: {e.details()}")
                    elif e.code() == grpc.StatusCode.NOT_FOUND:
                        raise ValueError(f"Project {project_id} or subnet not found")
                raise ValueError(f"Failed to create instance: {e.details() if hasattr(e, 'details') else str(e)}")


# -----------------------------------------------------------------------------
# Helper utilities used by the Nebius launch flow
# -----------------------------------------------------------------------------


async def poll_operation_until_done(
    operation_service: operation_service_pb2_grpc.OperationServiceStub,
    operation_id: str,
    *,
    metadata: Optional[Sequence[Tuple[str, str]]] = None,
    poll_interval: float = 2.0,
    timeout: float = 600.0,  # 10 minute timeout
) -> operation_pb2.Operation:
    """
    Poll OperationService.Get until the specified operation is done.
    """
    start_time = time.time()
    while True:
        if time.time() - start_time > timeout:
            raise ValueError(f"Operation {operation_id} timed out after {timeout}s")
        
        operation = await operation_service.Get(
            operation_service_pb2.GetOperationRequest(id=operation_id),
            metadata=metadata,
        )
        # Nebius operations don't expose the standard google.longrunning `done` flag.
        # Instead, the presence of `status`/`finished_at` indicates completion.
        if operation.HasField("status") or operation.HasField("finished_at"):
            return operation
        await asyncio.sleep(poll_interval)


async def create_boot_disk(
    disk_service: disk_service_pb2_grpc.DiskServiceStub,
    project_id: str,
    image_family: str,
    *,
    image_folder: Optional[str] = None,
    disk_size_gb: int = 100,
    disk_name: Optional[str] = None,
    metadata: Optional[Sequence[Tuple[str, str]]] = None,
) -> operation_pb2.Operation:
    """
    Create a boot disk by calling DiskService.Create and return the operation.
    """
    resolved_name = disk_name or f"omniference-boot-{int(time.time())}"
    size_bytes = disk_size_gb * 1024**3
    
    logger.debug(
        "create_boot_disk: name=%s, project=%s, image_family=%s, image_folder=%s, size_gb=%d",
        resolved_name, project_id, image_family, image_folder, disk_size_gb,
    )
    
    # Build SourceImageFamily - only include parent_id if image_folder is provided
    # If None, the API will use its default (project-{region}public-images)
    source_image_family = disk_pb2.SourceImageFamily(
        image_family=image_family,
    )
    if image_folder:
        source_image_family.parent_id = image_folder
    
    disk_spec = disk_pb2.DiskSpec(
        size_bytes=size_bytes,
        block_size_bytes=4096,
        type=disk_pb2.DiskSpec.DiskType.NETWORK_SSD,
        source_image_family=source_image_family,
    )

    request = disk_service_pb2.CreateDiskRequest(
        metadata=metadata_pb2.ResourceMetadata(parent_id=project_id, name=resolved_name),
        spec=disk_spec,
    )
    return await disk_service.Create(request, metadata=metadata)


async def launch_instance(
    instance_service: instance_service_pb2_grpc.InstanceServiceStub,
    project_id: str,
    platform_id: str,
    preset_id: str,
    subnet_id: str,
    disk_id: str,
    public_key_content: str,
    *,
    vm_name: str = "omniference-nebius-vm",
    metadata: Optional[Sequence[Tuple[str, str]]] = None,
) -> operation_pb2.Operation:
    """
    Launch a Nebius VM by wiring the preset/platform, subnet, boot disk, and SSH user data.
    """
    cloud_init = f"""#cloud-config
users:
  - name: omniference
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - {public_key_content.strip()}
"""

    network_interface = network_interface_pb2.NetworkInterfaceSpec(
        name="eth0",
        subnet_id=subnet_id,
        ip_address=network_interface_pb2.IPAddress(),
        public_ip_address=network_interface_pb2.PublicIPAddress(),
    )

    boot_disk = instance_pb2.AttachedDiskSpec(
        attach_mode=instance_pb2.AttachedDiskSpec.AttachMode.READ_WRITE,
        existing_disk=instance_pb2.ExistingDisk(id=disk_id),
        device_id="boot-disk",
    )

    instance_spec = instance_pb2.InstanceSpec(
        resources=instance_pb2.ResourcesSpec(platform=platform_id, preset=preset_id),
        boot_disk=boot_disk,
        network_interfaces=[network_interface],
        cloud_init_user_data=cloud_init,
    )

    request = instance_service_pb2.CreateInstanceRequest(
        metadata=metadata_pb2.ResourceMetadata(parent_id=project_id, name=vm_name),
        spec=instance_spec,
    )

    return await instance_service.Create(request, metadata=metadata)

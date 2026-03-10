"""Nebius API helpers (token + compute platform listing)."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import grpc
import jwt
from grpc import aio

from nebius.compute.v1 import platform_service_pb2, platform_service_pb2_grpc
from nebius.iam.v1 import token_exchange_service_pb2_grpc, token_service_pb2

logger = logging.getLogger(__name__)

_TOKEN_ENDPOINT = "tokens.iam.api.nebius.cloud:443"
_COMPUTE_ENDPOINT = "compute.api.nebius.cloud:443"
_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:token-exchange"
_SUBJECT_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:jwt"
_REQUESTED_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"


@dataclass
class NebiusCredentialBundle:
    """Resolved credential trio required for JWT exchange."""

    service_account_id: str
    key_id: str
    private_key: str


class NebiusCredentialProvider:
    """Loads credentials from env or per-request overrides."""

    def __init__(self) -> None:
        self._cached_default_key: Optional[str] = None

    def resolve(
        self,
        override: Optional[dict] = None,
    ) -> NebiusCredentialBundle:
        override = override or {}
        service_account_id = (
            override.get("service_account_id")
            or os.getenv("NEBIUS_SERVICE_ACCOUNT_ID")
        )
        key_id = (
            override.get("key_id")
            or os.getenv("NEBIUS_AUTHORIZED_KEY_ID")
            or os.getenv("NEBIUS_KEY_ID")
        )
        private_key = override.get("private_key") or self._load_default_private_key()

        if not service_account_id:
            raise ValueError("Nebius service account id not configured")
        if not key_id:
            raise ValueError("Nebius authorized key id not configured")
        if not private_key:
            raise ValueError("Nebius private key is missing")

        return NebiusCredentialBundle(
            service_account_id=service_account_id.strip(),
            key_id=key_id.strip(),
            private_key=self._normalize_private_key(private_key),
        )

    def _load_default_private_key(self) -> str:
        if self._cached_default_key:
            return self._cached_default_key
        env_key = os.getenv("NEBIUS_PRIVATE_KEY")
        if env_key:
            self._cached_default_key = self._normalize_private_key(env_key)
            return self._cached_default_key
        path = os.getenv("NEBIUS_PRIVATE_KEY_PATH")
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                data = fh.read()
            self._cached_default_key = self._normalize_private_key(data)
            return self._cached_default_key
        secret = os.getenv("NEBIUS_SECRET_KEY")
        if secret:
            decoded = self._maybe_decode_secret(secret)
            if decoded:
                self._cached_default_key = decoded
                return decoded
        return ""

    @staticmethod
    def _normalize_private_key(raw: str) -> str:
        text = raw.replace("\\n", "\n").strip()
        if "BEGIN" not in text and len(text) > 0:
            # Accept base64 payloads without headers
            try:
                decoded = base64.b64decode(text).decode("utf-8")
                text = decoded
            except Exception:  # pragma: no cover - best effort
                pass
        return text

    @staticmethod
    def _maybe_decode_secret(secret: str) -> str:
        try:
            decoded = base64.b64decode(secret).decode("utf-8")
            if "BEGIN" in decoded:
                return decoded
        except Exception:
            return ""
        return ""


class NebiusTokenManager:
    """Caches bearer tokens issued via TokenExchangeService."""

    def __init__(self, credential_provider: NebiusCredentialProvider) -> None:
        self._credential_provider = credential_provider
        self._token: Optional[str] = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_token(self, cred_override: Optional[dict]) -> str:
        async with self._lock:
            now = time.time()
            if self._token and now < self._expires_at - 60:
                return self._token
            bundle = self._credential_provider.resolve(cred_override)
            jwt_token = self._build_jwt(bundle)
            request = token_service_pb2.ExchangeTokenRequest(
                grant_type=_GRANT_TYPE,
                requested_token_type=_REQUESTED_TOKEN_TYPE,
                subject_token=jwt_token,
                subject_token_type=_SUBJECT_TOKEN_TYPE,
            )
            ssl_credentials = grpc.ssl_channel_credentials()
            async with aio.secure_channel(_TOKEN_ENDPOINT, ssl_credentials) as channel:
                stub = token_exchange_service_pb2_grpc.TokenExchangeServiceStub(channel)
                response = await stub.Exchange(request)
            self._token = response.access_token
            ttl = response.expires_in or 3600
            self._expires_at = now + ttl
            return self._token

    @staticmethod
    def _build_jwt(bundle: NebiusCredentialBundle) -> str:
        payload = {
            "iss": bundle.service_account_id,
            "sub": bundle.service_account_id,
            "exp": int(time.time()) + 300,
        }
        token = jwt.encode(
            payload,
            bundle.private_key,
            algorithm="RS256",
            headers={"kid": bundle.key_id},
        )
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        return token


class NebiusComputeClient:
    """Thin wrapper over PlatformService.List."""

    def __init__(self) -> None:
        self._credential_provider = NebiusCredentialProvider()
        self._token_manager = NebiusTokenManager(self._credential_provider)
        self._region_project_map = self._load_region_project_map()
        self._ssl_credentials = grpc.ssl_channel_credentials()

    async def list_platform_presets(
        self,
        region: str,
        project_id: Optional[str] = None,
        include_non_gpu: bool = False,
        min_gpu_count: int = 1,
        credential_override: Optional[dict] = None,
    ) -> Dict[str, object]:
        parent = project_id or self._region_project_map.get(region)
        if not parent:
            raise ValueError(
                f"No Nebius project id configured for region '{region}'. "
                "Set NEBIUS_REGION_PROJECT_MAP or pass project_id explicitly."
            )
        token = await self._token_manager.get_token(credential_override)
        presets = await self._fetch_all_platforms(
            parent,
            token,
        )
        data = self._normalize_platforms(
            presets,
            region=region,
            include_non_gpu=include_non_gpu,
            min_gpu_count=min_gpu_count,
        )
        return {
            "region": region,
            "project_id": parent,
            "platforms": data,
        }

    async def _fetch_all_platforms(
        self, parent_id: str, token: str
    ) -> List[platform_service_pb2.Platform]:
        page_token = ""
        items: List[platform_service_pb2.Platform] = []
        metadata = (("authorization", f"Bearer {token}"),)
        async with aio.secure_channel(_COMPUTE_ENDPOINT, self._ssl_credentials) as channel:
            stub = platform_service_pb2_grpc.PlatformServiceStub(channel)
            while True:
                request = platform_service_pb2.ListPlatformsRequest(
                    parent_id=parent_id,
                    page_token=page_token,
                    page_size=100,
                )
                response = await stub.List(request, metadata=metadata)
                items.extend(response.items)
                if not response.next_page_token:
                    break
                page_token = response.next_page_token
        return items

    @staticmethod
    def _normalize_platforms(
        platforms: Iterable[platform_service_pb2.Platform],
        region: str,
        include_non_gpu: bool,
        min_gpu_count: int,
    ) -> List[Dict[str, object]]:
        normalized: List[Dict[str, object]] = []
        for platform in platforms:
            presets = []
            for preset in platform.spec.presets:
                gpu_count = preset.resources.gpu_count
                if not include_non_gpu and gpu_count <= 0:
                    continue
                if gpu_count < min_gpu_count:
                    continue
                presets.append(
                    {
                        "preset_name": preset.name,
                        "gpu_count": gpu_count,
                        "vcpu_count": preset.resources.vcpu_count,
                        "memory_gibibytes": preset.resources.memory_gibibytes,
                        "gpu_memory_gibibytes": platform.spec.gpu_memory_gibibytes,
                        "allow_gpu_clustering": preset.allow_gpu_clustering,
                    }
                )
            if not presets:
                continue
            normalized.append(
                {
                    "platform_id": platform.metadata.id,
                    "platform_name": platform.metadata.name,
                    "region": region,
                    "human_name": platform.spec.human_readable_name or platform.spec.short_human_readable_name,
                    "gpu_memory_gibibytes": platform.spec.gpu_memory_gibibytes,
                    "allow_preset_change": platform.spec.allow_preset_change,
                    "allowed_for_preemptibles": platform.status.allowed_for_preemptibles,
                    "presets": presets,
                }
            )
        return normalized

    @staticmethod
    def _load_region_project_map() -> Dict[str, str]:
        raw = os.getenv("NEBIUS_REGION_PROJECT_MAP", "")
        mapping: Dict[str, str] = {}
        for entry in raw.split(","):
            entry = entry.strip()
            if not entry or ":" not in entry:
                continue
            region, project = entry.split(":", 1)
            mapping[region.strip()] = project.strip()
        default_project = os.getenv("NEBIUS_DEFAULT_PROJECT_ID")
        default_region = os.getenv("NEBIUS_DEFAULT_REGION")
        if default_project and default_region and default_region not in mapping:
            mapping[default_region] = default_project
        return mapping

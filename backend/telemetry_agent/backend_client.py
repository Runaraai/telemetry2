"""Client helpers for communicating with the Omniference backend."""

from __future__ import annotations

import asyncio
import logging
from typing import Iterable
from uuid import UUID

import httpx

from .models import MetricSample

logger = logging.getLogger(__name__)


class BackendClient:
    """Pushes metric batches to the backend API."""

    def __init__(
        self,
        base_url: str,
        run_id: UUID,
        *,
        timeout: float,
    ) -> None:
        self._base_url = base_url
        self._run_id = run_id
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "BackendClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def send_metrics(self, samples: Iterable[MetricSample]) -> int:
        payload = {
            "run_id": str(self._run_id),
            "metrics": [sample.to_payload() for sample in samples],
        }

        async with self._lock:
            response = await self._client.post("/metrics/batch", json=payload)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - network error path
            logger.error(
                "Backend metrics ingestion failed (status=%s, body=%s)",
                exc.response.status_code,
                exc.response.text,
            )
            raise

        data = response.json()
        inserted = int(data.get("inserted", 0))
        logger.debug("Inserted %s metrics for run %s", inserted, self._run_id)
        return inserted



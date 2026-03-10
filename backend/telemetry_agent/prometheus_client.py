"""Utilities for fetching GPU metrics from Prometheus."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

import httpx

from .models import MetricSample, current_utc_timestamp

logger = logging.getLogger(__name__)

# Mapping of agent fields to Prometheus expressions.
METRIC_QUERIES: Dict[str, str] = {
    "gpu_utilization": "DCGM_FI_DEV_GPU_UTIL",
    "sm_utilization": "DCGM_FI_DEV_SM_ACTIVE",
    "memory_used_mb": "DCGM_FI_DEV_FB_USED",
    "memory_total_mb": "DCGM_FI_DEV_FB_TOTAL",
    "power_draw_watts": "DCGM_FI_DEV_POWER_USAGE",
    "temperature_celsius": "DCGM_FI_DEV_GPU_TEMP",
    "pcie_rx_mb_per_sec": "DCGM_FI_DEV_PCIE_RX_BYTES / 1048576",
    "pcie_tx_mb_per_sec": "DCGM_FI_DEV_PCIE_TX_BYTES / 1048576",
    "nvlink_rx_mb_per_sec": "DCGM_FI_DEV_NVLINK_RX_BYTES / 1048576",
    "nvlink_tx_mb_per_sec": "DCGM_FI_DEV_NVLINK_TX_BYTES / 1048576",
    "ecc_errors": "DCGM_FI_DEV_ECC_SBE_VOL_TOTAL",
}


class PrometheusClient:
    """Very small wrapper around the Prometheus HTTP API."""

    def __init__(self, base_url: str, *, timeout: float) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "PrometheusClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def fetch_samples(self) -> List[MetricSample]:
        """Fetch the latest GPU metrics and return merged samples."""

        metric_results: Dict[str, Dict[int, float]] = defaultdict(dict)
        timestamps: Dict[int, datetime] = {}

        for field, query in METRIC_QUERIES.items():
            response = await self._client.get("/api/v1/query", params={"query": query})
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:  # pragma: no cover - network error path
                logger.error(
                    "Prometheus query failed (status=%s, body=%s)",
                    exc.response.status_code,
                    exc.response.text,
                )
                raise

            payload = response.json()
            if payload.get("status") != "success":
                logger.warning("Prometheus query returned non-success status: %s", payload)
                continue

            for series in payload.get("data", {}).get("result", []):
                labels = series.get("metric", {})
                gpu_identifier = _parse_gpu_id(labels)
                if gpu_identifier is None:
                    continue

                value = _parse_sample_value(series.get("value"))
                if value is None:
                    continue

                metric_results[field][gpu_identifier] = value
                series_time = _parse_sample_time(series.get("value"))
                if series_time:
                    timestamps[gpu_identifier] = series_time

        samples: List[MetricSample] = []
        for gpu_id, metrics in metric_results.items():
            time = timestamps.get(gpu_id, current_utc_timestamp())
            sample = MetricSample(
                time=time,
                gpu_id=gpu_id,
                gpu_utilization=metrics.get("gpu_utilization"),
                memory_used_mb=metrics.get("memory_used_mb"),
                memory_total_mb=metrics.get("memory_total_mb"),
                sm_utilization=metrics.get("sm_utilization"),
                power_draw_watts=metrics.get("power_draw_watts"),
                temperature_celsius=metrics.get("temperature_celsius"),
                pcie_rx_mb_per_sec=metrics.get("pcie_rx_mb_per_sec"),
                pcie_tx_mb_per_sec=metrics.get("pcie_tx_mb_per_sec"),
                nvlink_rx_mb_per_sec=metrics.get("nvlink_rx_mb_per_sec"),
                nvlink_tx_mb_per_sec=metrics.get("nvlink_tx_mb_per_sec"),
                ecc_errors=metrics.get("ecc_errors"),
            )

            if (
                sample.memory_used_mb is not None
                and sample.memory_total_mb not in (None, 0)
            ):
                sample.memory_utilization = (
                    min(sample.memory_used_mb / sample.memory_total_mb * 100.0, 100.0)
                )

            samples.append(sample)

        return samples


def _parse_gpu_id(labels: Dict[str, str]) -> Optional[int]:
    """Extract the GPU identifier from Prometheus labels."""

    for key in ("gpu", "GPU", "gpu_id", "index"):
        if key in labels:
            try:
                return int(labels[key])
            except ValueError:
                continue
    return None


def _parse_sample_value(value: Optional[Iterable[str]]) -> Optional[float]:
    if not value:
        return None
    try:
        return float(value[1])
    except (ValueError, IndexError, TypeError):
        return None


def _parse_sample_time(value: Optional[Iterable[str]]) -> Optional[datetime]:
    if not value:
        return None
    try:
        timestamp = float(value[0])
    except (ValueError, IndexError, TypeError):
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)



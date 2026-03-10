"""Domain models used by the telemetry agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional


@dataclass(slots=True)
class MetricSample:
    """Single GPU metric sample prepared for backend ingestion."""

    time: datetime
    gpu_id: int
    gpu_utilization: Optional[float] = None
    memory_used_mb: Optional[float] = None
    memory_total_mb: Optional[float] = None
    memory_utilization: Optional[float] = None
    sm_utilization: Optional[float] = None
    power_draw_watts: Optional[float] = None
    temperature_celsius: Optional[float] = None
    pcie_rx_mb_per_sec: Optional[float] = None
    pcie_tx_mb_per_sec: Optional[float] = None
    nvlink_rx_mb_per_sec: Optional[float] = None
    nvlink_tx_mb_per_sec: Optional[float] = None
    ecc_errors: Optional[int] = None

    def to_payload(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "time": self.time.isoformat(),
            "gpu_id": self.gpu_id,
        }

        optional_fields = {
            "gpu_utilization": self.gpu_utilization,
            "memory_used_mb": self.memory_used_mb,
            "memory_total_mb": self.memory_total_mb,
            "memory_utilization": self.memory_utilization,
            "sm_utilization": self.sm_utilization,
            "power_draw_watts": self.power_draw_watts,
            "temperature_celsius": self.temperature_celsius,
            "pcie_rx_mb_per_sec": self.pcie_rx_mb_per_sec,
            "pcie_tx_mb_per_sec": self.pcie_tx_mb_per_sec,
            "nvlink_rx_mb_per_sec": self.nvlink_rx_mb_per_sec,
            "nvlink_tx_mb_per_sec": self.nvlink_tx_mb_per_sec,
            "ecc_errors": self.ecc_errors,
        }

        for key, value in optional_fields.items():
            if value is not None:
                payload[key] = value

        return payload


def current_utc_timestamp() -> datetime:
    """Return the current UTC timestamp as an aware datetime."""

    return datetime.now(timezone.utc)



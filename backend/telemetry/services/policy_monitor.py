"""Policy monitoring and alerting service for GPU telemetry."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import GpuMetric, GpuPolicyEvent
from ..schemas import MetricSample

logger = logging.getLogger(__name__)


class PolicyMonitor:
    """Monitor GPU metrics and generate policy violation events."""

    # Threshold configuration (can be made configurable per-run in the future)
    THERMAL_WARNING_THRESHOLD = 80.0  # Celsius
    THERMAL_CRITICAL_THRESHOLD = 85.0  # Celsius
    POWER_WARNING_THRESHOLD = 0.9  # 90% of power limit
    POWER_CRITICAL_THRESHOLD = 0.95  # 95% of power limit
    ECC_WARNING_THRESHOLD = 10  # Single-bit errors
    ECC_CRITICAL_THRESHOLD = 1  # Double-bit errors (any DBE is critical)
    THROTTLE_WARNING_BITMASK = 0x0000000000000008  # HW thermal slowdown
    THROTTLE_CRITICAL_BITMASK = 0x0000000000000010  # HW power brake

    async def evaluate_metrics(
        self,
        session: AsyncSession,
        run_id: UUID,
        samples: List[MetricSample],
    ) -> List[GpuPolicyEvent]:
        """Evaluate metric samples and generate policy events."""
        events: List[GpuPolicyEvent] = []

        for sample in samples:
            # Thermal policy
            if sample.temperature_celsius is not None:
                if sample.temperature_celsius >= self.THERMAL_CRITICAL_THRESHOLD:
                    events.append(
                        self._create_event(
                            run_id=run_id,
                            gpu_id=sample.gpu_id,
                            event_time=sample.time,
                            event_type="thermal",
                            severity="critical",
                            message=f"GPU temperature critical: {sample.temperature_celsius:.1f}°C",
                            metric_value=sample.temperature_celsius,
                            threshold_value=self.THERMAL_CRITICAL_THRESHOLD,
                        )
                    )
                elif sample.temperature_celsius >= self.THERMAL_WARNING_THRESHOLD:
                    events.append(
                        self._create_event(
                            run_id=run_id,
                            gpu_id=sample.gpu_id,
                            event_time=sample.time,
                            event_type="thermal",
                            severity="warning",
                            message=f"GPU temperature high: {sample.temperature_celsius:.1f}°C",
                            metric_value=sample.temperature_celsius,
                            threshold_value=self.THERMAL_WARNING_THRESHOLD,
                        )
                    )

            # Power policy
            if (
                sample.power_draw_watts is not None
                and sample.power_limit_watts is not None
                and sample.power_limit_watts > 0
            ):
                power_ratio = sample.power_draw_watts / sample.power_limit_watts
                if power_ratio >= self.POWER_CRITICAL_THRESHOLD:
                    events.append(
                        self._create_event(
                            run_id=run_id,
                            gpu_id=sample.gpu_id,
                            event_time=sample.time,
                            event_type="power",
                            severity="critical",
                            message=f"Power draw critical: {sample.power_draw_watts:.1f}W ({power_ratio*100:.1f}% of limit)",
                            metric_value=sample.power_draw_watts,
                            threshold_value=sample.power_limit_watts * self.POWER_CRITICAL_THRESHOLD,
                        )
                    )
                elif power_ratio >= self.POWER_WARNING_THRESHOLD:
                    events.append(
                        self._create_event(
                            run_id=run_id,
                            gpu_id=sample.gpu_id,
                            event_time=sample.time,
                            event_type="power",
                            severity="warning",
                            message=f"Power draw high: {sample.power_draw_watts:.1f}W ({power_ratio*100:.1f}% of limit)",
                            metric_value=sample.power_draw_watts,
                            threshold_value=sample.power_limit_watts * self.POWER_WARNING_THRESHOLD,
                        )
                    )

            # ECC policy
            if sample.ecc_dbe_errors and sample.ecc_dbe_errors >= self.ECC_CRITICAL_THRESHOLD:
                events.append(
                    self._create_event(
                        run_id=run_id,
                        gpu_id=sample.gpu_id,
                        event_time=sample.time,
                        event_type="ecc",
                        severity="critical",
                        message=f"Double-bit ECC errors detected: {sample.ecc_dbe_errors}",
                        metric_value=float(sample.ecc_dbe_errors),
                        threshold_value=float(self.ECC_CRITICAL_THRESHOLD),
                    )
                )

            if sample.ecc_sbe_errors and sample.ecc_sbe_errors >= self.ECC_WARNING_THRESHOLD:
                events.append(
                    self._create_event(
                        run_id=run_id,
                        gpu_id=sample.gpu_id,
                        event_time=sample.time,
                        event_type="ecc",
                        severity="warning",
                        message=f"Single-bit ECC errors accumulating: {sample.ecc_sbe_errors}",
                        metric_value=float(sample.ecc_sbe_errors),
                        threshold_value=float(self.ECC_WARNING_THRESHOLD),
                    )
                )

            # Throttle policy
            if sample.throttle_reasons:
                if sample.throttle_reasons & self.THROTTLE_CRITICAL_BITMASK:
                    events.append(
                        self._create_event(
                            run_id=run_id,
                            gpu_id=sample.gpu_id,
                            event_time=sample.time,
                            event_type="throttle",
                            severity="critical",
                            message=f"GPU throttled (critical): bitmask 0x{sample.throttle_reasons:016x}",
                            metric_value=float(sample.throttle_reasons),
                        )
                    )
                elif sample.throttle_reasons & self.THROTTLE_WARNING_BITMASK:
                    events.append(
                        self._create_event(
                            run_id=run_id,
                            gpu_id=sample.gpu_id,
                            event_time=sample.time,
                            event_type="throttle",
                            severity="warning",
                            message=f"GPU throttled (thermal): bitmask 0x{sample.throttle_reasons:016x}",
                            metric_value=float(sample.throttle_reasons),
                        )
                    )

            # XID errors (critical hardware errors)
            if sample.xid_errors and sample.xid_errors > 0:
                events.append(
                    self._create_event(
                        run_id=run_id,
                        gpu_id=sample.gpu_id,
                        event_time=sample.time,
                        event_type="xid",
                        severity="critical",
                        message=f"XID hardware error detected: {sample.xid_errors}",
                        metric_value=float(sample.xid_errors),
                    )
                )

        # Persist events to database
        if events:
            session.add_all(events)
            await session.flush()
            logger.info(f"Generated {len(events)} policy events for run {run_id}")

        return events

    def _create_event(
        self,
        run_id: UUID,
        gpu_id: int,
        event_time: datetime,
        event_type: str,
        severity: str,
        message: str,
        metric_value: Optional[float] = None,
        threshold_value: Optional[float] = None,
    ) -> GpuPolicyEvent:
        """Create a policy event instance."""
        return GpuPolicyEvent(
            run_id=run_id,
            gpu_id=gpu_id,
            event_time=event_time,
            event_type=event_type,
            severity=severity,
            message=message,
            metric_value=metric_value,
            threshold_value=threshold_value,
        )


# Singleton instance
policy_monitor = PolicyMonitor()


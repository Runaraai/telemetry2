from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Tuple

import snappy
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from .schemas import MetricSample

logger = logging.getLogger(__name__)

# Thread pool for CPU-bound protobuf parsing
# Using max_workers=4 to avoid overwhelming the system while still providing
# parallelism for concurrent remote_write requests
_parse_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="remote_write_parse")


class RemoteWriteDecodeError(Exception):
    """Raised when a remote write payload cannot be decoded."""


@dataclass(frozen=True)
class _FieldMapping:
    field: str
    transform: Callable[[float], float]


_FIELD_MAPPINGS: Mapping[str, _FieldMapping] = {
    "DCGM_FI_DEV_GPU_UTIL": _FieldMapping("gpu_utilization", lambda v: v),
    # SM utilization - prioritize device-level (works without profiler mode)
    # DCGM_FI_DEV_SM_ACTIVE typically returns percentage (0-100), but can vary by GPU
    "DCGM_FI_DEV_SM_ACTIVE": _FieldMapping("sm_utilization", lambda v: v if v <= 100.0 else v * 100.0),
    # Profiling SM utilization returns ratio (0-1), convert to percentage
    "DCGM_FI_PROF_SM_ACTIVE": _FieldMapping("sm_utilization", lambda v: v * 100.0),
    "DCGM_FI_PROF_SM_ACTIVE_gauge": _FieldMapping("sm_utilization", lambda v: v * 100.0),
    # HBM/Memory utilization - prioritize device-level memory copy utilization
    # DCGM_FI_DEV_MEM_COPY_UTIL returns percentage (0-100) of memory bandwidth used
    "DCGM_FI_DEV_MEM_COPY_UTIL": _FieldMapping("hbm_utilization", lambda v: v),
    "DCGM_FI_DEV_MEM_COPY_UTIL_gauge": _FieldMapping("hbm_utilization", lambda v: v),
    # Encoder/Decoder utilization
    "DCGM_FI_DEV_ENC_UTIL": _FieldMapping("encoder_utilization", lambda v: v),
    "DCGM_FI_DEV_ENC_UTIL_gauge": _FieldMapping("encoder_utilization", lambda v: v),
    "DCGM_FI_DEV_DEC_UTIL": _FieldMapping("decoder_utilization", lambda v: v),
    "DCGM_FI_DEV_DEC_UTIL_gauge": _FieldMapping("decoder_utilization", lambda v: v),
    # Profiling DRAM utilization returns ratio (0-1), convert to percentage
    "DCGM_FI_PROF_DRAM_ACTIVE": _FieldMapping("hbm_utilization", lambda v: v * 100.0),
    "DCGM_FI_PROF_DRAM_ACTIVE_gauge": _FieldMapping("hbm_utilization", lambda v: v * 100.0),
    "DCGM_FI_PROF_SM_OCCUPANCY": _FieldMapping("sm_occupancy", lambda v: v * 100.0),
    "DCGM_FI_PROF_PIPE_TENSOR_ACTIVE": _FieldMapping("tensor_active", lambda v: v * 100.0),
    "DCGM_FI_PROF_PIPE_FP64_ACTIVE": _FieldMapping("fp64_active", lambda v: v * 100.0),
    "DCGM_FI_PROF_PIPE_FP32_ACTIVE": _FieldMapping("fp32_active", lambda v: v * 100.0),
    "DCGM_FI_PROF_PIPE_FP16_ACTIVE": _FieldMapping("fp16_active", lambda v: v * 100.0),
    "DCGM_FI_PROF_GR_ENGINE_ACTIVE": _FieldMapping("gr_engine_active", lambda v: v * 100.0),
    # Also handle DCGM exporter metric name suffixes (gauge, counter, etc.)
    "DCGM_FI_DEV_SM_ACTIVE_gauge": _FieldMapping("sm_utilization", lambda v: v if v <= 100.0 else v * 100.0),
    "DCGM_FI_PROF_SM_ACTIVE_gauge": _FieldMapping("sm_utilization", lambda v: v * 100.0),
    "DCGM_FI_DEV_MEM_COPY_UTIL_gauge": _FieldMapping("hbm_utilization", lambda v: v),
    "DCGM_FI_PROF_DRAM_ACTIVE_gauge": _FieldMapping("hbm_utilization", lambda v: v * 100.0),
    "DCGM_FI_PROF_SM_OCCUPANCY_gauge": _FieldMapping("sm_occupancy", lambda v: v * 100.0),
    "DCGM_FI_PROF_PIPE_TENSOR_ACTIVE_gauge": _FieldMapping("tensor_active", lambda v: v * 100.0),
    "DCGM_FI_PROF_PIPE_FP64_ACTIVE_gauge": _FieldMapping("fp64_active", lambda v: v * 100.0),
    "DCGM_FI_PROF_PIPE_FP32_ACTIVE_gauge": _FieldMapping("fp32_active", lambda v: v * 100.0),
    "DCGM_FI_PROF_PIPE_FP16_ACTIVE_gauge": _FieldMapping("fp16_active", lambda v: v * 100.0),
    "DCGM_FI_PROF_GR_ENGINE_ACTIVE_gauge": _FieldMapping("gr_engine_active", lambda v: v * 100.0),
    # Memory metrics
    "DCGM_FI_DEV_FB_USED": _FieldMapping("memory_used_mb", lambda v: v / 1048576.0),
    "DCGM_FI_DEV_FB_TOTAL": _FieldMapping("memory_total_mb", lambda v: v / 1048576.0),
    "DCGM_FI_DEV_FB_FREE": _FieldMapping("memory_free_mb", lambda v: v / 1048576.0),
    "DCGM_FI_DEV_FB_RESERVED": _FieldMapping("memory_reserved_mb", lambda v: v / 1048576.0),
    "DCGM_FI_DEV_FB_RESERVED_gauge": _FieldMapping("memory_reserved_mb", lambda v: v / 1048576.0),
    "DCGM_FI_DEV_FB_USED_PERCENT": _FieldMapping("memory_used_percent", lambda v: v),
    "DCGM_FI_DEV_FB_USED_PERCENT_gauge": _FieldMapping("memory_used_percent", lambda v: v),
    # Power and temperature
    "DCGM_FI_DEV_POWER_USAGE": _FieldMapping("power_draw_watts", lambda v: v),
    "DCGM_FI_DEV_POWER_LIMIT": _FieldMapping("power_limit_watts", lambda v: v),
    "DCGM_FI_DEV_POWER_MGMT_LIMIT": _FieldMapping("power_limit_watts", lambda v: v),
    "DCGM_FI_DEV_GPU_TEMP": _FieldMapping("temperature_celsius", lambda v: v),
    "DCGM_FI_DEV_MEMORY_TEMP": _FieldMapping("memory_temperature_celsius", lambda v: v),
    "DCGM_FI_DEV_SLOWDOWN_TEMP": _FieldMapping("slowdown_temperature_celsius", lambda v: v),
    "DCGM_FI_DEV_SLOWDOWN_TEMP_gauge": _FieldMapping("slowdown_temperature_celsius", lambda v: v),
    # PCIe metrics
    # Note: THROUGHPUT and BYTES fields are not available in DCGM 3.x
    # Only REPLAY_COUNTER is available in DCGM 3.x
    "DCGM_FI_DEV_PCIE_RX_THROUGHPUT": _FieldMapping("pcie_rx_mb_per_sec", lambda v: v / 1048576.0),
    "DCGM_FI_DEV_PCIE_TX_THROUGHPUT": _FieldMapping("pcie_tx_mb_per_sec", lambda v: v / 1048576.0),
    "DCGM_FI_DEV_PCIE_RX_THROUGHPUT_gauge": _FieldMapping("pcie_rx_mb_per_sec", lambda v: v / 1048576.0),
    "DCGM_FI_DEV_PCIE_TX_THROUGHPUT_gauge": _FieldMapping("pcie_tx_mb_per_sec", lambda v: v / 1048576.0),
    "DCGM_FI_DEV_PCIE_RX_BYTES": _FieldMapping("pcie_rx_mb_per_sec", lambda v: v / 1048576.0),
    "DCGM_FI_DEV_PCIE_TX_BYTES": _FieldMapping("pcie_tx_mb_per_sec", lambda v: v / 1048576.0),
    "DCGM_FI_DEV_PCIE_REPLAY_COUNTER": _FieldMapping("pcie_replay_errors", lambda v: v),
    "DCGM_FI_DEV_PCIE_REPLAY_COUNTER_counter": _FieldMapping("pcie_replay_errors", lambda v: v),
    # Profiling PCIe metrics (DCP metrics - prefer these when available)
    "DCGM_FI_PROF_PCIE_RX_BYTES": _FieldMapping("pcie_rx_mb_per_sec", lambda v: v / 1048576.0),
    "DCGM_FI_PROF_PCIE_TX_BYTES": _FieldMapping("pcie_tx_mb_per_sec", lambda v: v / 1048576.0),
    "DCGM_FI_PROF_PCIE_RX_BYTES_counter": _FieldMapping("pcie_rx_mb_per_sec", lambda v: v / 1048576.0),
    "DCGM_FI_PROF_PCIE_TX_BYTES_counter": _FieldMapping("pcie_tx_mb_per_sec", lambda v: v / 1048576.0),
    # NVLink metrics
    # Note: DEV_NVLINK_TX_BYTES/RX_BYTES are not available in DCGM 3.x
    # Use PROF_NVLINK_TX_BYTES/RX_BYTES when profiling is enabled (these are counters, Prometheus will calculate rate)
    "DCGM_FI_DEV_NVLINK_RX_BYTES": _FieldMapping("nvlink_rx_mb_per_sec", lambda v: v / 1048576.0),
    "DCGM_FI_DEV_NVLINK_TX_BYTES": _FieldMapping("nvlink_tx_mb_per_sec", lambda v: v / 1048576.0),
    "DCGM_FI_PROF_NVLINK_RX_BYTES": _FieldMapping("nvlink_rx_mb_per_sec", lambda v: v / 1048576.0),
    "DCGM_FI_PROF_NVLINK_TX_BYTES": _FieldMapping("nvlink_tx_mb_per_sec", lambda v: v / 1048576.0),
    "DCGM_FI_PROF_NVLINK_RX_BYTES_counter": _FieldMapping("nvlink_rx_mb_per_sec", lambda v: v / 1048576.0),
    "DCGM_FI_PROF_NVLINK_TX_BYTES_counter": _FieldMapping("nvlink_tx_mb_per_sec", lambda v: v / 1048576.0),
    "DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL": _FieldMapping("nvlink_bandwidth_total", lambda v: v / 1048576.0),
    "DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL_gauge": _FieldMapping("nvlink_bandwidth_total", lambda v: v / 1048576.0),
    "DCGM_FI_DEV_NVLINK_REPLAY_ERROR_COUNT_TOTAL": _FieldMapping("nvlink_replay_errors", lambda v: v),
    "DCGM_FI_DEV_NVLINK_REPLAY_ERROR_COUNT_TOTAL_gauge": _FieldMapping("nvlink_replay_errors", lambda v: v),
    "DCGM_FI_DEV_NVLINK_RECOVERY_ERROR_COUNT_TOTAL": _FieldMapping("nvlink_recovery_errors", lambda v: v),
    "DCGM_FI_DEV_NVLINK_RECOVERY_ERROR_COUNT_TOTAL_gauge": _FieldMapping("nvlink_recovery_errors", lambda v: v),
    "DCGM_FI_DEV_NVLINK_CRC_FLIT_ERROR_COUNT_TOTAL": _FieldMapping("nvlink_crc_errors", lambda v: v),
    "DCGM_FI_DEV_NVLINK_CRC_FLIT_ERROR_COUNT_TOTAL_gauge": _FieldMapping("nvlink_crc_errors", lambda v: v),
    # Clock frequencies (DCGM returns MHz already, no conversion needed)
    "DCGM_FI_DEV_SM_CLOCK": _FieldMapping("sm_clock_mhz", lambda v: v),
    "DCGM_FI_DEV_MEM_CLOCK": _FieldMapping("memory_clock_mhz", lambda v: v),
    # ECC errors
    "DCGM_FI_DEV_ECC_SBE_VOL_TOTAL": _FieldMapping("ecc_sbe_errors", lambda v: v),
    "DCGM_FI_DEV_ECC_DBE_VOL_TOTAL": _FieldMapping("ecc_dbe_errors", lambda v: v),
    "DCGM_FI_DEV_ECC_SBE_AGG_TOTAL": _FieldMapping("ecc_sbe_aggregate", lambda v: v),
    "DCGM_FI_DEV_ECC_DBE_AGG_TOTAL": _FieldMapping("ecc_dbe_aggregate", lambda v: v),
    # Throttle reasons
    "DCGM_FI_DEV_CLOCK_THROTTLE_REASONS": _FieldMapping("throttle_reasons", lambda v: v),
    # XID errors
    "DCGM_FI_DEV_XID_ERRORS": _FieldMapping("xid_errors", lambda v: v),
    # Remapped rows (memory error correction)
    "DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS": _FieldMapping("uncorrectable_remapped_rows", lambda v: v),
    "DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS_counter": _FieldMapping("uncorrectable_remapped_rows", lambda v: v),
    "DCGM_FI_DEV_CORRECTABLE_REMAPPED_ROWS": _FieldMapping("correctable_remapped_rows", lambda v: v),
    "DCGM_FI_DEV_CORRECTABLE_REMAPPED_ROWS_counter": _FieldMapping("correctable_remapped_rows", lambda v: v),
    "DCGM_FI_DEV_ROW_REMAP_FAILURE": _FieldMapping("row_remap_failure", lambda v: v),
    "DCGM_FI_DEV_ROW_REMAP_FAILURE_gauge": _FieldMapping("row_remap_failure", lambda v: v),
    # Datadog recommended fields
    "DCGM_FI_DEV_FAN_SPEED": _FieldMapping("fan_speed_percent", lambda v: v),
    "DCGM_FI_DEV_FAN_SPEED_gauge": _FieldMapping("fan_speed_percent", lambda v: v),
    "DCGM_FI_DEV_PSTATE": _FieldMapping("pstate", lambda v: v),
    "DCGM_FI_DEV_PSTATE_gauge": _FieldMapping("pstate", lambda v: v),
    # VGPU License status
    "DCGM_FI_DEV_VGPU_LICENSE_STATUS": _FieldMapping("vgpu_license_status", lambda v: v),
    "DCGM_FI_DEV_VGPU_LICENSE_STATUS_gauge": _FieldMapping("vgpu_license_status", lambda v: v),
    # Configuration from health exporter
    "gpu_compute_mode": _FieldMapping("compute_mode", lambda v: v),
    "gpu_persistence_mode": _FieldMapping("persistence_mode", lambda v: v),
    "gpu_power_limit_watts": _FieldMapping("power_limit_watts", lambda v: v),
    "gpu_power_min_limit_watts": _FieldMapping("power_min_limit", lambda v: v),
    "gpu_power_max_limit_watts": _FieldMapping("power_max_limit", lambda v: v),
    "gpu_slowdown_temp_celsius": _FieldMapping("slowdown_temp", lambda v: v),
    "gpu_shutdown_temp_celsius": _FieldMapping("shutdown_temp", lambda v: v),
    "gpu_throttle_reasons": _FieldMapping("throttle_reasons", lambda v: v),
    "gpu_throttle_hw_thermal": _FieldMapping("throttle_thermal", lambda v: v),
    "gpu_throttle_hw_power_brake": _FieldMapping("throttle_power", lambda v: v),
    "gpu_throttle_sw_power": _FieldMapping("throttle_sw_power", lambda v: v),
    "gpu_ecc_mode": _FieldMapping("ecc_mode", lambda v: v),
    "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION": _FieldMapping("total_energy_joules", lambda v: v),
    "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION_gauge": _FieldMapping("total_energy_joules", lambda v: v),
    # Retired pages
    "DCGM_FI_DEV_RETIRED_SBE": _FieldMapping("retired_pages_sbe", lambda v: v),
    "DCGM_FI_DEV_RETIRED_DBE": _FieldMapping("retired_pages_dbe", lambda v: v),
    "DCGM_FI_DEV_RETIRED_PENDING": _FieldMapping("retired_pages_pending", lambda v: v),
    # NVIDIA-SMI exporter metrics (fallback when DCGM is not available)
    "nvidia_smi_utilization_gpu_percent": _FieldMapping("gpu_utilization", lambda v: v),
    "nvidia_smi_utilization_memory_percent": _FieldMapping("memory_utilization", lambda v: v),
    "nvidia_smi_memory_used_mib": _FieldMapping("memory_used_mb", lambda v: v),
    "nvidia_smi_memory_total_mib": _FieldMapping("memory_total_mb", lambda v: v),
    "nvidia_smi_memory_free_mib": _FieldMapping("memory_free_mb", lambda v: v),
    "nvidia_smi_power_draw_watts": _FieldMapping("power_draw_watts", lambda v: v),
    "nvidia_smi_power_limit_watts": _FieldMapping("power_limit_watts", lambda v: v),
    "nvidia_smi_temperature_celsius": _FieldMapping("temperature_celsius", lambda v: v),
    "nvidia_smi_clock_sm_mhz": _FieldMapping("sm_clock_mhz", lambda v: v),
    "nvidia_smi_clock_memory_mhz": _FieldMapping("memory_clock_mhz", lambda v: v),
    # Token exporter metrics (application-level, not GPU-specific)
    "tokens_per_second": _FieldMapping("tokens_per_second", lambda v: v),
    "token_throughput_per_second": _FieldMapping("tokens_per_second", lambda v: v),
    "inference_requests_per_second": _FieldMapping("requests_per_second", lambda v: v),
    "ttft_p50_ms": _FieldMapping("ttft_p50_ms", lambda v: v),
    "ttft_p95_ms": _FieldMapping("ttft_p95_ms", lambda v: v),
    "cost_per_watt": _FieldMapping("cost_per_watt", lambda v: v),
    "performance_per_watt": _FieldMapping("cost_per_watt", lambda v: v),
}

_GPU_LABEL_CANDIDATES: Tuple[str, ...] = ("gpu", "GPU", "gpu_id", "index")


def parse_remote_write(body: bytes, *, content_encoding: Optional[str] = None) -> List[MetricSample]:
    """Parse a Prometheus remote write request into metric samples."""

    if not body:
        return []

    try:
        payload = _decompress_body(body, content_encoding)
    except Exception as exc:  # pragma: no cover - defensive
        raise RemoteWriteDecodeError("Failed to decompress remote write payload") from exc

    write_request = _new_write_request_message()
    try:
        write_request.ParseFromString(payload)
    except Exception as exc:  # pragma: no cover - defensive
        raise RemoteWriteDecodeError("Failed to parse remote write protobuf") from exc

    buckets: MutableMapping[Tuple[int, int], Dict[str, float]] = defaultdict(dict)
    timestamps: MutableMapping[Tuple[int, int], datetime] = {}

    logger.info(f"Parsing remote write with {len(getattr(write_request, 'timeseries', []))} timeseries")

    metric_names_seen = set()
    for series in getattr(write_request, "timeseries", []):
        labels = {label.name: label.value for label in series.labels}
        metric_name = labels.get("__name__")
        if not metric_name:
            continue
        metric_names_seen.add(metric_name)

        # Debug: log SM and HBM related metrics to see what's being sent
        if "SM" in metric_name or "DRAM" in metric_name or "sm_utilization" in metric_name.lower() or "hbm" in metric_name.lower() or "MEM_COPY" in metric_name:
            logger.info(f"Received SM/HBM metric: {metric_name} with labels: {labels}")
        
        # Debug: log token metrics to see if they're being received
        token_metric_names = ("tokens_per_second", "token_throughput_per_second", "inference_requests_per_second", 
                             "ttft_p50_ms", "ttft_p95_ms", "cost_per_watt", "performance_per_watt")
        if metric_name in token_metric_names:
            logger.info(f"Received token metric: {metric_name} with labels: {labels}, value: {series.samples[0].value if series.samples else 'N/A'}")

        mapping = _FIELD_MAPPINGS.get(metric_name)
        if not mapping:
            # Try to find partial matches for DCGM metrics
            if "DCGM" in metric_name:
                # DCGM exporter might use different naming - try to match
                # Prioritize device-level metrics over profiling metrics
                device_matches = []
                prof_matches = []
                for dcgm_name, field_mapping in _FIELD_MAPPINGS.items():
                    # Check for exact field ID match (e.g., "DCGM_FI_DEV_SM_ACTIVE" in "DCGM_FI_DEV_SM_ACTIVE_gauge")
                    if dcgm_name in metric_name:
                        if "DCGM_FI_DEV" in dcgm_name:
                            device_matches.append((dcgm_name, field_mapping))
                        elif "DCGM_FI_PROF" in dcgm_name:
                            prof_matches.append((dcgm_name, field_mapping))
                    # Also try matching by field suffix (last part after underscore)
                    elif metric_name.endswith("_" + dcgm_name.split("_")[-1]):
                        if "DCGM_FI_DEV" in dcgm_name:
                            device_matches.append((dcgm_name, field_mapping))
                        elif "DCGM_FI_PROF" in dcgm_name:
                            prof_matches.append((dcgm_name, field_mapping))
                
                # Prefer device-level metrics (work without profiler mode)
                if device_matches:
                    mapping = device_matches[0][1]
                    logger.debug(f"Matched {metric_name} to device-level {device_matches[0][0]} -> {mapping.field}")
                elif prof_matches:
                    mapping = prof_matches[0][1]
                    logger.debug(f"Matched {metric_name} to profiling {prof_matches[0][0]} -> {mapping.field}")
            
            if not mapping:
                if "SM" in metric_name or "DRAM" in metric_name or "MEM_COPY" in metric_name:
                    logger.warning(f"No mapping found for SM/HBM metric: {metric_name}")
                continue

        gpu_id = _extract_gpu_id(labels)
        # Token metrics don't have GPU labels - assign to GPU 0 for consistency
        # This allows application-level metrics to be stored alongside GPU metrics
        if gpu_id is None:
            # Check if this is a token metric (application-level, not GPU-specific)
            token_metrics = (
                "tokens_per_second", "token_throughput_per_second", 
                "token_total_generated", "inference_requests_per_second", 
                "inference_total_requests", "ttft_p50_ms", "ttft_p95_ms", 
                "cost_per_watt", "performance_per_watt"
            )
            if metric_name in token_metrics:
                gpu_id = 0  # Assign to GPU 0 for application-level metrics
            else:
                continue  # Skip metrics without GPU ID that aren't token metrics

        for sample in series.samples:
            timestamp_ms = int(getattr(sample, "timestamp", 0))
            key = (gpu_id, timestamp_ms)
            buckets[key][mapping.field] = mapping.transform(sample.value)
            if key not in timestamps:
                timestamps[key] = _timestamp_from_milliseconds(timestamp_ms)

    samples: List[MetricSample] = []
    for key, metrics in buckets.items():
        gpu_id, _ = key
        time = timestamps.get(key, _timestamp_from_milliseconds(key[1]))
        sample = _build_sample(gpu_id, time, metrics)
        samples.append(sample)

    logger.info(f"Parsed {len(samples)} metric samples from {len(buckets)} unique (timestamp, gpu_id) combinations")
    if len(samples) == 0 and len(metric_names_seen) > 0:
        logger.warning(f"No GPU metrics parsed! Only Prometheus internal metrics received: {sorted(list(metric_names_seen))[:20]}")
    else:
        logger.debug(f"Unique metric names seen: {sorted(list(metric_names_seen))[:20]}")  # First 20
    return samples


async def parse_remote_write_async(
    body: bytes,
    *,
    content_encoding: Optional[str] = None,
) -> List[MetricSample]:
    """Async wrapper that offloads CPU-bound protobuf parsing to a thread pool.
    
    This prevents the GIL from blocking the event loop during parsing,
    which is critical for maintaining low latency at 200+ req/s.
    
    Args:
        body: Raw request body (compressed protobuf)
        content_encoding: Content encoding header (e.g., 'snappy')
    
    Returns:
        List of parsed MetricSample objects
    
    Raises:
        RemoteWriteDecodeError: If parsing fails
    """
    loop = asyncio.get_running_loop()
    
    # Run CPU-bound parsing in thread pool to avoid blocking event loop
    return await loop.run_in_executor(
        _parse_executor,
        partial(parse_remote_write, body, content_encoding=content_encoding),
    )


def _decompress_body(body: bytes, content_encoding: Optional[str]) -> bytes:
    encoding = (content_encoding or "").strip().lower()
    if encoding in {"snappy", "x-snappy-framed", "snappy-framed"}:
        return _snappy_decompress(body)
    if encoding == "":
        try:
            return _snappy_decompress(body)
        except Exception:
            return body
    if encoding and encoding != "identity":  # pragma: no cover - defensive
        raise RemoteWriteDecodeError(f"Unsupported Content-Encoding: {encoding}")
    return body


def _extract_gpu_id(labels: Mapping[str, str]) -> Optional[int]:
    for candidate in _GPU_LABEL_CANDIDATES:
        value = labels.get(candidate)
        if value is None:
            continue
        try:
            return int(value)
        except ValueError:  # pragma: no cover - defensive
            continue
    return None


def _timestamp_from_milliseconds(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)


def _build_sample(gpu_id: int, time: datetime, metrics: Mapping[str, float]) -> MetricSample:
    sample_kwargs: Dict[str, Any] = {
        "gpu_id": gpu_id,
        "time": time,
        # Core utilization
        "gpu_utilization": metrics.get("gpu_utilization"),
        "sm_utilization": metrics.get("sm_utilization"),
        "hbm_utilization": metrics.get("hbm_utilization"),
        "sm_occupancy": metrics.get("sm_occupancy"),
        "tensor_active": metrics.get("tensor_active"),
        "fp64_active": metrics.get("fp64_active"),
        "fp32_active": metrics.get("fp32_active"),
        "fp16_active": metrics.get("fp16_active"),
        "gr_engine_active": metrics.get("gr_engine_active"),
        "encoder_utilization": metrics.get("encoder_utilization"),
        "decoder_utilization": metrics.get("decoder_utilization"),
        # Memory
        "memory_used_mb": metrics.get("memory_used_mb"),
        "memory_total_mb": metrics.get("memory_total_mb"),
        # Clocks
        "sm_clock_mhz": metrics.get("sm_clock_mhz"),
        "memory_clock_mhz": metrics.get("memory_clock_mhz"),
        # Power
        "power_draw_watts": metrics.get("power_draw_watts"),
        "power_limit_watts": metrics.get("power_limit_watts"),
        # Temperature
        "temperature_celsius": metrics.get("temperature_celsius"),
        "memory_temperature_celsius": metrics.get("memory_temperature_celsius"),
        "slowdown_temperature_celsius": metrics.get("slowdown_temperature_celsius"),
        # PCIe
        "pcie_rx_mb_per_sec": metrics.get("pcie_rx_mb_per_sec"),
        "pcie_tx_mb_per_sec": metrics.get("pcie_tx_mb_per_sec"),
        # NVLink
        "nvlink_rx_mb_per_sec": metrics.get("nvlink_rx_mb_per_sec"),
        "nvlink_tx_mb_per_sec": metrics.get("nvlink_tx_mb_per_sec"),
        "nvlink_bandwidth_total": metrics.get("nvlink_bandwidth_total"),
        # Configuration
        "compute_mode": metrics.get("compute_mode"),
        "persistence_mode": metrics.get("persistence_mode"),
        "ecc_mode": metrics.get("ecc_mode"),
        "power_min_limit": metrics.get("power_min_limit"),
        "power_max_limit": metrics.get("power_max_limit"),
        "slowdown_temp": metrics.get("slowdown_temp"),
        "shutdown_temp": metrics.get("shutdown_temp"),
        "total_energy_joules": metrics.get("total_energy_joules"),
        # Additional metrics
        "fan_speed_percent": metrics.get("fan_speed_percent"),
        "pstate": metrics.get("pstate"),
        # Application-level token metrics
        "tokens_per_second": metrics.get("tokens_per_second"),
        "requests_per_second": metrics.get("requests_per_second"),
        "ttft_p50_ms": metrics.get("ttft_p50_ms"),
        "ttft_p95_ms": metrics.get("ttft_p95_ms"),
        "cost_per_watt": metrics.get("cost_per_watt"),
    }

    memory_used = sample_kwargs["memory_used_mb"]
    memory_total = sample_kwargs["memory_total_mb"]
    if memory_used is not None and memory_total not in (None, 0):
        sample_kwargs["memory_utilization"] = min(memory_used / memory_total * 100.0, 100.0)

    # Convert integer metrics
    for field in [
        "pcie_replay_errors", "nvlink_replay_errors", "nvlink_recovery_errors", "nvlink_crc_errors",
        "ecc_sbe_errors", "ecc_dbe_errors", "ecc_sbe_aggregate", "ecc_dbe_aggregate",
        "throttle_reasons", "throttle_thermal", "throttle_power", "throttle_sw_power", "xid_errors",
        "retired_pages_sbe", "retired_pages_dbe", "retired_pages_pending", "pstate"
    ]:
        value = metrics.get(field)
        if value is not None:
            sample_kwargs[field] = int(value)

    return MetricSample(**sample_kwargs)


def _snappy_decompress(body: bytes) -> bytes:
    if not body:
        return b""
    try:
        return snappy.uncompress(body)
    except Exception:
        decompressor = snappy.StreamDecompressor()
        data = decompressor.decompress(body)
        tail = decompressor.flush()
        return data + tail


_WRITE_REQUEST_DESCRIPTOR_NAME = "telemetry.prometheus.WriteRequest"
_WRITE_REQUEST_CLS = None


def _new_write_request_message():
    global _WRITE_REQUEST_CLS
    if _WRITE_REQUEST_CLS is None:
        _WRITE_REQUEST_CLS = _build_write_request_class()
    return _WRITE_REQUEST_CLS()


def _build_write_request_class():
    file_proto = descriptor_pb2.FileDescriptorProto()
    file_proto.name = "telemetry/prometheus_remote.proto"
    file_proto.package = "telemetry.prometheus"
    file_proto.syntax = "proto3"

    label_msg = file_proto.message_type.add()
    label_msg.name = "Label"
    field = label_msg.field.add()
    field.name = "name"
    field.number = 1
    field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    field.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
    field = label_msg.field.add()
    field.name = "value"
    field.number = 2
    field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    field.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING

    sample_msg = file_proto.message_type.add()
    sample_msg.name = "Sample"
    field = sample_msg.field.add()
    field.name = "value"
    field.number = 1
    field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    field.type = descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE
    field = sample_msg.field.add()
    field.name = "timestamp"
    field.number = 2
    field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    field.type = descriptor_pb2.FieldDescriptorProto.TYPE_INT64

    timeseries_msg = file_proto.message_type.add()
    timeseries_msg.name = "TimeSeries"
    field = timeseries_msg.field.add()
    field.name = "labels"
    field.number = 1
    field.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
    field.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    field.type_name = ".telemetry.prometheus.Label"
    field = timeseries_msg.field.add()
    field.name = "samples"
    field.number = 2
    field.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
    field.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    field.type_name = ".telemetry.prometheus.Sample"

    write_request_msg = file_proto.message_type.add()
    write_request_msg.name = "WriteRequest"
    field = write_request_msg.field.add()
    field.name = "timeseries"
    field.number = 1
    field.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
    field.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    field.type_name = ".telemetry.prometheus.TimeSeries"

    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    write_desc = pool.FindMessageTypeByName(_WRITE_REQUEST_DESCRIPTOR_NAME)
    factory = message_factory.MessageFactory(pool)
    get_prototype = getattr(factory, "GetPrototype", None)
    if callable(get_prototype):
        return get_prototype(write_desc)
    # Protobuf >= 6 removed MessageFactory.GetPrototype; use module-level helper instead.
    return message_factory.GetMessageClass(write_desc)

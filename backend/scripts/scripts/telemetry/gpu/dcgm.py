"""
telemetry.gpu.dcgm — DCGM HTTP exporter backend.

Works with:
  - Docker DCGM exporter:  nvcr.io/nvidia/k8s/dcgm-exporter  (data centre GPUs)
  - Native dcgm-exporter binary

Provides full profiling counters (SM Active, Tensor, DRAM BW, NVLink) on supported GPUs:
  NVIDIA A100, H100, L40, L40S, A40, A30, V100, B200, ...

Consumer GeForce GPUs will connect but profiling counters return 0 — in that
case AutoGpuBackend will prefer NVMLBackend instead.

Adding support for a new GPU generation: no code changes needed as long as DCGM
supports it and the exporter is configured to export the relevant metric IDs.
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from typing import Optional

import requests

from .base import (
    GpuBackend, GpuSample,
    CAP_UTIL, CAP_POWER, CAP_VRAM, CAP_TEMP, CAP_CLOCKS, CAP_PCIE,
    CAP_SM_ACTIVE, CAP_SM_OCC, CAP_TENSOR, CAP_DRAM,
    CAP_NVLINK, CAP_FP32, CAP_FP64, CAP_L2_CACHE,
)

# ── DCGM metric name → GpuSample field mapping ───────────────────────────────
_METRIC_MAP = {
    "gpu_util_pct":     "DCGM_FI_DEV_GPU_UTIL",
    "hbm_used_mib":     "DCGM_FI_DEV_FB_USED",
    "hbm_free_mib":     "DCGM_FI_DEV_FB_FREE",
    "power_w":          "DCGM_FI_DEV_POWER_USAGE",
    "temp_c":           "DCGM_FI_DEV_GPU_TEMP",
    "sm_clock_mhz":     "DCGM_FI_DEV_SM_CLOCK",
    "mem_clock_mhz":    "DCGM_FI_DEV_MEM_CLOCK",
    "pcie_tx_kbps":     "DCGM_FI_DEV_PCIE_TX_THROUGHPUT",
    "pcie_rx_kbps":     "DCGM_FI_DEV_PCIE_RX_THROUGHPUT",
    # Profiling counters (DCGM returns ratios 0–1; multiplied ×100 in collect())
    "sm_active":        "DCGM_FI_PROF_SM_ACTIVE",
    "sm_occupancy":     "DCGM_FI_PROF_SM_OCCUPANCY",
    "tensor_active":    "DCGM_FI_PROF_PIPE_TENSOR_ACTIVE",
    "dram_active":      "DCGM_FI_PROF_DRAM_ACTIVE",
    "fp32_active":      "DCGM_FI_PROF_PIPE_FP32_ACTIVE",
    "fp64_active":      "DCGM_FI_PROF_PIPE_FP64_ACTIVE",
    # NVLink aggregate bandwidth (KB/s) — multi-GPU systems only
    "nvlink_tx_kbps":   "DCGM_FI_DEV_NVLINK_BANDWIDTH_TX_TOTAL",
    "nvlink_rx_kbps":   "DCGM_FI_DEV_NVLINK_BANDWIDTH_RX_TOTAL",
    # L2 cache hit rates (ratios 0–1; multiplied ×100 in collect())
    "l2_read_hit":      "DCGM_FI_PROF_L2_READ_HIT",
    "l2_write_hit":     "DCGM_FI_PROF_L2_WRITE_HIT",
}

_MODEL_LABEL_RE = re.compile(r'modelName="([^"]+)"')

logger = logging.getLogger(__name__)


def _parse(text: str, metric: str) -> float:
    """Extract first scalar value for a metric from Prometheus text format."""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(metric + "{") or s.startswith(metric + " "):
            try:
                return float(s.rsplit(" ", 1)[1])
            except (ValueError, IndexError):
                pass
    return 0.0


def _parse_gpu_name(text: str) -> str:
    """Extract GPU model name from DCGM Prometheus label modelName="..."."""
    m = _MODEL_LABEL_RE.search(text)
    return m.group(1) if m else ""


class DCGMBackend(GpuBackend):
    """
    GPU metrics via the DCGM Prometheus exporter HTTP endpoint.

    Add support for a new GPU generation: as long as DCGM supports it,
    no code changes are needed. Ensure the DCGM exporter is running and
    configured to export the relevant metric IDs.
    """

    name = "dcgm_http"

    def __init__(self, url: str = "http://localhost:9400/metrics", timeout: float = 2.0):
        self.url     = url
        self.timeout = timeout
        # Fetch once on init: used for capability probing and metadata
        try:
            logger.debug("DCGM: connecting to %s", self.url)
            self._init_text = requests.get(self.url, timeout=self.timeout).text
        except Exception as exc:
            logger.warning("DCGM: connection failed: %s", exc)
            self._init_text = ""
        self.capabilities = self._probe_capabilities(self._init_text)

    def _probe_capabilities(self, text: str) -> list[str]:
        """Determine which metric groups are present in the exporter output."""
        caps = [CAP_UTIL, CAP_POWER, CAP_VRAM, CAP_TEMP, CAP_CLOCKS, CAP_PCIE]
        if "DCGM_FI_PROF_SM_ACTIVE" in text:
            caps += [CAP_SM_ACTIVE, CAP_SM_OCC, CAP_TENSOR, CAP_DRAM]
        if "DCGM_FI_PROF_PIPE_FP32_ACTIVE" in text:
            caps.append(CAP_FP32)
        if "DCGM_FI_PROF_PIPE_FP64_ACTIVE" in text:
            caps.append(CAP_FP64)
        if "DCGM_FI_DEV_NVLINK_BANDWIDTH" in text:
            caps.append(CAP_NVLINK)
        if "DCGM_FI_PROF_L2_READ_HIT" in text:
            caps.append(CAP_L2_CACHE)
        return caps

    def collect(self) -> Optional[GpuSample]:
        try:
            text = requests.get(self.url, timeout=self.timeout).text
        except Exception:
            return None

        g = lambda m: _parse(text, _METRIC_MAP[m])
        hbm_used = g("hbm_used_mib")
        hbm_free = g("hbm_free_mib")

        return GpuSample(
            timestamp=time.time(),
            gpu_util_pct=g("gpu_util_pct"),
            hbm_used_mib=hbm_used,
            hbm_total_mib=hbm_used + hbm_free,
            power_w=g("power_w"),
            temp_c=g("temp_c"),
            sm_clock_mhz=g("sm_clock_mhz"),
            mem_clock_mhz=g("mem_clock_mhz"),
            pcie_tx_kbps=g("pcie_tx_kbps"),
            pcie_rx_kbps=g("pcie_rx_kbps"),
            # Profiling counters: DCGM returns ratios 0–1, convert to 0–100 pct
            sm_active_pct=g("sm_active") * 100,
            sm_occupancy_pct=g("sm_occupancy") * 100,
            tensor_active_pct=g("tensor_active") * 100,
            dram_active_pct=g("dram_active") * 100,
            fp32_active_pct=g("fp32_active") * 100,
            fp64_active_pct=g("fp64_active") * 100,
            # NVLink — 0.0 if counter not exported or single-GPU
            nvlink_tx_kbps=g("nvlink_tx_kbps"),
            nvlink_rx_kbps=g("nvlink_rx_kbps"),
            # L2 cache hit rates — 0.0 if not exported (consumer GPU / older DCGM)
            l2_read_hit_pct=g("l2_read_hit") * 100,
            l2_write_hit_pct=g("l2_write_hit") * 100,
        )

    def _get_gpu_count(self) -> int:
        """Query nvidia-smi for actual GPU count (DCGM Prometheus text does not expose it)."""
        try:
            r = subprocess.run(
                ["nvidia-smi", "-L"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0 and r.stdout:
                lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
                return max(1, len(lines))
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            logger.debug("nvidia-smi -L failed, assuming gpu_count=1: %s", exc)
        return 1

    def get_metadata(self) -> dict:
        gpu_name = _parse_gpu_name(self._init_text)
        gpu_count = self._get_gpu_count()
        logger.debug("DCGM metadata: gpu_name=%s gpu_count=%d", gpu_name, gpu_count)

        from .specs import get_gpu_specs
        specs = get_gpu_specs(gpu_name)

        return {
            "gpu_name":         gpu_name,
            "gpu_count":        gpu_count,
            "gpu_index":        0,
            "driver_version":   "",   # not exposed in Prometheus text format
            "cuda_version":     "",
            "gpu_backend":      self.name,
            "gpu_capabilities": list(self.capabilities),
            "peak_hbm_bw_gbps": specs["peak_hbm_bw_gbps"],
            "peak_tflops_bf16": specs["peak_tflops_bf16"],
            "nvlink_bw_gbps":   specs["nvlink_bw_gbps"],
        }

    @classmethod
    def is_available(cls, url: str = "http://localhost:9400/metrics", **kwargs) -> bool:
        try:
            r = requests.get(url, timeout=2.0)
            return r.status_code == 200 and "DCGM_FI_DEV" in r.text
        except Exception:
            return False

"""
telemetry.gpu.base — Abstract GPU backend + shared GpuSample dataclass.

To add support for a new GPU vendor/platform:
  1. Create a new file in this directory (e.g. rocm.py, xpu.py)
  2. Subclass GpuBackend and implement collect() + is_available()
  3. Optionally override get_metadata() to return GPU name, driver, spec constants
  4. Register it in auto.py's BACKEND_PRIORITY list
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


# ── Capability constants ───────────────────────────────────────────────────────
# Each backend declares which of these it can provide.

CAP_UTIL        = "gpu_util"        # GPU utilisation %
CAP_POWER       = "power"           # Power draw (W)
CAP_VRAM        = "vram"            # Framebuffer used / total
CAP_TEMP        = "temperature"     # Die temperature
CAP_CLOCKS      = "clocks"          # SM / memory clock
CAP_PCIE        = "pcie"            # PCIe TX / RX bandwidth
CAP_SM_ACTIVE   = "sm_active"       # SM active ratio  (DCGM PROF counters)
CAP_SM_OCC      = "sm_occupancy"    # SM occupancy ratio
CAP_TENSOR      = "tensor_active"   # Tensor core active ratio
CAP_DRAM        = "dram_active"     # DRAM active ratio → estimated BW
CAP_NVLINK      = "nvlink"          # NVLink TX / RX bandwidth (multi-GPU)
CAP_FP32        = "fp32_active"     # FP32 arithmetic pipe active (DCGM PROF)
CAP_FP64        = "fp64_active"     # FP64 arithmetic pipe active (DCGM PROF)
CAP_L2_CACHE    = "l2_cache"        # L2 cache read/write hit rates (DCGM PROF)


# ── GpuSample ─────────────────────────────────────────────────────────────────

@dataclass
class GpuSample:
    """
    One GPU telemetry snapshot. Fields not supported by a backend stay 0.0.
    Never set unsupported fields to None — always use the 0.0 default.
    """
    timestamp: float = 0.0

    # Available on all NVIDIA backends (NVML / DCGM)
    gpu_util_pct:   float = 0.0
    hbm_used_mib:   float = 0.0
    hbm_total_mib:  float = 0.0
    power_w:        float = 0.0
    temp_c:         float = 0.0
    sm_clock_mhz:   float = 0.0
    mem_clock_mhz:  float = 0.0
    pcie_tx_kbps:   float = 0.0
    pcie_rx_kbps:   float = 0.0

    # DCGM profiling counters — data-centre GPUs only (0.0 on consumer / NVML)
    sm_active_pct:      float = 0.0   # 0–100  fraction of SMs executing instructions
    sm_occupancy_pct:   float = 0.0   # 0–100  warps resident / theoretical max warps
    tensor_active_pct:  float = 0.0   # 0–100  tensor core pipe active cycles
    dram_active_pct:    float = 0.0   # 0–100  memory interface active cycles
    fp32_active_pct:    float = 0.0   # 0–100  FP32 arithmetic pipe active
    fp64_active_pct:    float = 0.0   # 0–100  FP64 arithmetic pipe active

    # NVLink — multi-GPU only; 0.0 on single-GPU or PCIe-only systems
    nvlink_tx_kbps:  float = 0.0
    nvlink_rx_kbps:  float = 0.0

    # L2 cache hit rates (DCGM PROF counters; 0.0 on NVML / consumer GPU)
    l2_read_hit_pct:  float = 0.0   # 0–100  fraction of L2 reads that hit
    l2_write_hit_pct: float = 0.0   # 0–100  fraction of L2 writes that hit

    @property
    def hbm_util_pct(self) -> float:
        return 100.0 * self.hbm_used_mib / self.hbm_total_mib if self.hbm_total_mib else 0.0


# ── GpuBackend ABC ────────────────────────────────────────────────────────────

class GpuBackend(ABC):
    """
    Abstract base class for GPU metric collection.

    Subclasses must implement:
      - collect() → Optional[GpuSample]
      - is_available() classmethod → bool

    They should also set:
      - name: str                  human-readable backend name
      - capabilities: list[str]   from the CAP_* constants above

    Optionally override:
      - get_metadata() → dict      GPU identity and spec constants
    """

    name: str = "base"
    capabilities: list[str] = []

    @abstractmethod
    def collect(self) -> Optional[GpuSample]:
        """Return the latest GPU sample, or None on transient error."""
        ...

    @classmethod
    @abstractmethod
    def is_available(cls, **kwargs) -> bool:
        """Return True if this backend can run on the current system."""
        ...

    def get_metadata(self) -> dict:
        """
        Return static GPU identity and spec constants.

        Override in subclasses to provide real values. Returned dict always
        contains all keys shown here — callers must not assume any key is absent.
        """
        return {
            "gpu_name":         "",
            "gpu_count":        0,
            "gpu_index":        0,
            "driver_version":   "",
            "cuda_version":     "",
            "gpu_backend":      self.name,
            "gpu_capabilities": list(self.capabilities),
            "peak_hbm_bw_gbps": 0.0,
            "peak_tflops_bf16": 0.0,
            "nvlink_bw_gbps":   0.0,
        }

    def describe(self) -> str:
        return f"{self.name} [{', '.join(self.capabilities)}]"

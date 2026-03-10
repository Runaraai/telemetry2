"""
telemetry.gpu.auto — Auto-detect the best available GPU backend.

Priority order:
  1. DCGMBackend   — full profiling counters, prefers data-centre GPUs
  2. NVMLBackend   — basic metrics, works on any NVIDIA GPU
  # Future: ROCmBackend, XPUBackend, ...

To add a new GPU platform:
  1. Create your backend file (e.g. rocm.py) implementing GpuBackend
  2. Import it here and insert into BACKEND_PRIORITY
"""

from __future__ import annotations

from .base import GpuBackend, CAP_SM_ACTIVE
from .dcgm import DCGMBackend
from .nvml import NVMLBackend

# Ordered list of (BackendClass, kwargs_for_is_available)
# First available backend wins.
BACKEND_PRIORITY: list[tuple[type[GpuBackend], dict]] = [
    (DCGMBackend, {"url": "http://localhost:9400/metrics"}),
    (NVMLBackend, {}),
    # (ROCmBackend, {}),   # add here when rocm.py is ready
    # (XPUBackend, {}),    # add here for Intel GPUs
]


class AutoGpuBackend(GpuBackend):
    """
    Selects the best available GPU backend automatically.

    Preference: DCGM (full counters) > NVML (basic) > ...

    Special rule: if DCGM is available but reports zero for profiling
    counters (consumer GPU), fall back to NVML which gives cleaner
    basic metrics without the zero-filled profiling fields.
    """

    def __init__(self, dcgm_url: str = "http://localhost:9400/metrics",
                 gpu_index: int = 0, prefer_dcgm: bool = True):
        self._backend = self._select(dcgm_url, gpu_index, prefer_dcgm)
        self.name = f"auto→{self._backend.name}"
        self.capabilities = self._backend.capabilities

    def _select(self, dcgm_url: str, gpu_index: int, prefer_dcgm: bool) -> GpuBackend:
        if prefer_dcgm and DCGMBackend.is_available(url=dcgm_url):
            b = DCGMBackend(url=dcgm_url)
            # If DCGM has profiling counters, it's strictly better
            if CAP_SM_ACTIVE in b.capabilities:
                return b
            # DCGM reachable but no profiling counters (consumer GPU):
            # NVML gives the same basic metrics more reliably (no extra HTTP hop)
            if NVMLBackend.is_available():
                return NVMLBackend(gpu_index=gpu_index)
            return b  # DCGM without profiling is still fine
        if NVMLBackend.is_available():
            return NVMLBackend(gpu_index=gpu_index)
        raise RuntimeError(
            "No GPU backend available. "
            "Install pynvml ('pip install nvidia-ml-py3') or start a DCGM exporter."
        )

    def collect(self):
        return self._backend.collect()

    def get_metadata(self) -> dict:
        meta = self._backend.get_metadata()
        # Override gpu_backend to show the auto→underlying name
        meta["gpu_backend"] = self.name
        meta["gpu_capabilities"] = list(self.capabilities)
        return meta

    @classmethod
    def is_available(cls, **kwargs) -> bool:
        return DCGMBackend.is_available(**kwargs) or NVMLBackend.is_available()

    def describe(self) -> str:
        return f"AutoGpuBackend → {self._backend.describe()}"
